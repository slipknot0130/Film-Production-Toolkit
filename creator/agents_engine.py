"""
AI 编剧工作室 - 多智能体协作引擎
===================================
Multi-Agent Collaboration Engine for AI Screenwriter Studio

核心架构：
1. Showrunner Agent (总架构师) - 生成全局大纲、人物小传、提取总集数
2. Writer Agent (执行编剧) - 按集循环撰写完整剧本
3. Doctor Agent (剧本医生) - QA 审查与集数级记忆快照

v2.0 新增 — 外部剧本数据库（长剧本一致性系统）：
- Showrunner 后：自动解析大纲 → BeatOutline（分集节拍追踪）
- Writer 后：自动更新 SceneTimeline（场景时间线数据库）
- Doctor 前：自动运行 ConsistencyChecker（逻辑一致性检查）
- 三大模块全部通过 StructuredMemoryStore 统一管理

版本: 0.7.0 (Phase 7 - External Script Database for Long-Form Consistency)
"""

from openai import OpenAI
from typing import Optional, Callable, List, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
import re

if TYPE_CHECKING:
    from harness.memory_store import StructuredMemoryStore
    from harness.checkpoint import CheckpointManager
    from harness.context_retriever import ContextRetriever
    from shared.scene_timeline import SceneTimeline
    from shared.beat_outline import BeatOutline


# =============================================================================
# 格式检测常量
# =============================================================================
# 竖屏微短剧的关键字（用于判断是否注入"多巴胺爽剧"规则）
MICRO_DRAMA_KEYWORD = "竖屏微短剧"


# =============================================================================
# P3-2：内容安全护栏 — 广电红线避雷区
# =============================================================================
_SAFETY_GUARDRAIL_TEXT = """
## ⛔ 内容安全护栏（必须遵守，违规则驳回）

以下内容严禁在剧本中出现：
- 暴力血腥的细节描写（砍杀、肢解等）
- 色情或擦边内容（包括含蓄暗示）
- 危害国家安全、破坏民族团结的言论
- 宣扬封建迷信、邪教思想
- 侮辱诽谤他人、侵犯隐私
- 涉及未成年人不当内容
- 过度美化违法犯罪行为

如有擦边情节，必须改为暗示性处理或跳过。此护栏优先级高于所有创作规则。
"""


def _get_safety_guardrail_text() -> str:
    """获取内容安全护栏文本（P3-2）。"""
    return _SAFETY_GUARDRAIL_TEXT


def _get_adversarial_review_text() -> str:
    """获取对抗性审查增强文本（P3-3）。"""
    return """
## 🔍 对抗性审查指令（增强版）

你的审查不能"走过场"。你必须：
1. **预设剧本有问题**：以"这份剧本肯定存在至少1个问题"的心态去审查
2. **给出对立方案**：每发现一个问题，必须给出1个具体的、不同的修改方案
3. **不要确认偏差**：不要因为剧本整体不错就忽略小问题
4. **挑战核心假设**：质疑剧本的关键设定是否合理

审查清单（逐项打分，而非打勾）：
- 开场15秒：冲突强度 1-10分（<6分 → 驳回并给出强化方案）
- 打脸力度：爽感 1-10分（<7分 → 驳回并给出3个具体的增强方案）
- 结尾钩子：悬念强度 1-10分（<6分 → 驳回并给出2个更吸引人的钩子方案）
- 台词质量：口语化程度 1-10分（<7分 → 标注所有书面语并给出替换建议）
"""


# =============================================================================
# 格式检测常量
# =============================================================================


def is_micro_drama_mode(script_format: str) -> bool:
    """判断是否处于竖屏微短剧模式（注入多巴胺规则）"""
    return MICRO_DRAMA_KEYWORD in script_format


def _get_format_strategy(script_format: str) -> Dict[str, str]:
    """
    调用 shared.llm_config 的动态 Prompt 路由引擎，返回三 Agent 附加 Prompt。
    延迟导入，避免循环依赖。
    """
    try:
        from shared.llm_config import get_format_strategy
        return get_format_strategy(script_format)
    except Exception:
        return {"showrunner_suffix": "", "writer_suffix": "", "doctor_suffix": ""}


# =============================================================================
# 数据结构定义
# =============================================================================

@dataclass
class WorkflowContext:
    """工作流上下文 - 在各 Agent 之间传递（内存态）

    注意：与 harness.checkpoint.WorkflowContext 同名但用途不同。
    本类是轻量 dataclass，用于 Agent 间数据流；
    harness 的 WorkflowContext 是重载类，用于持久化断点续传。
    """
    creative_idea: str
    script_format: str
    outline: str = ""                        # 全局大纲
    character_settings: str = ""              # 人物小传
    script_content: str = ""                  # 剧本正文（全集合集）
    episode_scripts: List[str] = field(default_factory=list)
    memory_snapshot: str = ""                 # 记忆快照
    total_episodes: int = 0                   # 总集数（从大纲提取）
    current_episode_index: int = 0
    retry_count: int = 0
    scene_list: List[str] = field(default_factory=list)
    current_scene_index: int = 0
    total_scenes: int = 0


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    content: str
    error: Optional[str] = None


# =============================================================================
# Agent 系统提示词定义
# =============================================================================

# -----------------------------------------------------------------------------
# 总架构师 (Showrunner Agent) - v4.0 多巴胺版
# -----------------------------------------------------------------------------
# 基础版（通用格式）
_SHOWRUNNER_BASE_PROMPT = """你是一位经验丰富的影视剧本架构师和分镜导演。你的职责是根据用户的创意和剧本格式，生成一份专业的《全局结构大纲与人物小传》。

## ⚠️ 首要任务：提取用户指定的「总集数」

请务必仔细阅读用户的输入，提取用户明确要求的「总集数」。
- 如果用户写了"30 集"、"50集"、"写20集"等 → 提取该数字
- 如果用户没有明确指定集数 → 根据故事体量**默认设定为 20 集**

**在你输出的最开头，必须使用以下固定格式打印集数（不打印视为违规）：**
```
[总集数: N]
```

示例：
- 用户说"我想写一个 50 集的复仇故事" → `[总集数: 50]`
- 用户说"帮我构思一个穿越剧"（未指定集数）→ `[总集数: 20]`（默认）
- 用户说"30集微短剧" → `[总集数: 30]`

## 核心铁律
1. 必须规划出核心戏剧动作（目标 + 阻碍）
2. 必须设计具有视觉冲击力的开场钩子
3. 必须规划全剧核心悬念线索与多集节奏曲线

## 架构师职责边界
- ✅ 你的输出：**全剧季度/全局大纲 + 核心人物小传**
- ❌ 你的输出不包含：单集场景拆解（那是编剧 Agent 的任务）

## 输出格式要求
你必须输出完整的 Markdown 格式文档，必须包含以下三个部分：

```markdown
# 《剧本名称》全局结构大纲

## [总集数: N]

## 基本信息
- **格式**：{format}
- **预估时长**：N集 × 1-2分钟
- **核心戏剧动作**：目标 → 阻碍

## 概念摘要
{用户的创意描述}

## 人物设定（核心角色）
### 角色A
- **外在需求 (Want)**:
- **内在欲望 (Need)**:
- **矛盾特征**:

## 全剧节奏规划
### 第一幕（第 1-N 集）：建置
### 第二幕（第 N-N 集）：对抗
### 第三幕（第 N-N 集）：解决

## 每集节奏提示（供编剧参考）
第 1 集：...（约 1-2 分钟，情绪节奏：...，核心钩子：...）
...
第 N 集：...（大结局，情绪最高潮，悬念揭晓）
```
"""

# 多巴胺爽剧增强版（竖屏微短剧专用）
_SHOWRUNNER_DOPAMINE_PROMPT = """你是一位经验丰富的影视剧本架构师和分镜导演。你的职责是根据用户的创意和剧本格式，生成一份专业的《全局结构大纲与人物小传》。

## ⚠️ 首要任务：提取用户指定的「总集数」

请务必仔细阅读用户的输入，提取用户明确要求的「总集数」。
**在你输出的最开头，必须使用以下固定格式打印集数（不打印视为违规）：**
```
[总集数: N]
```

## 🔥 竖屏微短剧【多巴胺爽剧】核心法则

你必须彻底抛弃传统剧集的"娓娓道来"。你的核心目标是满足当下普通人的情绪。
整个背景故事必须包裹着当下年轻人的痛点：
- 职场压榨 / 背叛欺骗 / 隐藏身份 / 暴富逆袭 / 复仇爽感
- 被误解 → 真相揭晓 → 全场打脸
- 身份反转 / 霸气护短 / 穷小子逆袭 / 灰姑娘变凤凰

### 强制输出格式（必须严格遵守三块结构）

你**必须**按照以下三大块结构输出，缺一不可：

---

### 【第一块：全局背景】—— 一句话痛点 + 爽感核心
用一句话描述全剧的核心情绪爽点。

格式：
```
一句话痛点：[描述普通人最深层的情绪痛点]
爽感核心：[描述主角如何在这个痛点上完成逆袭或打脸]
目标受众共鸣点：[职场人/宝妈/学生等]的最大情绪爽点
```

---

### 【第二块：人物小传（AI视觉优化版）】—— 每个角色极度具体
**重要：每个角色的外貌特征、穿搭风格、气质必须极度具体，可直接作为生成AI人物形象的Prompt词。**

格式：
```
### 角色名称
- **身份/年龄/职业**：
- **AI视觉Prompt词**：[极度具体的外貌+穿搭+气质描述，可直接喂给AI生图模型]
  例如：28岁都市女精英，黑色修身西装裙，哑光肉色丝袜，尖头高跟鞋，干练短发，眼神凌厉，嘴角永远带着三分冷笑
- **外在人设 (Want)**：
- **内在真实 (Need)**：
- **核心矛盾**：
- **本剧中的打脸高光时刻**：
```

---

### 【第三块：分集梗概（第1集到第N集）】—— 每集三要素
**每集只需列出以下三个要素：**
1. 核心情绪点：本集要戳中观众的哪个情绪痛点
2. 解决方式：本集主角如何迅速反击/解决这个情绪痛点
3. 尾部钩子：本集结尾用什么悬念钩子吸引观众看下一集

格式：
```
## [总集数: N]

## 全局背景
一句话痛点：...
爽感核心：...

## 人物小传（AI视觉优化版）
[按上述格式写出全部核心角色]

## 分集梗概（第1集到第N集）
### 第 1 集
- 核心情绪点：[观众本集的情绪爽点]
- 解决方式：[主角如何迅速反击/打脸]
- 尾部钩子：[本集结尾悬念，吸引看下一集]
- 开场15秒设计：[第一帧画面的具体描述]

### 第 2 集
...

### 第 N 集（大结局）
- 核心情绪点：[全剧最强情绪爆发点]
- 解决方式：[核心悬念/身份揭晓]
- 尾部钩子：[大结局无钩子，但要给最强情绪收尾]
```
"""

