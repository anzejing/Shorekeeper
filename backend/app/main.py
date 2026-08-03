from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.approval import init_approval_api, router as approval_router
from app.api.chat import init_chat_api, router as chat_router
from app.api.config import router as config_router
from app.api.memory import init_memory_api, router as memory_router
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

    # 初始化 ToolRegistry + 注册 Memory Tools
    tool_registry = ToolRegistry()
    memory_tool_executor = MemoryToolExecutor(memory_service)
    tool_registry.register_many(MEMORY_TOOLS, memory_tool_executor)

    # 初始化 Skill 模块
    await init_skill_db(db)
    skill_store = SQLiteSkillStore(db)
    skills_dir = config_service.data_dir / "skills"
    skill_loader = SkillLoader(skills_dir, skill_store)
    skill_service = SkillService(skill_store, skill_loader)
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
            capability="memory.read", tool_name=None, arguments_pattern=None,
            conditions={}, policy=PermissionResult.ALLOW, priority=0,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="读取记忆安全",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="default-memory-write", layer=PermissionRuleLayer.BUILTIN_DEFAULT,
            capability="memory.write", tool_name=None, arguments_pattern=None,
            conditions={}, policy=PermissionResult.ALLOW, priority=0,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="写入记忆安全",
            created_at=now, updated_at=now,
        ),
        PermissionRule(
            rule_id="default-memory-search", layer=PermissionRuleLayer.BUILTIN_DEFAULT,
            capability="memory.search", tool_name=None, arguments_pattern=None,
            conditions={}, policy=PermissionResult.ALLOW, priority=0,
            scope_type=PermissionScope.GLOBAL, scope_id=None, expires_at=None,
            created_by="system", description="搜索记忆安全",
            created_at=now, updated_at=now,
        ),
    ]
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

    yield


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
