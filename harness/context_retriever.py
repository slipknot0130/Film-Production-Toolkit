"""
harness/context_retriever.py — JIT 上下文检索系统

解决长剧创作中的上下文膨胀问题：
- 当前：每集 Writer 携带全量 outline + character_settings + memory_snapshot (5000+ token)
- 优化：按集检索，仅注入当前大纲段落 + 前3集摘要 + 活跃角色/伏线 (~1500-2000 token)
- 目标：token 消耗降低 40-60%

核心类：
- OutlineParser：将全剧大纲解析为集数级段落
- ContextBundle：单集 Writer 所需的轻量上下文
- ContextRetriever：JIT 检索入口，统一组装上下文
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from .config import get_harness_config


# =============================================================================
# ContextBundle — 单集最小上下文
# =============================================================================

@dataclass
class ContextBundle:
    """单集 Writer 所需的最小上下文。所有字段均为可注入的纯文本。"""

    episode_num: int
    total_episodes: int

    # 当前集大纲段落（从全剧大纲中解析出的本集部分）
    episode_outline: str = ""

    # 前 N 集摘要（从 StructuredMemoryStore 的 episode_index 中获取）
    recent_summaries: str = ""

    # 角色上下文（仅包含本集出场的活跃角色状态）
    character_context: str = ""

    # 活跃伏线摘要
    active_plot_threads: str = ""

    # 全剧概述（极简版，始终注入以保持全局视野）
    global_synopsis: str = ""

    def build_injectable(self) -> str:
        """将所有字段拼接为可注入 prompt 的文本块。"""
        parts = []

        if self.global_synopsis:
            parts.append(f"【全剧概述】\n{self.global_synopsis}")

        if self.episode_outline:
            parts.append(f"【本集大纲】\n{self.episode_outline}")

        if self.character_context:
            parts.append(f"【角色当前状态】\n{self.character_context}")

        if self.recent_summaries:
            parts.append(f"【前集回顾】\n{self.recent_summaries}")

        if self.active_plot_threads:
            parts.append(f"【活跃伏线】\n{self.active_plot_threads}")

        return "\n\n".join(parts)

    def estimated_tokens(self) -> int:
        """粗略估算 token 数（中文约 2 char/token）。"""
        text = self.build_injectable()
        return len(text) // 2


# =============================================================================
# OutlineParser — 大纲解析器
# =============================================================================

class OutlineParser:
    """解析全剧大纲，提取集数级段落和全局信息。

    支持多种大纲格式：
    1. Markdown 分级标题：「第 N 集」/「第N集」/「Episode N」
    2. 数字序号：1. / 一、 / ① 等
    3. 自由文本：按自然段切分
    """

    # 集数分隔的正则模式（按优先级）
    EPISODE_PATTERNS = [
        # Markdown 标题格式
        re.compile(r'^#{1,4}\s*第\s*(\d+)\s*集', re.MULTILINE),
        # 纯文本格式「第N集：...」或「第N集 ...」
        re.compile(r'(?:^|\n)\s*第\s*(\d+)\s*集\s*[：:]', re.MULTILINE),
        re.compile(r'(?:^|\n)\s*第\s*(\d+)\s*集\s*\n', re.MULTILINE),
        # 数字段落「1. ...」「一、...」
        re.compile(r'(?:^|\n)\s*(\d+)\s*[\.、．)]\s*', re.MULTILINE),
    ]

    # 全局信息提取模式
    GLOBAL_PATTERNS = [
        re.compile(r'##\s*基本信息\s*\n(.*?)(?=##|\Z)', re.DOTALL),
        re.compile(r'##\s*概念摘要\s*\n(.*?)(?=##|\Z)', re.DOTALL),
        re.compile(r'##\s*核心戏剧动作\s*\n(.*?)(?=##|\Z)', re.DOTALL),
    ]

    def __init__(self):
        self._global_synopsis: str = ""
        self._episode_sections: Dict[int, str] = {}
        self._total_episodes: int = 0
        self._parsed = False

    @property
    def global_synopsis(self) -> str:
        return self._global_synopsis

    @property
    def episode_sections(self) -> Dict[int, str]:
        return self._episode_sections

    @property
    def total_episodes(self) -> int:
        return self._total_episodes

    def parse(self, outline: str, total_episodes: Optional[int] = None) -> "OutlineParser":
        """解析大纲文本。

        Args:
            outline: 全剧大纲全文
            total_episodes: 已知总集数（可选，用于校验）
        """
        self._parsed = True
        self._total_episodes = total_episodes or 0

        if not outline:
            return self

        # 1. 提取全局摘要
        self._extract_global(outline)

        # 2. 按集拆分
        self._split_episodes(outline)

        # 3. 如果 total_episodes 未指定，从解析结果推断
        if not self._total_episodes and self._episode_sections:
            self._total_episodes = max(self._episode_sections.keys())

        return self

    def _extract_global(self, outline: str) -> None:
        """提取全局信息（基本信息、概念摘要、核心戏剧动作）。"""
        parts = []
        for pattern in self.GLOBAL_PATTERNS:
            match = pattern.search(outline)
            if match:
                parts.append(match.group(0).strip())
        if parts:
            self._global_synopsis = "\n\n".join(parts)
        else:
            # Fallback：取大纲前 500 字符作为全局摘要
            self._global_synopsis = outline[:500].strip()

    def _split_episodes(self, outline: str) -> None:
        """按集拆分大纲段落。"""
        # 尝试每种分隔模式
        for pattern in self.EPISODE_PATTERNS:
            sections = self._try_split(outline, pattern)
            if sections and len(sections) >= 2:  # 至少分出2段才算成功
                self._episode_sections = sections
                return

        # 所有模式都失败 → 整篇作为第1集，其余集无单独段落
        if outline.strip():
            self._episode_sections = {1: outline.strip()}

    def _try_split(self, text: str, pattern: re.Pattern) -> Dict[int, str]:
        """用给定正则拆分文本，返回 {集号: 段落}。"""
        matches = list(pattern.finditer(text))
        if not matches:
            return {}

        sections: Dict[int, str] = {}
        for i, m in enumerate(matches):
            ep_num = int(m.group(1))
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            # 清理开头的标记字符（如 #、* 等）
            content = re.sub(r'^[#*\s]+', '', content)
            sections[ep_num] = content

        return sections

    def get_episode_outline(self, episode_num: int) -> str:
        """获取指定集的 outline 段落。

        如果找不到精确匹配，尝试返回最近一集的段落 + 全局信息。
        """
        if episode_num in self._episode_sections:
            return self._episode_sections[episode_num]

        # 找不到精确集 → 返回全局摘要（优于空字符串）
        # 同时尝试模糊匹配（如第1-5集的幕结构描述）
        for ep in sorted(self._episode_sections.keys()):
            if ep <= episode_num:
                section = self._episode_sections[ep]
                # 检查是否是幕级描述（包含多集范围）
                range_match = re.search(rf'第\s*(\d+)\s*[-–—]\s*(\d+)\s*集', section)
                if range_match:
                    start, end = int(range_match.group(1)), int(range_match.group(2))
                    if start <= episode_num <= end:
                        return f"本集属于「{section[:200]}...」的范围"

        return self._global_synopsis[:300] if self._global_synopsis else ""


# =============================================================================
# ContextRetriever — JIT 检索入口
# =============================================================================

class ContextRetriever:
    """JIT 上下文检索器。

    桥接 OutlineParser 和 StructuredMemoryStore，为每个 Writer 调用
    生成最小且精准的上下文注入。

    使用方式：
        retriever = ContextRetriever(outline, memory_store, total_episodes)
        for ep in range(1, total + 1):
            bundle = retriever.retrieve(ep)
            prompt += bundle.build_injectable()
            # ... Writer 调用 ...
            retriever.record_episode(ep, summary)
    """

    def __init__(
        self,
        outline: str,
        memory_store: Optional["StructuredMemoryStore"] = None,
        total_episodes: int = 0,
        recent_count: int = 3,
    ):
        """
        Args:
            outline: 全剧大纲全文
            memory_store: 结构化记忆（可选，无则降级为文本检索）
            total_episodes: 总集数
            recent_count: 注入的前集摘要数量（默认3）
        """
        self._outline = outline
        self._memory_store = memory_store
        self._total_episodes = total_episodes
        self._recent_count = recent_count

        # 解析大纲
        self._parser = OutlineParser()
        self._parser.parse(outline, total_episodes)

        # 摘要缓存（{ep_num: summary_text}），避免重复构建
        self._summary_cache: Dict[int, str] = {}

        # 统计信息
        self._stats = {
            "retrievals": 0,
            "total_tokens_saved_estimate": 0,
        }

    @property
    def parser(self) -> OutlineParser:
        return self._parser

    @property
    def stats(self) -> Dict:
        return {**self._stats}

    def retrieve(self, episode_num: int) -> ContextBundle:
        """为指定集构建 JIT 上下文。

        Args:
            episode_num: 当前集号（1-based）

        Returns:
            ContextBundle：可注入 prompt 的最小上下文
        """
        self._stats["retrievals"] += 1

        bundle = ContextBundle(
            episode_num=episode_num,
            total_episodes=self._total_episodes,
        )

        # 1. 全剧概述（第1集时给完整版，后续给精简版）
        if episode_num == 1:
            bundle.global_synopsis = self._parser.global_synopsis
        else:
            # 第2集起：极简概述（前200字）
            synopsis = self._parser.global_synopsis
            bundle.global_synopsis = synopsis[:200] + "..." if len(synopsis) > 200 else synopsis

        # 2. 本集大纲段落
        bundle.episode_outline = self._parser.get_episode_outline(episode_num)

        # 3. 前 N 集摘要
        bundle.recent_summaries = self._build_recent_summaries(episode_num)

        # 4. 角色上下文 + 活跃伏线（来自 StructuredMemoryStore）
        if self._memory_store and episode_num > 1:
            try:
                ms = self._memory_store
                # 获取活跃角色状态
                chars = ms._characters
                if chars:
                    char_lines = []
                    for name, state in list(chars.items())[:8]:  # 最多8个角色
                        recent_events = [
                            e for e in state.key_events[-3:]
                            if f"第{episode_num - 1}集" in e
                            or f"第{episode_num - 2}集" in e
                            or f"第{episode_num - 3}集" in e
                        ]
                        if state.current_emotion or recent_events:
                            line = f"- {name}：{state.current_emotion or '状态正常'}"
                            if recent_events:
                                line += f" | {recent_events[-1][:40]}"
                            char_lines.append(line)
                    if char_lines:
                        bundle.character_context = "\n".join(char_lines)

                # 获取活跃伏线
                active_threads = [
                    t for t in ms._plot_threads.values()
                    if t.status in ("铺垫中", "推进中", "引爆")
                ]
                if active_threads:
                    thread_lines = []
                    for t in active_threads[:5]:
                        thread_lines.append(
                            f"- {t.name}（{t.status}，始于第{t.planted_episode}集）：{t.description[:60]}"
                        )
                    bundle.active_plot_threads = "\n".join(thread_lines)
            except Exception:
                pass  # 记忆检索失败不阻塞

        # 5. 兜底：episode_num=1 且无 memory_store 时，返回完整全局信息
        if episode_num == 1 and not bundle.recent_summaries:
            bundle.episode_outline = self._parser.get_episode_outline(1) or self._parser.global_synopsis

        # 估算 token 节省
        full_context_tokens = len(self._outline) // 2
        jit_tokens = bundle.estimated_tokens()
        saved = full_context_tokens - jit_tokens
        if saved > 0:
            self._stats["total_tokens_saved_estimate"] += saved

        return bundle

    def record_episode(self, episode_num: int, summary: str) -> None:
        """记录本集摘要到缓存（为后续检索提供素材）。

        调用时机：每集 Doctor 审核通过后。
        """
        if summary:
            self._summary_cache[episode_num] = summary[:200]  # 限制每集摘要长度

    def _build_recent_summaries(self, episode_num: int) -> str:
        """构建前 N 集摘要文本。

        优先级：
        1. StructuredMemoryStore 的 episode_index
        2. 本地的 summary_cache
        """
        parts = []
        start = max(1, episode_num - self._recent_count)

        for ep in range(start, episode_num):
            summary = None

            # 优先从 StructuredMemoryStore 获取
            if self._memory_store:
                try:
                    summary = self._memory_store._episode_index.get_summary(ep)
                except Exception:
                    pass

            # 其次从本地缓存获取
            if not summary:
                summary = self._summary_cache.get(ep)

            if summary:
                parts.append(f"第{ep}集：{summary[:150]}")

        return "\n".join(parts) if parts else ""
