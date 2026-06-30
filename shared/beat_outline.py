"""
shared/beat_outline.py — 分集大纲节拍追踪器
============================================

解决长剧本创作中的剧情点遗漏：
- Showrunner 生成的大纲包含每集必须完成的剧情点（节奏提示、核心钩子）
- Writer 在逐集写作时可能遗漏关键剧情点
- 本模块从大纲中自动解析节拍，追踪每集的完成度

核心类：
- BeatPoint：单个剧情节拍
- BeatOutline：分集大纲节拍管理器

设计原则：
- Showrunner 生成大纲后，代码自动解析节拍
- Writer 每次生成完一集，代码自动标记节拍完成
- Writer 下一集生成前，代码注入「待完成节拍」提醒
"""

import re
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


# =============================================================================
# BeatPoint — 单个剧情节拍
# =============================================================================

@dataclass
class BeatPoint:
    """一个具体的剧情节拍（某集必须完成的剧情点）"""

    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_SKIPPED = "skipped"

    beat_id: str                # 唯一标识（如 e5_b1）
    episode: int                # 所属集数
    order: int                  # 在本集中的顺序
    description: str            # 节拍描述
    beat_type: str = ""         # 类型：emotion/plot/hook/transition
    status: str = STATUS_PENDING
    completed_at: str = ""      # 完成时间

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "episode": self.episode,
            "order": self.order,
            "description": self.description,
            "beat_type": self.beat_type,
            "status": self.status,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BeatPoint":
        return cls(
            beat_id=data.get("beat_id", ""),
            episode=data.get("episode", 0),
            order=data.get("order", 0),
            description=data.get("description", ""),
            beat_type=data.get("beat_type", ""),
            status=data.get("status", cls.STATUS_PENDING),
            completed_at=data.get("completed_at", ""),
        )


# =============================================================================
# BeatOutline — 分集大纲节拍管理器
# =============================================================================

