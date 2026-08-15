"""models.dev 目录同步。

- 拉取 https://models.dev/api.json（支持 ETag 增量判断，304 未变化）
- 解析目录数据，缓存为本地 JSON 文件（供前端浏览/搜索/导入）
- 提供目录 provider 摘要与单 provider 模型元数据查询
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiohttp

from app.models_config.litellm_mapping import kind_from_npm, official_base_url
from app.net.proxy import is_conn_error

log = logging.getLogger(__name__)

# models.dev API 端点
MODELS_DEV_URL = "https://models.dev/api.json"
# 本地缓存文件名（数据目录下）
CATALOG_FILE = "models_dev_catalog.json"


async def fetch_catalog(
    etag: str = "",
    *,
    timeout: float = 120.0,
    proxy_url: str | None = None,
    fallback_direct: bool = True,
) -> tuple[dict[str, Any] | None, str, str, bool]:
    """拉取 models.dev 目录。

    Args:
        etag: 上次同步的 ETag（304 未变化判断）。
        timeout: 请求总超时。
        proxy_url: 代理地址；非空时先走代理。
        fallback_direct: 代理连接失败时是否回退直连重试一次。

    Returns:
        (data, new_etag, data_date, changed)
        - data: 解析后的目录 dict；ETag 未变化时为 None
        - new_etag: 响应 ETag
        - data_date: 数据版本日期（模型 last_updated 最大值）
        - changed: 数据是否变化
    """
    headers = {"If-None-Match": etag} if etag else {}
    try:
        return await _fetch_once(headers, proxy_url, timeout)
    except Exception as e:
        if proxy_url and fallback_direct and is_conn_error(e):
            log.warning("models.dev 代理失败，回退直连: %s", e)
            return await _fetch_once(headers, None, timeout)
        raise


async def _fetch_once(
    headers: dict[str, str], proxy: str | None, timeout: float
) -> tuple[dict[str, Any] | None, str, str, bool]:
    """单次请求 models.dev（带或不带代理）。"""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            MODELS_DEV_URL,
            headers=headers,
            proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status == 304:
                return None, headers.get("If-None-Match", ""), "", False
            if resp.status != 200:
                raise RuntimeError(f"models.dev 请求失败: HTTP {resp.status}")
            data = await resp.json()
            new_etag = resp.headers.get("ETag", "")
            return data, new_etag, _compute_data_date(data), True


def _compute_data_date(data: dict[str, Any]) -> str:
    """数据版本日期 = 所有模型 last_updated 的最大值。"""
    max_date = ""
    for provider in data.values():
        models = provider.get("models") or {}
        for model in models.values():
            d = model.get("last_updated", "")
            if d and d > max_date:
                max_date = d
    return max_date


def count_models(data: dict[str, Any]) -> int:
    """统计目录模型总数。"""
    return sum(len((p.get("models") or {})) for p in data.values())


# ─── 本地缓存 ─────────────────────────────────────────────


def save_catalog_file(data_dir: Path, data: dict[str, Any]) -> None:
    """将目录数据缓存到本地 JSON 文件。"""
    path = data_dir / CATALOG_FILE
    path.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("models.dev 目录已缓存: %s (%.1f MB)", path, path.stat().st_size / 1e6)


def load_catalog_file(data_dir: Path) -> dict[str, Any] | None:
    """读取本地目录缓存，不存在返回 None。"""
    path = data_dir / CATALOG_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.exception("目录缓存解析失败: %s", path)
        return None


# ─── 目录查询 ─────────────────────────────────────────────


def list_catalog_providers(
    data: dict[str, Any], search: str = ""
) -> list[dict[str, Any]]:
    """目录 provider 摘要列表（不含模型），支持按 id/name 过滤。"""
    keyword = search.strip().lower()
    result: list[dict[str, Any]] = []
    for pid, p in data.items():
        name = p.get("name", pid)
        if keyword and keyword not in pid.lower() and keyword not in name.lower():
            continue
        kind = kind_from_npm(p.get("npm"))
        result.append(
            {
                "provider_id": pid,
                "name": name,
                "kind": kind,
                "api": p.get("api") or "",
                # 默认端点：目录 api 字段优先，兜底 kind 官方端点（供向导预填）
                "default_base_url": (p.get("api") or "").strip()
                or official_base_url(kind),
                "model_count": len(p.get("models") or {}),
                "doc": p.get("doc") or "",
            }
        )
    # 按模型数降序
    result.sort(key=lambda x: x["model_count"], reverse=True)
    return result


def get_catalog_provider(
    data: dict[str, Any], provider_id: str
) -> dict[str, Any] | None:
    """目录单 provider 详情（含 kind 推断）。"""
    p = data.get(provider_id)
    if p is None:
        return None
    kind = kind_from_npm(p.get("npm"))
    return {
        "provider_id": provider_id,
        "name": p.get("name", provider_id),
        "kind": kind,
        "api": p.get("api") or "",
        "default_base_url": (p.get("api") or "").strip()
        or official_base_url(kind),
        "doc": p.get("doc") or "",
        "model_count": len(p.get("models") or {}),
    }


def get_catalog_provider_models(
    data: dict[str, Any], provider_id: str
) -> dict[str, Any] | None:
    """目录单 provider 的模型元数据 {model_id: metadata}。"""
    p = data.get(provider_id)
    if p is None:
        return None
    return p.get("models") or {}
