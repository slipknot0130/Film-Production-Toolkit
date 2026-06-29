"""
harness/tool_schema.py — 工具 Schema 化系统

将 Agent 的隐式能力（写在 prompt 里的规则）转化为结构化工具描述，
使模型调用更精准，减少"prompt 中的隐含指令被忽略"的问题。

设计原则：
- 当前基于文本 prompt 架构，工具通过 prompt 注入声明（非 function-calling API）
- 未来可无缝升级到 OpenAI function calling / Structured Outputs
- 每个 Agent 的工具集按需注入，避免工具过载

使用方式：
    registry = ToolRegistry()
    registry.register_for("writer", [
        ToolSchema("save_script_draft", "保存当前集剧本草稿", ...),
        ToolSchema("query_character_state", "查询指定角色当前状态", ...),
    ])
    tools_text = registry.format_for("writer")  # → 可注入 prompt 的工具声明
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


# =============================================================================
# ToolSchema — 单个工具定义
# =============================================================================

@dataclass
class ToolSchema:
    """单个工具的结构化定义。

    遵循 OpenAI function-calling 兼容格式，当前用于 prompt 注入。
    """

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required,
            "examples": self.examples,
        }

    def to_prompt_text(self) -> str:
        """格式化为可注入 prompt 的文本块。"""
        lines = [f"- **{self.name}**：{self.description}"]
        if self.parameters:
            params = ", ".join(
                f"{k}" + ("*" if k in self.required else "")
                for k in self.parameters
            )
            lines.append(f"  参数：{params}")
        if self.examples:
            lines.append(f"  示例：{self.examples[0]}")
        return "\n".join(lines)


# =============================================================================
# ToolRegistry — 工具注册中心
# =============================================================================

class ToolRegistry:
    """按 Agent 注册和格式化工具 Schema。

    每个 Agent 拥有独立的工具集，避免工具过载。
    """

    def __init__(self):
        self._tools: Dict[str, List[ToolSchema]] = {}

    def register_for(self, agent: str, tools: List[ToolSchema]) -> None:
        """为指定 Agent 注册工具列表（覆盖式）。"""
        self._tools[agent] = tools

    def add_tool(self, agent: str, tool: ToolSchema) -> None:
        """为指定 Agent 追加一个工具。"""
        if agent not in self._tools:
            self._tools[agent] = []
        self._tools[agent].append(tool)

    def get_tools(self, agent: str) -> List[ToolSchema]:
        """获取指定 Agent 的工具列表。"""
        return self._tools.get(agent, [])

    def format_for(self, agent: str) -> str:
        """格式化为可注入 prompt 的工具声明文本。

        返回空字符串表示此 Agent 无工具声明。
        """
        tools = self._tools.get(agent)
        if not tools:
            return ""

        lines = [
            "",
            "## 可用工具",
            "",
            "你可以使用以下工具完成创作任务：",
            "",
        ]
        for t in tools:
            lines.append(t.to_prompt_text())
            lines.append("")

        return "\n".join(lines)

    def list_agents(self) -> List[str]:
        """列出所有已注册 Agent。"""
        return list(self._tools.keys())


# =============================================================================
# 标准工具定义
# =============================================================================

# --- Writer Agent 工具集 ---
WRITER_TOOLS = [
    ToolSchema(
        name="generate_episode_script",
        description="根据大纲和上下文生成一集完整剧本",
        parameters={
            "outline": "string",
            "character_states": "string",
            "previous_summary": "string",
            "memory_snapshot": "string",
        },
        required=["outline"],
    ),
    ToolSchema(
        name="query_character_state",
        description="查询指定角色在当前集之前的完整状态（情绪、目标、关系、伏笔）",
        parameters={"character_name": "string"},
        required=["character_name"],
        examples=["query_character_state('男主') → 返回男主的当前情绪/目标/关系状态"],
    ),
    ToolSchema(
        name="save_script_draft",
        description="保存当前集剧本草稿供后续审核",
        parameters={"episode_num": "int", "content": "string"},
        required=["episode_num", "content"],
    ),
    ToolSchema(
        name="apply_revision",
        description="根据反馈精修已驳回的剧本",
        parameters={
            "previous_script": "string",
            "doctor_feedback": "string",
        },
        required=["previous_script", "doctor_feedback"],
        examples=["apply_revision(上一个版本, 医生的驳回意见) → 输出修改后的完整剧本"],
    ),
]

# --- Doctor Agent 工具集 ---
DOCTOR_TOOLS = [
    ToolSchema(
        name="audit_script",
        description="审查剧本，检查写作红线和爆款节奏",
        parameters={
            "script_content": "string",
            "outline": "string",
            "format": "string",
        },
        required=["script_content"],
    ),
    ToolSchema(
        name="flag_issue",
        description="标记剧本中的具体问题（红线违规/节奏不达标/逻辑矛盾）",
        parameters={
            "issue_type": "string",
            "location": "string",
            "description": "string",
            "suggestion": "string",
        },
        required=["issue_type", "description"],
        examples=[
            'flag_issue("写作红线", "第3场对话", "存在心理描写", "改为动作+对白表达")',
            'flag_issue("爆款节奏", "开场15秒", "缺少情绪压迫", "增加冲突/羞辱场景")',
        ],
    ),
    ToolSchema(
        name="generate_memory_checkpoint",
        description="生成本集的记忆检查点（角色状态更新 + 集数摘要 + 进度记录）",
        parameters={
            "character_updates": "string",
            "episode_summary": "string",
        },
        required=["episode_summary"],
    ),
]

# --- Showrunner Agent 工具集 ---
SHOWRUNNER_TOOLS = [
    ToolSchema(
        name="set_episode_count",
        description="根据故事体量设定总集数",
        parameters={"count": "int", "reasoning": "string"},
        required=["count"],
    ),
    ToolSchema(
        name="add_character",
        description="创建一个新角色并设定其核心属性",
        parameters={
            "name": "string",
            "want": "string",
            "need": "string",
            "contradiction": "string",
            "abilities": "string",
        },
        required=["name", "want", "need"],
    ),
    ToolSchema(
        name="define_plot_arc",
        description="定义全剧三幕结构（建置/对抗/解决）",
        parameters={
            "act": "string",
            "start_episode": "int",
            "end_episode": "int",
            "key_events": "string",
        },
        required=["act", "start_episode", "end_episode"],
    ),
    ToolSchema(
        name="generate_episode_hints",
        description="为每集生成节奏提示（情绪节奏 + 核心钩子）",
        parameters={
            "episode_range": "string",
            "hints": "string",
        },
    ),
]


def create_default_registry() -> ToolRegistry:
    """创建包含标准工具集的注册中心。"""
    registry = ToolRegistry()
    registry.register_for("writer", WRITER_TOOLS)
    registry.register_for("doctor", DOCTOR_TOOLS)
    registry.register_for("showrunner", SHOWRUNNER_TOOLS)
    return registry
