"""
shared/scene_timeline.py — 场景级时间线数据库
==============================================

解决长剧本创作中的场景级上下文断裂：
- 现有 EpisodeIndex 只在「集」粒度记录摘要
- 本模块提供「场景」粒度的时间线，精准追踪每场戏的时间/地点/人物/关键事实
- 与 StructuredMemoryStore 集成，为 Writer/Doctor 提供精确的场景上下文

核心类：
- SceneRecord：单场戏的完整记录
- SceneTimeline：时间线主管理器（JSON 可持久化）

设计原则（与 v3.0 一致）：
- 代码做记录，LLM 做创意
- 每场戏写完后由代码自动记录，LLM 无需记忆
- Writer 生成下一场戏前，代码层自动注入前情提要
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any


# =============================================================================
# SceneRecord — 单场戏记录
# =============================================================================

class SceneRecord:
    """单场戏的完整结构化记录。

    每场戏写完后由 agents_engine 代码层自动调用 add_scene() 记录。
    """

    def __init__(
        self,
        scene_id: str,
        episode: int,
        scene_number: int,
    ):
        self.scene_id = scene_id
        self.episode = episode
        self.scene_number = scene_number

        # 时空信息
        self.location: str = ""           # 地点（如"黑水林深处""市中心咖啡馆"）
        self.location_type: str = ""      # 内景/外景
        self.time_of_day: str = ""        # 时间（如"深夜""周一下午"）
        self.time_label: str = ""         # 时间标签（如"三年前""第二天"）
        self.season: str = ""             # 季节

        # 人物信息
        self.characters_present: List[str] = []   # 出场角色

        # 剧情信息
        self.summary: str = ""            # 本场摘要（≤200字）
        self.key_facts: List[str] = []    # 新写入的关键事实（如"钥匙藏在花盆下"）
        self.emotion_tone: str = ""       # 情绪基调（紧张/温馨/悲伤/悬疑...）

        # 伏笔信息
        self.foreshadowing_planted: List[str] = []  # 本场埋下的伏笔
        self.foreshadowing_revealed: List[str] = []  # 本场揭晓的伏笔

        # 元信息
        self.word_count: int = 0          # 本场字数
        self.timestamp: str = ""          # 记录时间

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "episode": self.episode,
            "scene_number": self.scene_number,
            "location": self.location,
            "location_type": self.location_type,
            "time_of_day": self.time_of_day,
            "time_label": self.time_label,
            "season": self.season,
            "characters_present": self.characters_present,
            "summary": self.summary,
            "key_facts": self.key_facts,
            "emotion_tone": self.emotion_tone,
            "foreshadowing_planted": self.foreshadowing_planted,
            "foreshadowing_revealed": self.foreshadowing_revealed,
            "word_count": self.word_count,
            "timestamp": self.timestamp or datetime.now().isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneRecord":
        rec = cls(
            scene_id=data.get("scene_id", ""),
            episode=data.get("episode", 1),
            scene_number=data.get("scene_number", 1),
        )
        rec.location = data.get("location", "")
        rec.location_type = data.get("location_type", "")
        rec.time_of_day = data.get("time_of_day", "")
        rec.time_label = data.get("time_label", "")
        rec.season = data.get("season", "")
        rec.characters_present = data.get("characters_present", [])
        rec.summary = data.get("summary", "")
        rec.key_facts = data.get("key_facts", [])
        rec.emotion_tone = data.get("emotion_tone", "")
        rec.foreshadowing_planted = data.get("foreshadowing_planted", [])
        rec.foreshadowing_revealed = data.get("foreshadowing_revealed", [])
        rec.word_count = data.get("word_count", 0)
        rec.timestamp = data.get("timestamp", "")
        return rec

    def to_summary_text(self) -> str:
        """生成本场戏的一句话摘要（注入 prompt）"""
        parts = [f"第{self.episode}集第{self.scene_number}场"]
        if self.location:
            parts.append(self.location)
        if self.time_of_day:
            parts.append(self.time_of_day)
        chars = "、".join(self.characters_present[:4])
        if chars:
            parts.append(f"出场：{chars}")
        if self.summary:
            parts.append(self.summary[:120])
        return " | ".join(parts)

    def to_full_context(self) -> str:
        """生成完整上下文（供 Writer 注入）"""
        lines = [
            f"【第{self.episode}集 · 第{self.scene_number}场】",
            f"地点：{self.location or '未知'}（{self.location_type or '未知'}）",
            f"时间：{self.time_of_day or '未知'}{(' / ' + self.time_label) if self.time_label else ''}",
        ]
        if self.characters_present:
            lines.append(f"出场角色：{'、'.join(self.characters_present)}")
        if self.summary:
            lines.append(f"情节：{self.summary}")
        if self.key_facts:
            lines.append(f"关键事实：{'；'.join(self.key_facts)}")
        if self.foreshadowing_planted:
            lines.append(f"埋下伏笔：{'；'.join(self.foreshadowing_planted)}")
        if self.emotion_tone:
            lines.append(f"情绪：{self.emotion_tone}")
        return "\n".join(lines)


# =============================================================================
# SceneTimeline — 时间线主管理器
# =============================================================================

class SceneTimeline:
    """场景级时间线数据库。

    记录每一场戏的结构化信息，支持按集/场景/角色/地点查询。

    使用方式：
        timeline = SceneTimeline(project_id="我的剧本")

        # 写完后自动记录
        timeline.add_scene(SceneRecord(
            scene_id="e5_s3",
            episode=5, scene_number=3,
            location="黑水林深处", location_type="外景",
            time_of_day="深夜", time_label="婚礼当晚",
            characters_present=["钱阿龙"],
            summary="钱阿龙独自进入黑水林，在古榕树下发现上吊绳",
            key_facts=["上吊绳系在古榕树枝上", "钱阿龙左脸有勒痕"],
            foreshadowing_planted=["上吊绳是谁挂的？"],
            emotion_tone="悬疑恐怖",
        ))

        # Writer 写下一场前注入上下文
        prev = timeline.get_previous_scenes(episode=5, n=3)
        # → 返回最近3场戏的摘要文本

        # 持久化
        timeline.save()
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self._scenes: Dict[str, SceneRecord] = {}
        self._scene_order: List[str] = []  # 按写入顺序排列的 scene_id

        # 索引：辅助快速查询
        self._episode_index: Dict[int, List[str]] = {}   # episode → [scene_ids]
        self._character_index: Dict[str, List[str]] = {}  # character → [scene_ids]
        self._location_index: Dict[str, List[str]] = {}   # location → [scene_ids]
        self._fact_index: Dict[str, str] = {}             # fact → scene_id

        # 持久化路径
        self._file_path = Path("harness_data") / f"timeline_{self._safe_name(project_id)}.json"
        if self._file_path.exists():
            try:
                self.load()
            except Exception:
                pass

    @staticmethod
    def _safe_name(name: str) -> str:
        safe = ""
        for c in name:
            if c.isalnum() or c in ("-", "_", ".", " "):
                safe += c
            else:
                safe += "_"
        return safe.strip() or "default"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_scene(self, record: SceneRecord):
        """添加一场戏的记录，自动更新索引"""
        if not record.timestamp:
            record.timestamp = datetime.now().isoformat()

        self._scenes[record.scene_id] = record
        self._scene_order.append(record.scene_id)

        # 更新集索引
        ep = record.episode
        if ep not in self._episode_index:
            self._episode_index[ep] = []
        self._episode_index[ep].append(record.scene_id)

        # 更新角色索引
        for char in record.characters_present:
            if char not in self._character_index:
                self._character_index[char] = []
            self._character_index[char].append(record.scene_id)

        # 更新地点索引
        loc = record.location
        if loc:
            if loc not in self._location_index:
                self._location_index[loc] = []
            self._location_index[loc].append(record.scene_id)

        # 更新事实索引
        for fact in record.key_facts:
            self._fact_index[fact] = record.scene_id

    def get_scene(self, scene_id: str) -> Optional[SceneRecord]:
        return self._scenes.get(scene_id)

    def get_scenes_by_episode(self, episode: int) -> List[SceneRecord]:
        """获取指定集的所有场景记录（按场景号排序）"""
        ids = self._episode_index.get(episode, [])
        records = [self._scenes[sid] for sid in ids if sid in self._scenes]
        records.sort(key=lambda r: r.scene_number)
        return records

    def get_previous_scenes(self, episode: int, n: int = 3,
                            before_scene: Optional[int] = None) -> List[SceneRecord]:
        """获取指定集之前的最近 n 场戏。

        Args:
            episode: 当前集数
            n: 返回几场
            before_scene: 当前场景号（None=返回上一集最后n场）

        Returns:
            按时间顺序排列的场景记录列表
        """
        results: List[SceneRecord] = []

        # 当前集内、before_scene 之前的场景也纳入候选
        # （修复原死代码：循环从 episode-1 开始，ep 永远 != episode，原过滤永不生效）
        if before_scene is not None:
            cur_scenes = [s for s in self.get_scenes_by_episode(episode)
                          if s.scene_number < before_scene]
            for s in reversed(cur_scenes):
                results.append(s)
                if len(results) >= n:
                    results.reverse()
                    return results

        # 再收集之前各集的场景（从上一集往前回溯）
        for ep in range(episode - 1, 0, -1):
            ep_scenes = self.get_scenes_by_episode(ep)
            for s in reversed(ep_scenes):
                results.append(s)
                if len(results) >= n:
                    results.reverse()
                    return results

        results.reverse()
        return results

    def get_scenes_by_character(self, character_name: str) -> List[SceneRecord]:
        """获取指定角色出场过的所有场景"""
        ids = self._character_index.get(character_name, [])
        return [self._scenes[sid] for sid in ids if sid in self._scenes]

    def get_scenes_by_location(self, location: str) -> List[SceneRecord]:
        """获取在指定地点发生的所有场景"""
        ids = self._location_index.get(location, [])
        return [self._scenes[sid] for sid in ids if sid in self._scenes]

    def get_fact_source(self, fact_text: str) -> Optional[str]:
        """查找某个事实最初是在哪场戏中写入的"""
        return self._fact_index.get(fact_text)

    def get_current_timeline_context(self, episode: int,
                                     scene_number: int = 0) -> str:
        """生成「当前时间线上下文」，供 Writer 注入 prompt。

        包含：
        - 最近3场戏的摘要
        - 当前场景之前的时空信息
        - 角色出场记录

        Args:
            episode: 当前集数
            scene_number: 当前场景号（0 = 获取上一集最后场景的上下文）

        Returns:
            格式化的上下文字符串
        """
        prev_scenes = self.get_previous_scenes(episode, n=3,
                                                before_scene=scene_number if scene_number > 0 else None)

        if not prev_scenes:
            return "（暂无前情场景记录）"

        lines = ["═══ 场景时间线上下文 ═══", ""]
        for s in prev_scenes:
            lines.append(s.to_summary_text())

        # 统计关键事实
        all_facts = []
        for s in prev_scenes:
            all_facts.extend(s.key_facts)
        if all_facts:
            lines.append("")
            lines.append(f"📌 已知关键事实（共{len(all_facts)}条）：")
            for f in all_facts[-10:]:  # 最多10条
                lines.append(f"  · {f}")

        # 统计未揭晓伏笔
        all_planted = []
        for s in prev_scenes:
            all_planted.extend(s.foreshadowing_planted)
        all_revealed = set()
        for s in prev_scenes:
            all_revealed.update(s.foreshadowing_revealed)
        pending = [f for f in all_planted if f not in all_revealed]
        if pending:
            lines.append("")
            lines.append(f"🔮 待揭晓伏笔（{len(pending)}条）：")
            for f in pending[-5:]:
                lines.append(f"  · {f}")

        lines.append("")
        lines.append("═══ 时间线上下文结束 ═══")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 快速查询
    # ------------------------------------------------------------------

    def get_all_facts(self) -> List[str]:
        """获取所有已记录的关键事实"""
        return list(self._fact_index.keys())

    def get_all_characters(self) -> List[str]:
        """获取所有出场过的角色名"""
        return list(self._character_index.keys())

    def get_all_locations(self) -> List[str]:
        """获取所有出现过的地点"""
        return list(self._location_index.keys())

    def get_chapter_structure(self, episode: int) -> str:
        """获取某一集的场景结构概览（场次列表）"""
        scenes = self.get_scenes_by_episode(episode)
        if not scenes:
            return f"第{episode}集：暂无场景记录"
        lines = [f"第{episode}集场景结构（{len(scenes)}场）："]
        for s in scenes:
            lines.append(f"  第{s.scene_number}场 | {s.location} | {s.time_of_day} | "
                         f"{'、'.join(s.characters_present[:3])} | {s.summary[:50]}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "total_scenes": len(self._scenes),
            "total_episodes": len(self._episode_index),
            "total_characters": len(self._character_index),
            "total_locations": len(self._location_index),
            "total_facts": len(self._fact_index),
        }

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "saved_at": datetime.now().isoformat(),
            "stats": self.stats,
            "scenes": {k: v.to_dict() for k, v in self._scenes.items()},
            "scene_order": self._scene_order,
        }

    def save(self):
        """持久化到 JSON"""
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self):
        """从 JSON 加载"""
        with open(self._file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._scenes = {}
        for k, v in data.get("scenes", {}).items():
            rec = SceneRecord.from_dict(v)
            self._scenes[k] = rec

        self._scene_order = data.get("scene_order", list(self._scenes.keys()))

        # 重建索引
        self._episode_index = {}
        self._character_index = {}
        self._location_index = {}
        self._fact_index = {}

        for sid, rec in self._scenes.items():
            ep = rec.episode
            if ep not in self._episode_index:
                self._episode_index[ep] = []
            self._episode_index[ep].append(sid)

            for char in rec.characters_present:
                if char not in self._character_index:
                    self._character_index[char] = []
                self._character_index[char].append(sid)

            if rec.location:
                if rec.location not in self._location_index:
                    self._location_index[rec.location] = []
                self._location_index[rec.location].append(sid)

            for fact in rec.key_facts:
                self._fact_index[fact] = sid

    def reset(self):
        """清空所有记录"""
        self._scenes.clear()
        self._scene_order.clear()
        self._episode_index.clear()
        self._character_index.clear()
        self._location_index.clear()
        self._fact_index.clear()
        if self._file_path.exists():
            self._file_path.unlink()
