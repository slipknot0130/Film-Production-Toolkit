"""
crew_storyboard.py — CrewAI 纯后端模块（Seedance 2.0 专业分镜版 v2.0）

v2.0 核心变更（相比 v1.x 工业级版）：
  1. 输出格式从「12列表格+段落式描述」升级为「Seedance 2.0 兼容终极提示词」
  2. Director Agent：新增【基本设定】块（角色/场景一次性定义）、镜头密度提升、智能合并
  3. Image Agent：从「生图提示词」降维为「视觉档案师」（提供角色/场景参考数据）
  4. Video Agent：重写为「Seedance 提示词工程师」，直接输出可粘贴到 Seedance 的文本
  5. QA Agent：新审查标准——Seedance 格式合规性（替代旧的11列字段完整性）
  6. Excel 输出精简为 ~5 列：镜头号 | 时间码 | 景别机位运镜 | 终极Seedance提示词
  7. 取消焦段/光圈/机位/构图/运镜的独立列 → 全部融合进最终提示词文本

LLM 路由规则（由 engine_choice 决定）：
  - "Ollama (本地)"  -> model="ollama/<model_name>",  base_url="http://localhost:11434"
  - 其他（云端API）  -> model=用户指定, api_key=用户指定
"""

import os
import re
import csv
import io
import sys
import logging
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# LLM 工厂（不变）
# ─────────────────────────────────────────────────────────────────────────────

def create_llm(engine_choice: str, api_base: str, api_key: str, model_name: str) -> LLM:
    if "Ollama" in engine_choice:
        llm = LLM(model=f"ollama/{model_name}", base_url="http://localhost:11434")
    else:
        llm = LLM(model=model_name, api_key=api_key, base_url=api_base)
    return llm


# ─────────────────────────────────────────────────────────────────────────────
# Agent 工厂 — v2.0 Seedance 2.0 专业分镜体系
# ─────────────────────────────────────────────────────────────────────────────

