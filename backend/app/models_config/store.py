"""模型配置 SQLite 持久化。

表结构：
- model_providers: 已配置的 provider
- model_entries: provider 下的模型（含 models.dev 元数据）
- app_settings: 全局设置（如 current_model）
- model_catalog_meta: models.dev 目录同步元信息
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.models_config.schema import CatalogMeta, ModelEntry, ModelProvider

# ─── 建表 SQL ─────────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS model_providers (
    provider_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    api_key TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    use_proxy INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'custom',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_entries (
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    litellm_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    meta_source TEXT NOT NULL DEFAULT 'custom',
    metadata TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (provider_id, model_id),
    FOREIGN KEY (provider_id) REFERENCES model_providers(provider_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_catalog_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    etag TEXT NOT NULL DEFAULT '',
    data_date TEXT NOT NULL DEFAULT '',
    synced_at TEXT NOT NULL DEFAULT '',
    provider_count INTEGER NOT NULL DEFAULT 0,
    model_count INTEGER NOT NULL DEFAULT 0
);
"""

# 全局设置键
SETTING_CURRENT_MODEL = "current_model"


async def init_models_config_db(db: aiosqlite.Connection) -> None:
    """初始化模型配置表。"""
    await db.executescript(_CREATE_TABLES)
    await _migrate(db)
    await db.commit()


async def _migrate(db: aiosqlite.Connection) -> None:
    """旧库迁移：补齐缺失列（幂等，列已存在则跳过）。"""
    # model_providers.use_proxy（v2：LLM 请求走代理开关）
    await _ensure_column(db, "model_providers", "use_proxy", "INTEGER NOT NULL DEFAULT 0")


