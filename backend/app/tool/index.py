"""ToolIndex — 工具元数据索引，支持 BM25 搜索。

职责：
1. 存储工具元数据（name, description, parameters, category, tags）
2. 提供 BM25 关键词搜索
3. 支持按 category 过滤

不负责：
- 工具执行（由 ToolRegistry 负责）
- 工具注册到 LLM（由 Chat API 负责）
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ToolIndexEntry:
    """工具索引条目。"""

    name: str                       # 工具名（如 "bash_execute" 或 "github/list_repos"）
    description: str                # 简短描述
    parameters: dict[str, Any]      # JSON Schema 格式的参数定义
    category: str                   # core / mcp / skill / plugin
    source: str                     # 来源标识（如 "builtin"、"slack"）
    tags: list[str] = field(default_factory=list)  # 搜索标签


class ToolIndex:
    """工具索引——支持 BM25 搜索的工具元数据存储。

    BM25 参数（默认值适合短文本搜索）：
    - k1: 1.5（词频饱和参数）
    - b: 0.75（文档长度归一化参数）
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self._entries: dict[str, ToolIndexEntry] = {}
        self._k1 = k1
        self._b = b

        # BM25 索引数据
        self._doc_count: int = 0
        self._avg_doc_len: float = 0.0
        self._doc_lens: dict[str, int] = {}          # tool_name → 文档长度
        self._term_freqs: dict[str, dict[str, int]] = {}  # term → {tool_name: freq}
        self._idf_cache: dict[str, float] = {}       # term → idf

    def add(self, entry: ToolIndexEntry) -> None:
        """添加工具到索引。如果同名已存在，覆盖并重建索引。"""
        if entry.name in self._entries:
            log.warning("ToolIndex: 覆盖已有条目 '%s'", entry.name)
            self._remove_from_index(entry.name)

        self._entries[entry.name] = entry
        self._add_to_index(entry)
        log.info("ToolIndex: 添加 '%s' (category=%s)", entry.name, entry.category)

    def remove(self, tool_name: str) -> bool:
        """从索引移除工具。返回是否成功。"""
        if tool_name not in self._entries:
            return False

        del self._entries[tool_name]
        self._remove_from_index(tool_name)
        log.info("ToolIndex: 移除 '%s'", tool_name)
        return True

    def get(self, tool_name: str) -> ToolIndexEntry | None:
        """按名称获取工具索引条目。"""
        return self._entries.get(tool_name)

    def list_all(self) -> list[ToolIndexEntry]:
        """列出所有索引条目。"""
        return list(self._entries.values())

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[ToolIndexEntry]:
        """BM25 搜索工具。

        Args:
            query: 自然语言查询。
            category: 可选，按分类过滤。
            limit: 最大返回数量。

        Returns:
            按相关性排序的 ToolIndexEntry 列表。
        """
        if not query.strip():
            # 空查询 → 返回全部（按 category 过滤）
            results = self._filter_by_category(category)
            return results[:limit]

        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        # 计算每个文档的 BM25 得分
        scores: list[tuple[str, float]] = []
        candidates = self._filter_by_category(category)

        for entry in candidates:
            score = self._bm25_score(query_terms, entry.name)
            if score > 0:
                scores.append((entry.name, score))

        # 按得分降序排序
        scores.sort(key=lambda x: x[1], reverse=True)

        return [
            self._entries[name]
            for name, _ in scores[:limit]
        ]

    def count(self) -> int:
        """返回索引中的工具数量。"""
        return len(self._entries)

    # ─── BM25 索引维护 ─────────────────────────────────

    def _add_to_index(self, entry: ToolIndexEntry) -> None:
        """将条目添加到 BM25 索引。"""
        doc_text = self._build_document_text(entry)
        terms = self._tokenize(doc_text)
        self._doc_lens[entry.name] = len(terms)
        self._doc_count += 1

        # 统计词频
        term_counts: dict[str, int] = {}
        for term in terms:
            term_counts[term] = term_counts.get(term, 0) + 1

        for term, count in term_counts.items():
            if term not in self._term_freqs:
                self._term_freqs[term] = {}
            self._term_freqs[term][entry.name] = count

        # 更新平均文档长度
        self._update_avg_doc_len()
        # 清除 IDF 缓存
        self._idf_cache.clear()

    def _remove_from_index(self, tool_name: str) -> None:
        """从 BM25 索引移除条目。"""
        if tool_name not in self._doc_lens:
            return

        self._doc_count -= 1
        del self._doc_lens[tool_name]

        # 清理词频数据
        terms_to_remove: list[str] = []
        for term, freqs in self._term_freqs.items():
            freqs.pop(tool_name, None)
            if not freqs:
                terms_to_remove.append(term)

        for term in terms_to_remove:
            del self._term_freqs[term]

        self._update_avg_doc_len()
        self._idf_cache.clear()

    def _update_avg_doc_len(self) -> None:
        """更新平均文档长度。"""
        if self._doc_count > 0:
            self._avg_doc_len = sum(self._doc_lens.values()) / self._doc_count
        else:
            self._avg_doc_len = 0.0

    def _bm25_score(self, query_terms: list[str], doc_name: str) -> float:
        """计算查询词对指定文档的 BM25 得分。"""
        doc_len = self._doc_lens.get(doc_name, 0)
        if doc_len == 0:
            return 0.0

        score = 0.0
        for term in query_terms:
            tf = self._term_freqs.get(term, {}).get(doc_name, 0)
            if tf == 0:
                continue

            idf = self._get_idf(term)
            # BM25 公式
            numerator = tf * (self._k1 + 1)
            denominator = tf + self._k1 * (
                1 - self._b + self._b * doc_len / self._avg_doc_len
            )
            score += idf * (numerator / denominator)

        return score

    def _get_idf(self, term: str) -> float:
        """获取词的 IDF 值（带缓存）。"""
        if term in self._idf_cache:
            return self._idf_cache[term]

        df = len(self._term_freqs.get(term, {}))
        # IDF 平滑公式：log((N - df + 0.5) / (df + 0.5) + 1)
        idf = math.log(
            (self._doc_count - df + 0.5) / (df + 0.5) + 1
        )
        self._idf_cache[term] = idf
        return idf

    # ─── 文本处理 ──────────────────────────────────────

    def _build_document_text(self, entry: ToolIndexEntry) -> str:
        """构建用于搜索的文档文本。"""
        parts = [
            entry.name,
            entry.name.replace("/", " ").replace("_", " "),
            entry.description,
            " ".join(entry.tags),
        ]
        # 从 parameters 中提取属性名和描述
        properties = entry.parameters.get("properties", {})
        for prop_name, prop_def in properties.items():
            parts.append(prop_name)
            if isinstance(prop_def, dict):
                parts.append(prop_def.get("description", ""))

        return " ".join(parts)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """分词：英文按空格/标点切分，中文逐字拆分。

        中文没有天然分隔符，逐字拆分可以确保
        "发送消息" 能匹配到文档中的 "发送" 和 "消息"。
        """
        tokens: list[str] = []
        # 先按非字母数字中文字符切分
        parts = re.findall(r'[\w]+|[\u4e00-\u9fff]+', text.lower())
        for part in parts:
            # 中文字符逐字拆分
            if re.match(r'[\u4e00-\u9fff]+$', part):
                tokens.extend(list(part))
            else:
                tokens.append(part)
        return [t for t in tokens if len(t) >= 1]  # 中文单字也保留

    def _filter_by_category(
        self, category: str | None
    ) -> list[ToolIndexEntry]:
        """按 category 过滤条目。"""
        if category is None:
            return list(self._entries.values())
        return [
            e for e in self._entries.values()
            if e.category == category
        ]