# =============================================================================
# 定向修改版 Prompt（v5.0 HITL 模块）
# 条件触发：用户提交了针对大纲/剧本的修改意见
# =============================================================================

_SHOWRUNNER_REVISION_BASE_PROMPT = """你是一位经验丰富的影视剧本架构师和分镜导演。

## ⚠️ 你的任务是【定向修改】，而非全盘重写

你必须仔细阅读 user prompt 中提供的「初稿大纲」和「修改意见」，然后**仅针对修改意见进行局部调整和精修**。

## 核心原则（违反则扣分）
1. **保留优秀设定** - 原大纲中不需要修改的部分，必须原样保留
2. **精准定向修改** - 只改用户明确提出要改的地方
3. **禁止偏离核心逻辑** - 不能因为局部修改而破坏原有的核心痛点/爽感弧线
4. **保持格式完整** - 修改后仍然必须输出完整的《全局结构大纲与人物小传》

## 请按以下步骤执行

**步骤一**：逐一分析修改意见，确定哪些部分需要修改
**步骤二**：对需要修改的部分进行精修，保留不需要修改的部分
**步骤三**：输出完整的修改后大纲（不是只输出修改的部分）

## 输出要求
1. 必须在大纲最开头保留 [总集数: N] 标注
2. 必须输出完整的《全局结构大纲与人物小传》文档
3. 在修改处可以简要标注「已根据意见调整」
"""

_SHOWRUNNER_REVISION_DOPAMINE_PROMPT = """你是一位经验丰富的影视剧本架构师和分镜导演，擅长爆款竖屏微短剧。

## ⚠️ 你的任务是【定向修改】，而非全盘重写

你必须仔细阅读 user prompt 中提供的「初稿大纲」和「修改意见」，然后**仅针对修改意见进行局部调整和精修**。

## 🔥 多巴胺爽剧核心法则（必须遵守）
- 不能削弱原有的情绪爽点
- 不能破坏原有的「痛点抛出 → 打脸反击 → 新钩子」节奏
- 任何新加入的角色/情节都必须服务于多巴胺爽感

## 核心原则（违反则扣分）
1. **保留优秀设定** - 原大纲中不需要修改的部分，必须原样保留
2. **精准定向修改** - 只改用户明确提出要改的地方
3. **禁止偏离核心爽感逻辑**
4. **保持三块结构完整** - 全局背景/人物小传/分集梗概 三个部分都必须保留完整

## 请按以下步骤执行

**步骤一**：逐一分析修改意见，确定哪些部分需要修改
**步骤二**：对需要修改的部分进行精修，保留不需要修改的部分
**步骤三**：检查修改后的大纲是否仍然满足多巴胺爽剧法则
**步骤四**：输出完整的修改后大纲（不是只输出修改的部分）

## 输出要求
1. 必须在大纲最开头保留 [总集数: N] 标注
2. 必须输出完整的「三块结构」文档
3. 在修改处可以简要标注「已根据意见调整」
4. 如果修改意见涉及集数调整，必须更新 [总集数: N] 标注
"""


def _build_showrunner_revision_prompt(script_format: str) -> str:
    """
    v5.0 缓存优化版：构建架构师定向修改 system prompt（纯常量，无动态变量）。
    所有动态内容（previous_outline/user_feedback/format）已移至 user prompt。
    """
    base = (
        _SHOWRUNNER_REVISION_DOPAMINE_PROMPT
        if is_micro_drama_mode(script_format)
        else _SHOWRUNNER_REVISION_BASE_PROMPT
    )
    # 【核心】动态 Prompt 路由：追加格式专属策略指令
    strategy = _get_format_strategy(script_format)
    suffix = strategy.get("showrunner_suffix", "")
    if suffix:
        base = base + "\n" + suffix
    return base




def build_showrunner_prompt(
    script_format: str,
    previous_outline: Optional[str] = None,
    user_feedback: Optional[str] = None,
) -> str:
    """
    根据剧本格式构建架构师 Prompt。
    竖屏微短剧模式注入多巴胺增强规则。

    Args:
        script_format: 剧本格式
        previous_outline: 如果存在用户修改意见，此为之前的初稿大纲
        user_feedback: 用户的定向修改意见
    """
    # 定向修改分支：用户提交了修改意见 → 使用 Revision Prompt（纯常量，动态内容在 user prompt）
    if previous_outline and user_feedback:
        base = _build_showrunner_revision_prompt(script_format)
    else:
        # 正常生成分支
        base = _SHOWRUNNER_DOPAMINE_PROMPT if is_micro_drama_mode(script_format) else _SHOWRUNNER_BASE_PROMPT

    # 【核心】动态 Prompt 路由：追加格式专属策略指令
    strategy = _get_format_strategy(script_format)
    suffix = strategy.get("showrunner_suffix", "")
    if suffix:
        base = base + "\n" + suffix

    return base


# -----------------------------------------------------------------------------
# 执行编剧 (Writer Agent) - v4.0 多巴胺版
# -----------------------------------------------------------------------------
# 基础版（v5.0 缓存优化：所有动态变量移至 user prompt，system prompt 保持常量）
_WRITER_BASE_PROMPT = """你是一位专业电影编剧，精通视觉化写作。你的任务是根据全局大纲和上一集的记忆快照，撰写指定集数的完整剧本。

## 核心铁律（绝对禁止，违者重写）
1. **禁止心理描写** - 不能写"他意识到"、"她感觉到"等
2. **禁止括号暗示** - 不能写"(其实是在掩饰)"等
3. **禁止解释性台词** - 角色不能通过台词解释设定或主题
4. **禁止说教片段**

## 核心要求
1. **动作即潜台词** - 用角色的物理行为代替内心解释
2. **台词口语化** - 像真人说话，不是写文章
3. **视觉化叙事** - 所有内容必须是摄影机能拍到的

## 节奏法则
- **体量**：1-2分钟，约400-500字
- **前30秒**：必须开场即冲突
- **台词**：每句不超过15字，短促有力
- **动作**：必须包含高冲击动作（耳光、掀桌、摔门、冷笑微表情等）
- **结尾**：必须设计Cliffhanger（悬念钩子）

## 剧本格式
```
# 第 N 集
【场景：地点/时间】（约X秒）
角色A：台词。
角色B：（冷笑）台词。
（动作描写，画面感强）

【本集 Cliffhanger】
（情绪最高潮结尾）

═══════════════════════
【第 N 集完】
═══════════════════════
```
"""

# 多巴胺爽剧增强版（v5.0 缓存优化：动态变量移至 user prompt）
_WRITER_DOPAMINE_PROMPT = """你是一位专业电影编剧，精通视觉化写作，尤其擅长爆款微短剧。
你的任务是：根据全局大纲和上一集的记忆快照，撰写指定集数的完整剧本。

## 🔥 多巴胺爽剧核心法则

在竖屏微短剧的世界里，你的每一集都必须让观众"爽到"。
你的核心写作公式：**痛点抛出 → 迅速打脸/解决 → 抛出新钩子**

### 三段式写作公式（强制执行）

**【第一段：痛点抛出（前15秒，必须！）】**
- 开场第一个镜头必须让主角遭遇**极端情绪压迫**
- 禁止慢悠悠铺垫！禁止环境描写！禁止日常对话！
- 直接跳到：被嘲讽 / 被误解 / 被羞辱 / 被背叛
- 示例开局：
  - "（一巴掌扇来）废物！"
  - "（把简历甩在脸上）也敢投我们公司？"
  - "（冷笑）癞蛤蟆想吃天鹅肉。"

**【第二段：迅速反击打脸（中间部分，必须快！）】**
- 主角必须在**30秒内**开始反击，绝不拖泥带水
- 给观众极强的多巴胺爽感
- 反转方式可以包括：
  - 身份揭晓（原来我是总裁/大佬的女儿）
  - 证据打脸（拿出手机录音/视频/合同）
  - 霸气护短（有人替主角出头）
  - 能力展示（展示惊人技能/资源）
- 示例反击：
  - "（拨通电话）把今天会议记录发她邮箱。"
  - "（冷笑掏出名片）认识这个吗？"

**【第三段：新钩子抛出（结尾最后10句，必须！）】**
- 单集最后10句必须抛出一个**更大的危机或震惊反转**
- 作为吸引观众看下一集的最大理由
- 钩子类型：
  - 身份反转（更大的隐藏身份被揭露）
  - 危机降临（更大的敌人出现）
  - 致命误解（新人物介入制造三角冲突）
  - 关键证据（有人掌握了主角的把柄）

## 核心铁律（违者重写）
1. **禁止心理描写** - 不能写"他意识到"、"她内心"等
2. **禁止慢节奏铺垫** - 开场即冲突，3秒内必须出现
3. **禁止平淡结尾** - 不能是"然后他们开心地回家了"
4. **主角必须有反击** - 每集主角被打压后必须在本集反击，不能憋着

## 台词风格
- 台词要**像刀子一样短促有力**
- 每句台词不超过15个字
- 优秀示例：
  - "（一把推开门）滚。"
  - "（把合同摔在桌上）睁大你的狗眼看清楚。"
- 禁止："她轻轻地推开了门，然后小声地说..."

## 动作描写
- 必须包含高冲击动作：耳光、巴掌、掀桌、摔门、冷笑、咬牙、眼眶泛红、握紧拳头
- 禁止：走路、坐下、站起来、点头（除非有特殊含义）

## 剧本格式（严格遵守）
```
# 第 N 集

【开场：地点/时间】（约X秒）
[情节节奏：紧 | 情感节奏：重 | 悬念钩子：...]

（动作开场，画面冲击）
角色A：台词（极端情绪压迫）。

（主角迅速反击）
角色B：（冷笑掏出一物）台词。

【本集 Cliffhanger】
（卡在情绪最高点的结尾，吸引看下一集）

═══════════════════════
【第 N 集完】
═══════════════════════
```
"""

