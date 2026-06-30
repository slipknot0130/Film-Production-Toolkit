"""
harness/memory_store.py — 结构化记忆系统 v2.0

解决长剧创作中的上下文断裂问题：
- 现有 Doctor memory_snapshot 是单段文本，跨 50+ 集会漂移
- 此模块提供结构化记忆，精准追踪每个角色状态和每条伏线

v2.0 新增：
- 集成 SceneTimeline（场景级时间线数据库）
- 集成 ConsistencyChecker（逻辑一致性检查器）
- 集成 BeatOutline（分集大纲节拍追踪器）
- get_character_profile() — 用户提出的"角色档案管理器"工具

核心类：
- CharacterState：单个角色的状态快照
- PlotThread：伏线/悬念追踪
- EpisodeIndex：轻量级集数索引
- StructuredMemoryStore：统一管理入口（集成所有子模块）
"""

import json
import time
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, TYPE_CHECKING

from .config import get_harness_config

if TYPE_CHECKING:
    from shared.scene_timeline import SceneTimeline, SceneRecord
    from harness.consistency_checker import ConsistencyChecker, ConsistencyIssue
    from shared.beat_outline import BeatOutline


# =============================================================================
# CharacterState — 角色状态快照
# =============================================================================

class CharacterState:
    """单个角色的当前状态快照

    每集 Doctor QA 后更新，Writer 下一集开始前注入 prompt。
    """

    def __init__(self, name: str):
        self.name = name
        self.last_updated_episode = 0

        self.current_location = ""
        self.current_emotion = ""
        self.current_goal = ""
        self.relationship_status: Dict[str, str] = {}

        self.key_events: List[str] = []
        self.secrets: List[str] = []
        self.wounds: List[str] = []

        self.appearance_notes = ""
        self.ability_notes = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "last_updated_episode": self.last_updated_episode,
            "current_location": self.current_location,
            "current_emotion": self.current_emotion,
            "current_goal": self.current_goal,
            "relationship_status": self.relationship_status,
            "key_events": self.key_events,
            "secrets": self.secrets,
            "wounds": self.wounds,
            "appearance_notes": self.appearance_notes,
            "ability_notes": self.ability_notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CharacterState":
        state = cls(data.get("name", ""))
        state.last_updated_episode = data.get("last_updated_episode", 0)
        state.current_location = data.get("current_location", "")
        state.current_emotion = data.get("current_emotion", "")
        state.current_goal = data.get("current_goal", "")
        state.relationship_status = data.get("relationship_status", {})
        state.key_events = data.get("key_events", [])
        state.secrets = data.get("secrets", [])
        state.wounds = data.get("wounds", [])
        state.appearance_notes = data.get("appearance_notes", "")
        state.ability_notes = data.get("ability_notes", "")
        return state

    def to_prompt_snippet(self, max_events: int = 3) -> str:
        """生成注入 prompt 的简洁摘要"""
        lines = [f"【{self.name}】（第{self.last_updated_episode}集更新）"]
        if self.current_emotion:
            lines.append(f"  情绪：{self.current_emotion}")
        if self.current_goal:
            lines.append(f"  目标：{self.current_goal}")
        if self.current_location:
            lines.append(f"  位置：{self.current_location}")
        if self.key_events:
            recent = self.key_events[-max_events:]
            lines.append(f"  近期：{' / '.join(recent)}")
        if self.secrets:
            lines.append(f"  秘密：{' / '.join(self.secrets[-2:])}")
        return "\n".join(lines)


# =============================================================================
# PlotThread — 伏线/悬念追踪
# =============================================================================

