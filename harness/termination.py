"""
harness/termination.py — Token 预算监控与分层终止条件

解决运行中的无限循环和 token 浪费问题：
- 当前仅 max_retry=3 硬编码终止
- 此模块提供六层终止体系 + token 预算监控

终止层级：
1. 自然终止 — Agent 自主输出"完成"/"通过"
2. 轮次限制 — 单集 Writer+Doctor 最多 N 轮（默认10）
3. Token 预算 — 单集累计消耗超预算 → 终止标记人工审核
4. 护栏触发 — 红线违规强制终止
5. 用户中断 — Streamlit 停止按钮
6. 安全拒绝 — API 返回安全拒绝信号
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
from enum import Enum, auto


# =============================================================================
# 终止原因枚举
# =============================================================================

class TerminationReason(Enum):
    NATURAL = auto()          # 自然完成
    ROUND_LIMIT = auto()      # 轮次超限
    BUDGET_EXCEEDED = auto()  # Token 预算耗尽
    GUARDRAIL = auto()        # 护栏触发（红线违规）
    USER_INTERRUPT = auto()   # 用户手动中断
    SAFETY_REJECT = auto()    # API 安全拒绝


# =============================================================================
# BudgetTracker — Token 预算追踪
# =============================================================================

@dataclass
class BudgetTracker:
    """追踪单集创作周期的 token 消耗。

    中文 token 估算：~2 characters/token（保守估计）
    """

    episode_num: int
    max_rounds: int = 10              # 单集最多 Writer+Doctor 轮次
    max_tokens_per_episode: int = 50000  # 单集 token 预算上限
    max_writer_context_tokens: int = 3000  # Writer 单次调用上下文 token 上限

    current_round: int = 0
    estimated_tokens: int = 0
    writer_calls: int = 0
    doctor_calls: int = 0
    start_time: float = 0.0

    def __post_init__(self):
        self.start_time = time.time()

    def record_writer_call(self, prompt_tokens: int, output_tokens: int):
        """记录一次 Writer 调用。"""
        self.writer_calls += 1
        self.current_round += 1
        self.estimated_tokens += prompt_tokens + output_tokens

    def record_doctor_call(self, prompt_tokens: int, output_tokens: int):
        """记录一次 Doctor 调用。"""
        self.doctor_calls += 1
        self.estimated_tokens += prompt_tokens + output_tokens

    def estimate_cn_tokens(self, text: str) -> int:
        """估算中文文本的 token 数（保守：2 char/token）。"""
        return max(1, len(text) // 2)

    def is_round_exhausted(self) -> bool:
        """轮次用尽？"""
        return self.current_round >= self.max_rounds

    def is_budget_exhausted(self) -> bool:
        """Token 预算耗尽？"""
        return self.estimated_tokens >= self.max_tokens_per_episode

    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def summary(self) -> str:
        return (
            f"第{self.episode_num}集预算："
            f"{self.estimated_tokens}/{self.max_tokens_per_episode} tokens，"
            f"第{self.current_round}/{self.max_rounds} 轮，"
            f"耗时{self.elapsed_seconds():.0f}s，"
            f"Writer×{self.writer_calls} Doctor×{self.doctor_calls}"
        )

    def to_dict(self) -> Dict:
        return {
            "episode_num": self.episode_num,
            "current_round": self.current_round,
            "max_rounds": self.max_rounds,
            "estimated_tokens": self.estimated_tokens,
            "max_tokens": self.max_tokens_per_episode,
            "writer_calls": self.writer_calls,
            "doctor_calls": self.doctor_calls,
            "elapsed_seconds": self.elapsed_seconds(),
        }


# =============================================================================
# TerminationGuard — 终止条件守卫
# =============================================================================

@dataclass
class TerminationEvent:
    """终止事件记录。"""
    reason: TerminationReason
    episode_num: int
    budget: BudgetTracker
    message: str = ""
    force_approve: bool = False  # 是否强制通过当前版本


class TerminationGuard:
    """六层终止条件守卫。

    在每轮 Writer→Doctor 循环中轮询，决定是否触发终止。

    使用方式：
        guard = TerminationGuard(budget)
        while not guard.should_terminate():
            # ... Writer → Doctor ...
            guard.tick(budget)
        event = guard.last_event
    """

    def __init__(
        self,
        budget: BudgetTracker,
        user_interrupt_check: Optional[Callable[[], bool]] = None,
    ):
        self._budget = budget
        self._user_interrupt_check = user_interrupt_check
        self._terminated = False
        self._last_event: Optional[TerminationEvent] = None
        self._events: list[TerminationEvent] = []

    @property
    def terminated(self) -> bool:
        return self._terminated

    @property
    def last_event(self) -> Optional[TerminationEvent]:
        return self._last_event

    @property
    def events(self) -> list[TerminationEvent]:
        return self._events

    def should_terminate(self, additional_check: bool = False) -> bool:
        """轮询所有终止条件。

        Returns:
            True = 应终止当前循环
        """
        b = self._budget

        # 层级6：安全拒绝（外部注入）
        if additional_check:
            self._record(TerminationEvent(
                TerminationReason.SAFETY_REJECT,
                b.episode_num, b,
                "安全策略触发终止"
            ))
            return True

        # 层级5：用户中断
        if self._user_interrupt_check and self._user_interrupt_check():
            self._record(TerminationEvent(
                TerminationReason.USER_INTERRUPT,
                b.episode_num, b,
                "用户手动中断"
            ))
            return True

        # 层级4：护栏触发（暂由 Doctor Agent 的写作红线检查替代）
        # 此处预留给后续增强

        # 层级3：Token 预算耗尽
        if b.is_budget_exhausted():
            self._record(TerminationEvent(
                TerminationReason.BUDGET_EXCEEDED,
                b.episode_num, b,
                f"Token 预算耗尽（{b.estimated_tokens}/{b.max_tokens_per_episode}），强制通过当前版本",
                force_approve=True,
            ))
            return True

        # 层级2：轮次限制
        if b.is_round_exhausted():
            self._record(TerminationEvent(
                TerminationReason.ROUND_LIMIT,
                b.episode_num, b,
                f"轮次超限（{b.current_round}/{b.max_rounds}），强制通过当前版本",
                force_approve=True,
            ))
            return True

        return False

    def mark_natural(self, msg: str = "自然完成"):
        """标记自然终止。"""
        self._record(TerminationEvent(
            TerminationReason.NATURAL,
            self._budget.episode_num, self._budget, msg
        ))

    def mark_guardrail(self, msg: str):
        """护栏触发。"""
        self._record(TerminationEvent(
            TerminationReason.GUARDRAIL,
            self._budget.episode_num, self._budget, msg
        ))

    def _record(self, event: TerminationEvent):
        self._last_event = event
        self._events.append(event)
        self._terminated = True

    def summary(self) -> str:
        """终止条件摘要。"""
        if not self._events:
            return "无终止事件"
        last = self._events[-1]
        return f"[{last.reason.name}] {last.message} | {self._budget.summary()}"
