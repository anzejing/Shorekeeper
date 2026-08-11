import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

# 审批过期清理周期（秒）
_APPROVAL_CLEANUP_INTERVAL = 600

from app.api.approval import init_approval_api, router as approval_router
from app.api.chat import init_chat_api, router as chat_router
from app.api.config import router as config_router
from app.api.memory import init_memory_api, router as memory_router
from app.api.mcp import init_mcp_api, router as mcp_router
from app.api.permission import init_permission_api, router as permission_router
from app.api.runtime import router as runtime_router
from app.api.runtime import set_runtime
from app.api.skill import init_skill_api, router as skill_router
from app.config.service import ConfigService
from app.memory.memory_store import MemoryStore
from app.memory.service import MemoryService
from app.memory.session_store import SessionStore
from app.memory.sqlite_store import SQLiteMemoryStore, SQLiteSessionStore, init_memory_db
from app.memory.tools import MEMORY_TOOLS, MemoryToolExecutor
from app.plugin.loader import PluginLoader
from app.tools import BUILTIN_TOOLS
from app.tools.bash import BashExecutor
from app.tools.file import ReadFileExecutor, WriteFileExecutor
from app.tools.web_search import WEB_SEARCH_TOOL, WebSearchExecutor
from app.tool.definitions import PROXY_TOOLS, TOOL_SEARCH_DEF, TOOL_EXECUTOR_DEF
from app.tool.index import ToolIndex, ToolIndexEntry
from app.tool.proxy_executor import ProxyToolExecutor
from app.tool.schema_validator import SchemaValidator
from app.tool.search import ToolSearchExecutor
from app.mcp.models import MCPConfig as MCPConfigModel, MCPServerConfig as MCPServerConfigModel
from app.mcp.service import MCPService
from app.permission.analyzer.bash import BashAnalyzer
from app.permission.approval import ApprovalManager
from app.permission.engine import PermissionEngine
from app.permission.interceptor import PermissionInterceptor
from app.permission.models import PermissionResult, PermissionRule, PermissionRuleLayer, PermissionScope
from app.permission.parser.bash import BashParser
from app.permission.store import (
    SQLiteApprovalStore,
    SQLiteClaimStore,
    SQLitePermissionStore,
    init_permission_db,
)
from app.runtime.interceptor import InterceptorChain
from app.runtime.native_litellm_client import NativeLiteLLMClient
from app.runtime.runtime import NativePythonRuntime
from app.runtime.store import SQLiteCheckpointStore, SQLiteEventStore, SQLiteRunStore, init_db
from app.skill.loader import SkillLoader
from app.skill.service import SkillService
from app.skill.store import SQLiteSkillStore, init_skill_db
from app.tool.registry import ToolRegistry

