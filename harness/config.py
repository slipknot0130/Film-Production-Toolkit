"""
harness/config.py — Harness 统一配置

Harness Engineering 的核心配置中心，管理系统级参数。
所有模块从此读取配置，保持一致的行为。
"""

from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass
class HarnessConfig:
    """Harness 统一配置 —— 控制所有 Harness 子系统的行为"""

    # === Checkpoint 设置 ===
    checkpoint_dir: str = ".checkpoints"
    auto_checkpoint: bool = True          # 是否自动保存断点（逐集）
    max_checkpoints: int = 20             # 最多保留的 checkpoint 数量
    checkpoint_interval_episodes: int = 1  # 每 N 集保存一次

    # === Memory 设置 ===
    memory_dir: str = ".harness_memory"
    auto_persist_memory: bool = True      # 是否自动持久化结构化记忆（独立于 checkpoint）
    enable_character_tracking: bool = True
    enable_plot_tracking: bool = True
    enable_episode_index: bool = True
    episode_index_max_chars: int = 200  # 每集索引最大字符数

    # === 编排设置 ===
    max_retries_per_episode: int = 3
    token_budget_per_episode: int = 4000  # 每集最大 token 消耗
    enable_human_in_the_loop: bool = True

    # === 安全设置 ===
    enable_safety_guardrails: bool = True
    max_episodes_per_session: int = 100  # 防止无限循环

    def __post_init__(self):
        """初始化后处理，确保目录存在"""
        # 转换为绝对路径
        if not os.path.isabs(self.checkpoint_dir):
            self.checkpoint_dir = str(Path.cwd() / self.checkpoint_dir)
        if not os.path.isabs(self.memory_dir):
            self.memory_dir = str(Path.cwd() / self.memory_dir)

        # 创建目录
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        os.makedirs(self.memory_dir, exist_ok=True)

    @classmethod
    def from_env(cls) -> "HarnessConfig":
        """从环境变量加载配置（可选）"""
        config = cls()
        
        # Checkpoint 设置
        if os.getenv("HARNESS_CHECKPOINT_DIR"):
            config.checkpoint_dir = os.getenv("HARNESS_CHECKPOINT_DIR")
        if os.getenv("HARNESS_AUTO_CHECKPOINT"):
            config.auto_checkpoint = os.getenv("HARNESS_AUTO_CHECKPOINT").lower() == "true"
        
        # Memory 设置
        if os.getenv("HARNESS_MEMORY_DIR"):
            config.memory_dir = os.getenv("HARNESS_MEMORY_DIR")
        if os.getenv("HARNESS_AUTO_PERSIST_MEMORY"):
            config.auto_persist_memory = os.getenv("HARNESS_AUTO_PERSIST_MEMORY").lower() == "true"
        
        # 安全设置
        if os.getenv("HARNESS_MAX_EPISODES"):
            config.max_episodes_per_session = int(os.getenv("HARNESS_MAX_EPISODES"))
        
        config.__post_init__()  # 重新初始化目录
        return config

    def to_dict(self) -> dict:
        """转换为字典，用于序列化"""
        return {
            "checkpoint_dir": self.checkpoint_dir,
            "auto_checkpoint": self.auto_checkpoint,
            "max_checkpoints": self.max_checkpoints,
            "checkpoint_interval_episodes": self.checkpoint_interval_episodes,
            "memory_dir": self.memory_dir,
            "auto_persist_memory": self.auto_persist_memory,
            "enable_character_tracking": self.enable_character_tracking,
            "enable_plot_tracking": self.enable_plot_tracking,
            "enable_episode_index": self.enable_episode_index,
            "episode_index_max_chars": self.episode_index_max_chars,
            "max_retries_per_episode": self.max_retries_per_episode,
            "token_budget_per_episode": self.token_budget_per_episode,
            "enable_human_in_the_loop": self.enable_human_in_the_loop,
            "enable_safety_guardrails": self.enable_safety_guardrails,
            "max_episodes_per_session": self.max_episodes_per_session,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HarnessConfig":
        """从字典加载配置。
        
        路径安全：__post_init__ 中 isabs 检查保证绝对路径不会被重复拼接；
        即使 data 来自 to_dict() 序列化的绝对路径，也能安全还原。
        """
        config = cls()
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        config.__post_init__()  # 统一标准化路径 + 创建目录
        return config


# 全局配置实例（单例模式）
_global_config: HarnessConfig = None


def get_harness_config() -> HarnessConfig:
    """获取全局 Harness 配置（单例）"""
    global _global_config
    if _global_config is None:
        _global_config = HarnessConfig.from_env()
    return _global_config


def set_harness_config(config: HarnessConfig):
    """设置全局 Harness 配置"""
    global _global_config
    _global_config = config
