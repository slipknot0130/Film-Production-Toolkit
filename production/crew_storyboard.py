"""
crew_storyboard.py — CrewAI 纯后端模块（无 Gradio 依赖）

从 main.py 提取，供 storyboard_local.py 调用。

核心变更（相比 main.py）：
  1. 移除所有 gradio import 和 create_gradio_interface()
  2. 移除 if __name__ == "__main__" 启动块
  3. create_llm() 改为接收参数而非硬编码读 .env：
       create_llm(engine_choice, api_base, api_key, model_name)
  4. run_production_pipeline() 同步更新，使用新 create_llm() 签名
  5. 新增工具函数 run_crew_on_chunk()，供 storyboard_local.py 分块调用

LLM 路由规则（由 engine_choice 决定）：
  - "Ollama (本地)"  → model="ollama/<model_name>",  base_url=api_base
  - 其他（云端API）  → model="deepseek/deepseek-chat", api_key=api_key
"""

import os
import re
import csv
import io
import sys
import logging
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

# 加载同目录 .env（若 storyboard_local.py 还未加载则补充加载）
load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# LLM 工厂
# ─────────────────────────────────────────────────────────────────────────────

def create_llm(engine_choice: str, api_base: str, api_key: str, model_name: str) -> LLM:
    """
    创建并配置 LLM 实例（CrewAI 原生 LLM 类，适配 1.14.3+）。

    参数说明：
        engine_choice : 引擎选项字符串，来自 storyboard_local.py 侧边栏
                        实际值如 "🟢 本地轻量版 (Ollama) - ..." 等
        api_base      : API 地址，如 "http://localhost:11434" 或 "https://api.deepseek.com"
        api_key       : API 密钥（Ollama 不使用，传空字符串即可）
        model_name    : 模型名，如 "qwen3:8b"、"Qwen2.5-32B"、"deepseek-chat"

    返回：
        配置好的 LLM 实例
    """
    if "Ollama" in engine_choice:
        # Ollama：LiteLLM ollama 路由，base_url 固定指向本地 Ollama 服务
        llm = LLM(
            model=f"ollama/{model_name}",
            base_url="http://localhost:11434"
        )
    else:
        # 云端 API（DeepSeek、OpenAI、Moonshot 等）
        # 直接使用用户传入的 model_name，不强制加任何前缀
        llm = LLM(
            model=model_name,
            api_key=api_key,
            base_url=api_base
        )
    return llm


# ─────────────────────────────────────────────────────────────────────────────
# Agent 工厂
# ─────────────────────────────────────────────────────────────────────────────