class PlotThread:
    """伏线/悬念追踪"""

    STATUS_PLANTED = "planted"
    STATUS_ACTIVE = "active"
    STATUS_REVEALED = "revealed"
    STATUS_ABANDONED = "abandoned"

    STATUS_LABELS = {
        STATUS_PLANTED: "已埋",
        STATUS_ACTIVE: "激活中",
        STATUS_REVEALED: "已揭示",
        STATUS_ABANDONED: "已废弃",
    }

    def __init__(self, thread_id: str, title: str):
        self.thread_id = thread_id
        self.title = title
        self.status = self.STATUS_PLANTED
        self.planted_episode = 0
        self.revealed_episode = 0
        self.description = ""
        self.involved_characters: List[str] = []
        self.updates: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "status": self.status,
            "planted_episode": self.planted_episode,
            "revealed_episode": self.revealed_episode,
            "description": self.description,
            "involved_characters": self.involved_characters,
            "updates": self.updates,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlotThread":
        pt = cls(data.get("thread_id", ""), data.get("title", ""))
        pt.status = data.get("status", cls.STATUS_PLANTED)
        pt.planted_episode = data.get("planted_episode", 0)
        pt.revealed_episode = data.get("revealed_episode", 0)
        pt.description = data.get("description", "")
        pt.involved_characters = data.get("involved_characters", [])
        pt.updates = data.get("updates", [])
        return pt

    def to_prompt_snippet(self) -> str:
        label = self.STATUS_LABELS.get(self.status, self.status)
        chars = "、".join(self.involved_characters) if self.involved_characters else "—"
        snippet = f"[{label}] {self.title}（第{self.planted_episode}集埋入，涉及：{chars}）"
        if self.description:
            snippet += f"\n  内容：{self.description[:60]}"
        if self.updates:
            snippet += f"\n  最近进展：{self.updates[-1]}"
        return snippet


# =============================================================================
# EpisodeIndex — 轻量集数索引
# =============================================================================

