"""
shared/llm_config.py — 统一 LLM 配置管理
========================================

全格式影视剧本工业流水线专用配置层。
支持主流云端 API + 本地 Ollama，动态 Prompt 路由引擎。
"""

import streamlit as st
import httpx
import requests
from openai import OpenAI
from typing import Optional, Tuple, List, Dict


# =============================================================================
# 模型服务商配置
# =============================================================================

LLM_PROVIDERS: Dict[str, Dict[str, str]] = {
    # ── 国内主力 ──
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",
        "placeholder": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "硅基流动 SiliconFlow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "placeholder": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "阿里通义 Qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "placeholder": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "Kimi (Moonshot)": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "placeholder": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "GLM (智谱)": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "placeholder": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "零一万物 Yi": {
        "base_url": "https://api.lingyiwanwu.com/v1",
        "default_model": "yi-large",
        "placeholder": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    # ── 海外主力 ──
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "placeholder": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "Claude (Anthropic)": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-4-20250514",
        "placeholder": "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "placeholder": "gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "Gemini (Google)": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
        "placeholder": "AIzaSyxxxxxxxxxxxxxxxxxxxxxxx"
    },
    "Mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "placeholder": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    },
    # ── 本地 ──
    "本地 Ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.2",
        "placeholder": "ollama"
    },
}

# 二级联动：各服务商对应的可选模型列表
MODEL_OPTIONS: Dict[str, List[str]] = {
    "DeepSeek": [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "硅基流动 SiliconFlow": [
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-V2.5",
        "Qwen/Qwen2.5-72B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.3",
    ],
    "阿里通义 Qwen": [
        "qwen-plus",
        "qwen-plus-latest",
        "qwen-turbo",
        "qwen-long",
    ],
    "Kimi (Moonshot)": [
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ],
    "GLM (智谱)": [
        "glm-4-flash",
        "glm-4-air",
        "glm-4-plus",
        "glm-4v-flash",
    ],
    "零一万物 Yi": [
        "yi-large",
        "yi-large-rag",
        "yi-medium",
        "yi-spark",
    ],
    "OpenAI": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
    ],
    "Claude (Anthropic)": [
        "claude-sonnet-4-20250514",
        "claude-opus-4-5",
        "claude-haiku-3-5",
    ],
    "Groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ],
    "Gemini (Google)": [
        "gemini-2.0-flash",
        "gemini-2.5-pro-preview-06-05",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ],
    "Mistral": [
        "mistral-large-latest",
        "mistral-small-latest",
        "open-mixtral-8x22b",
    ],
    "本地 Ollama": [],       # 运行时动态检测
}


# =============================================================================
# 剧本格式选项（全格式影视工业流水线）
# =============================================================================

SCRIPT_FORMATS: Dict[str, str] = {
    "默认（跟随创意要求）":
        "默认模式 | 由用户创意决定格式、时长与体量 | 不套用固定模板",
    "竖屏微短剧（1-2分钟/集，主打极致情绪）":
        "竖屏微短剧 | 1-2分钟/集 | 极致情绪爽感 | 多巴胺爆款公式",
    "短剧（5-10分钟/集，情绪与逻辑并重）":
        "短剧 | 5-10分钟/集 | 情绪与逻辑并重 | 四段式结构",
    "中剧（10-20分钟/集，结构相对完善）":
        "中剧 | 10-20分钟/集 | 结构相对完善 | 多集叙事节奏",
    "长剧（40-60分钟/集，标准电视剧制式）":
        "长剧 | 40-60分钟/集 | 标准电视剧制式 | 双层嵌套结构",
    "电影长片（90-120分钟，工业标准与爆款节拍）":
        "电影长片 | 90-120分钟 | Save the Cat 15节拍 | Ghost/Lie/Flaw",
}


# =============================================================================
# 动态 Prompt 路由引擎（关键！）
# =============================================================================