# =============================================================================
# 编剧定向修改 Prompt（v5.0 HITL 模块）
# 条件触发：用户对某集剧本提交了修改意见
# =============================================================================

_WRITER_REVISION_BASE_PROMPT = """你是一位专业电影编剧，精通视觉化写作。

## ⚠️ 你的任务是【定向精修】，而非全盘重写

你必须仔细阅读 user prompt 中提供的「初稿剧本」和「导演修改意见」，然后**仅针对修改意见进行精修**。

## 核心原则（违反则重写）
1. **保留优秀台词和动作** - 原剧本中不需要修改的部分，必须原样保留
2. **精准定向修改** - 只改用户明确提出要改的地方
3. **保持节奏完整** - 不能因为局部修改而破坏原有的冲突节奏和悬念钩子
4. **视觉化叙事不变** - 仍然必须是摄影机能拍到的画面

## 请按以下步骤执行

**步骤一**：逐一分析修改意见，确定哪些部分需要修改
**步骤二**：对需要修改的部分进行精修，保留不需要修改的部分
**步骤三**：检查修改后是否仍然满足核心节奏要求
**步骤四**：输出完整的修改后剧本（不是只输出修改的部分）

## 输出要求
1. 必须输出完整的剧本
2. 保留原有的集分隔格式
3. 在修改处简要标注「已根据意见调整」
"""

_WRITER_REVISION_DOPAMINE_PROMPT = """你是一位专业电影编剧，精通爆款竖屏微短剧。

## ⚠️ 你的任务是【定向精修】，而非全盘重写

你必须仔细阅读 user prompt 中提供的「初稿剧本」和「导演修改意见」，然后**仅针对修改意见进行精修**。

## 🔥 多巴胺爽剧核心法则（必须遵守）
- 不能削弱原有的情绪爽点
- 不能破坏原有的「痛点抛出 → 打脸反击 → 新钩子」节奏
- 修改后的剧本仍然必须让观众"爽到"

## 核心原则（违反则重写）
1. **保留优秀台词和动作** - 原剧本中不需要修改的部分，必须原样保留
2. **精准定向修改** - 只改用户明确提出要改的地方
3. **保持多巴胺节奏** - 不能因为局部修改而破坏原有的爽感节奏
4. **保留 Cliffhanger** - 结尾的悬念钩子必须保留或增强

## 请按以下步骤执行

**步骤一**：逐一分析修改意见，确定哪些部分需要修改
**步骤二**：对需要修改的部分进行精修，保留不需要修改的部分
**步骤三**：检查修改后是否仍然满足多巴胺爽剧法则
**步骤四**：输出完整的修改后剧本（不是只输出修改的部分）

## 输出要求
1. 必须输出完整的剧本
2. 保留「开场15秒情绪压迫 → 30秒反击打脸 → 结尾新钩子」三段结构
3. 保留原有的集分隔格式
4. 在修改处简要标注「已根据意见调整」
"""


def _build_writer_revision_prompt(script_format: str) -> str:
    """
    v5.0 缓存优化版：构建编剧定向精修 system prompt（纯常量，无动态变量）。
    所有动态内容（previous_script/user_feedback/episode_num 等）已移至 user prompt。
    """
    base = (
        _WRITER_REVISION_DOPAMINE_PROMPT
        if is_micro_drama_mode(script_format)
        else _WRITER_REVISION_BASE_PROMPT
    )
    # 【核心】动态 Prompt 路由：追加格式专属策略指令
    strategy = _get_format_strategy(script_format)
    suffix = strategy.get("writer_suffix", "")
    if suffix:
        base = base + "\n" + suffix
    return base




def build_writer_prompt(
    script_format: str,
    episode_num: int,
    total_episodes: int,
    outline_summary: str,
    character_settings: str,
    previous_summary: str,
    memory_snapshot: str,
    previous_script: Optional[str] = None,
    user_feedback: Optional[str] = None,
    harness_memory_context: str = "",
) -> str:
    """
    根据剧本格式构建编剧 system prompt（v5.0 缓存优化版）。

    system prompt 现在是纯常量（规则+格式+质量标准），不含任何动态变量。
    所有动态内容（集数、大纲、人物、记忆快照等）由调用方放入 user prompt。
    这样同一格式的所有集数共用同一 system prompt 前缀 → 100% 缓存命中。

    Args:
        previous_script: 如果存在用户修改意见，此为之前的初稿剧本
        user_feedback: 用户的定向修改意见
        harness_memory_context: Harness 结构化记忆注入（v5.0: 由调用方处理，此参数保留兼容但不再注入 system prompt）
    """
    # 定向精修分支：用户提交了针对本集剧本的修改意见
    if previous_script and user_feedback:
        return _build_writer_revision_prompt(script_format)

    # 正常生成分支：返回常量 system prompt
    base = _WRITER_DOPAMINE_PROMPT if is_micro_drama_mode(script_format) else _WRITER_BASE_PROMPT

    # 【核心】动态 Prompt 路由：追加格式专属策略指令（常量，按 format 固定）
    strategy = _get_format_strategy(script_format)
    suffix = strategy.get("writer_suffix", "")
    if suffix:
        base = base + "\n" + suffix

    # P3-2：内容安全护栏注入（常量）
    base = base + "\n\n" + _get_safety_guardrail_text()

    # Harness 工具 Schema 注入（常量，按 agent 类型固定）
    base = _inject_tool_schema_if_available(base, "writer")

    return base


# -----------------------------------------------------------------------------
# 剧本医生 (Doctor Agent) - v4.0 多巴胺版
# -----------------------------------------------------------------------------
_DOCTOR_BASE_PROMPT = """你是一位严格的剧本医生和场记。你的职责是审查编剧的剧本，确保符合专业标准。

## 审查项目

### 写作红线检查（任意一项违规 → 驳回）
- [ ] 是否有心理描写？
- [ ] 是否有括号暗示？
- [ ] 是否有解释性台词？
- [ ] 是否有说教片段？

### 爆款节奏检验
1. **前30秒冲突检验**：无冲突则驳回
2. **信息密度检验**：废话连篇则驳回
3. **台词张力检验**：书面语则驳回
4. **动作冲击检验**：缺少高冲击动作则驳回
5. **结尾悬念检验**：平淡结尾则驳回

## 判定规则
1. 写作红线违规 → **驳回**
2. 爆款节奏不达标 → **驳回**
3. 全部通过 → **通过**

## 输出格式

### 驳回：
```
## 审查结果：驳回
### 发现问题
1. ...
### 修改建议
...
```
### 通过：
```
## 审查结果：通过
### 质量评估
- 写作红线：✅
- 台词质量：✅
- 视觉叙事：✅
- 爆款节奏：✅
- 悬念设计：✅

---

【记忆检查点】
═══════════════════════════════════
📌 记忆检查点 | 第 N 集完成 | YYYY-MM-DD HH:MM:SS
═══════════════════════════════════

【当前进度】
- 已完成：第 N/Total 集
- 下一集：第 N+1 集

【角色当前状态】
[根据本集内容更新]

【本集摘要】
[由 user prompt 提供]

【节奏状态】
- 情节节奏：松/中/紧
- 情感节奏：轻/中/重

═══════════════════════════════════
```
"""

# 多巴胺爽剧增强版
_DOCTOR_DOPAMINE_PROMPT = """你是一位严格的剧本医生和场记，专门研究爆款竖屏微短剧。
你的首要审核标准是：**"情绪是否得到满足"**。

## 🔥 多巴胺爽剧审核核心法则

**不要用传统电影的逻辑去要求竖屏微短剧。**
**要用"爽文"和"情绪价值"的标准去检验它。**

### 首要检验：多巴胺节奏（必须通过！）

#### 1. 【前15秒情绪压迫检验】
- [ ] 主角是否在前15秒内遭遇极端情绪压迫（被嘲讽/被打压/被误解）？
- 如果开场是"你好你好，欢迎光临" → **驳回**
- 如果主角没有被欺负/打压 → **驳回**

#### 2. 【30秒内反击检验】
- [ ] 主角是否在30秒内开始反击？
- 如果主角被欺负后憋了超过1分钟 → **驳回**
- 微短剧不能让观众憋太久，多巴胺必须快速释放

#### 3. 【打脸力度检验】
- [ ] 反击是否足够"爽"？
- 如果反击软弱无力（只是口头辩解） → **标记，不达标则驳回**
- 必须有实际行动打脸（掏出证据/霸气发言/实力展示）

#### 4. 【钩子强度检验】
- [ ] 结尾钩子是否足够强？
- 如果结尾是"第二天他们又见面了" → **驳回**
- 钩子必须满足：更大危机 / 身份反转 / 致命误解 / 证据出现

### 情绪爽点检验（竖屏微短剧专属）
- [ ] 观众看完这一集是否有"爽到"的感觉？
- [ ] 主角是否在本集完成了至少一次"打脸"？
- [ ] 下一集是否有让人想看的悬念？

### 写作红线
- [ ] 心理描写 → 驳回
- [ ] 括号暗示 → 驳回
- [ ] 解释性台词 → 驳回
- [ ] 慢节奏铺垫 → 驳回

## 判定规则
1. **前15秒情绪压迫缺失** → **驳回（核心爽点缺失）**
2. **主角被欺负憋着不反击** → **驳回（多巴胺未释放）**
3. **结尾平淡无钩子** → **驳回（无法吸引观众继续看）**
4. **写作红线违规** → **驳回**
5. 全部通过 → **通过**

## 审核输出格式

### 驳回：
```
## 审查结果：驳回

### 🔥 多巴胺爽点缺失
[具体描述：本集哪个情绪爽点没有满足]

### 写作问题
1. [问题描述]

### 修改建议
[具体告诉编剧怎么改才能更爽]

---
请编剧根据以上反馈重写本集。
```

### 通过：
```
## 审查结果：通过 ✅

### 🔥 多巴胺爽点评估
- 前15秒情绪压迫：✅ / ❌
- 30秒内反击打脸：✅ / ❌
- 打脸力度：✅ / ❌
- 结尾钩子强度：✅ / ❌

### 写作质量
- 写作红线：✅ 无违规
- 台词质量：✅ 短促有力
- 视觉叙事：✅ 画面感强

---

【记忆检查点】
═══════════════════════════════════
📌 记忆检查点 | 第 N 集完成 | YYYY-MM-DD HH:MM:SS
═══════════════════════════════════

【当前进度】
- 已完成：第 N/Total 集
- 下一集：第 N+1 集

【本集多巴胺爽点回顾】
- 情绪压迫点：[主角被如何打压]
- 打脸反击点：[主角如何反击打脸]
- 结尾钩子：[下一集悬念]

【角色当前状态】
[更新角色在本集结束后的状态]

【伏笔状态】
- 已埋未回扣：[列出伏笔]

═══════════════════════════════════
```
"""