def create_agents(llm: LLM) -> dict:
    """
    创建 4 个 Agent：
      director       — 剧本分镜导演（叙事节奏分析 + 物理逻辑校验 + 工业级分镜规范）
      image_prompt   — AI 美术指导（极简五要素 + 摄像机透视法则）
      video_prompt   — 视效总监（中文视频运镜提示词）
      qa_reviewer    — 质检总监（工业级分镜 JSON 输出 + 5维度连贯性）
    """
    # Agent 0: 剧本分镜导演（工业级规范）
    director_agent = Agent(
        role='剧本分镜导演',
        goal='将剧本拆解为工业级分镜头列表，包含焦段、光圈、机位（5要素）、构图、运镜、主体动作表情（含台词）、限制字段',
        backstory="""你是一位专业的剧本分镜导演，精通工业化 AI 视频分镜规范，擅长将文字剧本转化为可直接送入 AI 视频生成模型的分镜头。

【你的核心工作原则】

一、情境映射（每镜必须选定 ID）
你必须为每个分镜选定情境 ID，情境 ID 决定了该镜头的核心组合（焦段+光圈+机位+运镜），不允许自由发挥替换。
常用情境 ID：
  E01 主角觉醒（写实）：中焦50-85mm + 光圈f/4 + 低角度仰拍中景 + 缓慢轨道推
  E02 反派登场（漫改/古装）：广角24-35mm + 大光圈f/2.0 + 低角度仰拍静态 + 固定极轻微缓推
  E03 紧张追逐：长焦85-200mm + 大光圈 + 手持跟拍 + 手持快摇+快切
  E04 审讯对峙：正面居中解锁 + 长焦 + 静态
  E05 孤独沉思：长焦 + 大光圈 + 空旷noseroom
  E06 暴怒爆发：广角 + 大光圈 + 手持快摇
  E07 暧昧试探：长焦 + 大光圈 + 过肩静态
  E08 内向退缩：过肩 + 长焦 + 手持微动
  E09 突破内心：长焦 + 仰拍 + 缓推
  E10 仪式威严：对称居中解锁 + 长焦 + 静态
  E11 干脆决断：微距标点 + 静切动
  E12 释放释怀：中焦 + 俯拍 + 拉远 + 大景深
  E13 异化失控（库布里克式）：强对称居中解锁 + 广角 + 缓推
  E14 被困压抑：头顶贴边解锁 + 广角 + 静态
  E15 神性显现/顿悟：背景过亮解锁 + 逆光剪影 + 缓升
  E16 末日废土/战后静寂：广角24-35mm + 小光圈f/8+ + 低机位水平长焦 + 固定静态（建立镜头，环境叙事，展现废墟全貌与战场残骸）
  E17 荒诞动作/黑色幽默：标准50mm + 中等光圈f/4 + 侧面低机位 + 快速平移跟拍（捕捉物体飞行/撞击/弹跳的物理动态，保留荒诞节奏感）
  E18 环境扫视/巡逻确认：长焦135-200mm + 大光圈f/2.0 + 背后中景 + 缓慢横摇Pan（角色背对镜头眺望远方，展示纵深场景，不描写面部）
  E19 物体飞行/抛物线追踪：中焦85mm + 中等光圈f/4 + 侧面平视 + 固定+快摇Catch（跟踪物体抛物线轨迹，物入画→物出画，预留飞行弧线空间）
  E20 主观POV/沉浸确认：超广角14-16mm + 大光圈f/2.0 + 主观POV + 手持微晃（角色第一人称视角观察环境/确认目标，镜头代入感强）

二、80/15/5 权重机制
  核心组合（80%·锁死必用）：来自情境 ID，全部必须用上，不可替换删除
  辅助锚点（15%·选1-2）：增强情绪细节
  增强项（5%·仅情绪命中点用）：一段戏内最多1个镜头使用

三、6必填+1可选字段（严格按此输出每个分镜）
  1. 焦段：自然语言（超广角14-16mm / 广角24-35mm / 标准50mm / 中焦85mm / 长焦135-200mm / 微距）
  2. 光圈：自然语言（超大光圈f/1.2-f/1.8 / 大光圈f/2.0-f/2.8 / 中等光圈f/4-f/5.6 / 小光圈f/8+）
  3. 机位：必须包含5要素——摄影机位于[主体/对象]的[正面/背后/左前45°/右前45°/左侧/右侧/过肩谁拍谁/主观POV]，高度在[眼平/胸口/腰部/膝盖/地面/头顶]，以[平视/仰拍/俯拍/鸟瞰/倾斜]拍摄[主体部位/动作]，景别为[远景/全景/中景/近景/特写/超特写]。
  4. 构图：先写构图法则名（三分法/黄金分割/框架式/对角线/留白/对称等），再写空间分区内容说明——即画面各区域的具体内容分布。格式："构图法则，前景：X，左侧：X，右侧：X，背景：X"。示例："三分法，前景：泳池边缘丧尸头颅居中，左侧：泳池水面，右侧：走道与躺椅，背景：别墅"；微距/超特写必须写明"X占满画面"
  5. 运镜：中文歧义时加英文（滑轨Slider/轨道推Dolly In/斯坦尼康Steadicam/希区柯克变焦Dolly Zoom等需加英文；推/拉/摇/移/跟/升/降/手持呼吸感等无歧义则只写中文）
  6. 主体动作表情：台词必须嵌入此行，格式为"[角色]+[动作或语气描述]+：'[台词原文]'"，不另立项
  7. 限制（可选）：仅当AI视频模型可能出错时填写（如"不允许出现字幕""服装与上一镜完全一致""杯中水量保持半杯"等）

四、5维度视觉连贯性（段内相邻分镜必须遵守）
  A. 180°轴线规则：两人对话中摄影机不跨假想轴线（除非仪式性越轴）
  B. 视线匹配：A镜角色看向右侧→B镜角色必须从左入画且看左
  C. 动作衔接60%：A镜末尾动作=B镜开头动作的延续60-80%
  D. 道具/物件状态延续：同一场景中道具状态前后一致（必要时写入"限制"字段）
  E. 禁止连续3镜同景别：景别跳跃要有变化（同景别切同景别=跳切焦虑感，慎用）

五、抽象描述转译原则
  "内心崩溃" → 手指在桌下捏紧另一只手（桌下手部超特写）
  "他意识到..." → 禁止出现，必须用具体肢体动作替换
  "燃烧着怒火" → 双眉紧锁、牙关绷紧、攥紧拳头微微颤抖

六、文戏/武戏节奏规则
  文戏：静态或缓慢运镜为主，镜头稀疏（每段1-3个），重点近景/特写表情
  武戏：手持快摇+快切为主，密度是文戏的2-3倍，景别快速交替

你严格基于原文，不添加不存在的内容。输出分镜头时按"镜头号+6字段+可选限制"的格式输出。""",
        llm=llm,
        verbose=False,
        allow_delegation=False
    )

    # Agent 1: AI 美术指导（生图提示词）
    image_prompt_agent = Agent(
        role='AI 美术指导',
        goal='根据分镜内容和美术风格，编写极简的中英双语生图提示词',
        backstory="""你是一位精通 AI 图像生成的美术指导。
        你会根据分镜导演提供的分镜列表，以及用户直接输入的全局美术风格关键词，
        为每个镜头编写极简的生图提示词。
        你的提示词只包含五个要素：景别、人物名称、动作、场景名称、全局美术风格。
        人物外貌和场景细节已由外部工作流固定，你不需要在提示词中重复描述。
        你必须将 $StyleTokens（即用户输入的美术风格关键词）追加到每一个镜头的英文提示词末尾。
        由于部分生图软件只支持英文，你需要同时输出中文和英文两个版本。""",
        llm=llm,
        verbose=False,
        allow_delegation=False
    )

    # Agent 2: 视效总监（视频运镜提示词）
    video_prompt_agent = Agent(
        role='视效总监',
        goal='根据分镜和画面描述，编写中文的视频运镜提示词',
        backstory="""你是一位专业的视效总监，精通图生视频的提示词编写。
        你会基于分镜和生图提示词，为每个镜头编写视频运镜提示词。
        提示词需要包含：主体动作、摄像机运动（如"缓慢推进"、"向左平移"、"静态"）。
        你的输出使用中文，适用于 Kling、即梦等中文友好的视频生成工具。""",
        llm=llm,
        verbose=False,
        allow_delegation=False
    )

    # Agent 3: 质检总监（输出 JSON 格式）
    qa_reviewer_agent = Agent(
        role='质检总监',
        goal='审查所有 Agent 输出的提示词格式和节奏匹配度，输出标准 JSON 格式的最终数据',
        backstory="""你是一位极其严苛的剧组制片主任，专门负责审查下游 Agent 输出的提示词质量和节奏匹配度。
        你的眼睛里容不得一粒沙子：任何格式不规范、冗长啰嗦、含有多余符号的提示词，以及节奏与剧本激烈程度不匹配的分镜，都会被你打回重写。
        你的审查范围覆盖全部镜头的生图提示词、视频运镜提示词，以及分镜密度与剧本节奏的匹配度。
        当你发现问题时，你会直接指出错误，并依靠底层推理能力重新整理出一份完美的数据。
        你的最终输出是一份标准 JSON 数组，可以被 Python json.loads() 直接解析。""",
        llm=llm,
        verbose=False,
        allow_delegation=False
    )

    return {
        'director': director_agent,
        'image_prompt': image_prompt_agent,
        'video_prompt': video_prompt_agent,
        'qa_reviewer': qa_reviewer_agent
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 工厂
# ─────────────────────────────────────────────────────────────────────────────

def create_tasks(agents: dict) -> dict:
    """
    创建 4 个 Task，串行依赖：
      task_director → task_image → task_video → task_qa_review
    """
    # ── Task 0: 剧本分镜拆解（工业级规范：情境映射 + 6字段 + 5维度连贯性）──
    task_director = Task(
        description="""请仔细阅读以下剧本，按工业级分镜规范拆解为分镜头列表：

{script}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第一步：叙事节奏分析（必须先完成）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

将剧本划分为「节奏段落」，标注类型：
  [文戏]：对话、内心独白、情感交流为主
  [武戏]：激烈动作、打斗、冲突为主
  [过渡]：文戏向武戏的转折

输出格式（放在分镜列表最前面）：
--- 叙事节奏分析 ---
[文戏] 段落1（约X字）：[本段内容] → 预计分镜数：Y
[武戏] 段落2（约X字）：[本段内容] → 预计分镜数：Y（≈段落1的2-3倍）
--- 分析结束 ---

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第二步：工业级分镜拆解（核心规范，严格执行）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

每个分镜头必须包含以下 6个必填字段 + 1个可选字段：

【必填1】焦段：描述焦距语义（超广角14-16mm / 广角24-35mm / 标准50mm / 中焦85mm / 长焦135-200mm / 微距）
【必填2】光圈：描述景深效果（超大光圈f/1.2-f/1.8 / 大光圈f/2.0-f/2.8 / 中等光圈f/4-f/5.6 / 小光圈f/8+）
【必填3】机位：必须按"5要素模板"写清楚——
    格式：摄影机位于 [主体/对象] 的 [正面/背后/左前45°/右前45°/左侧/右侧/过肩谁拍谁/主观POV]，
          高度在 [眼平/胸口/腰部/膝盖/地面/头顶]，
          以 [平视/仰拍/俯拍/鸟瞰/倾斜] 拍摄 [主体部位/动作]，
          景别为 [远景/全景/中景/近景/特写/超特写]。
    注意：过肩镜头必须写"过谁的肩拍谁"；多人镜头必须写清主体与次主体身份
    ⚠️【透视屏蔽法则】：如果机位设定为"背后"、"过肩"或"侧后方"，主体动作表情中【绝对禁止】描写五官、眼神、面部表情或眼泪等正面特征。必须用背影、肩膀起伏、手部动作等替代。
【必填4】构图：先写构图法则名（三分法/黄金分割/框架式/对角线/留白/对称等），再写空间分区内容——即画面各区域的具体内容分布。格式："构图法则，前景：X，左侧：X，右侧：X，背景：X"。示例："三分法，前景：泳池边缘丧尸头颅居中，左侧：泳池水面，右侧：走道与躺椅，背景：别墅"。微距/超特写写明"X占满画面"
【必填5】运镜：中文歧义时加英文（滑轨Slider/轨道推Dolly In/轨道拉Dolly Out/斯坦尼康Steadicam/变焦推Zoom In/希区柯克变焦Dolly Zoom/360度环绕360° Orbit/快切Cut In等需加英文；推/拉/摇/移/跟/升/降/手持摄像机呼吸感等无歧义只写中文）
【必填6】主体动作表情：台词必须嵌入此行，不另立项。格式：[角色]+[动作或语气描述]+"[台词原文]"；无对白镜头则只写动作，不留"台词：无"等占位。
    ⚠️【透视屏蔽法则】：当机位为"背后/过肩/侧后方"时，此字段【绝对禁止】出现五官、眼神、面部表情、眼泪等正面特征，必须用背影姿态、肩膀起伏、手部动作、握拳等替代。
【可选7】限制：仅当AI视频模型可能出错时填写（如"不允许出现字幕""服装与上一镜完全一致""杯中水量保持半杯"）；AI默认能做对的不写

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【5维度视觉连贯性（相邻分镜间必须遵守）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A. 180°轴线规则：两人对话中，摄影机不越过假想轴线（允许仪式性越轴）
B. 视线匹配：A镜角色视线→右侧，B镜角色必须从左入画且视线朝左
C. 动作衔接60%：A镜末尾动作=B镜开头动作的延续60-80%，不允许动作突跳
D. 道具/物件状态延续：同一场景中水杯量/烟头长度/服装等前后一致（需要时写入"限制"字段）
E. 禁止连续3镜同景别：景别要有跳跃变化（同景别连切=跳切焦虑感，慎用）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【抽象描述转译（摄影机拍不到的必须转译）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✗ "他内心崩溃了" → ✓ "手指在桌下捏紧另一只手，呼吸短促但表情维持平静"
✗ "他的眼神中燃烧着怒火" → ✓ "双眉紧锁，牙关绷紧，攥紧的拳头微微颤抖"
✗ "她鼓起勇气" → ✓ "吸管搅拌奶茶的动作慢一拍，抬头时机比对方晚0.5秒"
识别剧本中的文学夸张/抽象情绪词 → 一律替换为具体可见的肢体语言/物理动作

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【台词融合规范（强制执行）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

台词不另立项！必须嵌入"主体动作表情"行。
✅ 正确：主体动作表情：华雄挺矛冷笑，高声喝道："何人敢来送死？"
✅ 正确：主体动作表情：关羽微微颔首，举起酒杯，低沉地说："温酒一杯，末将片刻便回。"
❌ 错误：主体动作表情：关羽举杯。台词：关羽："温酒一杯，末将片刻便回。"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【文戏/武戏密度规则】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

文戏：静态或缓慢运镜为主，镜头稀疏（每段1-3个），近景/特写为主体现情绪
武戏：手持快摇+快切为主，密度是文戏的2-3倍，景别快速交替：特写→全景→侧拍
文戏对话场景：每隔2-3句台词必须插入"反应镜头"（标注【反应镜头】），聚焦听者的表情变化

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出格式（每个镜头按此格式，先节奏分析再分镜列表）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

镜头 1
焦段：[焦距语义]
光圈：[景深效果]
机位：[5要素完整描述]
构图：[构图方式]
运镜：[中文/中英混合]
主体动作表情：[动作描述，台词嵌入此行]
（限制：[可选，仅AI易错点]）

镜头 2
...""",
        expected_output="""一份工业级分镜头列表，包含「叙事节奏分析」和所有分镜头。
每个分镜头包含6个必填字段：焦段/光圈/机位（5要素模板）/构图/运镜/主体动作表情（台词嵌入）；必要时有限制字段。
台词全部嵌入主体动作表情行，不另立项。
机位字段包含完整的摄影机位置/高度/角度/景别描述。
相邻分镜满足5维度视觉连贯性；文戏稀疏/武戏密集，密度差达2~3倍。
所有抽象文学描述已转译为具体可拍摄的肢体动作/物理动作。""",
        agent=agents['director']
    )

    # ── Task 2: 生图提示词编写（极简五要素 + 摄像机透视与道具法则）──
    task_image = Task(
        description="""根据分镜列表和全局美术风格，为每个镜头编写极简生图提示词。

分镜列表（来自导演）：{script}
全局美术风格关键词（用户直接输入）：{style}
$StyleTokens = {style}（直接使用用户输入的美术风格关键词，追加到英文提示词末尾）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第一法则：摄像机透视与道具物理法则 — 最高优先级】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ 这是本次修改的核心规则！违反此规则的提示词将导致严重穿帮。

【规则一：绝对禁止物品正面朝向镜头】

当你看到剧本中角色「阅读信件」「注视手中物品」「查看文书」时，
你必须理解一个物理事实：真实摄影中，物品不可能同时面向演员的手又面向镜头。

错误的做法：直接写 "reading a letter"、"staring at conscription notice"
→ 这会让 AI 以为要展示物品正面文字，导致纸张/竹简违背透视地翻转朝向镜头

正确的做法（按摄像机角度二选一）：
  A. 拍正脸（正面特写）时：
     → 写 "looking down at hand, back of the paper facing camera, no text visible"
     → 翻译为中文：眼神向下看手中物品，纸张背面朝向镜头，无文字可见
  B. 拍过肩/主观镜头时：
     → 必须使用摄像机术语 "over-the-shoulder shot" 或 "POV shot"
     → 写 "over-the-shoulder shot, looking at a piece of rough paper in hand"
     → 翻译为中文：过肩镜头，看向手中一张粗糙的纸

【规则二：道具降维翻译 — 删除一切剧情属性词】

你的任务是构图，不是解释剧情。禁止在道具上「写字」来证明场景。

剧本中的剧情道具 → 必须降维翻译为纯物理属性词：

  · "征兵令" → "a piece of rough paper"（一张粗糙的纸）
  · "密信" → "a folded letter in hand"（手中一封折叠的信）
  · "令牌" → "a bronze token"（一枚青铜令牌）
  · "画卷" → "a scroll"（一幅卷轴）
  · "令牌" → "a jade seal"（一枚玉印）
  · "地图" → "a worn map spread on table"（桌上摊开的一张破旧地图）

禁止：直接使用 "conscription notice"、"secret letter"、"imperial decree"
允许：仅描述物品的物理材质/形状，不描述内容/意义/文字

【规则三：禁止物体做出违背物理的动作】

剧本说「张飞看着征兵令」→ 真实拍摄时，他低头看手中物品，物品背面朝镜头
剧本说「将军举起令牌」→ 令牌边缘朝向镜头，不是印章面
剧本说「书生展开画卷」→ 只能拍到画卷局部/侧面/展开中的手部特写

你的翻译原则：
  · 物品的「用途」和「内容」≠ 物品的「外观」
  · 永远只描述物品能被镜头拍到的那个面
  · 永远不让文字、印章、图案正面朝向镜头（除非是专门拍物品的特写）

【规则四：人物正反面透视冲突消除】

当你遇到机位在角色背后的镜头时（机位包含"背后"、"过肩"、"侧后方"等关键词），
如果上游传来的动作描述中包含了面部表情（如：皱眉、流泪、怒目、微笑、眼神变化等），
你必须在翻译成生图提示词时将其【强制剔除】。

背面镜头只允许描写背影姿态和服装，绝不允许出现面部特征。

  ✗ 错误（机位=背后）：over-the-shoulder shot, character, frowning, tears rolling down cheeks
  ✓ 正确（机位=背后）：over-the-shoulder shot, character, shoulders trembling slightly, back facing camera
  ✗ 错误（机位=背后）：from behind, character, glaring with anger
  ✓ 正确（机位=背后）：from behind, character, fists clenched at sides, back stiff with tension

翻译原则：
  · 面部表情 → 替换为肩背姿态（肩膀紧绷/松垮/颤抖/耸起）
  · 眼神描写 → 替换为手部动作（攥拳/松手/抓紧衣角）
  · 五官描写 → 替换为头部朝向（低头/抬头/侧头转向）+ 发丝/衣领细节

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第二法则：极简五要素】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

在遵守透视法则的前提下，你的提示词必须极度精简，只包含以下五个要素：

  1. 景别（shot type）：如 close-up / wide shot / over-the-shoulder shot
  2. 人物名称 / 核心触发词（character / core trigger word）
  3. 人物的具体动作（action）
  4. 场景名称（scene）
  5. 全局美术风格 {style}

禁止在提示词中详细描写人物的外貌特征（如"络腮胡"、"马尾辫"、"蓝外套"）
禁止在提示词中描写场景的具体建筑细节（如"木制案板"、"瓷器架"、"暖光"）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【摄像机类型速查表】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

当你需要拍「看物品」「读物品」「手中拿物品」的镜头时，强制使用以下术语：

  · 正面特写（物品不可见）：close-up, [人物], eyes looking down at hand, [物品物理描述], back facing camera, no text visible
  · 过肩镜头（物品可见）：over-the-shoulder shot, [人物], looking at [物品] in hand
  · 主观镜头 POV（沉浸感）：POV shot, looking down at [物品] in hand, hands visible
  · 手部特写（物品不可见）：extreme close-up, hands holding [物品物理描述], slightly out of focus background
  · 反打镜头（从物品方向拍人）：reverse angle shot, [人物] wiping sweat from brow, looking away

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出格式】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

必须输出纯粹的、由逗号分隔的自然语言关键词序列。
禁止任何中括号 []、加号 +、格式排版符号。
英文提示词以 $StyleTokens 结尾。

【正确输出范例】（这是唯一正确的标准）：

镜头 1 生图提示词：
中文：近景，张飞，怒目圆睁，大喝一声，长坂坡桥头，写实光影，8k
英文：close-up, Zhang Fei, glaring with fury, shouting loudly, at Changban Bridge, realistic lighting, 8k, $StyleTokens

镜头 2 生图提示词：
中文：正面特写，张飞，擦汗低头看向手中粗糙纸张背面，长坂坡桥头，写实光影，8k
英文：close-up, Zhang Fei, wiping sweat, lowering head, looking down at hand, back of rough paper facing camera, no text visible, at Changban Bridge, realistic lighting, 8k, $StyleTokens

【硬性要求】
1. 每个镜头必须同时输出中文和英文两个版本
2. 英文提示词必须以 $StyleTokens 结尾
3. 禁止出现任何人物外貌描述词汇（如胡子颜色、服装颜色、体型等）
4. 禁止出现任何场景建筑细节词汇（如案板、瓷器、暖光等）
5. 只写：景别 + 人物名 + 动作 + 场景名 + 全局风格
6. 涉及「阅读/注视手中物品」的镜头，必须遵守摄像机透视法则（物品背面/边缘朝镜头）
7. 禁止在提示词中使用剧情属性词（征兵令、密信、令牌、诏书等），一律降维翻译为物理属性词""",
        expected_output="""一份完整的生图提示词列表，严格对应分镜头列表中的每一个镜头。
每个镜头包含中文和英文两个版本的提示词。
提示词严格遵循极简五要素结构，无人物外貌描写，无场景建筑细节。
英文提示词以 $StyleTokens 结尾。
额外校验：涉及「阅读/注视手中物品」的镜头，物品必须背面/边缘朝镜头（禁止正面穿帮）。
额外校验：禁止出现剧情属性词（征兵令、密信、令牌、诏书等），必须降维翻译为物理属性词。""",
        agent=agents['image_prompt'],
        context=[task_director]
    )

    # ── Task 3: 视频运镜提示词编写（中文）──
    task_video = Task(
        description="""根据前几步的所有输出，为每个镜头编写视频运镜提示词。

你是最后一步（质检前），你能看到：
1. 分镜头列表（来自导演，含节奏分析）
2. 生图提示词列表（来自美术指导）

你的任务是：
1. 为每个分镜头编写视频运镜提示词（中文）
2. 运镜提示词必须体现节奏感：
   · 文戏镜头：摄像机运动以「静态、缓慢推进、缓慢拉远」为主，时长偏长（4-6秒）
   · 武戏镜头：摄像机运动以「快速推进、快速拉远、手持晃动、跳剪」为主，时长偏短（2-3秒）
3. 【重要】被摄主体运动轨迹描述：当剧本中涉及物体飞行、人物跑动、抛物线、弹跳、被叼走等物理动态时，必须在该镜头提示词中明确写出主体的运动轨迹和动态过程。示例："丧尸头颅被踢飞，呈抛物线向画面左侧远远飞出，飞至远处被一只海鸟在空中接力叼走"。这直接影响AI视频模型的物理模拟质量。
4. 输出每个镜头的运镜提示词，格式简洁清晰

输出格式（每个镜头一段）：

镜头 1 视频运镜提示词：
[主体动作描述]，[主体运动轨迹（如有物理动态）]，[摄像机运动]，[时长建议]

镜头 2 视频运镜提示词：
..

【硬性要求】
- 使用中文
- 文戏与武戏的运镜风格必须有明显差异，体现节奏感
- 适用于 Kling、即梦等中文友好的视频生成工具
- 不要添加多余的解释文字""",
        expected_output="""一份完整的视频运镜提示词列表，严格对应分镜头列表中的每一个镜头。
每个镜头包含：主体动作描述、主体运动轨迹（涉及物理动态时）、摄像机运动、时长建议。
文戏镜头运动稳定缓慢，武戏镜头运动快速动态，节奏感明显。
涉及物体飞行/抛物线/弹跳/被接走等物理动态的镜头，必须明确描述运动轨迹。
使用中文，格式简洁。""",
        agent=agents['video_prompt'],
        context=[task_director, task_image]
    )

    # ── Task 4: 质检审查与纠错（输出工业级 JSON 数组·8列）──
    task_qa_review = Task(
        description="""你是质检总监，一位极其严苛的剧组制片主任。
你刚刚收到了整个工作流的全部输出，现在必须进行最终审查，并输出标准 JSON 数组数据。

你可以看到以下全部上游输出：
1. 工业级分镜头列表（来自导演，含6字段+可选限制字段）
2. 生图提示词（来自美术指导，包含中文版和英文版）
3. 视频运镜提示词（来自视效总监）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【审查标准一：6字段完整性】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

逐一核查每个分镜头的6个必填字段：

✓ 焦段：是否使用了自然语言描述（超广角/广角/标准/中焦/长焦/微距）
✓ 光圈：是否描述了景深效果（超大光圈/大光圈/中等光圈/小光圈）
✓ 机位：是否包含5要素——[摄影机位置] + [高度] + [拍摄角度] + [主体动作] + [景别]
  ✗ 错误：只写"仰拍近景"——缺少摄影机位置和高度描述
  ✓ 正确：摄影机位于关羽正前方偏右15°，高度在腰部以下，向上仰拍关羽挺矛出阵，近景。
✓ 构图：是否有明确构图方式（三分法/黄金分割/框架式等）
✓ 运镜：中文歧义运镜是否已加英文注释
✓ 主体动作表情：台词是否嵌入此行（不允许台词另立项）
✓ 机位透视冲突核查：如果机位描述包含"背面"、"背后"、"过肩"或"侧后方"，检查其动作描述和生图提示词中是否违背物理常识地出现了"表情、眼神、面容、五官、流泪、皱眉"等正面特征。如果出现，立刻要求打回修改——背面镜头只能描写背影姿态和手部动作，禁止出现面部特征。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【审查标准二：台词融合合规性】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ 台词必须嵌入"主体动作表情"行，格式为 [角色]+[动作/语气]+"[台词]"
✗ 错误：有独立的"台词：..." 字段
✗ 错误：有独立的"对白：..." 字段
→ 发现此类问题必须将台词合并到主体动作表情中

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【审查标准三：5维度视觉连贯性】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

从第2个分镜开始，逐镜检查与前一镜的连贯性：

维度A 180°轴线：对话场景摄影机是否越轴（除非有合法越轴意图）
维度B 视线匹配：A镜角色视线方向→B镜角色是否从对应方向入画并回看
维度C 动作衔接：A镜末尾动作与B镜开头动作是否有60%重合
维度D 道具状态：道具（杯中水量/烟头长度/服装等）是否前后一致
维度E 景别跳跃：是否出现连续3个以上同景别的情况

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【审查标准四：生图提示词极简五要素】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ 正确格式（英文）：shot type, character name, action, scene name, style, $StyleTokens
✗ 错误：包含外貌描写词汇（"with blue jacket and ponytail"等）
✗ 错误：包含建筑细节词汇
✗ 错误：含有任何中括号、加号、中文字符

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【审查标准五：节奏密度匹配度】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ 武戏段落镜头密度应是文戏的2-3倍
✗ 错误：激烈打斗场景只有1-2个镜头（节奏过慢）
✗ 错误：平淡对话拆出8-10个细碎镜头（节奏过碎）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【最终输出格式：JSON 数组（8列字段，必须严格遵守）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

你的最终输出必须是一个严格的 JSON 数组。

JSON 字段说明（10列）：
- "镜头号"：连续编号，字符串
- "焦段"：如"中焦85mm"、"长焦135-200mm"
- "光圈"：如"大光圈f/2.0-f/2.8"
- "机位"：包含5要素的完整描述
- "构图"：构图法则 + 空间分区内容说明（如"三分法，前景：丧尸头颅居中，左侧：泳池，右侧：走道，背景：别墅"）
- "运镜"：如"固定静态"、"缓慢轨道推（Slow Dolly In）"
- "主体动作表情"：动作描述，台词已嵌入（含 [反应镜头] 标注）
- "时长"：该镜头的预估时长（如"2s"、"5s"），从视频运镜提示词的时长建议中提取
- "限制"：可选，AI易错点约束；无需要则填"—"
- "视觉连贯性建议"：第1个镜头填"—"，第2个及之后必须填写（如"沿用前景参考图/Seed"、"使用前镜生成图作为底层垫图（Image-to-Image）"、"新场景，需重新调整环境词权重"、"无连贯性要求"等）

JSON 数组格式示例：
[
  {
    "镜头号": "1",
    "焦段": "广角24-35mm",
    "光圈": "大光圈f/2.0",
    "机位": "摄影机位于华雄正前方，高度在腰部以下，向上仰拍华雄挺矛立马，全景。",
    "构图": "低角度仰拍，华雄居画面中央偏左，天空占据上方三分之一",
    "运镜": "固定静态",
    "主体动作表情": "华雄手持长矛挺立马背，俯视对阵诸侯，冷声喝道：'谁敢出战！'",
    "时长": "3s",
    "限制": "—",
    "视觉连贯性建议": "—"
  },
  {
    "镜头号": "2",
    "焦段": "中焦85mm",
    "光圈": "中等光圈f/4",
    "机位": "摄影机位于关羽右侧方，高度眼平，平视拍关羽端起酒杯，近景。",
    "构图": "三分法，关羽居右侧三分线，左侧留出视线空间",
    "运镜": "缓慢推",
    "主体动作表情": "关羽微微颔首，双手捧起酒杯，沉声道：'温酒一杯，末将片刻便回。'",
    "时长": "5s",
    "限制": "不允许出现字幕或文字",
    "视觉连贯性建议": "新场景，需重新调整环境词权重"
  }
]

注意：
- 字段顺序：镜头号, 焦段, 光圈, 机位, 构图, 运镜, 主体动作表情, 时长, 限制, 视觉连贯性建议
- "限制"字段：有需要则写约束内容，无需要则填"—"
- "视觉连贯性建议"：第1个镜头填"—"，第2个及之后每个镜头必须填写
- 不要输出任何 Markdown 标记（如 ```json ```），只输出纯 JSON 数组文本""",
        expected_output="""一份标准 JSON 数组文本，每个元素是一个镜头对象（共10个字段）。
JSON 对象字段：镜头号, 焦段, 光圈, 机位, 构图, 运镜, 主体动作表情, 时长, 限制, 视觉连贯性建议
机位字段包含完整5要素描述（不接受只有景别名称的简写）。
构图字段包含构图法则 + 空间分区内容说明。
台词已嵌入主体动作表情字段（无独立台词字段）。
时长字段为该镜头预估时长（如"2s"、"5s"），从视频运镜提示词的时长建议中提取。
限制字段：有AI易错点约束时填写，无则填"—"。
视觉连贯性建议：第1镜填"—"，第2镜起每镜必填一条建议。
无任何 Markdown 标记或解释文字，纯 JSON 数组。""",
        agent=agents['qa_reviewer'],
        context=[task_director, task_image, task_video]
    )

    return {
        'task_director': task_director,
        'task_image': task_image,
        'task_video': task_video,
        'task_qa_review': task_qa_review
    }


# ─────────────────────────────────────────────────────────────────────────────
# Crew 工厂
# ─────────────────────────────────────────────────────────────────────────────

def create_crew(agents: dict, tasks: dict) -> Crew:
    """
    创建 Crew 对象，串行执行（4 步：分镜 → 生图提示词 → 视频运镜 → 质检）
    verbose=True 开启详细日志
    """
    crew = Crew(
        agents=[
            agents['director'],
            agents['image_prompt'],
            agents['video_prompt'],
            agents['qa_reviewer']
        ],
        tasks=[
            tasks['task_director'],
            tasks['task_image'],
            tasks['task_video'],
            tasks['task_qa_review']
        ],
        process=Process.sequential,
        verbose=True
    )
    return crew


# ─────────────────────────────────────────────────────────────────────────────
# JSON 解析工具
# ─────────────────────────────────────────────────────────────────────────────

def parse_json_from_qa_output(raw_text: str):
    """
    从质检总监的输出中解析 JSON 数组数据。
    Agent 可能输出 JSON 数组周围有解释文字，需要精准提取。
    返回：(header_list, rows_list) 或 (None, None) 如果解析失败。

    为什么用 JSON 中转而不是直接 CSV：
    - 生图提示词(英) 内部含有英文逗号（如 "close-up, Zhang Fei, ..."）
    - 如果让 Agent 直接拼接 CSV 文本，内部逗号会被 csv.reader 误判为列分隔符
    - 用 JSON 字符串传递，json.loads() 自动安全解析所有字符（含逗号、引号、换行）
    - 最终用 Python 原生 csv.writer 写入 CSV，自动将含逗号字段用双引号包裹
    """
    import json as _json

    # 策略1：提取 JSON 数组部分（[ ... ]）
    json_start = raw_text.find('[')
    json_end = raw_text.rfind(']')

    if json_start != -1 and json_end != -1 and json_end > json_start:
        json_text = raw_text[json_start:json_end + 1]
        try:
            shots = _json.loads(json_text)
            if isinstance(shots, list) and len(shots) > 0:
                field_names = [
                    "镜头号", "焦段", "光圈", "机位",
                    "构图", "运镜", "主体动作表情", "时长", "限制", "视觉连贯性建议"
                ]
                header = field_names
                rows = []
                for shot in shots:
                    row = [shot.get(field, "") for field in field_names]
                    rows.append(row)
                return header, rows
        except Exception as e:
            print(f"⚠️ JSON 解析失败: {e}")

    # 策略2：解析整个 JSON 对象（单个对象或数组）
    import json as _json
    try:
        data = _json.loads(raw_text.strip())
        if isinstance(data, list) and len(data) > 0:
            shots = data
        elif isinstance(data, dict):
            shots = [data]
        else:
            return None, None

        field_names = [
            "镜头号", "焦段", "光圈", "机位",
            "构图", "运镜", "主体动作表情", "时长", "限制", "视觉连贯性建议"
        ]
        header = field_names
        rows = []
        for shot in shots:
            row = [shot.get(field, "") for field in field_names]
            rows.append(row)
        return header, rows
    except Exception as e:
        print(f"⚠️ JSON 整体解析失败: {e}")

    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# 核心适配器：供 storyboard_local.py 分块调用
# ─────────────────────────────────────────────────────────────────────────────

def run_crew_on_chunk(
    chunk: str,
    global_chars: str,
    style_tokens: str,
    engine_choice: str,
    api_base: str,
    api_key: str,
    model_name: str
) -> list:
    """
    对单个剧本切块运行 CrewAI 4-Agent 工作流，返回 shot_list。

    参数：
        chunk         : 当前剧本切块文本（来自 split_script_smart 分块结果）
        global_chars  : 全局角色信息字符串（透传给 task_director 的 script 变量）
        style_tokens  : 美术风格关键词（来自 StyleTokens.txt 或用户输入）
        engine_choice : 引擎选项字符串（来自 Streamlit 侧边栏）
        api_base      : API 地址
        api_key       : API 密钥
        model_name    : 模型名

    返回：
        list of dict — 每个元素是一个镜头的字段字典，字段为：
            镜头号, 焦段, 光圈, 机位, 构图, 运镜, 主体动作表情, 时长, 限制, 视觉连贯性建议
        解析失败时返回空列表 []

    注意：
        - 每次调用都会重新创建 LLM/Agents/Tasks/Crew 实例（CrewAI 要求）
        - global_chars 会被拼接到 chunk 前面，作为 script 变量传入 task_director
    """
    # 拼接角色信息 + 剧本切块，作为完整 script 输入
    script_input = f"{global_chars}\n\n{chunk}" if global_chars.strip() else chunk

    effective_style = style_tokens.strip() if style_tokens.strip() else "（无，请根据剧本内容自动推断全系列美术风格）"

    # 创建 LLM → Agents → Tasks → Crew
    llm = create_llm(engine_choice, api_base, api_key, model_name)
    agents = create_agents(llm)
    tasks = create_tasks(agents)
    crew = create_crew(agents, tasks)

    # 执行工作流
    result = crew.kickoff(inputs={
        'script': script_input,
        'style': effective_style
    })

    # 提取质检 Agent 的输出（最后一个 Task）
    qa_result_raw = ""
    if hasattr(result, 'tasks_output') and len(result.tasks_output) >= 4:
        qa_result_raw = result.tasks_output[-1].raw
    elif hasattr(result, 'raw'):
        qa_result_raw = result.raw
    else:
        qa_result_raw = str(result)

    if not qa_result_raw:
        return []

    # 解析 JSON → 返回 shot_list（list of dict）
    header, rows = parse_json_from_qa_output(qa_result_raw)
    if not header or not rows:
        return []

    # 将 rows（list of list）转为 list of dict
    shot_list = []
    for row in rows:
        shot_dict = {header[i]: row[i] for i in range(len(header))}
        shot_list.append(shot_dict)

    return shot_list


# ─────────────────────────────────────────────────────────────────────────────
# 完整流程入口（保留，供独立测试使用）
# ─────────────────────────────────────────────────────────────────────────────

def run_production_pipeline(
    style_context: str,
    script_content: str,
    engine_choice: str = "云端API",
    api_base: str = "https://api.deepseek.com",
    api_key: str = "",
    model_name: str = "deepseek-v4-pro",
    output_file: str = '分镜与提示词.csv'
):
    """
    完整流程入口（不依赖 Gradio，供独立测试或命令行调用）。

    参数:
        style_context  : 全局美术风格关键词
        script_content : 剧本内容
        engine_choice  : 引擎选项（默认云端API）
        api_base       : API 地址
        api_key        : API 密钥（优先使用传参，若为空则从 .env 读取）
        model_name     : 模型名
        output_file    : CSV 输出文件名

    返回:
        tuple: (display_data list[list], csv_path_or_None, captured_log_str)
    """
    try:
        if not script_content or not script_content.strip():
            return [], "❌ 错误：请输入剧本内容！", None

        # 若 api_key 未传入，尝试从环境变量读取
        resolved_api_key = api_key.strip() if api_key.strip() else os.environ.get("DEEPSEEK_API_KEY", "")

        effective_style = style_context.strip() if style_context.strip() else "（无，请根据剧本内容自动推断全系列美术风格）"

        # 创建日志捕获器
        log_capture = io.StringIO()

        print(f"\n{'='*60}")
        print("开始执行 AI 漫剧多智能体生产流水线")
        print(f"引擎: {engine_choice} | 模型: {model_name}")
        print(f"输入剧本长度: {len(script_content)} 字符")
        print(f"全局美术风格: {style_context if style_context.strip() else '（无，由 AI 自动推断）'}")
        print(f"{'='*60}\n")

        llm = create_llm(engine_choice, api_base, resolved_api_key, model_name)
        print("✓ LLM 初始化成功")

        agents = create_agents(llm)
        print(f"✓ 已创建 {len(agents)} 个 Agent")

        tasks_obj = create_tasks(agents)
        print(f"✓ 已创建 {len(tasks_obj)} 个 Task")

        crew = create_crew(agents, tasks_obj)
        print(f"\n正在执行工作流（4 步：分镜 → 生图提示词 → 视频运镜 → 质检）...\n")

        # 日志捕获
        class LogCaptureHandler(logging.Handler):
            def __init__(self, capture):
                super().__init__()
                self.capture = capture

            def emit(self, record):
                try:
                    msg = self.format(record)
                    self.capture.write(msg + '\n')
                except Exception:
                    self.handleError(record)

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.handlers.clear()

        capture_handler = LogCaptureHandler(log_capture)
        capture_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(message)s')
        capture_handler.setFormatter(formatter)
        root_logger.addHandler(capture_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        try:
            result = crew.kickoff(inputs={
                'script': script_content,
                'style': effective_style
            })
        finally:
            root_logger.removeHandler(capture_handler)
            root_logger.removeHandler(console_handler)
            capture_handler.close()
            console_handler.close()

        captured_log = log_capture.getvalue()
        log_capture.close()

        qa_result_raw = ""
        if hasattr(result, 'tasks_output') and len(result.tasks_output) >= 4:
            qa_result_raw = result.tasks_output[-1].raw
            print(f"✓ 各任务输出已获取：共 {len(result.tasks_output)} 个任务")
        elif hasattr(result, 'raw'):
            qa_result_raw = result.raw
            print("⚠️ 警告：无法获取分任务输出，将只返回最终结果")
        else:
            qa_result_raw = str(result)

        csv_path = output_file
        display_data = []

        if qa_result_raw:
            header, rows = parse_json_from_qa_output(qa_result_raw)

            if header and rows:
                with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(header)
                    writer.writerows(rows)
                print(f"\n✓ 分镜与提示词已保存为 CSV: {csv_path}")
                print(f"✓ 共 {len(rows)} 个镜头")
                display_data = [header] + rows
            else:
                fallback_path = '分镜与提示词_原始输出.txt'
                with open(fallback_path, 'w', encoding='utf-8') as f:
                    f.write(qa_result_raw)
                print(f"\n⚠️ JSON 解析失败，原始输出已保存: {fallback_path}")
                display_data = []
        else:
            print("\n❌ 警告：未生成有效结果")
            display_data = []

        return display_data, csv_path if os.path.exists(csv_path) else None, captured_log

    except Exception as e:
        error_msg = f"❌ 执行过程中发生错误:\n\n错误类型: {type(e).__name__}\n错误信息: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return [], error_msg, None