def get_format_strategy(format_name: str) -> Dict[str, Dict[str, str]]:
    """
    根据剧本格式返回专属的附加 System Prompt。

    每个格式返回三个 Agent 的追加 Prompt：
      showrunner_suffix : 架构师（Showrunner）的格式专属指令
      writer_suffix     : 编剧（Writer）的格式专属指令
      doctor_suffix     : 医生（Doctor）的格式专属指令

    这些后缀会被动态追加到各 Agent 的主 System Prompt 末尾，
    确保模型严格遵守格式规范，与 HITL 两阶段审批流无缝兼容。
    """
    strategies = {

        # ══════════════════════════════════════════════════════════
        # 0. 默认模式（跟随用户创意要求，不套用固定模板）
        # ══════════════════════════════════════════════════════════
        "默认（跟随创意要求）": {
            "showrunner_suffix": """
## 【格式策略：默认模式 — 严格跟随用户创意要求】

### 架构师核心指令（最高优先级，覆盖基础提示中的默认假设）
1. **不套用任何固定格式模板**：不要强制使用 Save the Cat、三幕式、多巴胺爽剧、四段式等任何固定结构，除非用户明确要求。
2. **严格解析用户创意中的格式要求**：仔细阅读「用户创意」，提取其中关于字数、时长、集数、类型、风格、结构的任何明确要求。
   - 例如："2000字短片" → 按约2000字的独立短片处理，[总集数: 1]。
   - 例如："5分钟短片" → 按5分钟体量短片处理，[总集数: 1]。
   - 例如："写30集" / "50集微短剧" → 按对应集数处理，[总集数: 30] / [总集数: 50]。
   - 例如："电影长片" / "90分钟电影" → 按电影长片处理，[总集数: 1]，使用场次结构而非集结构。
3. **用户未明确时自主判断**：如果用户没有明确字数/时长/集数，根据创意内容自主推断最合适的影视形式，并在大纲中说明你的判断依据。
4. **输出格式仍须规范**：即使不套用模板，也必须在大纲开头标注 [总集数: N]，并在「基本信息」里写明用户指定的格式或你的判断。
5. **基础提示中的默认假设失效**：当用户选择本模式时，基础提示里的"默认设定为20集"、"1-2分钟"等默认假设均不再适用；一切以用户创意或你的自主判断为准。
""",
            "writer_suffix": """
## 【格式策略：默认模式 — 跟随创意要求，不强制固定模板】

### 编剧核心指令（最高优先级，覆盖基础提示中的默认假设）
1. **严格按用户创意中的格式/体量要求输出**：若用户要求"2000字短片"则输出约2000字；若要求"5分钟短片"则按5分钟节奏；若要求多集则按多集输出。
2. **不强制微短剧节奏**：不要求每集1-2分钟、每句15字、必须30秒内反击、必须Cliffhanger等，除非用户创意本身符合爽剧/短剧要求。
3. **结构与形式由创意决定**：用户写电影则写电影场次；用户写短片则写单篇完整剧本；用户写剧集则按集输出。绝对禁止把单篇短片拆成多集。
4. **保留专业编剧铁律**：禁止心理描写、括号暗示、解释性台词、说教片段；坚持视觉化叙事、口语化台词。
""",
            "doctor_suffix": """
## 【格式策略：默认模式 — 按用户创意要求审核】

### 医生核心指令（最高优先级，覆盖基础提示中的默认假设）
1. **审核标准由用户创意决定**：若用户要求是慢节奏文艺短片、实验片、电影长片或任意非爽剧形式，不得以微短剧的"30秒冲突、每句15字、必须钩子"等标准强行驳回。
2. **检查是否满足用户明确提出的格式/体量要求**：如字数、时长、集数、结构形式是否达标。
3. **保留基础红线**：心理描写、括号暗示、解释性台词、说教片段仍属违规。
4. **若用户创意未明确格式，则检查编剧是否给出了合理的自主判断并执行一致**。
""",
        },

        # ══════════════════════════════════════════════════════════
        # 1. 竖屏微短剧（1-2分钟/集）
        # ══════════════════════════════════════════════════════════
        "竖屏微短剧（1-2分钟/集，主打极致情绪）": {
            "showrunner_suffix": """
## 【格式策略：竖屏微短剧 — 多巴胺爆款引擎】

### 架构师核心指令
1. **彻底抛弃"娓娓道来"** — 不允许有慢热铺垫，开场即冲突
2. 大纲必须包含【一句话痛点 + 爽感核心 + 目标受众共鸣点】
3. 每集只需三要素：核心情绪点 / 解决方式 / 尾部钩子
4. 主角必须有至少一次"打脸反击"，禁止憋屈不反击
5. 大结局情绪峰值必须高于前所有集，禁止虎头蛇尾
6. 集数建议：每集1-2分钟体量，10-30集为宜
7. 必须在 [总集数: N] 标注后，额外标注【格式标签：竖屏微短剧/多巴胺爽剧】
""",
            "writer_suffix": """
## 【格式策略：竖屏微短剧 — 多巴胺爆款引擎】

### 编剧核心指令
1. **强制三段式公式**：痛点抛出（前15秒）→ 迅速打脸（30秒内）→ 新钩子（结尾最后10句）
2. 禁止慢节奏铺垫，开场3秒内必须出现极端情绪压迫
3. 主角被打压后**必须在本集反击**，绝不能憋到下一集
4. 反转方式：身份揭晓 / 证据打脸 / 霸气护短 / 能力展示（必须有实际行动）
5. 台词像刀子一样短促有力，每句不超过15字
6. 必须包含高冲击动作：耳光、巴掌、掀桌、摔门、冷笑微表情
7. 结尾 Cliffhanger 必须是：更大危机 / 身份反转 / 致命误解 / 关键证据出现
8. 体量：1-2分钟，约400-500字
""",
            "doctor_suffix": """
## 【格式策略：竖屏微短剧 — 多巴胺爽剧审核】

### 医生核心指令
1. **首要标准：情绪是否得到满足** — 不要用传统电影逻辑要求微短剧
2. **前15秒情绪压迫检验**：主角必须在前15秒内遭遇极端情绪压迫，无则驳回
3. **30秒内反击检验**：主角被欺负后憋超过1分钟则驳回，多巴胺必须快速释放
4. **打脸力度检验**：反击必须是实际行动（掏出证据/霸气发言），口头辩解不达标
5. **钩子强度检验**：平淡结尾（如"第二天又见面了"）驳回；钩子必须满足更大危机/身份反转/致命误解/证据出现
6. 写作红线：心理描写驳回 / 括号暗示驳回 / 解释性台词驳回 / 慢节奏铺垫驳回
7. 单集结尾必须卡在最高潮悬念，吸引继续看下一集
8. 全剧最后一集情绪峰值必须高于前集，禁止虎头蛇尾
""",
        },

        # ══════════════════════════════════════════════════════════
        # 2. 短剧（5-10分钟/集）
        # ══════════════════════════════════════════════════════════
        "短剧（5-10分钟/集，情绪与逻辑并重）": {
            "showrunner_suffix": """
## 【格式策略：短剧 — 情绪与逻辑并重】

### 架构师核心指令
1. **四段式结构**：起因 / 发展 / 高潮 / 结局（每段约1/4体量）
2. 主角必须有明确的 Want（外在需求）和 Need（内在欲望），以及一次完整的 A→B 弧光变化
3. 保留微短剧快节奏钩子优点，但必须保证故事逻辑和人物动机的合理性
4. 反派/阻碍力量必须足够强大，让解决过程有张力
5. 需要设计1-2个"情感炸弹时刻"，让观众既爽又有情感共鸣
6. 集数建议：每集5-10分钟体量，3-12集为宜
7. 每集结尾仍需悬念钩子，但可以比微短剧稍长（30-60秒铺垫+钩子）
""",
            "writer_suffix": """
## 【格式策略：短剧 — 情绪与逻辑并重】

### 编剧核心指令
1. **四段式节奏**：起因（建置冲突）→ 发展（升级冲突）→ 高潮（最强对峙）→ 结局（解决/新冲突）
2. 平衡情节密度与呼吸感 — 允许少量情感铺垫，但不能拖沓
3. 人物动机必须有逻辑支撑 — 不能为了爽感牺牲合理性
4. 台词兼顾视觉冲击力和口语化 — 比微短剧稍长（单句20字以内），但必须掷地有声
5. 动作描写要有画面感 — 比微短剧更注重场景氛围营造
6. 必须设计1-2个"情感炸弹"场景 — 让观众既爽又被打动
7. Cliffhanger 可以比微短剧复杂 — 允许30-60秒的悬念铺陈
8. 体量：5-10分钟，约1500-2500字
""",
            "doctor_suffix": """
## 【格式策略：短剧 — 情绪与逻辑并重】

### 医生核心指令
1. **核心戏剧动作有效性检验**：每个场景必须有明确的戏剧动作，无效场景驳回
2. **人物动机合理性检验**：主角/反派的每个决定是否有内在逻辑支撑，强行降智驳回
3. **情感共鸣检验**：是否有1-2个"情感炸弹"时刻让观众被打动
4. **节奏张弛检验**：是否有呼吸感（情感铺垫）穿插在紧张冲突之间
5. 写作红线：心理描写驳回 / 括号暗示驳回 / 解释性台词驳回 / 无效情节（推进不了故事的纯过渡场景）驳回
6. **四段式完整性检验**：起因/发展/高潮/结局是否完整，哪段缺失驳回
7. 伏笔必须有回扣，埋而不揭超过1/2体量需警告
""",
        },

        # ══════════════════════════════════════════════════════════
        # 3. 中剧（10-20分钟/集）
        # ══════════════════════════════════════════════════════════
        "中剧（10-20分钟/集，结构相对完善）": {
            "showrunner_suffix": """
## 【格式策略：中剧 — 结构相对完善】

### 架构师核心指令
1. **完整单集结构**：开场（建置15%）→ 第一个转折点（25%）→ 中点（50%）→ 第二个转折点（75%）→ 高潮+结局（90-100%）
2. 主角弧光必须在单集内完成一次完整的 Want vs Need 对峙
3. 必须有清晰的 B Story（副线）或 C Story（调味线）作为节奏调节
4. 允许更复杂的角色关系网络 — 单集可容纳3-5个主要角色互动
5. 潜台词密度提升 — 禁止过于直白的台词，鼓励言外之意
6. 集数建议：每集10-20分钟体量，6-24集为宜
7. 规划跨集暗线 — 标记哪些线索需要多集铺垫后引爆
""",
            "writer_suffix": """
## 【格式策略：中剧 — 结构相对完善】

### 编剧核心指令
1. **单集五段式节奏**：开场建置 → 第一个转折 → 中点标志 → 第二个转折 → 高潮+解决
2. 每集主角必须有明确的"本集欲望"和"本集障碍"
3. 允许30-90秒的情感铺垫段落，但必须有明确目的（建立关系/揭示秘密/制造误解）
4. 潜台词写作 — 禁止"我知道你心里在想什么"式直白台词，用物理行为暗示心理
5. B Plot 与 A Plot 交织 — 副线必须与主线产生化学反应，不能独立存在
6. 对话节奏更从容 — 单句可稍长（20-30字），但必须有潜台词层次
7. 体量：10-20分钟，约3000-6000字
""",
            "doctor_suffix": """
## 【格式策略：中剧 — 结构相对完善】

### 医生核心指令
1. **单集结构完整性检验**：开场建置/转折点/中点/高潮是否完整，哪段缺失驳回
2. **角色弧光检验**：主角本集 Want vs Need 的对峙是否有足够强度
3. **潜台词密度检验**：检测直白心理台词，直白出现3次以上则驳回
4. **B Plot 有效性检验**：副线是否与主线有化学反应，孤立无关联的副线驳回
5. **连续性检验**：本集发生的事件与前集是否连贯，连续性错误驳回
6. **节奏张弛检验**：紧张段落与情感段落交替是否合理
7. 伏笔登记：标记本集埋下了哪些伏笔，剧终前必须全部回扣
""",
        },

        # ══════════════════════════════════════════════════════════
        # 4. 长剧（40-60分钟/集）
        # ══════════════════════════════════════════════════════════
        "长剧（40-60分钟/集，标准电视剧制式）": {
            "showrunner_suffix": """
## 【格式策略：长剧 — 双层嵌套结构 + 季度弧线】

### 架构师核心指令
1. **双层嵌套结构**：单集结构（每集独立弧线）+ 季度弧线（全季完整弧光）
2. 每集必须分配明确的"弧光预算" — 本集在季度弧线中的功能是什么？
3. 必须设计跨集暗线（B Story）— 与主线交织的副线，需要多集铺垫
4. 世界观分层释放时间表 — 标记哪些信息在哪一集/哪一季才揭示
5. 多角色关系网络 — 设计核心5人组+扩展角色池，标注每集谁与谁互动
6. 单集仍需完整的 Want vs Need 对峙，但解决可能是"部分解决+新障碍"
7. 集数建议：每集40-60分钟体量，20-50集/季为宜
8. 大结局必须有"全季最大爆点" — 比任何单集都强烈的情绪/悬念/揭示
""",
            "writer_suffix": """
## 【格式策略：长剧 — 双线交织 + 季度叙事】

### 编剧核心指令
1. **主副线交织原则**：A Plot（主线）与 B Plot（副线）必须在单集内产生化学反应，不能各说各话
2. **季度弧线意识**：每个场景在单集弧线中的功能之外，还需标注对季度弧线的贡献
3. **潜台词强制使用**：人物对话必须用潜台词，禁止直白表达情感/意图
4. **跨集连续性**：主动追踪活跃线索，本集引入的线索必须有后续交代
5. **记忆检查点必须更新**：每集结尾必须生成结构化记忆快照，防止长剧遗忘前面剧情
6. 单集允许多个小高潮+一个大高潮，避免单集情绪平淡
7. 体量：40-60分钟，约8000-15000字
8. 每集结尾：可以是单集解决+新障碍引入，也可以是未解决悬念
""",
            "doctor_suffix": """
## 【格式策略：长剧 — 双层审核 + 连续性严查】

### 医生核心指令
1. **双层结构检验**：单集弧线（是否完整）+ 季度弧线（是否推进了一步）
2. **连续性错误严查**：追踪本集角色状态/关系/事件与前集是否一致，错误则驳回
3. **活跃线索追踪**：检查是否有超过3集未推进的悬置线索，悬置警告
4. **记忆检查点检验**：检查本集结尾是否生成了有效的结构化记忆快照，无则强制生成
5. **潜台词密度**：直白心理台词出现5次以上则驳回
6. **B Plot 质量检验**：副线是否有独立戏剧价值，还是只是主线的附庸
7. **季度节奏评估**：当前集在季度中的位置（建置期/中段/高潮期），节奏是否与位置匹配
8. 跨集伏笔登记 — 确保多集伏笔有计划地回扣
""",
        },

        # ══════════════════════════════════════════════════════════
        # 5. 电影长片（90-120分钟）
        # ══════════════════════════════════════════════════════════
        "电影长片（90-120分钟，工业标准与爆款节拍）": {
            "showrunner_suffix": """
## 【格式策略：电影长片 — Save the Cat + McKee 原理】

### 架构师核心指令
1. **强制套用 Save the Cat 15 节拍表**（必须标注每节拍的精确时间点）：
   - 开场画面（0-5分钟）/ 主题陈述（5分钟）/ 设定（1-12分钟）
   - 催化剂（12分钟）/ 第二回合（12-25分钟）/ 游戏时间（25-55分钟）
   - 一切皆失（55分钟）/ 深夜（55-75分钟）/ 第三回合（75-85分钟）
   - 结局（85-110分钟）/ 终场画面（110分钟）
2. **必须设定 Ghost（前史创伤）、Lie（核心谎言）、Flaw（角色缺陷）**
3. **伏笔与回扣登记表**：每个伏笔标注在哪个节拍埋入、在哪里回扣
4. 主角必须经历完整的 A→B 弧光变化，从 False Believing 到 Catharsis
5. 结尾不允许有"第二幕拖尾" — 每分钟都必须有叙事价值
6. **三幕结构严格对齐**：第一幕（0-25分钟）/ 第二幕（25-85分钟）/ 第三幕（85-110分钟）
7. 必须在 [总集数: 1] 后标注【格式标签：电影长片 / Save the Cat 15节拍 / Ghost-Lie-Flaw】
""",
            "writer_suffix": """
## 【格式策略：电影长片 — 双轨节奏 + Save the Cat】

### 编剧核心指令
1. **双轨节奏系统**：外部情节节奏（节拍器驱动）与内在情感节奏（弧光推进）必须张弛对比
2. **严格对齐 Save the Cat 节拍表**：每场戏必须标注属于哪个节拍，功能是什么
3. **Ghost/Lie/Flaw 贯穿始终**：主角的 False Believing 必须在第一幕建立，并在第三幕彻底打破
4. **伏笔即承诺**：每个铺垫都必须在后续某处兑现，埋而不用是叙事欺诈
5. **场景价值转变**：每个场景结束时，核心价值必须发生翻转（正面→负面或负面→正面），价值不变的场景必须重写
6. **潜台词强制使用**：台词必须像冰山，只有1/3浮在水面，2/3在水面以下
7. **禁止无效场景**：每个场景必须有独立戏剧功能，不能只是"过渡"或"介绍"
8. 体量：90-120分钟，约20000-35000字
""",
            "doctor_suffix": """
## 【格式策略：电影长片 — 全盘价值审核】

### 医生核心指令
1. **场景价值翻转审核（最核心！）**：
   每个场景结束时核心价值是否发生了翻转？
   价值未变则必须重写，这是电影质量的核心标准
2. **Ghost/Lie/Flaw 贯穿审核**：
   - Ghost（前史创伤）是否在第一幕建立？
   - Lie（核心谎言）是否在第三幕被主角认清并打破？
   - Flaw（缺陷）是否导致了第二幕的"一切皆失"？
3. **节拍对齐检验**：每场戏是否对齐 Save the Cat 节拍表，偏离超30秒警告
4. **伏笔兑现检验**：检查伏笔登记表，每个伏笔是否有对应回扣，遗漏驳回
5. **节奏张弛对比检验**：外部情节紧张时是否有情感喘息空间？情感重场戏后是否用轻节奏调节？
6. **潜台词密度**：直白台词出现5次以上则驳回
7. **三幕比例检验**：第一幕/第二幕/第三幕是否各占约25%/50%/25%，偏差超10%警告
8. **全剧情感弧线检验**：观众情绪是否沿着合理曲线推进，大结局是否有足够的情感释放
""",
        },
    }

    # 默认策略（兜底）
    default_strategy = {
        "showrunner_suffix": "",
        "writer_suffix": "",
        "doctor_suffix": "",
    }

    return strategies.get(format_name, default_strategy)


