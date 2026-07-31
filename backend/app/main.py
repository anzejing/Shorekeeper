from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.config import router as config_router
from app.api.runtime import router as runtime_router
from app.api.runtime import set_runtime
from app.config.service import ConfigService
from app.runtime.interceptor import InterceptorChain
from app.runtime.native_litellm_client import NativeLiteLLMClient
from app.runtime.runtime import NativePythonRuntime
from app.runtime.store import SQLiteCheckpointStore, SQLiteEventStore, SQLiteRunStore, init_db

# 加载 .env 文件
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时初始化 Runtime。"""
    # 初始化配置
    config_service = ConfigService.get_instance()
    runtime_config = config_service.config.runtime

    # 初始化数据库
    db_path = config_service.config.storage.database_url
    # 从 sqlite:///path 转换为 path
    if db_path.startswith("sqlite:///"):
        db_path = db_path[len("sqlite:///"):]
    db = await init_db(db_path)

    # 初始化存储层
    run_store = SQLiteRunStore(db)
    event_store = SQLiteEventStore(db)
    checkpoint_store = SQLiteCheckpointStore(db)

    # 初始化 LLM 客户端
    llm = NativeLiteLLMClient()

    # LLM 配置
    llm_extra = {}
    if runtime_config.base_url:
        llm_extra["base_url"] = runtime_config.base_url
    if runtime_config.api_key:
        llm_extra["api_key"] = runtime_config.api_key

    # 创建 Runtime
    runtime = NativePythonRuntime(
        llm=llm,
        tool_executor=_NoopToolExecutor(),
        interceptor=_NoopInterceptorChain(),
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


@app.get("/health")
async def health():
    return {"status": "ok"}


# ─── 启动时的临时实现（后续替换为真实实现） ────────────────


class _NoopToolExecutor:
    """空工具执行器——暂不执行任何工具。"""

    async def execute(self, tool_call, *, cancellation, context=None):
        from app.runtime.models import TextPart, ToolResult

        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            content=[TextPart(text="工具执行暂未实现")],
        )


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