async def _ensure_column(
    db: aiosqlite.Connection, table: str, column: str, ddl: str
) -> None:
    """检查列是否存在，不存在则 ALTER TABLE 添加。"""
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    if any(row[1] == column for row in rows):
        return
    await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _now_iso() -> str:
    """当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _row_to_provider(row: aiosqlite.Row) -> ModelProvider:
    return ModelProvider(
        provider_id=row["provider_id"],
        name=row["name"],
        kind=row["kind"],
        base_url=row["base_url"],
        api_key=row["api_key"],
        enabled=bool(row["enabled"]),
        use_proxy=bool(row["use_proxy"]) if "use_proxy" in row.keys() else False,
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_entry(row: aiosqlite.Row) -> ModelEntry:
    return ModelEntry(
        provider_id=row["provider_id"],
        model_id=row["model_id"],
        display_name=row["display_name"],
        litellm_name=row["litellm_name"],
        enabled=bool(row["enabled"]),
        meta_source=row["meta_source"],
        metadata=json.loads(row["metadata"] or "{}"),
    )


class ModelConfigStore:
    """模型配置的 SQLite 存储，统一入口。"""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ─── Provider ─────────────────────────────────────────

    async def list_providers(self) -> list[ModelProvider]:
        cur = await self._db.execute(
            "SELECT * FROM model_providers ORDER BY created_at ASC"
        )
        rows = await cur.fetchall()
        return [_row_to_provider(r) for r in rows]

    async def get_provider(self, provider_id: str) -> ModelProvider | None:
        cur = await self._db.execute(
            "SELECT * FROM model_providers WHERE provider_id = ?", (provider_id,)
        )
        row = await cur.fetchone()
        return _row_to_provider(row) if row else None

    async def create_provider(self, provider: ModelProvider) -> None:
        await self._db.execute(
            "INSERT INTO model_providers"
            " (provider_id, name, kind, base_url, api_key, enabled, use_proxy, source,"
            "  created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                provider.provider_id,
                provider.name,
                provider.kind,
                provider.base_url,
                provider.api_key,
                int(provider.enabled),
                int(provider.use_proxy),
                provider.source,
                provider.created_at,
                provider.updated_at,
            ),
        )
        await self._db.commit()

    async def update_provider(self, provider: ModelProvider) -> None:
        await self._db.execute(
            "UPDATE model_providers SET name=?, kind=?, base_url=?, api_key=?, enabled=?,"
            " use_proxy=?, source=?, updated_at=? WHERE provider_id=?",
            (
                provider.name,
                provider.kind,
                provider.base_url,
                provider.api_key,
                int(provider.enabled),
                int(provider.use_proxy),
                provider.source,
                provider.updated_at,
                provider.provider_id,
            ),
        )
        await self._db.commit()

    async def delete_provider(self, provider_id: str) -> None:
        await self._db.execute(
            "DELETE FROM model_providers WHERE provider_id = ?", (provider_id,)
        )
        await self._db.commit()

    # ─── Model Entries ────────────────────────────────────

    async def list_entries(self, provider_id: str) -> list[ModelEntry]:
        cur = await self._db.execute(
            "SELECT * FROM model_entries WHERE provider_id = ?"
            " ORDER BY display_name ASC",
            (provider_id,),
        )
        rows = await cur.fetchall()
        return [_row_to_entry(r) for r in rows]

    async def get_entry(self, provider_id: str, model_id: str) -> ModelEntry | None:
        cur = await self._db.execute(
            "SELECT * FROM model_entries WHERE provider_id = ? AND model_id = ?",
            (provider_id, model_id),
        )
        row = await cur.fetchone()
        return _row_to_entry(row) if row else None

    async def upsert_entry(self, entry: ModelEntry) -> None:
        await self._db.execute(
            "INSERT INTO model_entries"
            " (provider_id, model_id, display_name, litellm_name, enabled,"
            "  meta_source, metadata)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(provider_id, model_id) DO UPDATE SET"
            "  display_name=excluded.display_name,"
            "  litellm_name=excluded.litellm_name,"
            "  enabled=excluded.enabled,"
            "  meta_source=excluded.meta_source,"
            "  metadata=excluded.metadata",
            (
                entry.provider_id,
                entry.model_id,
                entry.display_name,
                entry.litellm_name,
                int(entry.enabled),
                entry.meta_source,
                json.dumps(entry.metadata, ensure_ascii=False),
            ),
        )
        await self._db.commit()

    async def delete_entry(self, provider_id: str, model_id: str) -> None:
        await self._db.execute(
            "DELETE FROM model_entries WHERE provider_id = ? AND model_id = ?",
            (provider_id, model_id),
        )
        await self._db.commit()

    async def replace_entries(self, provider_id: str, entries: list[ModelEntry]) -> None:
        """全量替换某 provider 的模型列表（/models 端点同步用）。"""
        await self._db.execute(
            "DELETE FROM model_entries WHERE provider_id = ?", (provider_id,)
        )
        await self._db.executemany(
            "INSERT INTO model_entries"
            " (provider_id, model_id, display_name, litellm_name, enabled,"
            "  meta_source, metadata)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    e.provider_id,
                    e.model_id,
                    e.display_name,
                    e.litellm_name,
                    int(e.enabled),
                    e.meta_source,
                    json.dumps(e.metadata, ensure_ascii=False),
                )
                for e in entries
            ],
        )
        await self._db.commit()

    # ─── 全局设置 ─────────────────────────────────────────

    async def get_setting(self, key: str) -> Any | None:
        cur = await self._db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    async def set_setting(self, key: str, value: Any) -> None:
        await self._db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        await self._db.commit()

    async def delete_setting(self, key: str) -> None:
        await self._db.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        await self._db.commit()

    # ─── models.dev 目录元信息 ────────────────────────────

    async def get_catalog_meta(self) -> CatalogMeta:
        cur = await self._db.execute("SELECT * FROM model_catalog_meta WHERE id = 1")
        row = await cur.fetchone()
        if row is None:
            return CatalogMeta()
        return CatalogMeta(
            etag=row["etag"],
            data_date=row["data_date"],
            synced_at=row["synced_at"],
            provider_count=row["provider_count"],
            model_count=row["model_count"],
        )

    async def save_catalog_meta(self, meta: CatalogMeta) -> None:
        await self._db.execute(
            "INSERT INTO model_catalog_meta"
            " (id, etag, data_date, synced_at, provider_count, model_count)"
            " VALUES (1, ?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET"
            "  etag=excluded.etag, data_date=excluded.data_date,"
            "  synced_at=excluded.synced_at, provider_count=excluded.provider_count,"
            "  model_count=excluded.model_count",
            (
                meta.etag,
                meta.data_date,
                meta.synced_at,
                meta.provider_count,
                meta.model_count,
            ),
        )
        await self._db.commit()