# =============================================================================
# OpenAI Client 创建（httpx 长超时方案）
# =============================================================================

_httpx_client_singleton = None

def _get_shared_http_client():
    global _httpx_client_singleton
    if _httpx_client_singleton is None:
        _httpx_client_singleton = httpx.Client(timeout=600.0, trust_env=False)
    return _httpx_client_singleton


def create_openai_client(base_url: str, api_key: str) -> Optional[OpenAI]:
    """创建 OpenAI Client 实例（统一使用httpx长超时，复用 httpx.Client 避免连接泄漏）"""
    try:
        return OpenAI(base_url=base_url, api_key=api_key, http_client=_get_shared_http_client())
    except Exception as e:
        st.error(f"创建 OpenAI Client 失败: {str(e)}")
        return None


# =============================================================================
# CrewAI LLM 创建（延迟导入）
# =============================================================================

def create_crewai_llm(provider: str, base_url: str, api_key: str, model_name: str):
    """创建 CrewAI LLM 实例。延迟导入 crewai，未安装时返回 None 并给出提示。"""
    try:
        from crewai import LLM
    except ImportError:
        st.error("❌ 分镜工作台需要 crewai 依赖。请运行: pip install crewai langchain-openai")
        return None

    if "Ollama" in provider:
        return LLM(model=f"ollama/{model_name}", base_url="http://localhost:11434")
    else:
        return LLM(model=model_name, api_key=api_key, base_url=base_url)