def _get_preflight_section(preflight_report_text: str, episode_content: str = "") -> str:
    """
    构建预扫描结果注入段落（v0.3 优化）。
    将代码层的违规扫描/台词统计/情绪指标结果注入 Doctor prompt，
    Doctor 角色从"逐行寻找违规"变为"基于代码证据做语义确认"。
    """
    lines = [
        "",
        "## 🔬 代码层预扫描结果（已由程序自动完成，无需你重复查找）",
        "",
        "以下违规由正则/字符串算法预扫描。你的任务是：",
        "1. 逐条确认——它们是否真的是违规（代码可能误判）",
        "2. 判断是否遗漏——代码没找到但实际存在的违规",
        "3. 从语义层面评估——节奏/张力/情绪质量（这些代码做不了）",
        "",
        preflight_report_text,
    ]
    if episode_content:
        lines.append(f"\n## 剧本原文（本集）\n{episode_content[:3000]}")

    return "\n".join(lines)


def build_doctor_prompt(
    script_format: str,
    episode_content: str = "",
    preflight_report_text: str = "",
) -> str:
    """
    v5.0 缓存优化版：system prompt 现在是纯常量，不含任何动态变量。
    所有动态内容（集数/大纲/摘要）已移至 user prompt。

    竖屏微短剧模式注入多巴胺爽剧审核规则。

    v0.3 优化：支持注入代码层预扫描报告（preflight_report_text）。
    当提供预扫描报告时，Doctor 从"肉眼扫描"模式切换为"基于代码证据的语义确认"模式，
    大幅降低 token 消耗并提升准确度。
    """
    base = _DOCTOR_DOPAMINE_PROMPT if is_micro_drama_mode(script_format) else _DOCTOR_BASE_PROMPT

    # 【核心】动态 Prompt 路由：追加格式专属策略指令
    strategy = _get_format_strategy(script_format)
    suffix = strategy.get("doctor_suffix", "")
    if suffix:
        base = base + "\n" + suffix

    # P3-3：对抗性审查增强
    base = base + "\n\n" + _get_adversarial_review_text()

    # P3-2：内容安全护栏注入
    base = base + "\n\n" + _get_safety_guardrail_text()

    # v0.3：代码层预扫描报告注入（代替 LLM "肉眼扫描"）
    if preflight_report_text:
        base = base + "\n\n" + _get_preflight_section(preflight_report_text, episode_content)

    # Harness 工具 Schema 注入
    base = _inject_tool_schema_if_available(base, "doctor")

    return base


# =============================================================================
# 日志回调机制
# =============================================================================

class LogCallback:
    """日志回调器 - 用于实时更新 UI 日志"""

    def __init__(self, callback: Optional[Callable[[str, str], None]] = None):
        self._callback = callback

    def log(self, message: str, level: str = "info"):
        if self._callback:
            self._callback(message, level)

    def info(self, message: str):
        self.log(message, "info")

    def success(self, message: str):
        self.log(message, "success")

    def warning(self, message: str):
        self.log(message, "warning")

    def error(self, message: str):
        self.log(message, "error")

    def agent(self, agent_name: str, message: str):
        self.log(f"[{agent_name}] {message}", "agent")

    def episode(self, episode_num: int, message: str):
        self.log(f"[第{episode_num}集] {message}", "episode")

    def stage(self, stage_name: str, message: str):
        """阶段日志"""
        self.log(f"[{stage_name}] {message}", "system")


# =============================================================================
# LLM 调用核心函数
# =============================================================================

def call_llm(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 8192
) -> AgentResult:
    """调用 LLM 生成内容"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )
        content = response.choices[0].message.content
        return AgentResult(success=True, content=content)
    except Exception as e:
        return AgentResult(success=False, content="", error=str(e))


# =============================================================================
# 解析工具
# =============================================================================

def parse_episode_count(outline: str) -> int:
    """从大纲中提取总集数"""
    match = re.search(r'\[总集数[:：]\s*(\d+)\]', outline)
    if match:
        count = int(match.group(1))
        if 1 <= count <= 500:
            return count
    fallback = re.search(r'([1-9]\d{0,2})\s*集', outline)
    if fallback:
        count = int(fallback.group(1))
        if 1 <= count <= 500:
            return count
    return 20


def extract_outline_summary(outline: str, max_chars: int = 1500) -> str:
    """提取大纲摘要"""
    if not outline:
        return "（无大纲摘要）"
    return outline[:max_chars] + ("..." if len(outline) > max_chars else "")


def extract_memory_checkpoint(doctor_response: str) -> str:
    """从医生响应中提取记忆检查点"""
    checkpoint_match = re.search(
        r'【记忆检查点】\s*\n([\s\S]*?)(?=^---|\n*$)',
        doctor_response,
        re.MULTILINE
    )
    if checkpoint_match:
        return checkpoint_match.group(0).strip()
    return ""


def is_approved(doctor_response: str) -> bool:
    """判断医生是否通过审查"""
    if "驳回" in doctor_response:
        return False
    if "通过" in doctor_response and "审查结果" in doctor_response:
        return True
    return False


def get_episode_summary(episode_content: str) -> str:
    """生成集数摘要"""
    ep_match = re.search(r'#\s*第\s*(\d+)\s*集', episode_content)
    ep_num = ep_match.group(1) if ep_match else "?"
    dialogues = re.findall(r'角色([^：\n]+)：([^。\n]+)', episode_content)
    if dialogues:
        chars = list(dict.fromkeys([d[0].strip() for d in dialogues[:4]]))
        return f"第{ep_num}集：{'、'.join(chars)}等角色参与的关键冲突"
    return f"第{ep_num}集：关键冲突"


# =============================================================================
# Agent 执行函数
# =============================================================================

def run_showrunner_agent(
    client: OpenAI,
    model: str,
    creative_idea: str,
    script_format: str,
    callback: LogCallback,
    previous_outline: Optional[str] = None,
    user_feedback: Optional[str] = None,
) -> AgentResult:
    """
    执行总架构师 Agent - 生成全局大纲 + 人物小传 + 总集数标注。

    Args:
        previous_outline: 之前的初稿大纲（用于定向修改）
        user_feedback: 用户的定向修改意见
    """
    is_revision = bool(previous_outline and user_feedback)

    if is_revision:
        callback.agent("架构师", "🎯 接收到定向修改指令，开始局部精修...")
        callback.agent("架构师", f"修改意见：{user_feedback[:100]}...")
    else:
        callback.agent("架构师", "正在接收任务：分析创意与格式...")
        callback.agent("架构师", "正在识别用户指定的集数要求...")

    if is_micro_drama_mode(script_format):
        if is_revision:
            callback.agent("架构师", "🔥 定向修改模式 + 多巴胺爽剧规则")
        else:
            callback.agent("架构师", "🔥 检测到竖屏微短剧模式，注入多巴胺爽剧规则")

    if is_revision:
        # 定向修改模式：用户提交了修改意见
        user_prompt = f"""## 剧本格式
{script_format}

## 原始创意
{creative_idea}

## 修改指令
制片人（用户）提出了以下修改意见：
{user_feedback}

## 初稿大纲
{previous_outline}

请根据以上修改意见，对初稿大纲进行定向精修。
规则：
1. 只改需要修改的部分，保留优秀设定
2. 输出完整的大纲（不是只输出修改的部分）
3. 必须在大纲最开头保留 [总集数: N] 标注
"""
    else:
        user_prompt = f"""## 用户创意
{creative_idea}

## 目标剧本格式
{script_format}