class EpisodeIndex:
    """每集一句话摘要索引"""

    def __init__(self):
        self._index: Dict[int, Dict[str, Any]] = {}

    def update(self, episode: int, summary: str):
        self._index[episode] = {
            "summary": summary[:200],
            "timestamp": time.time(),
        }

    def get_summary(self, episode: int) -> str:
        return self._index.get(episode, {}).get("summary", "")

    def recent(self, n: int = 5, before_episode: int = 9999) -> List[str]:
        """获取最近 n 集的摘要"""
        episodes = sorted(
            [ep for ep in self._index if ep < before_episode],
            reverse=True,
        )[:n]
        episodes.reverse()
        result = []
        for ep in episodes:
            s = self.get_summary(ep)
            if s:
                result.append(f"第{ep}集：{s}")
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {str(k): v for k, v in self._index.items()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpisodeIndex":
        idx = cls()
        for k, v in data.items():
            try:
                idx._index[int(k)] = v
            except (ValueError, TypeError):
                pass
        return idx


# =============================================================================
# StructuredMemoryStore — 统一管理入口
# =============================================================================

class StructuredMemoryStore:
    """结构化记忆系统主入口

    与 Doctor memory_snapshot（单段文本）共存，提供精准的结构化索引。
    Writer 生成下一集 prompt 时，由此系统注入精准上下文。

    使用方式：
        store = StructuredMemoryStore(project_id="我的剧本")

        # 更新角色状态（Doctor QA 后调用）
        char = store.get_or_create_character("男主")
        char.current_emotion = "愤怒"
        char.key_events.append("第5集：发现妻子背叛")
        store.update_character(char, episode=5)

        # 更新集数索引
        store.update_episode_index(5, "男主发现妻子背叛，离家出走")

        # 生成写作注入摘要
        snippet = store.build_writer_context_snippet(current_episode=6)
        # → 注入到 Writer 的 system prompt

        # 持久化
        store.save()
    """

    def __init__(self, project_id: str = "default", config=None,
                 scene_timeline=None, beat_outline=None):
        """
        Args:
            project_id: 项目唯一标识（用于文件隔离）
            config: HarnessConfig，不传则用全局配置
            scene_timeline: SceneTimeline 实例（可选，用于场景级时间线追踪）
            beat_outline: BeatOutline 实例（可选，用于分集节拍追踪）
        """
        self.project_id = project_id
        self.config = config or get_harness_config()

        self._characters: Dict[str, CharacterState] = {}
        self._plot_threads: Dict[str, PlotThread] = {}
        self._episode_index = EpisodeIndex()

        # 风格锚点（用于防止文风漂移）
        self.style_anchors: List[str] = []
        self.world_rules: List[str] = []

        # v2.0：集成子模块
        self.scene_timeline = scene_timeline          # SceneTimeline | None
        self.beat_outline = beat_outline              # BeatOutline | None
        self._consistency_checker = None              # ConsistencyChecker（懒加载）

        self._memory_path = Path(self.config.memory_dir) / f"{self._safe_filename(project_id)}.json"

        # 尝试自动加载已有记忆
        if self._memory_path.exists():
            try:
                self.load()
            except Exception:
                pass  # 加载失败则从空白开始，不影响运行

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_filename(name: str) -> str:
        """转换为安全文件名"""
        safe = ""
        for c in name:
            if c.isalnum() or c in ("-", "_", ".", " "):
                safe += c
            else:
                safe += "_"
        return safe.strip() or "default"

    # ------------------------------------------------------------------
    # 角色状态操作
    # ------------------------------------------------------------------

    def get_or_create_character(self, name: str) -> CharacterState:
        """获取或新建角色状态"""
        if name not in self._characters:
            self._characters[name] = CharacterState(name)
        return self._characters[name]

    def update_character(self, state: CharacterState, episode: int):
        """更新角色状态并记录集数"""
        state.last_updated_episode = episode
        self._characters[state.name] = state
        if self.config.auto_persist_memory:
            self.save()

    def get_character(self, name: str) -> Optional[CharacterState]:
        return self._characters.get(name)

    def get_character_profile(self, name: str) -> Dict[str, Any]:
        """获取角色的完整档案（用户提出的"工具1：角色档案管理器"）。

        返回包含角色所有设定、当前状态、历史事件的字典。
        Writer/Doctor 可通过此接口获取角色的准确状态，
        避免依赖"记忆"导致的细节漂移。

        Args:
            name: 角色名

        Returns:
            完整档案字典，含：身份/外貌/当前状态/情绪/目标/关系/关键事件/秘密/伤口
            如果角色不存在，返回空字典
        """
        char = self._characters.get(name)
        if not char:
            return {}

        profile = {
            "name": char.name,
            "last_seen_episode": char.last_updated_episode,
            "current_location": char.current_location,
            "current_emotion": char.current_emotion,
            "current_goal": char.current_goal,
            "relationship_status": char.relationship_status,
            "recent_events": char.key_events[-5:] if char.key_events else [],
            "secrets": char.secrets,
            "wounds": char.wounds,
            "appearance_notes": char.appearance_notes,
            "ability_notes": char.ability_notes,
        }

        # v2.0：如果集成了 SceneTimeline，追加场景出场记录
        if self.scene_timeline:
            scenes = self.scene_timeline.get_scenes_by_character(name)
            if scenes:
                profile["total_appearances"] = len(scenes)
                profile["first_appearance"] = f"第{scenes[0].episode}集第{scenes[0].scene_number}场"
                profile["last_appearance"] = f"第{scenes[-1].episode}集第{scenes[-1].scene_number}场"

        return profile

    def get_character_profile_text(self, name: str) -> str:
        """get_character_profile 的文本输出版本（可直接注入 LLM prompt）。"""
        profile = self.get_character_profile(name)
        if not profile:
            return f"角色「{name}」暂无档案记录。"

        lines = [
            f"═══ 角色档案：{name} ═══",
            f"最后出场：第{profile['last_seen_episode']}集",
        ]
        if profile.get("total_appearances"):
            lines.append(f"出场次数：{profile['total_appearances']}次"
                         f"（首现{profile.get('first_appearance', '')}，"
                         f"末现{profile.get('last_appearance', '')}）")
        if profile.get("current_location"):
            lines.append(f"当前位置：{profile['current_location']}")
        if profile.get("current_emotion"):
            lines.append(f"当前情绪：{profile['current_emotion']}")
        if profile.get("current_goal"):
            lines.append(f"当前目标：{profile['current_goal']}")
        if profile.get("relationship_status"):
            rel_str = "；".join(f"{k}: {v}" for k, v in profile["relationship_status"].items())
            lines.append(f"关系状态：{rel_str}")
        if profile.get("recent_events"):
            lines.append(f"近期事件：{' / '.join(profile['recent_events'][-3:])}")
        if profile.get("secrets"):
            lines.append(f"持有秘密：{'；'.join(profile['secrets'][-2:])}")
        if profile.get("wounds"):
            lines.append(f"状态标记：{'；'.join(profile['wounds'])}")
        if profile.get("appearance_notes"):
            lines.append(f"外貌备注：{profile['appearance_notes']}")
        if profile.get("ability_notes"):
            lines.append(f"能力备注：{profile['ability_notes']}")
        lines.append("═══ 档案结束 ═══")
        return "\n".join(lines)

    def list_characters(self) -> List[str]:
        return list(self._characters.keys())

    # ------------------------------------------------------------------
    # 伏线操作
    # ------------------------------------------------------------------

    def add_plot_thread(self, title: str, planted_episode: int,
                        description: str = "", characters: Optional[List[str]] = None) -> PlotThread:
        """添加新伏线"""
        thread_id = f"pt_{uuid.uuid4().hex[:8]}"
        pt = PlotThread(thread_id, title)
        pt.planted_episode = planted_episode
        pt.description = description
        pt.involved_characters = characters or []
        self._plot_threads[thread_id] = pt
        if self.config.auto_persist_memory:
            self.save()
        return pt

    def update_plot_thread(self, thread_id: str, status: Optional[str] = None,
                           update_note: str = "", revealed_episode: int = 0):
        """更新伏线状态"""
        if thread_id not in self._plot_threads:
            return
        pt = self._plot_threads[thread_id]
        if status:
            pt.status = status
        if update_note:
            pt.updates.append(update_note)
        if revealed_episode > 0:
            pt.revealed_episode = revealed_episode
        if self.config.auto_persist_memory:
            self.save()

    def get_active_plot_threads(self) -> List[PlotThread]:
        """获取所有未完结的伏线"""
        return [
            pt for pt in self._plot_threads.values()
            if pt.status in (PlotThread.STATUS_PLANTED, PlotThread.STATUS_ACTIVE)
        ]

    # ------------------------------------------------------------------
    # 集数索引操作
    # ------------------------------------------------------------------

    def update_episode_index(self, episode: int, summary: str):
        """更新某集摘要"""
        if self.config.enable_episode_index:
            self._episode_index.update(episode, summary[:self.config.episode_index_max_chars])
            if self.config.auto_persist_memory:
                self.save()

    # ------------------------------------------------------------------
    # 风格锚点
    # ------------------------------------------------------------------

    def set_style_anchors(self, anchors: List[str]):
        """设置风格锚点（从 StyleTokens.txt 或大纲提取）"""
        self.style_anchors = anchors

    def add_world_rule(self, rule: str):
        """添加世界观规则（防止矛盾）"""
        if rule not in self.world_rules:
            self.world_rules.append(rule)

    # ------------------------------------------------------------------
    # 写作上下文注入（核心方法）
    # ------------------------------------------------------------------

    def build_writer_context_snippet(
        self,
        current_episode: int,
        focus_characters: Optional[List[str]] = None,
        recent_episodes: int = 5,
    ) -> str:
        """构建注入 Writer prompt 的结构化上下文摘要

        Args:
            current_episode: 即将创作的集数
            focus_characters: 本集重点角色（None=全部主要角色）
            recent_episodes: 回溯几集的索引

        Returns:
            格式化的上下文字符串，可直接拼接到 system prompt
        """
        sections: List[str] = []

        # 1. 近期剧情索引
        recent = self._episode_index.recent(n=recent_episodes, before_episode=current_episode)
        if recent:
            sections.append("【近期剧情回顾】\n" + "\n".join(recent))

        # 2. 角色状态
        if self._characters and self.config.enable_character_tracking:
            chars_to_show = focus_characters or list(self._characters.keys())[:6]  # 最多6个角色
            char_snippets = []
            for name in chars_to_show:
                state = self._characters.get(name)
                if state and state.last_updated_episode > 0:
                    char_snippets.append(state.to_prompt_snippet())
            if char_snippets:
                sections.append("【角色当前状态】\n" + "\n\n".join(char_snippets))

        # 3. 未完结伏线
        if self.config.enable_plot_tracking:
            active_threads = self.get_active_plot_threads()
            if active_threads:
                thread_snippets = [pt.to_prompt_snippet() for pt in active_threads[:5]]
                sections.append("【待解伏线（需继续推进）】\n" + "\n".join(thread_snippets))

        # 4. 风格锚点
        if self.style_anchors:
            sections.append("【风格锚点（保持一致）】\n" + "、".join(self.style_anchors[:8]))

        # 5. v2.0：场景时间线上下文
        if self.scene_timeline and current_episode > 1:
            timeline_context = self.scene_timeline.get_current_timeline_context(
                current_episode, scene_number=0
            )
            if timeline_context and "暂无" not in timeline_context:
                sections.append(timeline_context)

        # 6. v2.0：本集待完成节拍
        if self.beat_outline:
            beat_context = self.beat_outline.build_writer_beat_context(current_episode)
            if beat_context and "无预设节拍" not in beat_context:
                sections.append(beat_context)

        if not sections:
            return ""

        header = f"═══ 结构化记忆注入（第{current_episode}集创作参考）═══"
        return header + "\n\n" + "\n\n".join(sections) + "\n═══ 记忆注入结束 ═══"

    def build_doctor_check_context(self, current_episode: int,
                                   new_content: str = "") -> str:
        """构建注入 Doctor QA prompt 的上下文（用于一致性检查）。

        v2.0 增强：集成 ConsistencyChecker + BeatOutline + SceneTimeline。
        """
        sections: List[str] = []

        recent = self._episode_index.recent(n=3, before_episode=current_episode)
        if recent:
            sections.append("【近期剧情】\n" + "\n".join(recent))

        active_threads = self.get_active_plot_threads()
        if active_threads:
            thread_titles = [f"- {pt.title}（{PlotThread.STATUS_LABELS.get(pt.status, pt.status)}）"
                             for pt in active_threads[:8]]
            sections.append("【需检查的伏线】\n" + "\n".join(thread_titles))

        # v2.0：代码层一致性预扫描
        if new_content:
            checker = self.get_consistency_checker()
            issues = checker.run_all_checks(current_episode, new_content)
            if issues:
                report = checker.format_report(issues)
                sections.append(report)
            else:
                sections.append("✅ 代码层一致性预扫描：未发现明显矛盾。")

        # v2.0：节拍完成度检查
        if self.beat_outline:
            beat_check = self.beat_outline.build_doctor_beat_context(current_episode)
            if beat_check:
                sections.append(beat_check)

        if not sections:
            return ""

        return "═══ 一致性检查参考 ═══\n\n" + "\n\n".join(sections) + "\n═══ 结束 ═══"

    # ------------------------------------------------------------------
    # v2.0：一致性检查器 + 集成工具
    # ------------------------------------------------------------------

    def get_consistency_checker(self):
        """获取 ConsistencyChecker 实例（懒加载）"""
        if self._consistency_checker is None:
            from harness.consistency_checker import ConsistencyChecker
            self._consistency_checker = ConsistencyChecker(
                memory_store=self,
                scene_timeline=self.scene_timeline,
            )
        return self._consistency_checker

    def run_consistency_check(self, current_episode: int,
                              new_content: str = "") -> List:
        """运行代码层一致性预扫描（用户提出的'工具3：逻辑一致性检查'）。

        Args:
            current_episode: 当前集数
            new_content: 当前集剧本内容

        Returns:
            ConsistencyIssue 列表
        """
        checker = self.get_consistency_checker()
        return checker.run_all_checks(current_episode, new_content)

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "saved_at": datetime.now().isoformat(),
            "characters": {k: v.to_dict() for k, v in self._characters.items()},
            "plot_threads": {k: v.to_dict() for k, v in self._plot_threads.items()},
            "episode_index": self._episode_index.to_dict(),
            "style_anchors": self.style_anchors,
            "world_rules": self.world_rules,
        }

    def save(self):
        """持久化到 JSON 文件"""
        self._memory_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._memory_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self):
        """从 JSON 文件加载"""
        with open(self._memory_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._characters = {
            k: CharacterState.from_dict(v)
            for k, v in data.get("characters", {}).items()
        }
        self._plot_threads = {
            k: PlotThread.from_dict(v)
            for k, v in data.get("plot_threads", {}).items()
        }
        self._episode_index = EpisodeIndex.from_dict(data.get("episode_index", {}))
        self.style_anchors = data.get("style_anchors", [])
        self.world_rules = data.get("world_rules", [])

    def reset(self):
        """清空所有记忆（重新开始项目时使用）"""
        self._characters.clear()
        self._plot_threads.clear()
        self._episode_index = EpisodeIndex()
        self.style_anchors = []
        self.world_rules = []
        if self._memory_path.exists():
            self._memory_path.unlink()
        # v2.0：重置子模块
        if self.scene_timeline:
            self.scene_timeline.reset()
        if self.beat_outline:
            self.beat_outline.reset()

    # ------------------------------------------------------------------
    # 统计信息
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        base = {
            "characters": len(self._characters),
            "plot_threads_total": len(self._plot_threads),
            "plot_threads_active": len(self.get_active_plot_threads()),
            "episodes_indexed": len(self._episode_index._index),
        }
        # v2.0：子模块统计
        if self.scene_timeline:
            base.update({f"timeline_{k}": v for k, v in self.scene_timeline.stats.items()})
        if self.beat_outline:
            base.update({f"beat_{k}": v for k, v in self.beat_outline.stats.items()})
        return base