# 加载 .env 文件
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时初始化 Runtime。"""
    # 初始化配置
    config_service = ConfigService.get_instance()
    runtime_config = config_service.config.runtime

    # 初始化数据库（路径相对于数据目录）
    db_path = config_service.config.storage.database_url
    if db_path.startswith("sqlite:///"):
        db_path = db_path[len("sqlite:///"):]
    # 相对路径解析为数据目录下的路径
    db_file = Path(db_path)
    if not db_file.is_absolute():
        db_file = config_service.data_dir / db_file
    db_file.parent.mkdir(parents=True, exist_ok=True)
    db = await init_db(str(db_file))

    # 初始化存储层
    run_store = SQLiteRunStore(db)
    event_store = SQLiteEventStore(db)
    checkpoint_store = SQLiteCheckpointStore(db)

    # 初始化 Memory 模块
    await init_memory_db(db)
    session_store = SQLiteSessionStore(db)
    memory_store = SQLiteMemoryStore(db)
    memory_service = MemoryService(session_store, memory_store)
    init_memory_api(memory_service)

    # 初始化 ToolRegistry + 注册 Tools
    tool_registry = ToolRegistry()
    memory_tool_executor = MemoryToolExecutor(memory_service)
    tool_registry.register_many(MEMORY_TOOLS, memory_tool_executor)

    # 注册通用 Tools
    bash_executor = BashExecutor()
    read_file_executor = ReadFileExecutor()
    write_file_executor = WriteFileExecutor()
    tool_registry.register(BUILTIN_TOOLS[0], bash_executor)   # bash_execute
    tool_registry.register(BUILTIN_TOOLS[1], read_file_executor)  # read_file
    tool_registry.register(BUILTIN_TOOLS[2], write_file_executor) # write_file

    # 注册网络搜索工具（只读，默认 ALLOW）
    web_search_executor = WebSearchExecutor(config_service)
    tool_registry.register(WEB_SEARCH_TOOL, web_search_executor)

    # 初始化 ToolIndex（渐进式披露）
    tool_index = ToolIndex()
    # 将核心工具注册到索引
    for td in tool_registry.get_all_tools():
        tool_index.add(ToolIndexEntry(
            name=td.name,
            description=td.description,
            parameters=td.parameters,
            category="core",
            source="builtin",
            tags=[],
        ))

    # 注册代理工具（tool_search + tool_executor）
    search_executor = ToolSearchExecutor(tool_index)
    proxy_executor = ProxyToolExecutor(tool_registry, SchemaValidator())
    tool_registry.register(TOOL_SEARCH_DEF, search_executor)
    tool_registry.register(TOOL_EXECUTOR_DEF, proxy_executor)
    logger.info("渐进式披露工具注册完成: tool_search, tool_executor")

    # 初始化 MCP 模块
    mcp_config_data = config_service.config.mcp
    mcp_config = MCPConfigModel(
        servers=[
            MCPServerConfigModel(
                name=s.name, transport=s.transport, enabled=s.enabled,
                command=s.command, args=s.args, env=s.env, cwd=s.cwd,
                url=s.url, headers=s.headers, timeout=s.timeout,
                auto_approve=s.auto_approve,
            )
            for s in mcp_config_data.servers
        ]
    )
    mcp_service = MCPService(mcp_config, tool_registry, tool_index)
    try:
        await mcp_service.initialize()
    except Exception as e:
        logger.error("MCP 服务初始化失败: %s", e)
    init_mcp_api(mcp_service, config_service)

    # 初始化 Skill 模块
    await init_skill_db(db)
    skill_store = SQLiteSkillStore(db)
    skills_dir = config_service.data_dir / "skills"
    skill_loader = SkillLoader(skills_dir, skill_store)
    plugins_dir = config_service.data_dir / "plugins"
    plugin_loader = PluginLoader(plugins_dir, skill_loader, skill_store)
    skill_service = SkillService(skill_store, skill_loader, plugin_loader)
    await skill_service.initialize()
    init_skill_api(skill_service)

    # 初始化 Permission 模块
    await init_permission_db(db)
    permission_store = SQLitePermissionStore(db)
    approval_store = SQLiteApprovalStore(db)
    claim_store = SQLiteClaimStore(db)

    # 创建 PermissionEngine（注册 Bash Parser + Analyzer）
    parsers = {"bash_execute": BashParser()}
    analyzers = {"bash_execute": BashAnalyzer(str(config_service.data_dir))}
    engine = PermissionEngine(
        store=permission_store,
        parsers=parsers,
        analyzers=analyzers,
    )

    # 创建 ApprovalManager
    approval_manager = ApprovalManager(approval_store, claim_store)

    # 创建 PermissionInterceptor
    permission_interceptor = PermissionInterceptor(
        engine=engine,
        approval_manager=approval_manager,
    )

    # 初始化 Permission API
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    default_rules = [
        PermissionRule(
            rule_id="sys-elevate", layer=PermissionRuleLayer.SYSTEM_GUARDRAIL,
            capability="system.elevate", tool_name=None, arguments_pattern=None,
            conditions={}, policy=PermissionResult.DENY, priority=100,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="系统强制：禁止提权",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="sys-dynamic", layer=PermissionRuleLayer.SYSTEM_GUARDRAIL,
            capability="system.execute_dynamic", tool_name=None, arguments_pattern=None,
            conditions={}, policy=PermissionResult.REQUIRE_APPROVAL, priority=100,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="系统强制：动态执行需审批",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="sys-unknown", layer=PermissionRuleLayer.SYSTEM_GUARDRAIL,
            capability="system.execute_unknown", tool_name=None, arguments_pattern=None,
            conditions={}, policy=PermissionResult.REQUIRE_APPROVAL, priority=100,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="系统强制：未知命令需审批",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="default-memory-read", layer=PermissionRuleLayer.BUILTIN_DEFAULT,
            capability=None, tool_name="read_memory", arguments_pattern=None,
            conditions={}, policy=PermissionResult.ALLOW, priority=0,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="读取记忆安全",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="default-memory-write", layer=PermissionRuleLayer.BUILTIN_DEFAULT,
            capability=None, tool_name="write_memory", arguments_pattern=None,
            conditions={}, policy=PermissionResult.ALLOW, priority=0,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="写入记忆安全",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="default-memory-search", layer=PermissionRuleLayer.BUILTIN_DEFAULT,
            capability=None, tool_name="search_memory", arguments_pattern=None,
            conditions={}, policy=PermissionResult.ALLOW, priority=0,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="搜索记忆安全",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="default-tool-search", layer=PermissionRuleLayer.BUILTIN_DEFAULT,
            capability=None, tool_name="tool_search", arguments_pattern=None,
            conditions={}, policy=PermissionResult.ALLOW, priority=0,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="工具搜索是只读操作，安全",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="default-tool-executor", layer=PermissionRuleLayer.BUILTIN_DEFAULT,
            capability=None, tool_name="tool_executor", arguments_pattern=None,
            conditions={}, policy=PermissionResult.REQUIRE_APPROVAL, priority=0,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="代理执行器默认需要审批",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="default-web-search", layer=PermissionRuleLayer.BUILTIN_DEFAULT,
            capability=None, tool_name="web_search", arguments_pattern=None,
            conditions={}, policy=PermissionResult.ALLOW, priority=0,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="网络搜索是只读操作，安全",
            created_at=now, updated_at=now,
        ),
    ]
    # 插入默认规则（已存在则删除重建，确保规则定义同步）
    for rule in default_rules:
        existing = await permission_store.get(rule.rule_id)
        if existing is not None:
            await permission_store.delete(rule.rule_id)
        await permission_store.create(rule)

    init_permission_api(permission_store, default_rules)
    init_approval_api(approval_manager)

    # 初始化 Chat API
    init_chat_api(memory_service, skill_service, tool_registry)

    # 初始化 LLM 客户端
    llm = NativeLiteLLMClient()

    # LLM 配置
    llm_extra = {}
    if runtime_config.base_url:
        llm_extra["base_url"] = runtime_config.base_url
    if runtime_config.api_key:
        llm_extra["api_key"] = runtime_config.api_key

    # 创建 Runtime（使用 PermissionInterceptor 替换 NoopInterceptorChain）
    runtime = NativePythonRuntime(
        llm=llm,
        tool_executor=tool_registry,
        interceptor=permission_interceptor,
        publisher=_EventStorePublisher(event_store),
        run_store=run_store,
        checkpoint_store=checkpoint_store,
        event_store=event_store,
        default_model=runtime_config.model,
        default_max_steps=20,
        llm_extra=llm_extra,
    )
    set_runtime(runtime)

    # 启动后台任务：定期清理过期审批
    approval_cleanup_task = asyncio.create_task(
        _approval_cleanup_loop(approval_manager)
    )

    try:
        yield
    finally:
        # 关闭 MCP 服务
        try:
            await mcp_service.shutdown()
        except Exception:
            logger.exception("MCP 服务关闭异常")

        approval_cleanup_task.cancel()
        try:
            await approval_cleanup_task
        except asyncio.CancelledError:
            pass


async def _approval_cleanup_loop(approval_manager: ApprovalManager) -> None:
    """定期将过期审批标记为 expired。

    每 10 分钟执行一次，避免过期审批永久残留在 DB。
    """
    while True:
        try:
            await asyncio.sleep(_APPROVAL_CLEANUP_INTERVAL)
            count = await approval_manager.expire_stale()
            if count:
                logger.info("已清理 %d 条过期审批", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("审批过期清理任务异常")


app = FastAPI(title="Shorekeeper", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router, prefix="/api/config", tags=["config"])
app.include_router(runtime_router, prefix="/api", tags=["runtime"])
app.include_router(memory_router)
app.include_router(skill_router)
app.include_router(mcp_router)
app.include_router(permission_router)
app.include_router(approval_router)
app.include_router(chat_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# ─── 启动时的临时实现（后续替换为真实实现） ────────────────


class _NoopInterceptorChain:
    """空拦截器链——默认允许所有工具调用。"""

    async def process(self, tool_call):
        from app.runtime.models import Allow

        return Allow()


class _EventStorePublisher:
    """基于 EventStore 的事件发布器。"""

    def __init__(self, event_store):
        self._event_store = event_store

    async def publish(self, event):
        await self._event_store.save(event)