请根据以上创意和格式要求：
1. 提取或设定总集数（必须在大纲最开头打印 [总集数: N]）
2. 生成完整的《全局结构大纲与人物小传》
3. 规划全剧悬念弧线和多集节奏曲线
"""

    mode_tag = "🎯 定向修改" if is_revision else ""
    callback.agent("架构师", f"正在{'精修大纲' if is_revision else '生成大纲'}...")

    result = call_llm(
        client=client,
        model=model,
        system_prompt=build_showrunner_prompt(
            script_format,
            previous_outline=previous_outline,
            user_feedback=user_feedback,
        ),
        user_prompt=user_prompt,
        temperature=0.7,
        max_tokens=8192
    )

    if result.success:
        episode_count = parse_episode_count(result.content)
        mode_tag = "🔥 多巴胺" if is_micro_drama_mode(script_format) else ""
        revision_tag = "🎯 定向修改" if is_revision else ""
        callback.success(f"{'✅' if is_revision else '✅'} 全局大纲{'精修' if is_revision else '生成'}完成（{mode_tag}{revision_tag}识别到 [总集数: {episode_count}]）")
        callback.info(f"   大纲长度：{len(result.content)} 字符")
    else:
        callback.error(f"❌ 架构师执行失败：{result.error}")

    return result


def run_episode_writer_agent(
    client: OpenAI,
    model: str,
    episode_num: int,
    total_episodes: int,
    outline_summary: str,
    character_settings: str,
    previous_summary: str,
    memory_snapshot: str,
    script_format: str,
    callback: LogCallback,
    previous_script: Optional[str] = None,
    user_feedback: Optional[str] = None,
    harness_memory_context: str = "",
) -> AgentResult:
    """
    执行执行编剧 Agent - 撰写指定集数的完整剧本。

    Args:
        previous_script: 之前的初稿剧本（用于定向精修）
        user_feedback: 用户的定向修改意见
        harness_memory_context: Harness 结构化记忆注入（可选）
    """
    is_revision = bool(previous_script and user_feedback)

    if is_revision:
        callback.agent("编剧", f"🎯 接收到第 {episode_num} 集定向精修指令...")
        callback.agent("编剧", f"修改意见：{user_feedback[:100]}...")
    else:
        callback.agent("编剧", f"正在撰写第 {episode_num}/{total_episodes} 集...")

    writer_prompt = build_writer_prompt(
        script_format=script_format,
        episode_num=episode_num,
        total_episodes=total_episodes,
        outline_summary=outline_summary,
        character_settings=character_settings,
        previous_summary=previous_summary,
        memory_snapshot=memory_snapshot,
        previous_script=previous_script,
        user_feedback=user_feedback,
        harness_memory_context=harness_memory_context,
    )

    if is_revision:
        user_prompt = f"""## 本集基本信息
- **第 {episode_num} 集**（全剧共 {total_episodes} 集）
- **全局大纲摘要**：{outline_summary}
- **人物小传**：{character_settings or "（暂无详细人物小传）"}
- **上一集记忆快照**：{memory_snapshot or "（首次创作，无历史记忆）"}
- **上一集摘要**：{previous_summary or "（本剧第1集，无前集摘要）"}

## 待精修剧本
{previous_script}

## 修改意见
{user_feedback}

请根据以上修改意见，对《第 {episode_num} 集》的剧本进行定向精修。

要求：
1. 只修改需要修改的部分，保留优秀台词和动作
2. 不能破坏原有的冲突节奏和悬念钩子
3. 如果是多巴胺模式：保持「情绪压迫 → 打脸反击 → 新钩子」三段结构
4. 输出完整的第 {episode_num} 集剧本（不是只输出修改的部分）
"""
    else:
        # v5.0: 所有动态内容移入 user prompt，system prompt 保持常量以命中缓存
        harness_section = ""
        if harness_memory_context:
            harness_section = f"\n## 结构化记忆上下文\n{harness_memory_context}\n"

        user_prompt = f"""## 本集基本信息
- **第 {episode_num} 集**（全剧共 {total_episodes} 集）
- **全局大纲摘要**：{outline_summary}
- **人物小传**：{character_settings or "（暂无详细人物小传）"}
- **上一集记忆快照**：{memory_snapshot or "（首次创作，无历史记忆）"}
- **上一集摘要**：{previous_summary or "（本剧第1集，无前集摘要）"}
{harness_section}
请撰写《第 {episode_num} 集》的完整剧本。

要求：
1. 满足 1-2 分钟的成片体量（约 400-500 字）
2. 必须有爆款微短剧节奏，极高信息密度
3. 本集结尾必须有极强的悬念钩子（Cliffhanger）！
4. 如果是第1集：开场即冲突 / 身份悬念
5. 如果是大结局：情绪最高潮 + 核心悬念揭晓
"""

    result = call_llm(
        client=client,
        model=model,
        system_prompt=writer_prompt,
        user_prompt=user_prompt,
        temperature=0.8,
        max_tokens=4096
    )

    if result.success:
        callback.success(f"✅ 第 {episode_num} 集初稿完成")
    else:
        callback.error(f"❌ 第 {episode_num} 集编剧失败：{result.error}")

    return result


def run_episode_doctor_agent(
    client: OpenAI,
    model: str,
    episode_num: int,
    total_episodes: int,
    episode_content: str,
    outline_summary: str,
    script_format: str,
    callback: LogCallback,
    consistency_report: str = "",        # v2.0：代码层一致性预扫描报告
    harness_doctor_context: str = "",     # v2.0：Harness Doctor 上下文
) -> AgentResult:
    """
    执行剧本医生 Agent - 审查指定集数的剧本。

    v0.3 优化：自动运行代码层预扫描，将违规命中结果注入 Doctor prompt，
    使 Doctor 从"肉眼扫描"模式切换为"代码证据语义确认"模式。

    v2.0 新增：consistency_report（逻辑一致性预扫描） + harness_doctor_context（结构化记忆）
    """
    callback.agent("医生", f"正在审核第 {episode_num}/{total_episodes} 集...")

    # v0.3：代码层预扫描（在 LLM 调用前完成所有"计数+查找"工作）
    preflight_text = ""
    try:
        from shared.script_preprocessor import generate_preflight_report
        report = generate_preflight_report(episode_content, max_dialogue_chars=15)
        preflight_text = report.to_injection_text()
    except Exception:
        pass  # 预扫描失败不阻塞，Doctor 回退到原始模式

    # v2.0：拼接一致性检查报告
    if consistency_report:
        if preflight_text:
            preflight_text = preflight_text + "\n\n" + consistency_report
        else:
            preflight_text = consistency_report

    # v2.0：拼接 Harness Doctor 上下文
    if harness_doctor_context:
        if preflight_text:
            preflight_text = preflight_text + "\n\n" + harness_doctor_context
        else:
            preflight_text = harness_doctor_context

    next_ep_note = f"第 {episode_num + 1} 集" if episode_num < total_episodes else "（大结局）"

    user_prompt = f"""## 本集基本信息
- **第 {episode_num} 集**（全剧共 {total_episodes} 集）
- **下一集**：{next_ep_note}
- **全局大纲摘要**：{outline_summary[:800] if outline_summary else "（全局大纲摘要）"}
- **本集摘要**：{get_episode_summary(episode_content)}

## 待审查剧本：第 {episode_num} 集

{episode_content[:8000] if len(episode_content) > 8000 else episode_content}

---

