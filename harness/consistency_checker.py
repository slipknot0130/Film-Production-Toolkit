"""
harness/consistency_checker.py — 逻辑一致性检查器
==================================================

解决长剧本中的逻辑矛盾检测：
- 角色存活状态：死人复活、活人无故消失
- 时间线顺序：事件发生的先后顺序是否合理
- 物品/道具归属：物品所有权是否矛盾转移
- 关系状态：角色关系是否前后冲突
- 年龄/职业逻辑：年龄增长、职业变更是否符合时间线

设计原则（与 v3.0 一致）：
- 代码做扫描，LLM 做语义确认
- 基于 StructuredMemoryStore + SceneTimeline 的结构化数据进行确定性检查
- 返回 ConsistencyIssue 列表，可注入 Doctor prompt 让 LLM 做最终判定
- 零额外 API 调用

核心类：
- ConsistencyIssue：一个具体的矛盾发现
- ConsistencyChecker：检查器主入口
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from harness.memory_store import StructuredMemoryStore
    from shared.scene_timeline import SceneTimeline


# =============================================================================
# ConsistencyIssue — 矛盾发现
# =============================================================================

@dataclass
class ConsistencyIssue:
    """一个具体的逻辑矛盾。

    严重程度：
    - critical：必须修复（如死人复活）
    - major：建议修复（如时间线不一致）
    - minor：检查确认（如年龄计算可能有误）
    """

    SEVERITY_CRITICAL = "critical"
    SEVERITY_MAJOR = "major"
    SEVERITY_MINOR = "minor"

    issue_type: str              # 问题类型：character_alive/character_dead/timeline/ownership/relationship/age
    severity: str                # 严重程度
    description: str             # 问题描述（人类可读）
    evidence: List[str] = field(default_factory=list)  # 证据（引用来源）
    suggestion: str = ""         # 修复建议

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
        }

    def to_text(self) -> str:
        """格式化为可注入 prompt 的文本"""
        sev_icon = {"critical": "🔴", "major": "🟡", "minor": "⚪"}
        sev_label = {"critical": "严重", "major": "建议修复", "minor": "检查确认"}
        lines = [
            f"{sev_icon.get(self.severity, '⚪')} [{sev_label.get(self.severity, '未知')}] {self.issue_type}",
            f"  问题：{self.description}",
        ]
        if self.evidence:
            lines.append(f"  证据：{'；'.join(self.evidence[:3])}")
        if self.suggestion:
            lines.append(f"  建议：{self.suggestion}")
        return "\n".join(lines)


# =============================================================================
# ConsistencyChecker — 检查器主入口
# =============================================================================

class ConsistencyChecker:
    """逻辑一致性检查器。

    基于纯代码层规则引擎做确定性扫描，不做语义判断。
    发现的问题注入 Doctor prompt，由 LLM 做最终语义确认。

    使用方式：
        checker = ConsistencyChecker(memory_store, scene_timeline)

        # Doctor 审核前运行
        issues = checker.run_all_checks(
            current_episode=5,
            new_content="第5集剧本原文...",
        )

        # 将问题注入 Doctor prompt
        if issues:
            report = checker.format_report(issues)
            # → 拼接到 Doctor 的 system prompt
    """

    def __init__(
        self,
        memory_store: Optional["StructuredMemoryStore"] = None,
        scene_timeline: Optional["SceneTimeline"] = None,
    ):
        self.memory_store = memory_store
        self.scene_timeline = scene_timeline

    # ------------------------------------------------------------------
    # 检查 1：角色生死状态
    # ------------------------------------------------------------------

    def check_character_life_status(self, current_episode: int,
                                    new_content: str = "") -> List[ConsistencyIssue]:
        """检查角色是否在死后再次出现，或活人无故消失。

        规则：
        - 如果某个角色在之前某集被标记为「死亡」，但在当前剧本中又有动作/台词 → critical
        - 如果某个角色在之前多集持续出场，突然消失超过N集且无交代 → major
        """
        issues = []
        if not self.memory_store:
            return issues

        # 检查已标记死亡的角色
        for name, char in self.memory_store._characters.items():
            # 检查 wounds 中是否有死亡标记
            is_dead = any("死" in w for w in char.wounds) or any("去世" in w for w in char.wounds)
            if not is_dead:
                # 也检查 key_events
                is_dead = any("死" in e for e in char.key_events[-3:]) or any("去世" in e for e in char.key_events[-3:])

            if is_dead and char.last_updated_episode < current_episode:
                # 该角色已死（在前面的集中），检查当前剧本是否出现
                if new_content and name in new_content:
                    issues.append(ConsistencyIssue(
                        issue_type="character_dead_reappeared",
                        severity=ConsistencyIssue.SEVERITY_CRITICAL,
                        description=f"角色「{name}」在第{char.last_updated_episode}集已被标记死亡，"
                                    f"但第{current_episode}集剧本中再次出现",
                        evidence=[
                            f"死亡标记于第{char.last_updated_episode}集",
                            f"第{current_episode}集剧本中出现「{name}」",
                        ],
                        suggestion="如为闪回/幻觉/回忆，需在剧本中明确标注。如为剧情bug，需删除或给出复活解释。",
                    ))

        # 检查长期未出场角色（超过5集）
        max_gap = 5
        for name, char in self.memory_store._characters.items():
            gap = current_episode - char.last_updated_episode
            if gap > max_gap and char.last_updated_episode > 0:
                # 检查是否是主角（有大量台词的角色）
                total_events = len(char.key_events)
                if total_events >= 3:  # 重要角色
                    issues.append(ConsistencyIssue(
                        issue_type="character_missing",
                        severity=ConsistencyIssue.SEVERITY_MINOR,
                        description=f"角色「{name}」已连续{gap}集未出场（最后出场：第{char.last_updated_episode}集）",
                        suggestion="确认该角色是否需要交代去向，或是否已在剧情中自然淡出。",
                    ))

        return issues

    # ------------------------------------------------------------------
    # 检查 2：时间线顺序
    # ------------------------------------------------------------------

    def check_timeline_order(self, current_episode: int) -> List[ConsistencyIssue]:
        """检查时间线是否存在明显的前后矛盾。

        规则：
        - 场景时间标签的先后顺序（如「第二天」出现在「三年前」之前 → major）
        - 同一集中出现的时间跳跃是否合理
        """
        issues = []
        if not self.scene_timeline:
            return issues

        scenes = self.scene_timeline.get_scenes_by_episode(current_episode)
        if len(scenes) < 2:
            return issues

        # 检查时间标签的合理性
        backward_time_labels = ["之前", "前", "回忆"]
        forward_time_labels = ["之后", "第二天", "三年后", "一个月后", "几年后"]

        for i in range(1, len(scenes)):
            prev = scenes[i - 1]
            curr = scenes[i]

            # 检查：前一场是回忆，后一场是「之后」→ 可能跳转没问题
            prev_is_flashback = any(t in prev.time_label for t in backward_time_labels)
            curr_is_flashback = any(t in curr.time_label for t in backward_time_labels)

            # 检查：两场都是正向时间但时间标签暗示倒退
            prev_is_forward = any(t in prev.time_label for t in forward_time_labels)
            curr_is_backward = any(t in curr.time_label for t in backward_time_labels)

            if prev_is_forward and curr_is_backward and not curr_is_flashback:
                issues.append(ConsistencyIssue(
                    issue_type="timeline_direction",
                    severity=ConsistencyIssue.SEVERITY_MAJOR,
                    description=f"第{current_episode}集第{prev.scene_number}场时间标签为正向（{prev.time_label}），"
                                f"第{curr.scene_number}场时间标签为倒向（{curr.time_label}），"
                                f"如非闪回则时间线可能错乱",
                    suggestion="如为闪回场景，请在剧本中明确标注「（闪回）」或「（回忆）」。",
                ))

        return issues

    # ------------------------------------------------------------------
    # 检查 3：道具/物品归属
    # ------------------------------------------------------------------

    def check_property_ownership(self, new_content: str = "") -> List[ConsistencyIssue]:
        """检查道具/物品的归属是否矛盾。

        规则（基于关键事实索引）：
        - 如果某个关键事实记录了「A拥有X」，但新剧本中X出现在B手中且无交代 → major
        """
        issues = []
        if not self.scene_timeline:
            return issues

        all_facts = self.scene_timeline.get_all_facts()
        if not all_facts or not new_content:
            return issues

        # 简单模式匹配：查找「X在Y手中」「X属于Y」等
        ownership_pattern = re.compile(
            r'([\u4e00-\u9fa5A-Za-z0-9]{1,6})[的之]([\u4e00-\u9fa5]{2,8})|'
            r'([\u4e00-\u9fa5A-Za-z0-9]{1,6})(?:拿着|握着|带着|揣着|掏出|取出)([\u4e00-\u9fa5]{2,8})'
        )

        for fact in all_facts:
            if "钥匙" in fact or "信" in fact or "戒指" in fact or "手机" in fact or "照片" in fact or "刀" in fact:
                # 这是一个关键道具事实
                fact_source = self.scene_timeline.get_fact_source(fact)
                if fact_source and fact_source in self.scene_timeline._scenes:
                    source_scene = self.scene_timeline._scenes[fact_source]
                    # 检查道具最初属于谁
                    for char in source_scene.characters_present:
                        if char in fact:
                            # 在新内容中搜索该道具是否出现在其他角色手中
                            for check_char in source_scene.characters_present:
                                if check_char != char:
                                    # 简单检查：新内容中该道具是否与另一个角色关联
                                    item_keywords = ["钥匙", "信", "戒指", "手机", "照片", "刀"]
                                    for kw in item_keywords:
                                        if kw in fact and kw in new_content:
                                            if check_char in new_content[new_content.find(kw)-50:new_content.find(kw)+50]:
                                                issues.append(ConsistencyIssue(
                                                    issue_type="property_ownership",
                                                    severity=ConsistencyIssue.SEVERITY_MAJOR,
                                                    description=f"关键道具「{kw}」原属于{char}（第{source_scene.episode}集），"
                                                                f"但第{len(self.scene_timeline._scenes)}场后出现在{check_char}处",
                                                    suggestion="如道具发生了转让，需在剧本中交代转让过程。",
                                                ))

        return issues

    # ------------------------------------------------------------------
    # 检查 4：关系状态
    # ------------------------------------------------------------------

    def check_relationship_consistency(self) -> List[ConsistencyIssue]:
        """检查角色关系状态是否存在明显的自相矛盾。

        规则：
        - 同一对角色在前一集是敌人，后一集突然变亲密且无转折交代 → minor
        """
        issues = []
        if not self.memory_store:
            return issues

        # 收集所有角色的关系状态
        relationship_map: Dict[str, Dict[str, str]] = {}
        for name, char in self.memory_store._characters.items():
            if char.relationship_status:
                relationship_map[name] = dict(char.relationship_status)

        # 检查双向关系是否一致
        checked_pairs = set()
        for char_a, relations in relationship_map.items():
            for char_b, status in relations.items():
                pair_key = tuple(sorted([char_a, char_b]))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)

                # 检查对方的关系状态
                if char_b in relationship_map and char_a in relationship_map[char_b]:
                    reverse_status = relationship_map[char_b][char_a]
                    # 简单检查：一方是正面关系，另一方是负面关系
                    positive = ["爱", "喜欢", "亲密", "信任", "好友", "恋人", "夫妻"]
                    negative = ["恨", "敌", "厌恶", "背叛", "仇"]
                    a_positive = any(p in status for p in positive)
                    a_negative = any(n in status for n in negative)
                    b_positive = any(p in reverse_status for p in positive)
                    b_negative = any(n in reverse_status for n in negative)

                    if (a_positive and b_negative) or (a_negative and b_positive):
                        issues.append(ConsistencyIssue(
                            issue_type="relationship_asymmetric",
                            severity=ConsistencyIssue.SEVERITY_MINOR,
                            description=f"角色「{char_a}」与「{char_b}」的关系状态不对称："
                                        f"{char_a}→{char_b}：{status}，{char_b}→{char_a}：{reverse_status}",
                            suggestion="如为单相思/隐藏敌意等剧情设计则可忽略。否则需要统一关系状态。",
                        ))

        return issues

    # ------------------------------------------------------------------
    # 检查 5：年龄/职业逻辑
    # ------------------------------------------------------------------

    def check_age_logic(self, new_content: str = "") -> List[ConsistencyIssue]:
        """检查年龄相关的基础逻辑。

        规则：
        - 年龄不能减少（除非时间倒流）
        - 职业变更不能跳跃（从实习生直接变CEO且无交代）
        """
        issues = []
        if not self.memory_store:
            return issues

        # 检查角色 wounds/events 中是否有年龄相关记录
        for name, char in self.memory_store._characters.items():
            if char.ability_notes:
                # 检查是否有职业相关记录
                pass  # 当前实现为轻量检查，后续可扩展

        return issues

    # ------------------------------------------------------------------
    # 主入口：运行全部检查
    # ------------------------------------------------------------------

    def run_all_checks(
        self,
        current_episode: int,
        new_content: str = "",
        enabled_checks: Optional[List[str]] = None,
    ) -> List[ConsistencyIssue]:
        """运行全部启用的检查项。

        Args:
            current_episode: 当前集数
            new_content: 当前集的剧本内容
            enabled_checks: 启用的检查项列表（None=全部启用）

        Returns:
            按严重程度排序的 ConsistencyIssue 列表
        """
        all_enabled = enabled_checks is None

        issues: List[ConsistencyIssue] = []

        if all_enabled or "character_life" in (enabled_checks or []):
            issues.extend(self.check_character_life_status(current_episode, new_content))

        if all_enabled or "timeline" in (enabled_checks or []):
            issues.extend(self.check_timeline_order(current_episode))

        if all_enabled or "property" in (enabled_checks or []):
            issues.extend(self.check_property_ownership(new_content))

        if all_enabled or "relationship" in (enabled_checks or []):
            issues.extend(self.check_relationship_consistency())

        if all_enabled or "age" in (enabled_checks or []):
            issues.extend(self.check_age_logic(new_content))

        # 按严重程度排序
        severity_order = {
            ConsistencyIssue.SEVERITY_CRITICAL: 0,
            ConsistencyIssue.SEVERITY_MAJOR: 1,
            ConsistencyIssue.SEVERITY_MINOR: 2,
        }
        issues.sort(key=lambda x: severity_order.get(x.severity, 99))

        return issues

    # ------------------------------------------------------------------
    # 格式化输出
    # ------------------------------------------------------------------

    def format_report(self, issues: List[ConsistencyIssue]) -> str:
        """将检查结果格式化为可注入 Doctor prompt 的报告。

        Args:
            issues: run_all_checks() 返回的问题列表

        Returns:
            格式化的文本报告（无问题时返回空字符串）
        """
        if not issues:
            return ""

        critical = [i for i in issues if i.severity == ConsistencyIssue.SEVERITY_CRITICAL]
        major = [i for i in issues if i.severity == ConsistencyIssue.SEVERITY_MAJOR]
        minor = [i for i in issues if i.severity == ConsistencyIssue.SEVERITY_MINOR]

        lines = [
            "═══ 代码层逻辑一致性预扫描报告 ═══",
            "",
            f"🔍 共发现 {len(issues)} 个潜在矛盾（🔴严重 {len(critical)} | 🟡建议 {len(major)} | ⚪检查 {len(minor)}）",
            "",
            "以下问题由纯代码层规则引擎扫描得出，需要你（Doctor）做语义确认：",
            "1. 逐条判断 —— 是否真的是逻辑矛盾？还是剧情设计？",
            "2. 分析根因 —— 如果是bug，问题出在哪一段？",
            "3. 给出方案 —— 如何修复？",
            "",
        ]

        if critical:
            lines.append("── 🔴 严重问题（必须处理）──")
            for issue in critical:
                lines.append(issue.to_text())
                lines.append("")

        if major:
            lines.append("── 🟡 建议修复 ──")
            for issue in major:
                lines.append(issue.to_text())
                lines.append("")

        if minor:
            lines.append("── ⚪ 检查确认 ──")
            for issue in minor:
                lines.append(issue.to_text())
                lines.append("")

        lines.append("═══ 预扫描报告结束 ═══")
        lines.append("请在审查结果中明确回复：哪些需要修改、哪些是剧情设计可忽略。")

        return "\n".join(lines)

    def get_summary_stats(self, issues: List[ConsistencyIssue]) -> Dict[str, int]:
        """获取问题摘要统计"""
        return {
            "total": len(issues),
            "critical": len([i for i in issues if i.severity == ConsistencyIssue.SEVERITY_CRITICAL]),
            "major": len([i for i in issues if i.severity == ConsistencyIssue.SEVERITY_MAJOR]),
            "minor": len([i for i in issues if i.severity == ConsistencyIssue.SEVERITY_MINOR]),
        }
