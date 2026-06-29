"""
harness/ — Agent Harness Engineering 核心模块

为 AI 剧本创作工具提供工程化管理能力：
1. CheckpointManager — 断点续传，防止进度丢失
2. StructuredMemoryStore — 结构化记忆，解决长剧上下文断裂
3. ContextRetriever — JIT 上下文检索，降低 token 消耗 40-60%
4. ToolSchema + ToolRegistry — 工具 Schema 化，替代 prompt 隐含指令

设计原则：
- 向后兼容：不破坏现有功能
- 增量增强：与现有机制共存，而非替换
- 可选启用：用户可选择是否使用 Harness 功能
"""

from .config import HarnessConfig, get_harness_config
from .checkpoint import CheckpointManager, WorkflowContext
from .memory_store import StructuredMemoryStore, CharacterState, PlotThread, EpisodeIndex
from .context_retriever import ContextRetriever, ContextBundle, OutlineParser

__version__ = "0.2.0"
__all__ = [
    "HarnessConfig",
    "get_harness_config",
    "CheckpointManager",
    "WorkflowContext",
    "StructuredMemoryStore",
    "CharacterState",
    "PlotThread",
    "EpisodeIndex",
    "ContextRetriever",
    "ContextBundle",
    "OutlineParser",
]