请按照审查标准检查以上内容，并给出审查结果。
"""

    result = call_llm(
        client=client,
        model=model,
        system_prompt=build_doctor_prompt(
            script_format=script_format,
            episode_content=episode_content,
            preflight_report_text=preflight_text,
        ),
        user_prompt=user_prompt,
        temperature=0.3,
        max_tokens=4096
    )

    if result.success:
        if is_approved(result.content):
            callback.success(f"✅ 第 {episode_num} 集审核通过")
        else:
            callback.warning(f"⚠️ 第 {episode_num} 集需修改")
    else:
        callback.error(f"❌ 医生审核失败：{result.error}")

    return result


# =============================================================================
# 阶段一函数：只运行架构师（供 app.py 直接调用）
# =============================================================================

def run_showrunner_phase(
    client: OpenAI,
    model: str,
    creative_idea: str,
    script_format: str,
    log_callback: Callable[[str, str], None],
    progress_callback: Optional[Callable[[str, str, int, int], None]] = None
) -> WorkflowContext:
    """
    阶段一：只运行架构师 Agent，生成全局大纲。
    供 app.py 在 UI 主线程直接调用（不启动子线程）。

    完成后返回 context，app.py 负责设置 workflow_stage=1，
    显示"大纲确认"按钮，等待用户审核。
    """
    context = WorkflowContext(
        creative_idea=creative_idea,
        script_format=script_format
    )
    callback = LogCallback(log_callback)

    callback.info("🚀 启动多智能体编剧工坊（阶段一：生成大纲）...")
    callback.info(f"   剧本格式：{script_format}")
    callback.log(f"[系统] 当前正在使用的 API 模型为：{model}", "system")

    mode_tag = "🔥 多巴胺" if is_micro_drama_mode(script_format) else ""
    if mode_tag:
        callback.info(f"   {mode_tag} 模式已激活")

    callback.stage("系统", f"阶段 1/2：架构师生成全局大纲（{mode_tag}版）")

    outline_result = run_showrunner_agent(
        client=client,
        model=model,
        creative_idea=creative_idea,
        script_format=script_format,
        callback=callback
    )

    if not outline_result.success:
        callback.error("❌ 架构师执行失败，流程终止")
        return context

    context.outline = outline_result.content
    context.character_settings = outline_result.content
    context.total_episodes = parse_episode_count(outline_result.content)

    callback.success(f"🎯 识别到 [总集数: {context.total_episodes}]")
    callback.info(f"   大纲已生成，等待用户审核...")

    # v2.0：自动从大纲解析节拍 → BeatOutline（如果 memory_store 可用）
    try:
        from shared.beat_outline import BeatOutline
        beat_outline = BeatOutline(project_id=creative_idea[:30])
        parsed_count = beat_outline.parse_from_showrunner_output(outline_result.content)
        if parsed_count > 0:
            callback.info(f"📋 自动解析节拍：{parsed_count}个剧情节拍已录入大纲追踪器")
            beat_outline.save()
    except Exception:
        pass  # 节拍解析失败不阻塞

    # 更新 UI 大纲区域
    if progress_callback:
        progress_callback("outline", context.outline, 1, 2)

    return context


# =============================================================================
# 阶段二函数：运行编剧+医生循环（供 app.py 在子线程调用）
# =============================================================================

def run_scripts_phase(
    client: OpenAI,
    model: str,
    creative_idea: str,
    script_format: str,
    outline: str,
    total_episodes: int,
    log_callback: Callable[[str, str], None],
    progress_callback: Optional[Callable[[str, str, int, int], None]] = None,
    memory_store: Optional["StructuredMemoryStore"] = None,
    checkpoint_manager: Optional["CheckpointManager"] = None,
    context_retriever: Optional["ContextRetriever"] = None,
) -> WorkflowContext:
    """
    阶段二：用户审核大纲后，按集数循环生成剧本。
    供 app.py 在子线程调用。

    Args:
        client: OpenAI 客户端
        model: 模型名
        creative_idea: 原始创意
        script_format: 剧本格式
        outline: 已确认的全局大纲
        total_episodes: 总集数
        log_callback: 日志回调
        progress_callback: 进度回调
        memory_store: Harness 结构化记忆（可选，None=不启用）
        checkpoint_manager: Harness 断点管理（可选，None=不启用）
        context_retriever: JIT 上下文检索器（可选，None=使用全量上下文）
    """
    context = WorkflowContext(
        creative_idea=creative_idea,
        script_format=script_format,
        outline=outline,
        total_episodes=total_episodes,
    )
    callback = LogCallback(log_callback)

    # Harness 内存记初始化日志（可选）
    _use_harness = memory_store is not None
    _use_jit = context_retriever is not None

    mode_tag = "🔥 多巴胺" if is_micro_drama_mode(script_format) else ""
    callback.info(f"🚀 阶段二启动：批量生成 {total_episodes} 集剧本（{mode_tag}版）")
    callback.log(f"[系统] 当前正在使用的 API 模型为：{model}", "system")
    if _use_harness:
        callback.info("🧠 Harness 结构化记忆已启用，长剧上下文一致性增强中...")
    if _use_jit:
        callback.info(f"⚡ JIT 上下文检索已启用（预期 token 消耗降低 40-60%）")

    callback.stage("系统", f"阶段 2/2：按集数循环生成剧本（共 {total_episodes} 集，{mode_tag}版）")

    outline_summary = extract_outline_summary(outline)
    previous_summary = ""
    final_episode_scripts: List[str] = []

    # JIT 优化：将全量 outline_summary 替换为逐集精简版
    _base_outline = outline_summary
    _base_char_settings = context.character_settings

    for episode_num in range(1, total_episodes + 1):
        context.current_episode_index = episode_num
        context.retry_count = 0
        episode_approved = False
        doctor_feedback = None   # P1修复：跨 retry 传递医生反馈
        writer_prev = None       # 用于 retry 时将上一版剧本传给 Writer 精修

        callback.episode(episode_num, f"开始生成第 {episode_num}/{total_episodes} 集...")
        callback.info("")

        # === JIT 上下文检索：按集构建精简版 outline_summary + character_settings ===
        _ep_outline = _base_outline
        _ep_char_settings = _base_char_settings
        _ep_prev_summary = previous_summary
        if _use_jit and episode_num > 1:
            try:
                jit_bundle = context_retriever.retrieve(episode_num)
                if jit_bundle.episode_outline:
                    _ep_outline = jit_bundle.episode_outline
                if jit_bundle.character_context:
                    _ep_char_settings = jit_bundle.character_context
                if jit_bundle.recent_summaries:
                    _ep_prev_summary = jit_bundle.recent_summaries
                callback.info(f"⚡ JIT 上下文：{jit_bundle.estimated_tokens()} tokens（vs 全量约 {len(_base_outline)//2} tokens）")
            except Exception:
                pass  # JIT 失败不阻塞，使用全量上下文

        # === Harness：构建结构化记忆上下文（第2集起注入）===
        harness_memory_context = ""
        if _use_harness and episode_num > 1:
            try:
                harness_memory_context = memory_store.build_writer_context_snippet(
                    current_episode=episode_num,
                    recent_episodes=5,
                )
                if harness_memory_context:
                    callback.info(f"🧠 已注入结构化记忆（角色×{memory_store.stats['characters']}，"
                                  f"伏线×{memory_store.stats['plot_threads_active']}活跃）")
            except Exception:
                pass  # 记忆注入失败不阻塞

        while not episode_approved and context.retry_count < 3:

            # === P3-1：Token 预算追踪 ===
            try:
                from harness.termination import BudgetTracker
                _budget = BudgetTracker(episode_num=episode_num, max_rounds=10)
                _budget.record_writer_call(
                    len(harness_memory_context or "") // 2 + len(_ep_outline) // 2,
                    0  # output 在 writer_result 后更新
                )
            except ImportError:
                _budget = None

            # 编剧 Agent（注入 Harness 记忆 + 医生反馈 + JIT 上下文优化）
            writer_result = run_episode_writer_agent(
                client=client,
                model=model,
                episode_num=episode_num,
                total_episodes=total_episodes,
                outline_summary=_ep_outline,
                character_settings=_ep_char_settings,
                previous_summary=_ep_prev_summary,
                memory_snapshot=context.memory_snapshot,
                script_format=script_format,
                callback=callback,
                previous_script=writer_prev if doctor_feedback else None,
                user_feedback=doctor_feedback,
                harness_memory_context=harness_memory_context,
            )

            if not writer_result.success:
                callback.error(f"❌ 第 {episode_num} 集编剧失败，跳过")
                break

            # P3-1：更新预算追踪（Writer output）
            if _budget:
                _budget.record_writer_call(0, len(writer_result.content) // 2)

            # v2.0：代码层一致性预扫描（Writer 完成后、Doctor 审核前）
            _consistency_report = ""
            if _use_harness and episode_num > 1:
                try:
                    issues = memory_store.run_consistency_check(
                        current_episode=episode_num,
                        new_content=writer_result.content,
                    )
                    if issues:
                        checker = memory_store.get_consistency_checker()
                        _consistency_report = checker.format_report(issues)
                        stats = checker.get_summary_stats(issues)
                        if stats["critical"] > 0:
                            callback.warning(f"🔍 一致性检查：发现 {stats['critical']} 个严重矛盾，"
                                             f"{stats['major']} 个建议修复")
                except Exception:
                    pass  # 一致性检查失败不阻塞

            # 医生 Agent 审核
            doctor_result = run_episode_doctor_agent(
                client=client,
                model=model,
                episode_num=episode_num,
                total_episodes=total_episodes,
                episode_content=writer_result.content,
                outline_summary=_ep_outline,
                script_format=script_format,
                callback=callback,
                consistency_report=_consistency_report,      # v2.0
                harness_doctor_context=(                     # v2.0
                    memory_store.build_doctor_check_context(
                        episode_num, writer_result.content
                    ) if _use_harness else ""
                ),
            )

            if not doctor_result.success:
                callback.error(f"❌ 第 {episode_num} 集医生审核失败，跳过")
                break

            # P3-1：更新预算追踪（Doctor call）
            if _budget:
                _budget.record_doctor_call(
                    len(writer_result.content) // 2 + 500,  # prompt estimate
                    len(doctor_result.content) // 2
                )

            if is_approved(doctor_result.content):
                episode_approved = True

                checkpoint = extract_memory_checkpoint(doctor_result.content)
                if checkpoint:
                    context.memory_snapshot = checkpoint

                final_episode_scripts.append(writer_result.content)
                context.episode_scripts = final_episode_scripts
                current_summary = get_episode_summary(writer_result.content)
                previous_summary = current_summary

                # === JIT：记录本集摘要供后续检索 ===
                if _use_jit and current_summary:
                    try:
                        context_retriever.record_episode(episode_num, current_summary)
                    except Exception:
                        pass

                # === Harness：更新结构化记忆 ===
                if _use_harness and current_summary:
                    try:
                        memory_store.update_episode_index(episode_num, current_summary)
                        # 从文本快照中提取角色信息（简单启发式）
                        _harness_update_characters_from_snapshot(
                            memory_store, checkpoint, episode_num
                        )
                    except Exception:
                        pass

                # === v2.0：更新场景时间线 + 标记节拍完成 ===
                if _use_harness:
                    try:
                        # 场景时间线：自动为该集的每个场景创建记录
                        _update_scene_timeline(
                            memory_store, episode_num, writer_result.content
                        )
                        # 节拍追踪：标记本集所有节拍为完成
                        if memory_store.beat_outline:
                            memory_store.beat_outline.mark_all_done(episode_num)
                            bs = memory_store.beat_outline.stats
                            callback.info(f"📋 节拍追踪：{bs['completed_beats']}/{bs['total_beats']} 已完成 ({bs['completion_rate']})")
                    except Exception:
                        pass

                # === Harness：自动保存断点 ===
                if checkpoint_manager is not None:
                    try:
                        checkpoint_manager.auto_save_if_needed(
                            current_episode=episode_num,
                            prefix="creator_",
                        )
                    except Exception:
                        pass

                # 实时追加到 UI 剧本正文
                if progress_callback:
                    progress_callback(
                        "script_episode",
                        writer_result.content,
                        episode_num,
                        total_episodes
                    )

                # P3-1：预算摘要
                if _budget:
                    callback.info(f"💰 预算：{_budget.summary()}")
            else:
                context.retry_count += 1
                if context.retry_count < 3:
                    callback.warning(f"🔄 第 {episode_num} 集需重写（第 {context.retry_count}/3 次）")
                    # P1修复：实际传递医生反馈给 Writer，而不是只打日志
                    doctor_feedback = doctor_result.content
                    callback.info(f"   已提取医生反馈（{len(doctor_feedback)}字符），下一轮传给编剧精修")
                    # 保存本轮被驳回的剧本，作为精修起点
                    writer_prev = writer_result.content
                else:
                    # P1修复：强制通过的集也要走完整的 Harness 更新流程
                    callback.error(f"❌ 第 {episode_num} 集重写次数超限，保留当前版本")
                    final_episode_scripts.append(writer_result.content)
                    context.episode_scripts = final_episode_scripts
                    current_summary = get_episode_summary(writer_result.content)
                    previous_summary = current_summary

                    # === JIT：记录本集摘要（强制通过也要记录）===
                    if _use_jit and current_summary:
                        try:
                            context_retriever.record_episode(episode_num, current_summary)
                        except Exception:
                            pass

                    # 提取医生最后一次审核的记忆快照
                    checkpoint = extract_memory_checkpoint(doctor_result.content)
                    if checkpoint:
                        context.memory_snapshot = checkpoint

                    # === Harness：强制通过也要更新结构化记忆 ===
                    if _use_harness and current_summary:
                        try:
                            memory_store.update_episode_index(episode_num, current_summary)
                            _harness_update_characters_from_snapshot(
                                memory_store, checkpoint, episode_num
                            )
                        except Exception:
                            pass

                    # === Harness：强制通过也要保存断点 ===
                    if checkpoint_manager is not None:
                        try:
                            checkpoint_manager.auto_save_if_needed(
                                current_episode=episode_num,
                                prefix="creator_",
                            )
                        except Exception:
                            pass

                    # 强制通过也要追加到 UI 剧本正文
                    if progress_callback:
                        progress_callback(
                            "script_episode",
                            writer_result.content,
                            episode_num,
                            total_episodes
                        )

                    episode_approved = True

        if progress_callback:
            progress_callback(
                "episode_progress",
                f"第 {episode_num}/{total_episodes} 集完成",
                episode_num,
                total_episodes
            )

    # 组合最终剧本
    separator = "\n\n" + "═" * 40 + "\n\n"
    context.script_content = separator.join(final_episode_scripts)

    # 生成最终记忆快照
    callback.info("")
    callback.stage("系统", "阶段 3/3：生成最终记忆快照")

    if not context.memory_snapshot or "════════" not in context.memory_snapshot:
        context.memory_snapshot = f"""# 最终记忆快照