# =============================================================================
# Ollama 模型检测
# =============================================================================

def detect_ollama_models() -> Tuple[List[str], bool]:
    """检测本地 Ollama 已安装的模型列表"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            return (models, True) if models else ([], True)
        return [], False
    except Exception:
        return [], False


def ensure_ollama_model(model_name):
    """Ollama 自动拉取模型。如果本地不存在该模型，自动下载。"""
    try:
        tags_resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if tags_resp.status_code == 200:
            existing_models = [model["name"] for model in tags_resp.json().get("models", [])]
            if model_name in existing_models or f"{model_name}:latest" in existing_models:
                return True
    except requests.exceptions.RequestException:
        st.error("❌ 无法连接到本地 Ollama 服务，请确认后台 Ollama 软件已开启！")
        return False

    url = "http://localhost:11434/api/pull"
    payload = {"name": model_name}
    progress_text = st.empty()
    progress_bar = st.progress(0)
    try:
        with requests.post(url, json=payload, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    data = __import__('json').loads(line)
                    if "total" in data and "completed" in data:
                        percent = data["completed"] / data["total"]
                        progress_bar.progress(min(1.0, max(0.0, percent)))
                        progress_text.markdown(
                            f"**📥 首次使用，正在拉取模型 `{model_name}`... {int(percent*100)}%**"
                        )
        progress_text.success(f"✅ 模型 `{model_name}` 下载完毕！")
        return True
    except Exception:
        progress_text.error("❌ 模型拉取失败。")
        return False


# =============================================================================
# 辅助函数
# =============================================================================

def detect_script_format_by_volume(text: str) -> dict:
    """
    根据剧本文本体量自动识别剧集类型。

    检测策略：
    1. 先检测分集标记（"第X集"）统计集数
    2. 有分集标记：根据单集平均字数分类
    3. 无分集标记：根据总字数分类

    Returns:
        {
            "category": "emotion" | "structure",
            "display_name": "竖屏微短剧/短剧/中剧/长剧/电影长片",
            "episode_count": int,         # 检测到的集数（0=未检测到）
            "avg_chars_per_episode": float,
            "total_chars": int,
            "confidence": "高" | "中" | "低",
        }
    """
    import re

    total_chars = len(text)

    # 1. 检测分集标记
    episode_pattern = r'第\s*(\d+)\s*集'
    episode_matches = re.findall(episode_pattern, text)

    # 去重并获取最大集数
    if episode_matches:
        episode_nums = sorted(set(int(m) for m in episode_matches))
        episode_count = len(episode_nums)  # 实际集数（去重后），非最大集号
    else:
        episode_count = 0

    # 2. 计算单集平均字数
    if episode_count > 0:
        avg_chars = total_chars / episode_count
    else:
        avg_chars = total_chars

    # 3. 分类逻辑
    if episode_count > 0:
        # 有分集标记，按单集平均字数分类
        if avg_chars < 600:
            format_name = "竖屏微短剧"
            category = "emotion"
            confidence = "高"
        elif avg_chars < 3000:
            format_name = "短剧"
            category = "emotion"
            confidence = "高"
        elif avg_chars < 7000:
            format_name = "中剧"
            category = "structure"
            confidence = "高"
        elif avg_chars < 15000:
            format_name = "长剧"
            category = "structure"
            confidence = "高"
        else:
            format_name = "长剧"
            category = "structure"
            confidence = "中"
    else:
        # 无分集标记，按总字数分类
        if total_chars < 5000:
            format_name = "竖屏微短剧"
            category = "emotion"
            confidence = "中"
        elif total_chars < 12000:
            format_name = "短剧"
            category = "emotion"
            confidence = "中"
        elif total_chars < 45000:
            # 此区间可能是中剧或电影长片，按长度细分
            if total_chars >= 18000:
                format_name = "电影长片"
                category = "structure"
                confidence = "中"
            else:
                format_name = "中剧"
                category = "structure"
                confidence = "中"
        elif total_chars < 100000:
            format_name = "长剧"
            category = "structure"
            confidence = "中"
        else:
            format_name = "长剧"
            category = "structure"
            confidence = "低"

    # 特殊判断：如果只有1集且字数在20000-40000之间，可能是电影长片
    if episode_count == 1 and 20000 <= total_chars <= 45000:
        format_name = "电影长片"
        category = "structure"
        confidence = "中"

    return {
        "category": category,
        "display_name": format_name,
        "episode_count": episode_count,
        "avg_chars_per_episode": round(avg_chars, 0),
        "total_chars": total_chars,
        "confidence": confidence,
    }


def update_base_url_placeholder(provider: str) -> tuple:
    """根据选择的提供商更新 Base URL 占位符"""
    config = LLM_PROVIDERS.get(provider, LLM_PROVIDERS["DeepSeek"])
    return config["base_url"], config["placeholder"]


def get_default_model(provider: str) -> str:
    """获取默认模型"""
    return LLM_PROVIDERS.get(provider, {}).get("default_model", "gpt-4o")


def get_llm_kwargs(provider: str) -> dict:
    """获取LLM调用参数（Ollama需要特殊处理上下文长度）"""
    if "Ollama" in provider:
        return {"extra_body": {"options": {"num_ctx": 100000, "num_predict": 8192}}}
    else:
        return {"max_tokens": 8192}


# =============================================================================
# 服务商单次输出上限（唯一真源）
# =============================================================================
# 各家 API 对 max_tokens 都有硬上限，**超过会直接返回 400，而不是自动截断**。
# 历史 bug：分镜侧把 max_tokens 提到 16000、改编侧提到 16384~32768，
# 在 DeepSeek（上限 8192）上一律请求失败，表现为「跑了很久却没有任何输出」。
# 所有云端调用在传 max_tokens 前都应先过 clamp_max_tokens()。

PROVIDER_MAX_OUTPUT: Dict[str, int] = {
    "DeepSeek": 8192,
    "硅基流动 SiliconFlow": 8192,
    "阿里通义 Qwen": 8192,
    "Kimi (Moonshot)": 8192,
    "GLM (智谱)": 4095,
    "零一万物 Yi": 4096,
    "OpenAI": 16384,
    "Claude (Anthropic)": 8192,
    "Groq": 8192,
    "Gemini (Google)": 8192,
}

# provider slug / 模型名关键词 → 上限（展示名对不上时的兜底匹配）
_PROVIDER_CAP_ALIASES: Dict[str, int] = {
    "deepseek": 8192,
    "moonshot": 8192,
    "kimi": 8192,
    "siliconflow": 8192,
    "硅基流动": 8192,
    "qwen": 8192,
    "dashscope": 8192,
    "阿里通义": 8192,
    "zhipu": 4095,
    "bigmodel": 4095,
    "glm": 4095,
    "零一万物": 4096,
    "lingyi": 4096,
    "openai": 16384,
    "gpt-": 16384,
    "anthropic": 8192,
    "claude": 8192,
    "groq": 8192,
    "gemini": 8192,
}

DEFAULT_MAX_OUTPUT = 8192


def resolve_output_cap(provider: str = "", model_name: str = "", extra_hint: str = "") -> int:
    """返回该服务商单次输出 token 上限。返回 0 表示不钳制（本地模型自行决定）。"""
    for key in (provider or "", extra_hint or ""):
        if key in PROVIDER_MAX_OUTPUT:
            return PROVIDER_MAX_OUTPUT[key]

    hay = f"{provider} {model_name} {extra_hint}".lower()
    if "ollama" in hay or "本地" in hay or "localhost" in hay:
        return 0

    for alias, cap in _PROVIDER_CAP_ALIASES.items():
        if alias in hay:
            return cap
    return DEFAULT_MAX_OUTPUT


def clamp_max_tokens(max_tokens, provider: str = "", model_name: str = "", extra_hint: str = ""):
    """把 max_tokens 钳制到服务商允许的上限内。

    None / 0 原样返回（表示调用方不想设限）。
    本地模型（Ollama）不钳制。
    """
    if not max_tokens:
        return max_tokens
    cap = resolve_output_cap(provider, model_name, extra_hint)
    if cap and max_tokens > cap:
        return cap
    return max_tokens
