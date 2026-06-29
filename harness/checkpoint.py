"""
harness/checkpoint.py — 断点续传系统

为 Streamlit 应用提供会话状态持久化能力，防止刷新页面或意外中断导致进度丢失。
与现有 session.py 共存，不替换现有机制，作为增量增强。

核心类：
- WorkflowContext：封装需要持久化的工作流状态
- CheckpointManager：管理 checkpoint 的保存、加载、列表、删除
"""

import json
import time
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

from .config import get_harness_config


def _get_st():
    """延迟导入 streamlit，避免在非 Streamlit 环境中报错"""
    import streamlit as st  # noqa: PLC0415
    return st


# =============================================================================
# WorkflowContext — 工作流上下文封装
# =============================================================================

class WorkflowContext:
    """工作流上下文，封装需要持久化的状态（持久态）

    设计原则：
    - 只持久化必要状态，避免保存临时变量
    - 与 session.py 的命名空间前缀保持一致
    - 支持 Streamlit session_state 双向同步

    注意：与 creator.agents_engine.WorkflowContext 同名但用途不同。
    本类是重载类，管理持久化断点；agents_engine 中是轻量 dataclass，
    用于 Agent 间数据流。
    """

    def __init__(self, workflow_type: str = "creator"):
        """
        Args:
            workflow_type: "creator" 或 "production"
        """
        self.workflow_type = workflow_type
        self.timestamp = time.time()
        self.checkpoint_id = self._generate_id()
        self.name = ""  # 用户可自定义的 checkpoint 名称

        # === 创作流状态 ===
        self.outline = ""
        self.character_settings = ""
        self.script_content = ""
        self.memory_snapshot = ""
        self.current_episode = 0
        self.total_episodes = 0
        self.workflow_stage = 0          # 对应 session.py 中 CREATOR_IDLE/OUTLINE/SCRIPTS
        self.workflow_running = False

        # 阶段一参数
        self.stage1_outline = ""
        self.stage1_total_episodes = 0
        self.stage1_creative_idea = ""

        # HITL 状态
        self.hitl_previous_outline = ""
        self.hitl_previous_episode_scripts: Dict[str, str] = {}
        self.hitl_editing_episode = 0
        self.last_doctor_rejection: Dict = {}

        # 日志（只保最近100条）
        self.logs: List[str] = []

        # === 制片流状态（预留）===
        self.production_last_result = None
        self.production_last_pro_budget = None

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _generate_id(self) -> str:
        """生成唯一的 checkpoint ID"""
        raw = f"{self.timestamp}_{id(self)}"
        hash_val = hashlib.md5(raw.encode()).hexdigest()[:8]
        return f"checkpoint_{int(self.timestamp)}_{hash_val}"

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，用于 JSON 序列化"""
        return {
            "workflow_type": self.workflow_type,
            "timestamp": self.timestamp,
            "checkpoint_id": self.checkpoint_id,
            "name": self.name,
            "readable_time": datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
            # 创作流
            "outline": self.outline,
            "character_settings": self.character_settings,
            "script_content": self.script_content,
            "memory_snapshot": self.memory_snapshot,
            "current_episode": self.current_episode,
            "total_episodes": self.total_episodes,
            "workflow_stage": self.workflow_stage,
            "workflow_running": False,          # 恢复时不保留 running 状态
            "stage1_outline": self.stage1_outline,
            "stage1_total_episodes": self.stage1_total_episodes,
            "stage1_creative_idea": self.stage1_creative_idea,
            "hitl_previous_outline": self.hitl_previous_outline,
            "hitl_previous_episode_scripts": self.hitl_previous_episode_scripts,
            "hitl_editing_episode": self.hitl_editing_episode,
            "last_doctor_rejection": self.last_doctor_rejection,
            "logs": self.logs[-100:],
            # 制片流
            "production_last_result": self.production_last_result,
            "production_last_pro_budget": self.production_last_pro_budget,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowContext":
        """从字典加载"""
        ctx = cls(workflow_type=data.get("workflow_type", "creator"))
        ctx.timestamp = data.get("timestamp", time.time())
        ctx.checkpoint_id = data.get("checkpoint_id", ctx._generate_id())
        ctx.name = data.get("name", "")
        ctx.outline = data.get("outline", "")
        ctx.character_settings = data.get("character_settings", "")
        ctx.script_content = data.get("script_content", "")
        ctx.memory_snapshot = data.get("memory_snapshot", "")
        ctx.current_episode = data.get("current_episode", 0)
        ctx.total_episodes = data.get("total_episodes", 0)
        ctx.workflow_stage = data.get("workflow_stage", 0)
        ctx.workflow_running = False       # 恢复后总是 False
        ctx.stage1_outline = data.get("stage1_outline", "")
        ctx.stage1_total_episodes = data.get("stage1_total_episodes", 0)
        ctx.stage1_creative_idea = data.get("stage1_creative_idea", "")
        ctx.hitl_previous_outline = data.get("hitl_previous_outline", "")
        ctx.hitl_previous_episode_scripts = data.get("hitl_previous_episode_scripts", {})
        ctx.hitl_editing_episode = data.get("hitl_editing_episode", 0)
        ctx.last_doctor_rejection = data.get("last_doctor_rejection", {})
        ctx.logs = data.get("logs", [])
        ctx.production_last_result = data.get("production_last_result")
        ctx.production_last_pro_budget = data.get("production_last_pro_budget")
        return ctx

    def save_to_file(self, filepath: str):
        """保存到 JSON 文件"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load_from_file(cls, filepath: str) -> "WorkflowContext":
        """从 JSON 文件加载"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    # ------------------------------------------------------------------
    # Streamlit session_state 同步
    # ------------------------------------------------------------------

    def from_streamlit_session(self, prefix: str = "creator_"):
        """从 Streamlit session_state 加载状态"""
        s = _get_st().session_state
        self.outline = s.get(f"{prefix}global_outline", "")
        self.character_settings = s.get(f"{prefix}character_settings", "")
        self.script_content = s.get(f"{prefix}script_content", "")
        self.memory_snapshot = s.get(f"{prefix}memory_snapshot", "")
        self.current_episode = s.get(f"{prefix}current_episode", 0)
        self.total_episodes = s.get(f"{prefix}total_episodes", 0)
        self.workflow_stage = s.get(f"{prefix}workflow_stage", 0)
        self.workflow_running = s.get(f"{prefix}workflow_running", False)
        self.stage1_outline = s.get(f"{prefix}stage1_outline", "")
        self.stage1_total_episodes = s.get(f"{prefix}stage1_total_episodes", 0)
        self.stage1_creative_idea = s.get(f"{prefix}stage1_creative_idea", "")
        self.hitl_previous_outline = s.get(f"{prefix}hitl_previous_outline", "")
        self.hitl_previous_episode_scripts = s.get(f"{prefix}hitl_previous_episode_scripts", {})
        self.hitl_editing_episode = s.get(f"{prefix}hitl_editing_episode", 0)
        self.last_doctor_rejection = s.get(f"{prefix}last_doctor_rejection", {})
        self.logs = list(s.get(f"{prefix}logs", []))

        if prefix.startswith("production"):
            self.production_last_result = s.get("production_last_result")
            self.production_last_pro_budget = s.get("production_last_pro_budget")

    def to_streamlit_session(self, prefix: str = "creator_"):
        """将上下文写回 Streamlit session_state"""
        s = _get_st().session_state
        s[f"{prefix}global_outline"] = self.outline
        s[f"{prefix}character_settings"] = self.character_settings
        s[f"{prefix}script_content"] = self.script_content
        s[f"{prefix}memory_snapshot"] = self.memory_snapshot
        s[f"{prefix}current_episode"] = self.current_episode
        s[f"{prefix}total_episodes"] = self.total_episodes
        s[f"{prefix}workflow_stage"] = self.workflow_stage
        s[f"{prefix}workflow_running"] = False   # 恢复后总是 False
        s[f"{prefix}stage1_outline"] = self.stage1_outline
        s[f"{prefix}stage1_total_episodes"] = self.stage1_total_episodes
        s[f"{prefix}stage1_creative_idea"] = self.stage1_creative_idea
        s[f"{prefix}hitl_previous_outline"] = self.hitl_previous_outline
        s[f"{prefix}hitl_previous_episode_scripts"] = self.hitl_previous_episode_scripts
        s[f"{prefix}hitl_editing_episode"] = self.hitl_editing_episode
        s[f"{prefix}last_doctor_rejection"] = self.last_doctor_rejection
        s[f"{prefix}logs"] = list(self.logs)

        if prefix.startswith("production"):
            if self.production_last_result is not None:
                s["production_last_result"] = self.production_last_result
            if self.production_last_pro_budget is not None:
                s["production_last_pro_budget"] = self.production_last_pro_budget

    # ------------------------------------------------------------------
    # 便捷属性
    # ------------------------------------------------------------------

    @property
    def display_name(self) -> str:
        """UI 显示名称"""
        ts = datetime.fromtimestamp(self.timestamp).strftime("%m-%d %H:%M")
        if self.name:
            return f"{self.name}（{ts}）"
        if self.total_episodes > 0:
            progress = f"{self.current_episode}/{self.total_episodes}集"
            return f"进度 {progress}（{ts}）"
        if self.outline:
            # 取大纲第一行作为摘要
            first_line = self.outline.split("\n")[0][:20]
            return f"{first_line}...（{ts}）"
        return f"未命名存档（{ts}）"

    @property
    def has_content(self) -> bool:
        """是否有实质内容"""
        return bool(self.outline or self.script_content)

    @property
    def progress_str(self) -> str:
        """进度字符串"""
        if self.total_episodes > 0:
            return f"{self.current_episode}/{self.total_episodes}集"
        if self.outline:
            return "已生成大纲"
        return "空"


# =============================================================================
# CheckpointManager — checkpoint 生命周期管理
# =============================================================================

class CheckpointManager:
    """管理 Checkpoint 的保存、加载、列表、删除

    使用方式：
        manager = CheckpointManager()

        # 保存当前 session 状态
        ctx = manager.save_current("我的存档名")

        # 列出所有 checkpoint
        checkpoints = manager.list_checkpoints()

        # 加载 checkpoint 到 session
        manager.restore(checkpoint_id)

        # 删除 checkpoint
        manager.delete(checkpoint_id)
    """

    def __init__(self, config=None):
        """
        Args:
            config: HarnessConfig 实例，不传则使用全局配置
        """
        self.config = config or get_harness_config()
        self.checkpoint_dir = Path(self.config.checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 核心操作
    # ------------------------------------------------------------------

    def save_current(
        self,
        name: str = "",
        prefix: str = "creator_",
        workflow_type: str = "creator",
    ) -> WorkflowContext:
        """从当前 Streamlit session_state 保存 checkpoint

        Args:
            name: 用户自定义名称（可选）
            prefix: session_state 前缀
            workflow_type: 工作流类型

        Returns:
            保存的 WorkflowContext
        """
        ctx = WorkflowContext(workflow_type=workflow_type)
        ctx.name = name
        ctx.from_streamlit_session(prefix=prefix)

        # 只有实质内容才保存
        if not ctx.has_content:
            return ctx

        filepath = self.checkpoint_dir / f"{ctx.checkpoint_id}.json"
        ctx.save_to_file(str(filepath))

        # 清理超出数量限制的旧 checkpoint
        self._cleanup_old_checkpoints()

        return ctx

    def restore(
        self,
        checkpoint_id: str,
        prefix: str = "creator_",
    ) -> Optional[WorkflowContext]:
        """从 checkpoint 恢复 session_state

        Args:
            checkpoint_id: checkpoint ID
            prefix: session_state 前缀

        Returns:
            恢复的 WorkflowContext，失败返回 None
        """
        filepath = self.checkpoint_dir / f"{checkpoint_id}.json"
        if not filepath.exists():
            return None

        try:
            ctx = WorkflowContext.load_from_file(str(filepath))
            ctx.to_streamlit_session(prefix=prefix)
            return ctx
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def list_checkpoints(
        self,
        workflow_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[WorkflowContext]:
        """列出所有 checkpoint（按时间倒序）

        Args:
            workflow_type: 过滤类型（None=全部）
            limit: 最多返回数量

        Returns:
            WorkflowContext 列表
        """
        checkpoints: List[WorkflowContext] = []
        for fp in self.checkpoint_dir.glob("checkpoint_*.json"):
            try:
                ctx = WorkflowContext.load_from_file(str(fp))
                if workflow_type is None or ctx.workflow_type == workflow_type:
                    checkpoints.append(ctx)
            except Exception:
                continue

        # 按时间倒序
        checkpoints.sort(key=lambda c: c.timestamp, reverse=True)
        return checkpoints[:limit]

    def delete(self, checkpoint_id: str) -> bool:
        """删除指定 checkpoint

        Returns:
            成功返回 True，文件不存在返回 False
        """
        filepath = self.checkpoint_dir / f"{checkpoint_id}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def delete_all(self, workflow_type: Optional[str] = None):
        """删除所有 checkpoint（谨慎使用）"""
        for fp in self.checkpoint_dir.glob("checkpoint_*.json"):
            try:
                ctx = WorkflowContext.load_from_file(str(fp))
                if workflow_type is None or ctx.workflow_type == workflow_type:
                    fp.unlink()
            except Exception:
                fp.unlink()

    def get(self, checkpoint_id: str) -> Optional[WorkflowContext]:
        """获取指定 checkpoint（不写入 session_state）"""
        filepath = self.checkpoint_dir / f"{checkpoint_id}.json"
        if not filepath.exists():
            return None
        try:
            return WorkflowContext.load_from_file(str(filepath))
        except Exception:
            return None

    def latest(
        self, workflow_type: str = "creator"
    ) -> Optional[WorkflowContext]:
        """获取最新 checkpoint（不写入 session_state）"""
        checkpoints = self.list_checkpoints(workflow_type=workflow_type, limit=1)
        return checkpoints[0] if checkpoints else None

    def count(self, workflow_type: Optional[str] = None) -> int:
        """返回 checkpoint 数量"""
        return len(self.list_checkpoints(workflow_type=workflow_type, limit=9999))

    # ------------------------------------------------------------------
    # 自动保存（供 ui_creator.py 定期调用）
    # ------------------------------------------------------------------

    def auto_save_if_needed(
        self,
        current_episode: int,
        prefix: str = "creator_",
    ) -> Optional[WorkflowContext]:
        """根据配置决定是否自动保存

        Args:
            current_episode: 当前集数（用于判断保存间隔）
            prefix: session_state 前缀

        Returns:
            如果保存了，返回 WorkflowContext；否则返回 None
        """
        if not self.config.auto_checkpoint:
            return None

        interval = self.config.checkpoint_interval_episodes
        if current_episode > 0 and current_episode % interval == 0:
            return self.save_current(
                name=f"第{current_episode}集自动存档",
                prefix=prefix,
            )
        return None

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _cleanup_old_checkpoints(self):
        """清理超出数量限制的旧 checkpoint"""
        checkpoints = self.list_checkpoints(limit=9999)
        if len(checkpoints) > self.config.max_checkpoints:
            # 删除最旧的
            for ctx in checkpoints[self.config.max_checkpoints:]:
                self.delete(ctx.checkpoint_id)