## 基本信息
- **剧本格式**: {script_format}
- **完成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **总集数**: {total_episodes} 集
- **完成率**: {total_episodes}/{total_episodes} (100%)

## 故事核心
**创意**: {creative_idea}

## 工作进度
- ✅ 全局大纲：已完成（{total_episodes} 集规划）
- ✅ 人物设定：已生成
- ✅ 剧本正文：{total_episodes} 集全部完成
- ✅ 记忆快照：已生成

## 各集摘要
{previous_summary}

---
*由 AI 编剧工作室 v4.0（{mode_tag}版）自动生成*
"""

    callback.success("✅ 记忆快照已更新")

    if progress_callback:
        progress_callback("memory", context.memory_snapshot, 3, 3)

    callback.success("")
    callback.success(f"🎉 多智能体编剧工坊全部完成！")
    callback.success(f"   剧本格式：{script_format}（{mode_tag}版）" if mode_tag else f"   剧本格式：{script_format}")
    callback.success(f"   生成集数：{total_episodes} 集")

    return context


# =============================================================================
# v2.0：场景时间线更新辅助函数
# =============================================================================

def _update_scene_timeline(
    memory_store: "StructuredMemoryStore",
    episode_num: int,
    episode_content: str,
):
    """从新生成的剧本中自动提取场景信息，更新 SceneTimeline。

    扫描剧本中的「【场景：...】」或「第N场」标记，
    为每个场景创建 SceneRecord 并记录关键事实。
    """
    if memory_store.scene_timeline is None:
        try:
            from shared.scene_timeline import SceneTimeline, SceneRecord
            memory_store.scene_timeline = SceneTimeline(
                project_id=memory_store.project_id
            )
        except Exception:
            return

    tl = memory_store.scene_timeline

    # 检测场景标记
    # 格式1：【场景：地点/时间】
    # 格式2：第X场
    scene_markers = list(re.finditer(
        r'(?:【场景[：:]?\s*([^】/]+)(?:[／/]\s*([^】]+))?】)|'
        r'(?:第\s*([一二三四五六七八九十\d]+)\s*场)',
        episode_content
    ))

    if not scene_markers:
        # 没有场景标记，创建一个默认场景记录
        rec_id = f"e{episode_num}_s1"
        rec = _build_scene_record(
            rec_id, episode_num, 1, episode_content, ["全文"]
        )
        tl.add_scene(rec)
        return

    # 按位置切分剧本为各场景
    scene_texts = []
    for i, m in enumerate(scene_markers):
        start = m.start()
        end = scene_markers[i + 1].start() if i + 1 < len(scene_markers) else len(episode_content)
        scene_texts.append(episode_content[start:end])

    for i, (match, text) in enumerate(zip(scene_markers, scene_texts)):
        scene_num = i + 1
        rec_id = f"e{episode_num}_s{scene_num}"

        # 提取地点和时间
        location = ""
        time_of_day = ""
        if match.group(1):  # 格式1的 地点
            location = match.group(1).strip()
            if match.group(2):
                time_of_day = match.group(2).strip()

        rec = _build_scene_record(rec_id, episode_num, scene_num, text, [location, time_of_day])
        tl.add_scene(rec)

    tl.save()


def _build_scene_record(
    rec_id: str,
    episode: int,
    scene_num: int,
    text: str,
    location_parts: list,
):
    """构建单个 SceneRecord"""
    from shared.scene_timeline import SceneRecord

    rec = SceneRecord(
        scene_id=rec_id,
        episode=episode,
        scene_number=scene_num,
    )

    # 地点
    location = next((p for p in location_parts if p and p != "全文"), "")
    rec.location = location

    # 位置类型判断
    if any(w in (location or "") for w in ["内", "室", "厅", "房", "屋"]):
        rec.location_type = "内景"
    elif any(w in (location or "") for w in ["外", "街", "林", "野", "山", "海"]):
        rec.location_type = "外景"

    # 时间
    time_pattern = re.search(
        r'(?:时间[：:]?\s*)?(深夜|清晨|上午|下午|傍晚|黄昏|夜晚|午夜|凌晨|白天|午后)',
        text[:200]
    )
    if time_pattern:
        rec.time_of_day = time_pattern.group(1)

    # 出场角色（从台词中提取）
    char_matches = re.findall(r'([\u4e00-\u9fa5A-Za-z0-9]{2,6})[：:](?![""「」『』])', text)
    rec.characters_present = list(dict.fromkeys(char_matches))[:8]  # 去重，最多8个

    # 摘要
    rec.summary = text[:150].replace('\n', ' ').strip()

    # 关键事实（从摘要中提取包含关键动词的句子）
    fact_patterns = [
        r'(?:发现|获得|失去|收到|藏|埋|拿出|递给|交给|留下|带走)([\u4e00-\u9fa5]{3,30})',
        r'([\u4e00-\u9fa5]{3,20})(?:被|在|从)(?:发现|获得|拿走|偷走)',
    ]
    for pat in fact_patterns:
        for fm in re.finditer(pat, text[:500]):
            fact = fm.group(0)[:40]
            if fact not in rec.key_facts:
                rec.key_facts.append(fact)

    # 字数
    rec.word_count = len(text)

    return rec


# =============================================================================
# v5.0 HITL 定向修改阶段函数
# ============================================================================

def run_showrunner_revision_phase(
    client: OpenAI,
    model: str,
    creative_idea: str,
    script_format: str,
    previous_outline: str,
    user_feedback: str,
    log_callback: Callable[[str, str], None],
    progress_callback: Optional[Callable[[str, str, int, int], None]] = None,
) -> WorkflowContext:
    """
    定向修改阶段（大纲）：用户对大纲提交修改意见后，架构师进行定向精修。

    Args:
        client: OpenAI 客户端
        model: 模型名
        creative_idea: 原始创意
        script_format: 剧本格式
        previous_outline: 之前的初稿大纲
        user_feedback: 用户的定向修改意见
        log_callback: 日志回调
        progress_callback: 进度回调
    """
    context = WorkflowContext(
        creative_idea=creative_idea,
        script_format=script_format,
    )
    callback = LogCallback(log_callback)

    mode_tag = "🔥 多巴胺" if is_micro_drama_mode(script_format) else ""
    callback.stage("系统", f"🎯 大纲定向修改阶段（{mode_tag}版）")
    callback.log(f"[系统] 当前正在使用的 API 模型为：{model}", "system")
    callback.info(f"   修改意见：{user_feedback[:80]}...")
    callback.info("")

    # 架构师定向精修（不经过医生，大纲阶段无需医生审核）
    outline_result = run_showrunner_agent(
        client=client,
        model=model,
        creative_idea=creative_idea,
        script_format=script_format,
        callback=callback,
        previous_outline=previous_outline,
        user_feedback=user_feedback,
    )

    if not outline_result.success:
        callback.error("❌ 大纲定向修改失败")
        return context

    context.outline = outline_result.content
    context.character_settings = outline_result.content
    context.total_episodes = parse_episode_count(outline_result.content)

    callback.success(f"🎯 大纲定向修改完成，识别到 [总集数: {context.total_episodes}]")
    callback.info("   请审核修改后的大纲，确认无误后继续")

    # 更新 UI 大纲区域
    if progress_callback:
        progress_callback("outline", context.outline, 1, 2)

    return context


def run_episode_revision_phase(
    client: OpenAI,
    model: str,
    episode_num: int,
    total_episodes: int,
    outline_summary: str,
    character_settings: str,
    previous_summary: str,
    memory_snapshot: str,
    script_format: str,
    previous_script: str,
    user_feedback: str,
    log_callback: Callable[[str, str], None],
    progress_callback: Optional[Callable[[str, str, int, int], None]] = None,
    memory_store: Optional["StructuredMemoryStore"] = None,
    checkpoint_manager: Optional["CheckpointManager"] = None,
) -> WorkflowContext:
    """
    定向精修阶段（单集剧本）：用户对某集剧本提交修改意见后，
    编剧精修 + 医生强制审核。

    这是核心协同要求：编剧修改后的剧本必须再次送给医生审核，
    只有医生通过才能输出给用户。

    Args:
        client: OpenAI 客户端
        model: 模型名
        episode_num: 待精修的集数
        total_episodes: 总集数
        outline_summary: 大纲摘要
        character_settings: 人物小传
        previous_summary: 上一集摘要
        memory_snapshot: 记忆快照
        script_format: 剧本格式
        previous_script: 之前的初稿剧本
        user_feedback: 用户的定向修改意见
        log_callback: 日志回调
        progress_callback: 进度回调（episode_rejected 表示医生驳回，episode_revised_ok 表示精修通过）
    """
    context = WorkflowContext(
        creative_idea="",
        script_format=script_format,
        total_episodes=total_episodes,
        current_episode_index=episode_num,
    )
    callback = LogCallback(log_callback)

    mode_tag = "🔥 多巴胺" if is_micro_drama_mode(script_format) else ""
    callback.stage("系统", f"🎯 第 {episode_num} 集定向精修阶段（{mode_tag}版）")
    callback.log(f"[系统] 当前正在使用的 API 模型为：{model}", "system")
    callback.info(f"   修改意见：{user_feedback[:80]}...")
    callback.info("")

    # === Harness：定向精修也注入结构化记忆 ===
    harness_memory_context = ""
    if memory_store is not None and episode_num > 1:
        try:
            harness_memory_context = memory_store.build_writer_context_snippet(
                current_episode=episode_num,
                recent_episodes=3,
            )
        except Exception:
            pass

    # 第一步：编剧 Agent 定向精修
    callback.episode(episode_num, "🎯 编剧正在根据意见精修...")
    writer_result = run_episode_writer_agent(
        client=client,
        model=model,
        episode_num=episode_num,
        total_episodes=total_episodes,
        outline_summary=outline_summary,
        character_settings=character_settings,
        previous_summary=previous_summary,
        memory_snapshot=memory_snapshot,
        script_format=script_format,
        callback=callback,
        previous_script=previous_script,
        user_feedback=user_feedback,
        harness_memory_context=harness_memory_context,
    )

    if not writer_result.success:
        callback.error(f"❌ 第 {episode_num} 集精修失败")
        return context

    # 第二步：医生 Agent 强制审核（绝不能跳过！）
    callback.episode(episode_num, "🔍 医生正在审核精修结果...")

    # v2.0：精修版也运行一致性检查
    _revision_consistency = ""
    if memory_store is not None and episode_num > 1:
        try:
            issues = memory_store.run_consistency_check(episode_num, writer_result.content)
            if issues:
                checker = memory_store.get_consistency_checker()
                _revision_consistency = checker.format_report(issues)
        except Exception:
            pass

    doctor_result = run_episode_doctor_agent(
        client=client,
        model=model,
        episode_num=episode_num,
        total_episodes=total_episodes,
        episode_content=writer_result.content,
        outline_summary=outline_summary,
        script_format=script_format,
        callback=callback,
        consistency_report=_revision_consistency,        # v2.0
        harness_doctor_context=(                         # v2.0
            memory_store.build_doctor_check_context(
                episode_num, writer_result.content
            ) if memory_store is not None else ""
        ),
    )

    if not doctor_result.success:
        callback.error(f"❌ 第 {episode_num} 集医生审核失败")
        return context

    if is_approved(doctor_result.content):
        # 医生审核通过
        callback.success(f"✅ 第 {episode_num} 集定向精修通过！")
        context.script_content = writer_result.content
        checkpoint = extract_memory_checkpoint(doctor_result.content)
        if checkpoint:
            context.memory_snapshot = checkpoint

        # === Harness：定向精修后更新结构化记忆 ===
        current_summary = get_episode_summary(writer_result.content)
        if memory_store is not None and current_summary:
            try:
                memory_store.update_episode_index(episode_num, current_summary)
                _harness_update_characters_from_snapshot(
                    memory_store, checkpoint, episode_num
                )
            except Exception:
                pass
        if checkpoint_manager is not None:
            try:
                checkpoint_manager.auto_save_if_needed(
                    current_episode=episode_num,
                    prefix="creator_",
                )
            except Exception:
                pass

        if progress_callback:
            progress_callback(
                "episode_revised_ok",
                writer_result.content,
                episode_num,
                total_episodes,
            )
    else:
        # 医生驳回：通知 UI 继续修改循环
        callback.warning(f"⚠️ 第 {episode_num} 集医生仍需修改（内部重试）")
        callback.info("   医生反馈：" + doctor_result.content[:200] + "...")
        if progress_callback:
            progress_callback(
                "episode_rejected",
                doctor_result.content,
                episode_num,
                total_episodes,
            )

    return context


# =============================================================================
# Harness 辅助函数
# =============================================================================

def _harness_update_characters_from_snapshot(
    memory_store: "StructuredMemoryStore",
    memory_snapshot: str,
    episode_num: int,
):
    """
    从 Doctor 记忆快照中提取角色信息，更新结构化记忆。

    采用启发式提取，兼容两种格式：
    1. 【角色当前状态】段落 + "角色名：状态" 模式（标准 Doctor 输出）
    2. **本集摘要** 行模式（兼容 Markdown 格式）

    容错设计：
    - 即使提取不完整也不影响创作（记忆注入是补充性的）
    - 所有异常静默处理，不回滚已成功的提取
    - 不同模型输出格式差异大，regex 仅匹配已知模式

    注意：如果 Doctor prompt 格式变更，此处的 regex 需要同步更新。
    """
    if not memory_snapshot or not memory_store:
        return

    import re
    extracted_any = False

    # 策略1：精确匹配【角色当前状态】段落（标准 Doctor 输出）
    char_section_match = re.search(
        r'【角色当前状态】(.*?)(?:【|(?:\n\n))',
        memory_snapshot, re.DOTALL
    )
    if char_section_match:
        char_text = char_section_match.group(1)
        for match in re.finditer(r'[【\s]*(\S{1,8})[：:](.*?)(?=\n[【\s]*\S{1,8}[：:]|\n\n|$)', char_text, re.DOTALL):
            name = match.group(1).strip()
            detail = match.group(2).strip()
            if not name or len(name) > 8:
                continue
            try:
                char = memory_store.get_or_create_character(name)
                char.current_emotion = detail[:60]
                char.key_events.append(f"第{episode_num}集：{detail[:40]}")
                memory_store.update_character(char, episode=episode_num)
                extracted_any = True
            except Exception:
                pass

    # 策略2：宽松 fallback — 匹配 Markdown 的 **角色名**：状态 格式
    if not extracted_any and '角色' in memory_snapshot:
        for match in re.finditer(
            r'\*\*(\S{1,8})\*\*[：:]\s*(.*?)(?:\n|$)',
            memory_snapshot
        ):
            name = match.group(1).strip()
            detail = match.group(2).strip()
            if not name or len(name) > 8:
                continue
            # 排除非角色词（章节、标题等）
            skip_words = {'本集', '上一集', '下一集', '摘要', '要点', '大纲', '注意'}
            if name in skip_words:
                continue
            try:
                char = memory_store.get_or_create_character(name)
                if not char.current_emotion or char.current_emotion == "未知":
                    char.current_emotion = detail[:60]
                char.key_events.append(f"第{episode_num}集：{detail[:40]}")
                memory_store.update_character(char, episode=episode_num)
                extracted_any = True
            except Exception:
                pass

    # 提取【本集摘要】（兼容两种格式）
    for pattern in [
        r'\*\*本集摘要\*\*[：:]\s*(.*?)(?:\n|$)',
        r'【本集摘要】[：:]\s*(.*?)(?:\n|$)',
    ]:
        summary_match = re.search(pattern, memory_snapshot)
        if summary_match:
            summary = summary_match.group(1).strip()
            if summary:
                try:
                    memory_store.update_episode_index(episode_num, summary)
                except Exception:
                    pass
            break


# =============================================================================
# 工具 Schema 注入辅助函数
# =============================================================================

def _inject_tool_schema_if_available(base_prompt: str, agent: str) -> str:
    """如果 Harness tool_schema 模块可用，注入对应 Agent 的工具声明。"""
    try:
        from harness.tool_schema import create_default_registry
        registry = create_default_registry()
        tool_text = registry.format_for(agent)
        if tool_text:
            return base_prompt + "\n\n" + tool_text
    except Exception:
        pass
    return base_prompt


def run_writer_studio(
    client: OpenAI,
    model: str,
    creative_idea: str,
    script_format: str,
    log_callback: Callable[[str, str], None],
    progress_callback: Optional[Callable[[str, str, int, int], None]] = None,
    memory_store: Optional["StructuredMemoryStore"] = None,
    checkpoint_manager: Optional["CheckpointManager"] = None,
) -> WorkflowContext:
    """
    兼容旧接口：一键运行完整流程（架构师→编剧→医生）。
    内部自动拆分为两阶段执行，但对外表现为一个调用。
    """
    # 阶段一
    context = run_showrunner_phase(
        client, model, creative_idea, script_format,
        log_callback, progress_callback
    )
    if not context.outline:
        return context

    # 阶段二（传递 Harness 组件）
    return run_scripts_phase(
        client, model, creative_idea, script_format,
        context.outline, context.total_episodes,
        log_callback, progress_callback,
        memory_store=memory_store,
        checkpoint_manager=checkpoint_manager,
    )


def run_workflow(
    base_url: str,
    api_key: str,
    model: str,
    creative_idea: str,
    script_format: str,
    log_callback: Callable[[str, str], None],
    progress_callback: Optional[Callable[[str, str, int, int], None]] = None,
    memory_store: Optional["StructuredMemoryStore"] = None,
    checkpoint_manager: Optional["CheckpointManager"] = None,
) -> WorkflowContext:
    """便捷入口函数"""
    client = OpenAI(base_url=base_url, api_key=api_key)
    return run_writer_studio(
        client=client, model=model,
        creative_idea=creative_idea, script_format=script_format,
        log_callback=log_callback, progress_callback=progress_callback,
        memory_store=memory_store,
        checkpoint_manager=checkpoint_manager,
    )