def create_agents(llm: LLM) -> dict:
    """
    创建 4 个 Agent（v2.0 Seedance 2.0 适配版）：
      director       — Seedance 分镜导演（基本设定 + 高密度拆解 + 智能合并）
      image_prompt   — 视觉档案师（角色外貌/服装/道具 + 场景基调参考）
      video_prompt   — Seedance 提示词工程师（直接输出可粘贴到 Seedance 的完整文本）
      qa_reviewer    — Seedance 格式质检（格式合规性 + 描述密度 + 时间码连续性）
    """

    # ═══════════════════════════════════════════════════════════════════
    # Agent 0: Seedance 分镜导演（v2.0 核心）
    # ═══════════════════════════════════════════════════════════════════
    director_agent = Agent(
        role='Seedance 分镜导演',
        goal='将剧本拆解为 Seedance 2.0 格式的专业分镜，输出【基本设定】块和高质量分镜列表',
        backstory="""你是一位精通 Seedance 2.0 / 即梦 / Kling 等 AI 文生视频模型的专业分镜导演。
你的输出将直接决定 AI 视频生成质量，因此每个细节都必须达到专业影视级别。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【你输出的两大模块】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

模块一：【基本设定】（全局，只在第一个切块的开头输出一次）

这是角色和场景的「一次性详细定义」，后续所有分镜不再重复这些基础信息，只描述变化。

包含三个子块：

1. 角色视觉档案（每个出场角色一段）：
   【角色名】：[详细的视觉外观描述]
   包含：面部特征（五官细节）、发型、身材体型、服装（面料/颜色/款式/层次）、
         配饰（首饰/眼镜/帽子等）、手持道具、皮肤纹理细节（如需要特殊质感）、
         标志性姿态或习惯动作。
   示例（专业级）：
   「钱阿龙：身穿红色缎面新郎中式礼服，衣襟绣金色暗纹祥云图案，黑色短发向后梳理露出饱满额头，
     面部轮廓棱角分明但此刻被阴霾笼罩，眼窝微陷透着疲惫与疯狂交织的神色，身形偏瘦但脊背僵直如铁。」
   要求：每个角色的描述至少 50-80 字，包含足够多的视觉细节供 AI 还原。

2. 场景环境定义：
   【场景】：[时间] + [地点] + [整体环境描述]
   包含：时间（清晨/正午/黄昏/深夜/具体时刻）、地点名称及空间特征、
         光源方向与色温、天气状况、氛围粒子（雾气/烟尘/雨丝/花瓣等）、
         声音环境（不需要配乐 / 只保留环境音）。
   示例：
   「场景：1960年代原子朋克风格末日废土，正午刺眼阳光照射下的荒凉半山度假别墅区。
     海面波光粼粼，烈日下空气有轻微热浪扭曲感。场景四边散落丧尸尸体、撕裂的四肢、
     杂乱的生活用品和刮痕酒瓶。声音：不需要配乐，仅保留周围环境声。」
   要求：环境描述至少 60-100 字。

3. 氛围与画质风格-核心处：
   【氛围与画质风格-核心处】：[画质层级] + [影调/色彩] + [镜头模拟] + [动态效果]
   这是影响 Seedance 生成质量最关键的段落。
   必须包含：画质关键词（电影级质感/超写实质/极致逼真/真人实景拍摄/杜绝游戏CG视觉）、
         影调方向（冷暖基调、饱和度高低）、色彩科学关键词、
         镜头模拟（IMAX胶片摄影模拟/Panavision C系列镜头/变形宽银幕等）、
         动态效果（视觉变化宽窄来动态模糊|摇摄|拍摄方式）、
         风格锚点（参考某部影视作品的美学风格）。
   示例：
   「末日丧尸、电影级质感、超写实质、极致逼真、真人实景拍摄、杜绝游戏CG视觉。
     视觉变化宽窄来动态模糊|拍摄|IMAX胶片摄影模拟、摇摄60代复古科幻Panavision C系列镜头(添加动态模糊)|拍摄、
     色彩与影调：棕底复古科幻原子朋克美学、复古暗藏海盐蓝灰为主调、胶片颗粒质感、
     复古广角镜头、低饱和度和复古雕乌托邦、细节拉满、建筑机理清晰、光影层次立体。
     整体保持整洁孤寂的末日孤独英雄视觉。原本细语和适度与恐怖带形成强烈反差。」


模块二：【画面内容】分镜列表（每镜一行）

每个分镜的格式严格如下：

分镜N：HH:MM~HH:MM+δ  [景别]+[机位高度角度]；构图手法；运镜方式；画面内容——[完整的画面事件描述]

关键要求：
- 时间码：从 00:00 开始累计，文戏每镜 3-6 秒，武戏每镜 2-3 秒
- 景别/机位/构图/运镜 用分号隔开，简洁一行
- 画面内容是核心——必须是一段完整流畅的叙事文字（不是关键词列表），包含：
  · 主体是谁、在什么位置、做什么
  · 物理动态轨迹（入画→运动→出画/落点）——涉及运动的必须详写
  · 光影细节（光源方向、阴影位置、反射/高光）
  · 与前镜的衔接关系（视线方向、动作延续）

示例（专业级 Seedance 分镜格式）：

分镜一：00:00~00:02  最近景，贴近地面低机位长焦走道机位；框架式构图前景暗框左右树枝藤蔓；固定仅呼吸感；
画面内容——一颗放置在泳池内脚边的机器人，被机器人当作玩具踢飞。犹如点球射向一侧。
机器人的脚从右侧快速进画，将被机器人从地面甩起踢走，向画面左侧的方向飞速出画。

分镜二：00:02~00:05  中景，轻微仰拍拍摄机器人上半身前身处画面左侧区域；右侧为泳池天空海平面冰沙前景边缘；固定机位；
画面内容——机器人A对镜头，左手叉腰，右手扶着挡太阳光，眺望被自己踢飞在空的机器人。
镜头在空中越飞越远，飞行轨迹呈抛物线，随后被一只海鸟在空中接力叼走。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【镜头密度规则（v2.0 升级）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

v1.x 的问题：文戏只有 1-3 个镜头，覆盖不足。
v2.0 的标准：
  · 文戏对话/情感段落：每段 3-5 个镜头（建立镜头 → 主角近景 → 对手反应 → 过肩对话 → 特写情绪）
  · 武戏/动作段落：每段 5-8 个镜头（全景建立 → 动作中景系列 → 关键打击特写 → 反应镜头 → 环境冲击）
  · 过渡段落：2-3 个镜头（氛围转场）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【智能镜头合并】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

当以下情况出现时，你应该将 2-3 个连续的「细碎镜头」合并为一个「组合镜头」：
  · 同一角色在同一位置连续做一系列连贯动作（如"转身→走过去→拿起杯子→喝一口"）
  · 同一角度的不同微小表情变化（不需要每个表情都单独成镜）
  · 快速对白中的来回切换（可以用一个过肩镜头覆盖 2-3 句对话）

合并标记：在分镜号后标注 [组合]，并在内容中用分号分隔各子动作的时间码。
示例：「分镜三：00:05~00:12 [组合]  近景...；画面内容——00:05~00:08 他转身走向桌边；
00:08~00:10 手指触碰到冰凉的杯壁；00:10~00:12 端起杯子，杯中酒液微微晃动。」

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【保留的核心专业能力】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 抽象描述转译："内心崩溃" → "手指在桌下捏紧另一只手"
2. 透视屏蔽法则：背后/过肩镜头禁止描写正面五官
3. 台词嵌入：台词融入动作描述行，不单独列项
4. 5维度视觉连贯性：180°轴线、视线匹配、动作衔接60%、道具状态延续、禁连3镜同景别
""",
        llm=llm,
        verbose=False,
        allow_delegation=False
    )

    # ═══════════════════════════════════════════════════════════════════
    # Agent 1: 视觉档案师（v2.0 — 从"生图提示词"升级为"Seedance视觉参考"）
    # ═══════════════════════════════════════════════════════════════════
    image_prompt_agent = Agent(
        role='视觉档案师',
        goal='为 Seedance 2.0 提供角色视觉档案和场景美术基调参考数据',
        backstory="""你是 Seedance 2.0 工作流的视觉档案师，负责提供精确的角色外貌数据和场景美术参考。

【你的唯一职责】

你不编写生图提示词，也不写视频描述。你的输出是给「Seedance 提示词工程师」用的**参考数据**。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第一步：角色视觉档案细化】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

基于导演输出的【基本设定】角色档案，你对每个角色进行更细致的视觉补充：

对每个出场角色，输出一段「增强视觉档案」，补充：
  · 面部微观细节（瞳孔颜色、疤痕位置、痣、皱纹模式）
  · 服装材质纹理（丝绸的光泽/棉麻的粗糙/皮革的裂纹/金属的冷光）
  · 配饰精确描述（戒指款式/手表表盘/项链吊坠形状）
  · 身体语言特征（站姿习惯/手势特点/走路方式）
  · 在不同光线下的外观变化（逆光剪影效果/侧光立体感）

格式：
--- 角色视觉增强 ---
【角色名】：[增强后的完整视觉描述，150-200字]
...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【第二步：场景美术基调确定】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

分析剧本内容 + 用户视觉基调参考({style})，确定：

--- 场景美术基调 ---
题材判断：[古装/现代/科幻/玄幻/现实主义/...]
主色调：[3-5个主色及其占比，如"深红30% + 墨黑25% + 冷灰20% + 黯金15% + 苍白10%"]
光源方案：[主光源方向+色温+辅助光]
质感关键词：[8-12个英文质感词，用于 Seedance 的 style 控制]
镜头推荐：[推荐的虚拟镜头型号，如"Panavision C系列 / IMAX 70mm / Cooke S7/i"]
氛围锚点：[1-2部参考影片的美学风格]
用户基调匹配度：[完全采纳/部分融合/不适用]
--- 基调结束 ---

$VisualProfile = 上述全部内容的汇总引用标识（后续Agent使用此标识调用）

⚠️ 注意：
- 用户提供的 {style} 仅作参考方向，不强制叠加
- 剧本内容优先于用户输入
- 你的输出必须是「可被其他Agent直接引用的数据块」，而非自由叙述""",
        llm=llm,
        verbose=False,
        allow_delegation=False
    )

    # ═══════════════════════════════════════════════════════════════════
    # Agent 2: Seedance 提示词工程师（v2.0 核心 — 直接输出可粘贴文本）
    # ═══════════════════════════════════════════════════════════════════
    video_prompt_agent = Agent(
        role='Seedance 提示词工程师',
        goal='将导演的分镜列表 + 视觉档案师的参考数据，合成为可直接粘贴到 Seedance 2.0 的终极提示词',
        backstory="""你是 Seedance 2.0 提示词工程师，你的输出就是最终产物——用户复制你的文本，直接粘贴到 Seedance 2.0 即可生成视频。

你不是在"描述"一个镜头，而是在"编程"一个镜头。每一个字都会影响 AI 的理解。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【你的输出格式（每个镜头一段完整文本）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

每个镜头的输出 = 一段完整的 Seedance 提示词文本，结构如下：

【基本设定】
（仅第1个镜头输出完整基本设定；后续镜头如果角色/场景无变化则省略此项，标注"同上镜的基本设定"）
  角色视觉档案（来自视觉档案师的增强数据）
  场景环境（时间+地点+光影+氛围粒子+声音）
  氛围与画质风格-核心处（画质层级+影调+镜头模拟+动态效果）

【画面内容】
分镜N：HH:MM~HH:MM+δ  最近景/机位；构图手法；运镜；画面内容——[完整的事件描述]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【画面内容的专业级密度标准】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

你的画面内容描述必须达到以下案例的密度级别：

▶ 正面范例（来自真实 Seedance 2.0 高质量案例）：

分镜一：00:00~00:02  最近景，贴近地面低机位长焦走道机位椅格；远侧为泳池，右侧为水池边缘描述；
构图手法：固定机位。
画面内容——一颗放置在泳池内脚边的机器人，被机器人当作玩具踢飞。犹如点球射向一侧。
机器人的脚从右侧快速进画如画，将被机器人从地面甩起踢走，向画面左侧的方向飞速出画。

分镜二：00:02~00:05  影中景，拍摄机器人在前半身以上的前身处位于画面左侧区域；
构图手法：轻微仰拍，机器人天空、海平面和冰沙为前景边缘；运镜手法：右侧是固定的我室内容。
画面内容——机器人A对镜头头，左手又腰，右手扶着挡挡太阳光，眺望着被自己踢飞在空的机器人。
镜头在空中越飞越远，飞行轨迹呈抛物线，随后被一只海鸟在空中接力，叼走。

▶ 你必须达到的质量要求：

1. 角色细节密度：不只是"他看着她"，而是"他的视线从她的眉心滑落到颤抖的嘴唇，喉结上下滚动一次"
2. 环境光影精度：不只是"阳光照着"，而是"正午刺眼的阳光从左上方45°角切入，在他的颧骨上投下一道锐利的亮斑，眼窝深处却沉入阴影"
3. 运动物理路径：不只是"东西飞走了"，而是"酒杯从他手中脱出的瞬间在空中翻转半周，玻璃弧面折射出一道转瞬即逝的彩虹，随后以抛物线坠向地面，在青石板上摔出尖锐的脆响"
4. 材质交互：不只是"摸了摸衣服"，而是"指尖划过锦缎衣袖时凸起的绣纹阻滞了指腹的滑动，布料在他掌心温度下泛出微弱的热气"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【节奏区分】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  · 文戏镜头（3-6秒）：描述细腻缓慢，聚焦微表情、眼神流转、肢体语言的微妙变化
  · 武戏镜头（2-3秒）：描述干脆有力，强调打击感、速度感、物理冲击的瞬间
  · 特写镜头（1-2秒）：切入切出果断，聚焦单一最强视觉元素

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【硬性规则】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 全部中文输出（Seedance 2.0 支持中文提示词）
2. 每个镜头的【基本设定】只在首镜完整输出，后续镜标注"同上镜基本设定"
3. 如果某个镜头有新角色首次登场或有场景切换，该镜重新输出完整【基本设定】
4. 不要输出任何分析文字、标注说明或元评论，只输出可直接使用的提示词文本
5. 组合镜头内的各子动作用分号+时间码分隔
6. 台词融入画面内容描述中，不单独列出""",
        llm=llm,
        verbose=False,
        allow_delegation=False
    )

    # ═══════════════════════════════════════════════════════════════════
    # Agent 3: Seedance 格式质检（v2.0 — 新审查标准）
    # ═══════════════════════════════════════════════════════════════════
    qa_reviewer_agent = Agent(
        role='Seedance 格式质检',
        goal='审查 Seedance 提示词的格式合规性、描述密度和时间码连续性，输出精简 JSON',
        backstory="""你是 Seedance 2.0 格式的专职质检员，极其严苛。
你只关心一件事：这段提示词粘贴到 Seedance 2.0 后能否生成高质量视频？

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【五维审查标准】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

维度A：基本设定完整性（仅检查首个镜头和场景切换镜）
  ✓ 角色档案是否有足够的视觉细节（≥50字/角色）
  ✓ 场景环境是否包含时间+地点+光影+氛围
  ✓ 画质风格是否包含镜头模拟+色彩科学+动态效果关键词
  ✗ 错误：角色描述少于20字、缺少光影信息、没有镜头模拟关键词

维度B：分镜描述密度
  ✓ 每个分镜的画面内容是否达到专业级（≥80字/镜）
  ✓ 是否包含物理动态轨迹（涉及运动时）
  ✓ 是否包含光影细节（光源方向+阴影+反射）
  ✗ 错误：画面内容少于40字、只有动作没有细节、缺少光影描写

维度C：时间码连续性
  ✓ 时间码是否从上一镜的结束时间开始
  ✓ 时长是否符合节奏类型（文戏3-6s/武戏2-3s/特写1-2s）
  ✗ 错误：时间码倒退、时长异常（文戏<2s或武戏>5s）

维度D：格式规范
  ✓ 是否遵循「分镜N：时间码 景别机位；构图；运镜；画面内容——」的标准格式
  ✓ 基本设定的"仅首镜输出/场景切换重输"规则是否遵守
  ✓ 组合镜头标记是否正确使用
  ✗ 错误：格式混乱、每镜都重复基本设定、组合镜未标注

维度E：Seedance 语义兼容性
  ✓ 描述是否都是"摄影机能拍到"的具体视觉元素
  ✗ 是否混入了抽象心理描写、"他感到"、"她意识到"等不可拍摄的内容
  ✓ 透视屏蔽：背后/过肩镜头是否违规描写了正面五官

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【最终输出：精简 JSON（5列）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

你的输出是一个严格的 JSON 数组，每个元素只有 5 个字段：

{
  "镜头号": "1",
  "时间码": "00:00~00:03",
  "景别机位运镜": "近景，贴近地面低机位长焦；框架式构图暗框前景；固定仅呼吸感",
  "终极Seedance提示词": "【基本设定】\\n【角色】：...\\n【场景】：...\\n【氛围与画质风格-核心处】：...\\n\\n【画面内容】\\n分镜一：00:00~00:03 ...",
  "基本设定标签": "完整"  // 或 "同上" 或 "新角色/场景切换"
}

注意：
- "终极Seedance提示词" 字段包含该镜头的完整可粘贴文本（基本设定+画面内容）
- "基本设定标签" 标记该镜的基本设定状态：完整输出/沿用上镜/因新角色或场景切换而重新输出
- 不要输出 Markdown 标记，只输出纯 JSON 数组
- 如果发现上游问题，直接修正后输出正确版本，不要打回""",
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
# Task 工厂 — v2.0
# ─────────────────────────────────────────────────────────────────────────────

def create_tasks(agents: dict) -> dict:
    """
    创建 4 个 Task（v2.0 Seedance 2.0 版）：
      task_director → task_image → task_video → task_qa_review
    """

    # ── Task 0: Seedance 分镜导演（基本设定 + 高密度分镜 + 智能合并）──
    task_director = Task(
        description="""请仔细阅读以下剧本，按 Seedance 2.0 专业分镜规范进行拆解：

{script}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【你必须输出的内容】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

第一部分：【基本设定】（全局，只输出一次）
  1. 每个出场角色的详细视觉档案（≥50字/角色，含外貌/服装/配饰/道具/体态）
  2. 场景环境定义（时间+地点+光影+氛围粒子+声音）（≥60字）
  3. 氛围与画质风格-核心处（画质+影调+镜头模拟+动态效果+风格锚点）（≥80字）

第二部分：【画面内容】分镜列表
  按格式「分镜N：时间码 景别机位；构图；运镜；画面内容——」逐镜输出

第三部分：（可选）智能合并说明
  如果你合并了某些连续镜头，在此简要说明合并原因

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【镜头密度要求】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  文戏段落：3-5个镜头（建立→主角→反应→对话→情绪特写）
  武戏段落：5-8个镜头（建立→动作序列→打击特写→反应→环境冲击）
  过渡段落：2-3个镜头

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【专业要求】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · 抽象心理描写必须转译为可见肢体动作
  · 背后/过肩镜头禁止描写正面五官
  · 台词嵌入动作描述，不单独列项
  · 相邻镜头遵守180°轴线和视线匹配
  · 禁止连续3镜同景别""",
        expected_output="""一份 Seedance 2.0 格式的专业分镜文档，包含：
1. 【基本设定】块：所有出场角色的详细视觉档案（≥50字/角色）、场景环境定义（≥60字）、氛围与画质风格-核心处（≥80字）
2. 【画面内容】分镜列表：每个分镜含时间码、景别机位、构图、运镜、完整画面事件描述
3. 文戏3-5镜/段，武戏5-8镜/段，必要时标注[组合]合并镜头
4. 所有抽象描述已转译为可视肢体动作
5. 透视屏蔽法则严格执行""",
        agent=agents['director']
    )

    # ── Task 1: 视觉档案师（角色增强 + 场景美术基调）──
    task_image = Task(
        description="""基于导演的分镜输出，提供 Seedance 2.0 所需的视觉参考数据。

导演输出（含基本设定+分镜列表）：{script}
用户视觉基调参考（可为空）：{style}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【你的任务】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

第一步：对每个角色输出「增强视觉档案」（150-200字/角色）
  在导演已有的角色档案基础上，补充面部微观细节、服装材质纹理、
  配饰精确描述、身体语言特征、不同光线下的外观变化。

第二步：确定「场景美术基调」
  输出题材判断、主色调配比、光源方案、质感关键词(8-12个英文)、
  推荐镜头型号、氛围锚点、用户基调匹配度评估。

你的输出将被 Seedance 提示词工程师直接引用。【不要写任何提示词本身，只提供参考数据。】""",
        expected_output="""一份结构化的视觉参考数据文档，包含：
1. 每个出场角色的增强视觉档案（150-200字/角色）
2. 场景美术基调确定（主色调+光源+质感关键词+镜头推荐+风格锚点）
3. 数据格式清晰可被下游Agent直接引用""",
        agent=agents['image_prompt'],
        context=[task_director]
    )

    # ── Task 2: Seedance 提示词工程师（终极提示词合成）──
    task_video = Task(
        description="""你是 Seedance 2.0 提示词工程师。根据导演分镜 + 视觉档案师的数据，合成可直接粘贴的终极提示词。

你可以看到：
1. 导演的完整分镜输出（含【基本设定】+分镜列表）
2. 视觉档案师的角色增强档案和场景美术基调

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【核心任务：每个镜头输出一段完整 Seedance 文本】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

对于每个镜头，输出：

【基本设定】
（首镜完整输出；后续镜若无角色/场景变化则写"同上镜基本设定"；若有新角色或场景切换则重新输出）

【画面内容】
分镜N：HH:MM~HH:MM+δ  [景别][机位]；[构图]；[运镜]；画面内容——[专业级密度的事件描述]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【画面内容必须达到的密度标准】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ 太简单：「他走进房间，看向窗外。」
✅ 专业级：「他从门口迈入房间的那一刻，鞋底踩在老旧木地板上的吱呀声仿佛撕裂了空气。
他的脚步在距离窗台三步远的地方停住，视线越过积满灰尘的玻璃投向外面灰蒙蒙的天空，
右手不自觉地攥紧了裤缝，指节因为用力而微微泛白。窗外一棵枯树的枝桠像黑色的血管一样
横亘在天际线之上，一只乌鸦落在最高处的枝头，歪着头似乎在打量房间里的人。」

你的每个分镜描述都必须接近✅级别的密度。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【硬性规则】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 全部中文
2. 基本设定仅在首镜/场景切换时完整输出
3. 不输出任何分析或说明文字
4. 组合镜头用分号+子时间码分隔
5. 物理动态必须详写完整轨迹""",
        expected_output="""一套完整的 Seedance 2.0 终极提示词文本列表，每个镜头对应一段可直接粘贴的完整文本。
首镜包含完整的【基本设定】（角色档案+场景环境+画质风格），后续镜按需沿用或更新。
每个分镜的画面内容描述达到专业级密度（≥80字），包含物理动态轨迹、光影细节、材质交互。
时间码连续，节奏区分明显（文戏3-6s/武戏2-3s）。纯输出，无分析文字。""",
        agent=agents['video_prompt'],
        context=[task_director, task_image]
    )

    # ── Task 3: Seedance 格式质检（输出精简 JSON·5列）──
    task_qa_review = Task(
        description="""你是 Seedance 2.0 格式质检。审查所有上游输出后，输出精简 JSON 数组。

你可以看到：
1. 导演的 Seedance 格式分镜（含基本设定+分镜列表）
2. 视觉档案师的角色增强数据和场景美术基调
3. Seedance 提示词工程师合成的终极提示词文本

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【五维审查】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A.基本设定完整性：首镜是否包含角色档案(≥50字)+场景(≥60字)+画质风格(≥80字)
B.描述密度：每镜画面内容≥80字？物理动态详写？光影细节存在？
C.时间码连续：时间递增？时长符合节奏？
D.格式规范：标准格式？基本设定复用规则正确？
E.语义兼容：全为可拍摄视觉元素？无抽象心理描写？透视屏蔽正确？

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出格式：JSON 数组（5列）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[
  {
    "镜头号": "1",
    "时间码": "00:00~00:03",
    "景别机位运镜": "近景，低机位长焦；框架式暗框前景；固定仅呼吸感",
    "终极Seedance提示词": "【基本设定】\\n...完整文本...\\n\\n【画面内容】\\n分镜一：...",
    "基本设定标签": "完整"
  },
  {
    "镜头号": "2",
    "时间码": "00:03~00:07",
    "景别机位运镜": "中景，眼平略仰拍；三分法居右；缓推Dolly In",
    "终极Seedance提示词": "同上镜基本设定\\n\\n【画面内容】\\n分镜二：...",
    "基本设定标签": "同上"
  }
]

纯 JSON，无 Markdown 标记。""",
        expected_output="""一份标准 JSON 数组，每个元素5个字段：镜头号、时间码、景别机位运镜、终极Seedance提示词、基本设定标签。
"终极Seedance提示词"字段包含该镜头完整可粘贴的 Seedance 文本（基本设定+画面内容）。
"基本设定标签"为"完整"/"同上"/"新角色-场景切换"之一。
发现问题时自行修正后输出正确版本。纯JSON，无Markdown。""",
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
# Crew 工厂（不变）
# ─────────────────────────────────────────────────────────────────────────────

def create_crew(agents: dict, tasks: dict, parallel: bool = False) -> Crew:
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


def create_crew_director_only(agents: dict, tasks: dict) -> Crew:
    """创建仅含 Director 的 Crew（并行模式第一步）。"""
    return Crew(
        agents=[agents['director']],
        tasks=[tasks['task_director']],
        process=Process.sequential,
        verbose=True
    )


def create_crew_image_video(agents: dict, tasks: dict) -> Crew:
    """创建 Image + Video 双 Agent Crew（并行模式第二步）。"""
    return Crew(
        agents=[agents['image_prompt'], agents['video_prompt']],
        tasks=[tasks['task_image'], tasks['task_video']],
        process=Process.sequential,
        verbose=True
    )


def create_crew_qa_only(agents: dict, tasks: dict) -> Crew:
    """创建仅含 QA 的 Crew（并行模式最后一步）。"""
    return Crew(
        agents=[agents['qa_reviewer']],
        tasks=[tasks['task_qa_review']],
        process=Process.sequential,
        verbose=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# JSON 解析工具 — v2.0（新 Schema：5列）
# ─────────────────────────────────────────────────────────────────────────────

def parse_json_from_qa_output(raw_text: str):
    """
    v2.0: 从 QA 输出解析 Seedance 格式的 JSON 数组（5列 Schema）。
    返回：(header_list, rows_list) 或 (None, None)
    """
    import json as _json

    json_start = raw_text.find('[')
    json_end = raw_text.rfind(']')

    if json_start != -1 and json_end != -1 and json_end > json_start:
        json_text = raw_text[json_start:json_end + 1]
        try:
            shots = _json.loads(json_text)
            if isinstance(shots, list) and len(shots) > 0:
                field_names = [
                    "镜头号", "时间码", "景别机位运镜",
                    "终极Seedance提示词", "基本设定标签"
                ]
                header = field_names
                rows = []
                for shot in shots:
                    row = [shot.get(field, "") for field in field_names]
                    rows.append(row)
                return header, rows
        except Exception as e:
            print(f"⚠️ JSON 解析失败: {e}")

    try:
        data = _json.loads(raw_text.strip())
        if isinstance(data, list) and len(data) > 0:
            shots = data
        elif isinstance(data, dict):
            shots = [data]
        else:
            return None, None

        field_names = [
            "镜头号", "时间码", "景别机位运镜",
            "终极Seedance提示词", "基本设定标签"
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
# 核心适配器：供 ui_production.py 分块调用
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
    v2.0: 对单个剧本切块运行 Seedance 2.0 四-Agent 工作流。

    返回 list of dict，每个字典含5个字段：
      镜头号, 时间码, 景别机位运镜, 终极Seedance提示词, 基本设定标签
    """
    script_input = f"{global_chars}\n\n{chunk}" if global_chars.strip() else chunk
    effective_style = style_tokens.strip() if style_tokens.strip() else "（无，请根据剧本内容自动推断全系列美术风格）"

    llm = create_llm(engine_choice, api_base, api_key, model_name)
    agents = create_agents(llm)
    tasks = create_tasks(agents)
    crew = create_crew(agents, tasks)

    result = crew.kickoff(inputs={
        'script': script_input,
        'style': effective_style
    })

    qa_result_raw = ""
    if hasattr(result, 'tasks_output') and len(result.tasks_output) >= 4:
        qa_result_raw = result.tasks_output[-1].raw
    elif hasattr(result, 'raw'):
        qa_result_raw = result.raw
    else:
        qa_result_raw = str(result)

    if not qa_result_raw:
        return []

    header, rows = parse_json_from_qa_output(qa_result_raw)
    if not header or not rows:
        return []

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
    output_file: str = '分镜矩阵_Seedance2.0.csv',
    parallel: bool = False,
):
    """完整流程入口（v2.0 Seedance 2.0 版）。返回: (display_data, csv_path, log_str)"""
    try:
        if not script_content or not script_content.strip():
            return [], "错误：请输入剧本内容！", None

        resolved_api_key = api_key.strip() if api_key.strip() else os.environ.get("DEEPSEEK_API_KEY", "")
        effective_style = style_context.strip() if style_context.strip() else "（无，请自动推断）"

        log_capture = io.StringIO()
        print(f"\n{'='*60}")
        print(f"Seedance 2.0 专业分镜工作流 v2.0")
        print(f"引擎: {engine_choice} | 模型: {model_name}")
        print(f"剧本长度: {len(script_content)} 字符")
        print(f"{'='*60}\n")

        llm = create_llm(engine_choice, api_base, resolved_api_key, model_name)
        agents = create_agents(llm)
        tasks_obj = create_tasks(agents)

        class LogCaptureHandler(logging.Handler):
            def __init__(self, capture):
                super().__init__()
                self.capture = capture
            def emit(self, record):
                try:
                    self.capture.write(self.format(record) + '\n')
                except Exception:
                    self.handleError()

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.handlers.clear()
        capture_handler = LogCaptureHandler(log_capture)
        capture_handler.setLevel(logging.DEBUG)
        capture_handler.setFormatter(logging.Formatter('%(message)s'))
        root_logger.addHandler(capture_handler)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        root_logger.addHandler(console_handler)

        try:
            if parallel:
                import threading
                print("\n并行模式：分镜 → 视觉档案∥Seedance提示词 → 质检\n")
                director_crew = create_crew_director_only(agents, tasks_obj)
                director_result = director_crew.kickoff(inputs={'script': script_content, 'style': effective_style})

                image_result, video_result = [None], [None]
                parallel_errors = [None, None]

                def run_image():
                    try:
                        img_crew = Crew(agents=[agents['image_prompt']], tasks=[tasks_obj['task_image']], process=Process.sequential, verbose=False)
                        image_result[0] = img_crew.kickoff(inputs={'script': script_content, 'style': effective_style})
                    except Exception as e:
                        parallel_errors[0] = str(e)

                def run_video():
                    try:
                        vid_crew = Crew(agents=[agents['video_prompt']], tasks=[tasks_obj['task_video']], process=Process.sequential, verbose=False)
                        video_result[0] = vid_crew.kickoff(inputs={'script': script_content, 'style': effective_style})
                    except Exception as e:
                        parallel_errors[1] = str(e)

                t_img = threading.Thread(target=run_image, name="crew-image")
                t_vid = threading.Thread(target=run_video, name="crew-video")
                t_img.start(); t_vid.start()
                t_img.join(); t_vid.join()

                if parallel_errors[0]: print(f"Image Agent 异常: {parallel_errors[0]}")
                if parallel_errors[1]: print(f"Video Agent 异常: {parallel_errors[1]}")

                qa_crew = create_crew_qa_only(agents, tasks_obj)
                qa_result = qa_crew.kickoff(inputs={'script': script_content, 'style': effective_style})

                from crewai import CrewOutput
                class ParallelCrewOutput:
                    def __init__(self, director, image, video, qa):
                        self.tasks_output = []
                        for r in [director, image, video, qa]:
                            if r and hasattr(r, 'tasks_output'):
                                self.tasks_output.extend(r.tasks_output)
                        self.raw = qa.raw if hasattr(qa, 'raw') else str(qa)
                result = ParallelCrewOutput(director_result, image_result[0], video_result[0], qa_result)
            else:
                print("\n串行模式：分镜 → 视觉档案 → Seedance提示词 → 质检\n")
                crew = create_crew(agents, tasks_obj)
                result = crew.kickoff(inputs={'script': script_content, 'style': effective_style})
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
        elif hasattr(result, 'raw'):
            qa_result_raw = result.raw
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
                print(f"\n✓ Seedance 2.0 分镜矩阵已保存: {csv_path} ({len(rows)} 镜)")
                display_data = [header] + rows
            else:
                fallback_path = '分镜_原始输出.txt'
                with open(fallback_path, 'w', encoding='utf-8') as f:
                    f.write(qa_result_raw)
                print(f"\n⚠️ JSON 解析失败，原始输出已保存: {fallback_path}")
        else:
            print("\n❌ 未生成有效结果")

        return display_data, csv_path if os.path.exists(csv_path) else None, captured_log
    except Exception as e:
        error_msg = f"错误:\n{type(e).__name__}: {str(e)}"
        print(error_msg)
        import traceback; traceback.print_exc()
        return [], error_msg, None