class BeatOutline:
    """分集大纲节拍管理器。

    从 Showrunner 大纲中自动解析每集的剧情节拍，追踪完成度。

    使用方式：
        outline = BeatOutline(project_id="我的剧本")
        outline.parse_from_showrunner_output(showrunner_text)

        # Writer 生成第5集前，获取待完成节拍
        remaining = outline.get_remaining_beats(5)
        # → "第5集还需完成：1.核心情绪点 ...  2.解决方式 ...  3.尾部钩子 ..."

        # Writer 完成后，标记节拍完成
        outline.mark_beat_done("e5_b1")

        # 检查是否有遗漏
        all_done = outline.is_episode_complete(5)
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self._beats: Dict[str, BeatPoint] = {}          # beat_id → BeatPoint
        self._episode_beats: Dict[int, List[str]] = {}  # episode → [beat_ids]
        self._total_episodes: int = 0

        self._file_path = Path("harness_data") / f"beats_{self._safe_name(project_id)}.json"
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
    # 大纲解析
    # ------------------------------------------------------------------

    def parse_from_showrunner_output(self, outline_text: str) -> int:
        """从 Showrunner 生成的大纲文本中自动解析每集的节拍。

        支持两种大纲格式：
        1. 多巴胺版：每集有「核心情绪点」「解决方式」「尾部钩子」
        2. 基础版：每集有「情绪节奏」「核心钩子」

        Returns:
            解析出的节拍总数
        """
        if not outline_text:
            return 0

        # 先提取总集数
        ep_match = re.search(r'\[总集数[:：]\s*(\d+)\]', outline_text)
        if ep_match:
            self._total_episodes = int(ep_match.group(1))

        beat_count = 0

        # ── 格式1：多巴胺版「### 第 N 集」块 ──
        episode_blocks = re.split(r'(?:###\s*)?第\s*(\d+)\s*集', outline_text)
        # episode_blocks[0] = 第1集之前的内容
        # episode_blocks[1] = 第1集的数字, episode_blocks[2] = 第1集内容
        # episode_blocks[3] = 第2集的数字, episode_blocks[4] = 第2集内容 ...

        for i in range(1, len(episode_blocks), 2):
            try:
                ep_num = int(episode_blocks[i])
                ep_text = episode_blocks[i + 1]
            except (IndexError, ValueError):
                continue

            beat_order = 0

            # 提取「核心情绪点」
            emotion_match = re.search(
                r'核心情绪点[：:]\s*(.+?)(?:\n|$)',
                ep_text, re.MULTILINE
            )
            if emotion_match:
                beat_order += 1
                beat = BeatPoint(
                    beat_id=f"e{ep_num}_b{beat_order}",
                    episode=ep_num,
                    order=beat_order,
                    description=f"核心情绪点：{emotion_match.group(1).strip()}",
                    beat_type="emotion",
                )
                self._add_beat(beat)
                beat_count += 1

            # 提取「解决方式」
            solution_match = re.search(
                r'解决方式[：:]\s*(.+?)(?:\n|$)',
                ep_text, re.MULTILINE
            )
            if solution_match:
                beat_order += 1
                beat = BeatPoint(
                    beat_id=f"e{ep_num}_b{beat_order}",
                    episode=ep_num,
                    order=beat_order,
                    description=f"解决方式：{solution_match.group(1).strip()}",
                    beat_type="plot",
                )
                self._add_beat(beat)
                beat_count += 1

            # 提取「尾部钩子」
            hook_match = re.search(
                r'尾部钩子[：:]\s*(.+?)(?:\n|$)',
                ep_text, re.MULTILINE
            )
            if hook_match:
                beat_order += 1
                beat = BeatPoint(
                    beat_id=f"e{ep_num}_b{beat_order}",
                    episode=ep_num,
                    order=beat_order,
                    description=f"尾部钩子：{hook_match.group(1).strip()}",
                    beat_type="hook",
                )
                self._add_beat(beat)
                beat_count += 1

            # ── 格式2：基础版「第 N 集：...情绪节奏：...核心钩子：...」 ──
            if beat_order == 0:
                # 尝试提取基础版格式的节拍
                rhythm_match = re.search(
                    r'情绪节奏[：:]\s*(.+?)(?:[，,]|$)',
                    ep_text, re.MULTILINE
                )
                if rhythm_match:
                    beat_order += 1
                    beat = BeatPoint(
                        beat_id=f"e{ep_num}_b{beat_order}",
                        episode=ep_num,
                        order=beat_order,
                        description=f"情绪节奏：{rhythm_match.group(1).strip()}",
                        beat_type="emotion",
                    )
                    self._add_beat(beat)
                    beat_count += 1

                core_hook_match = re.search(
                    r'核心钩子[：:]\s*(.+?)(?:\n|$)',
                    ep_text, re.MULTILINE
                )
                if core_hook_match:
                    beat_order += 1
                    beat = BeatPoint(
                        beat_id=f"e{ep_num}_b{beat_order}",
                        episode=ep_num,
                        order=beat_order,
                        description=f"核心钩子：{core_hook_match.group(1).strip()}",
                        beat_type="hook",
                    )
                    self._add_beat(beat)
                    beat_count += 1

        return beat_count

    def parse_from_custom_format(self, beats_data: List[Dict[str, Any]]) -> int:
        """从自定义格式数据中解析节拍（用于手动导入）。"""
        count = 0
        for item in beats_data:
            beat = BeatPoint.from_dict(item)
            self._add_beat(beat)
            count += 1
        return count

    def _add_beat(self, beat: BeatPoint):
        """内部：添加节拍并维护索引"""
        self._beats[beat.beat_id] = beat
        ep = beat.episode
        if ep not in self._episode_beats:
            self._episode_beats[ep] = []
        if beat.beat_id not in self._episode_beats[ep]:
            self._episode_beats[ep].append(beat.beat_id)
        # 按 order 排序
        self._episode_beats[ep].sort(
            key=lambda bid: self._beats[bid].order
        )

    # ------------------------------------------------------------------
    # 节拍状态操作
    # ------------------------------------------------------------------

    def get_outline(self, episode: int) -> List[BeatPoint]:
        """获取指定集的所有节拍"""
        beat_ids = self._episode_beats.get(episode, [])
        return [self._beats[bid] for bid in beat_ids if bid in self._beats]

    def get_remaining_beats(self, episode: int) -> List[BeatPoint]:
        """获取指定集尚未完成的节拍"""
        all_beats = self.get_outline(episode)
        return [b for b in all_beats if b.status == BeatPoint.STATUS_PENDING]

    def get_completed_beats(self, episode: int) -> List[BeatPoint]:
        """获取指定集已完成的节拍"""
        all_beats = self.get_outline(episode)
        return [b for b in all_beats if b.status == BeatPoint.STATUS_COMPLETED]

    def mark_beat_done(self, beat_id: str):
        """标记某个节拍为已完成"""
        if beat_id in self._beats:
            self._beats[beat_id].status = BeatPoint.STATUS_COMPLETED
            self._beats[beat_id].completed_at = datetime.now().isoformat()

    def mark_all_done(self, episode: int):
        """标记指定集的所有节拍为已完成"""
        for beat in self.get_remaining_beats(episode):
            beat.status = BeatPoint.STATUS_COMPLETED
            beat.completed_at = datetime.now().isoformat()

    def is_episode_complete(self, episode: int) -> bool:
        """检查指定集的所有节拍是否都已完成"""
        remaining = self.get_remaining_beats(episode)
        return len(remaining) == 0 and len(self.get_outline(episode)) > 0

    # ------------------------------------------------------------------
    # Prompt 注入
    # ------------------------------------------------------------------

    def build_writer_beat_context(self, episode: int) -> str:
        """构建注入 Writer prompt 的节拍提醒文本。

        告诉 Writer：本集必须完成哪些剧情点，哪些已经完成。
        """
        all_beats = self.get_outline(episode)
        remaining = self.get_remaining_beats(episode)

        if not all_beats:
            return "（本集无预设节拍，请根据大纲自由发挥）"

        lines = ["═══ 本集剧情节拍清单 ═══", ""]

        lines.append(f"第{episode}集共 {len(all_beats)} 个剧情节拍，"
                     f"已完成 {len(all_beats) - len(remaining)}，"
                     f"待完成 {len(remaining)}：")
        lines.append("")

        for beat in all_beats:
            status_icon = {
                BeatPoint.STATUS_COMPLETED: "✅",
                BeatPoint.STATUS_PENDING: "⬜",
                BeatPoint.STATUS_IN_PROGRESS: "🔄",
                BeatPoint.STATUS_SKIPPED: "⏭️",
            }.get(beat.status, "❓")

            type_label = {
                "emotion": "情绪",
                "plot": "情节",
                "hook": "钩子",
                "transition": "过渡",
            }.get(beat.beat_type, "")

            lines.append(f"  {status_icon} [{type_label}] {beat.description}")

        lines.append("")
        lines.append("请确保本集剧本覆盖所有 ⬜ 标记的节拍。")
        lines.append("═══ 节拍清单结束 ═══")

        return "\n".join(lines)

    def build_doctor_beat_context(self, episode: int) -> str:
        """构建注入 Doctor prompt 的节拍完成度检查文本"""
        all_beats = self.get_outline(episode)
        completed = self.get_completed_beats(episode)
        remaining = self.get_remaining_beats(episode)

        if not all_beats:
            return ""

        lines = ["═══ 节拍完成度预检查 ═══", ""]
        lines.append(f"第{episode}集应完成 {len(all_beats)} 个剧情节拍：")

        if remaining:
            lines.append(f"⚠️ 以下 {len(remaining)} 个节拍可能未完成：")
            for beat in remaining:
                lines.append(f"  · {beat.description}")
            lines.append("请在本集剧本中检查这些节拍是否确实缺失。")

        if completed:
            lines.append(f"✅ 已完成 {len(completed)} 个节拍。")

        lines.append("═══ 节拍检查结束 ═══")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        total = len(self._beats)
        completed = len([b for b in self._beats.values()
                         if b.status == BeatPoint.STATUS_COMPLETED])
        return {
            "total_episodes": self._total_episodes,
            "total_beats": total,
            "completed_beats": completed,
            "completion_rate": f"{completed / total:.0%}" if total > 0 else "0%",
        }

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "total_episodes": self._total_episodes,
            "saved_at": datetime.now().isoformat(),
            "beats": {k: v.to_dict() for k, v in self._beats.items()},
        }

    def save(self):
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self):
        with open(self._file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._total_episodes = data.get("total_episodes", 0)
        self._beats = {}
        self._episode_beats = {}
        for k, v in data.get("beats", {}).items():
            beat = BeatPoint.from_dict(v)
            self._beats[k] = beat
            ep = beat.episode
            if ep not in self._episode_beats:
                self._episode_beats[ep] = []
            self._episode_beats[ep].append(beat.beat_id)

    def reset(self):
        self._beats.clear()
        self._episode_beats.clear()
        self._total_episodes = 0
        if self._file_path.exists():
            self._file_path.unlink()
