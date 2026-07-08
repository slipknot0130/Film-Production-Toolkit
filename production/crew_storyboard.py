"""
crew_storyboard.py — CrewAI 后端模块（v4.1 纯文本四段式版）

v4.1 优化（2026-07-08）：
  去掉 Section 1-2 中的 <主体N>/<场景N> 占位符，改为纯文本自然语言描述。
  纯文本工作流（无 @图片/@视频 引用）下，<主体N> 锚定标签无对应媒体可锚定，
  会让视频创作者困惑"是否需要手动替换"。改为纯文本后可直接阅读和粘贴。

v4.0 核心升级（2026-07-08）：
  融合 Seedance 2.0 官方 Prompt 四段式规范，输出格式全面对齐文档规则：
  1. 主体与特征锚定 — 角色视觉特征 + 场景时间地点
  2. 参考关系和子任务判断 — 任务类型声明 + 故事概要
  3. 动态描述 — 时序分段的动作/镜头/台词{}/音效<>/BGM（）
  4. 静态描述 — 光线/色彩/画质/风格（不重复第3段）

  Agent 层面增强：
  - Director 注入音频符号约定、一镜到底规则、脸部安全约束、反主观词规则
  - QA 新增指令冲突检测、内容过载检测、持续声音标记检查

  架构不变：2-Agent 串行 + 代码组装，核心原则「LLM 做创意，代码做格式化」延续。

  输出格式：4 列（镜头号 | 时间码 | 景别机位运镜 | 终极Seedance提示词-四段式）
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


# ═════════════════════════════════════════════════════════════════════════════
# LLM 工厂（不变）
# ═════════════════════════════════════════════════════════════════════════════

def create_llm(engine_choice: str, api_base: str, api_key: str, model_name: str) -> LLM:
    if "Ollama" in engine_choice:
        llm = LLM(model=f"ollama/{model_name}", base_url="http://localhost:11434")
    else:
        llm = LLM(model=model_name, api_key=api_key, base_url=api_base)
    return llm


# ═════════════════════════════════════════════════════════════════════════════
# Agent 工厂 — v4.0 结构参数化版（2 Agent + Seedance 规则注入）
# ═════════════════════════════════════════════════════════════════════════════

def create_agents(llm: LLM) -> dict:
    """
    v4.0：创建 2 个 Agent（注入 Seedance 2.0 规则约束）
      director    — 分镜导演（读剧本 → 出结构化 JSON，含音频符号约定）
      qa_reviewer — 分镜质检（语义级抽查 + Seedance 规则合规审查）
    """

    # ═══════════════════════════════════════════════════════════════════
    # Agent 0: 分镜导演（v4.0 — 融合 Seedance 2.0 官方四段式规则）
    # ═══════════════════════════════════════════════════════════════════
    director_agent = Agent(
        role='Seedance 分镜导演',
        goal='分析剧本，输出结构化分镜 JSON（镜头参数 + 专业级画面描述 + 音频符号）',
        backstory="""你是精通 AI 文生视频的分镜导演，熟悉 Seedance 2.0 / Kling / 即梦 等模型。

你的唯一输出是结构化 JSON。所有排版格式由代码层处理，你不需要关心。

【Seedance 2.0 官方提示词规则 — 必须遵守】
· 音频符号约定：
  台词内容→用{花括号}包裹   例：她低声说道{你终于来了。}
  音效环境音→用<尖括号>包裹 例：<雨声和远处雷声持续>
  背景音乐BGM→用（圆括号）包裹 例：（低沉弦乐，节奏缓慢）
· 持续声音标记：镜头切换后若同一声源继续，在描述前方写"<雨声继续>"或"（BGM继续）"
· 台词规范：必须写清语言、音色、语气、语速；有嘴型时写"嘴型同步"
· 一镜到底规则：角色说话场景默认 5-8 秒、一镜到底、正面说话、1-2 句短台词
· 时长节奏：4-5 秒内只安排一个主要动作或一次镜头变化；复杂剧情用 12-15 秒或拆为多镜
· 脸部安全：避免生成写实真人清晰脸部特写（容易被内容审核拦截），面部镜头用中景/侧脸/光影遮挡替代大特写
· 反主观词：禁止"温馨""压抑""暧昧""廉价"等无视觉依据词；表达氛围时用可见依据支撑：如
  「暖黄色室内灯光 + 低对比度 + 人物距离较近，形成温和氛围」
· 指令一致性：不要同时要求"固定镜头"又写"环绕""推拉摇移"
· 内容不过载：4-5 秒内禁止塞入多个动作或多次镜头切换

【画面描述质量铁律】（你的核心竞争力）
1. 动作链完整：入画 → 运动过程 → 落点，轨迹每一步都清晰可辨
2. 光影精确：主光源方向 + 色温（如"高位冷月 6500K"）+ 阴影落在哪个部位 + 高光反射
3. 物理质感：材质触感（粗糙/光滑/潮湿）、重量感、步伐声音暗示（鞋底材质+地面材质+声音）
4. 微表情细节："视线从眉心滑落到嘴唇，喉结滚动一次，下眼睑微颤"
5. 氛围粒子：雾浓度、尘埃飘浮方向、植被运动幅度、水面波纹

❌ 绝对禁止：
  · "他感到悲伤/她意识到危险" → 转译为：低头、垂肩、咬唇、瞳孔收缩、后退半步
  · 背后/过肩镜头描写正面五官（透视屏蔽）
  · 干瘪的一句话 → 每个镜头画面内容必须 ≥80 字

✅ 参考级密度（你要达到的标准）：
  「瘴气流动的黑水林深处，月光艰难穿透雾气在地面投下斑驳的苍白光斑。
   钱阿龙身穿正红新郎服，步履僵硬地从画面深处走来，每一步脚跟先砸在地上，
   重心前倾，膝盖不打弯，像被无形丝线牵引的木偶。他走到一棵枝叶盘虬的
   古榕树前停住，肩膀有节奏地轻微耸动，喉间发出一阵混合着笑声和哭泣的
   诡异呜咽。推轨镜头缓慢向前，灌木枝条轻轻擦过镜头边缘，形成一层虚化的
   绿色前景。」""",
        llm=llm,
        verbose=False,
        allow_delegation=False
    )

    # ═══════════════════════════════════════════════════════════════════
    # Agent 1: 分镜质检（v4.0 — 新增 Seedance 规则专项检查）
    # ═══════════════════════════════════════════════════════════════════
    qa_reviewer_agent = Agent(
        role='分镜质检',
        goal='抽查Director的JSON输出，修正创意质量问题，保证画面描述密度达标，验证Seedance规则合规',
        backstory="""你是分镜质量审查员。Director已输出结构化JSON，你需要做语义级抽查 + Seedance 规则合规审查。

检查项：
1. 画面描述密度：是否有镜头画面内容 <60字？→ 补充动作/光影/质感细节
2. 抽象心理转译：是否有"他感到""她意识到"等不可拍摄内容？→ 转译为可见肢体动作
3. 透视屏蔽：背后/过肩镜头是否违规描写了正面五官？→ 修正视角
4. 场景一致性：镜头引用的场景名是否在场景定义中存在？→ 修正或补定义
5. 音频符号正确性：台词是否用{}而非其他符号？音效用<>而非{}？BGM用（）？
   → 修正为正确的 Seedance 符号约定
6. 指令冲突检测：「固定镜头」和「推/拉/摇/移/环绕」是否同时出现？→ 冲突则保留其一
7. 内容过载检测：4-5秒镜头内是否有 ≥2 个独立动作 + ≥2 次镜头切换？→ 拆分为多镜或延长时长
8. 持续声音标记：同一场景连续镜头中，若前镜有环境声/BGM，后镜是否标记了"<xx继续>"或"（BGM继续）"？
9. 脸部安全：是否有"写实真人清晰面部特写""毛孔级面部细节"等风险描述？→ 降级为"中景侧脸""光影遮挡面部"
10. 反主观词：是否有"温馨""压抑""暧昧""廉价""恐怖"等无视觉依据词？→ 转为可见依据

修正后直接输出完整 JSON，不要解释改了什么。纯 JSON，无 Markdown。""",
        llm=llm,
        verbose=False,
        allow_delegation=False
    )

    return {
        'director': director_agent,
        'qa_reviewer': qa_reviewer_agent
    }


# ═════════════════════════════════════════════════════════════════════════════
# Task 工厂 — v4.0
# ═════════════════════════════════════════════════════════════════════════════

def create_tasks(agents: dict) -> dict:
    """v4.0：2 个 Task（Director + QA，含 Seedance 2.0 规则约束）"""

    # ── Task 0: 分镜导演（结构化 JSON 输出）──
    task_director = Task(
        description="""请仔细阅读以下剧本，分析后输出结构化分镜 JSON。

{script}

{char_injection}
{duration_guide}

用户视觉基调参考（可为空）：{style}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【你唯一的输出格式 — 严格 JSON】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "全局氛围画质": "完整的【氛围与画质】描述文本（≥120字）。必须包含：风格核心关键词、视觉基调、色彩与影调、镜头/胶片模拟、质感描述、风格参考锚点（影视作品/美学流派）。例如：'风格核心：赛博朋克、霓虹暗黑、电影级质感。视觉基调：变形宽银幕 IMAX 胶片模拟。色彩影调：深紫+冷蓝高反差，霓虹品红点缀，胶片颗粒质感。镜头：Panavision C 系列变形宽银幕。参考美学：《银翼杀手2049》...'",
  "场景定义": {
    "场景名": "时间：xx | 地点：xx | 主光源：方向+色温 | 氛围粒子：xx | 声音环境：xx（50-80字）"
  },
  "分镜列表": [
    {
      "镜头号": 1,
      "场景名": "场景定义中已定义的场景名",
      "时长秒": 5,
      "景别": "全景",
      "机位": "平视低角度，贴近地面",
      "构图": "人物居中，前景灌木形成引导线，天空占1/3",
      "运镜": "慢速向前推轨",
      "画面内容": "该镜头的完整画面描述（≥80字）。必须包含：角色动作轨迹（入画→过程→落点）、光影效果（光源方向+色温+阴影位置）、物理质感（材质+声音暗示）、氛围细节（雾/尘埃/植被运动）。角色名直接写原名如'钱阿龙'，无需加@符号。",
      "出场角色": ["钱阿龙"]
    }
  ]
}

字段说明：
  · 全局氛围画质：一个完整文本块，不是键值对。输出给用户当作整个项目的视觉设定参考。
  · 场景定义：对本切块中出现的每个场景给出环境描述。场景名用简短中文名（如"黑水林""阿龙婚房"）。
  · 镜头号：从1开始的整数。
  · 时长秒：该镜建议持续秒数。单动作/单切镜=4-5s；对话文戏=5-8s；武戏打斗=2-3s；过渡衔接=2-3s；复杂剧情=12-15s 或拆多镜。绝不在4-5秒内塞≥2个独立动作。
  · 景别：全景 / 中景 / 近景 / 特写 / 大特写 / 远景。避免写实真人面部大特写（改中景/侧脸）。
  · 机位：拍摄高度+角度+距离，如"低角度仰拍，贴近地面""高机位微俯拍""眼平机位"。
  · 构图：人物在画面中的位置关系、前景/背景层次、引导线、三分法/黄金分割等。
  · 运镜：运动方式+速度，如"慢速推轨""固定仅呼吸感""手持微晃跟拍""快速横摇"。禁止「固定镜头」+「推拉摇移环绕」同时出现。
  · 画面内容：★ 核心创意输出 ★ 角色名直接写原名（如"钱阿龙"），代码会自动加@前缀。禁止只写"他走进来"这种干瘪描述！
    画面内容中请按 Seedance 约定嵌入音频符号：台词用{}、音效用<>、BGM用（）。
    例：压低声音说{别出声。}，<远处传来犬吠声>，（低沉钢琴渐起）
  · 出场角色：该镜头中出现的角色名列表，按出场顺序。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【按上方「剧本体量分析」参数严格执行】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  总镜数和总时长严格按代码计算的建议范围规划。
  对话段落：3-5镜/段（一镜到底对话5-8s） | 武戏段落：5-8镜/段（2-3s/镜） | 过渡段落：2-3镜/段（2-3s/镜）
  每镜严格遵守：4-5s内=一个主动作/一次切镜，复杂剧情=12-15s或拆多镜

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出铁律】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 纯 JSON，无任何 Markdown 标记（不要 ```json 包裹）
2. 无任何解释/分析/元评论文本
3. 画面内容每个 ≥80 字，核心镜头 ≥120 字
4. JSON 必须可被 Python json.loads() 直接解析""",
        expected_output="""一个严格的 JSON 对象，包含「全局氛围画质」「场景定义」「分镜列表」三个字段。
分镜列表中每个元素含10个字段（镜头号/场景名/时长秒/景别/机位/构图/运镜/画面内容/出场角色）。
画面内容描述达到专业影视级密度（动作轨迹+光影+质感+微表情）。
纯JSON，无Markdown，无解释文字。""",
        agent=agents['director']
    )

    # ── Task 1: 分镜质检（v4.0 新增 Seedance 规则审查）──
    task_qa_review = Task(
        description="""你是分镜质检。审查Director的结构化JSON输出，修正后输出。

你可以看到Director的完整JSON输出。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【审查项目】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A. 画面描述密度：
   - 是否有镜头「画面内容」<60字？→ 补充动作轨迹、光影细节、物理质感
   - 是否有镜头只写了动作没有氛围？→ 补充雾/尘埃/光影/声音等环境细节

B. 抽象心理转译：
   - 是否有「他感到紧张」「她意识到危险」等不可拍摄内容？→ 转译为肢体动作
   - 「紧张」→「手指在桌面下反复捏搓，指节泛白」
   - 「愤怒」→「下颌咬紧，太阳穴青筋微凸，手中的杯子被攥得发出细响」

C. 透视屏蔽：
   - 背后/过肩镜头是否违规描写了正面五官？→ 修正为可见的身体部位（后脑/后背/肩膀/手臂）

D. 场景一致性：
   - 分镜引用的场景名是否在「场景定义」中存在？→ 不存在则补充或修正

E. Seedance 音频符号正确性：
   - 台词是否用{}而非其他符号？→ 修正为{花括号}
   - 环境音/音效是否用<>？→ 修正为<尖括号>
   - BGM是否用（）？→ 修正为（圆括号）
   - 没有音效/台词的镜头不要强行添加符号

F. 指令冲突检测：
   - 「固定镜头」是否与「推/拉/摇/移/环绕」同时出现在同一镜头？→ 冲突则删除其一
   - 「无声」是否与「背景音乐」同时出现？→ 冲突则保留其一

G. 内容过载检测：
   - 4-5 秒镜头内是否有 ≥2 个独立动作 + ≥2 次镜头切换？→ 拆分镜头或延长至12-15秒
   - 是否有单一镜头塞入完整对话+打斗+场景转换？→ 拆分为多镜

H. 持续声音标记：
   - 同一场景连续镜头中，若前进有"<雨声>""（BGM）"，后镜画面描述起始处是否写"<雨声继续>""（BGM继续）"？

I. 脸部安全：
   - 是否出现"面部大特写""写实真人清晰脸部""毛孔级面部细节"？→ 降级

J. 反主观词：
   - 是否出现"温馨""压抑""暧昧""廉价""恐怖""浪漫"等无视觉依据词？→ 转为可见依据

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出格式】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

输出修正后的完整 JSON（结构与Director输出完全相同）。
纯 JSON，无 Markdown 标记，无解释文字。
如果无需修正，原样输出。""",
        expected_output="""修正后的完整 JSON 对象，与Director输出结构完全一致。
内容已修正至专业影视级质量标准，Seedance 2.0 规则全部合规。
纯JSON，无Markdown，无解释。""",
        agent=agents['qa_reviewer'],
        context=[task_director]
    )

    return {
        'task_director': task_director,
        'task_qa_review': task_qa_review
    }


# ═════════════════════════════════════════════════════════════════════════════
# 代码组装引擎 — v4.1 核心：结构化 JSON → Seedance 2.0 四段式提示词（纯文本无占位符）
# ═════════════════════════════════════════════════════════════════════════════

def _format_timecode(total_seconds: float) -> str:
    """将累计秒数格式化为 MM:SS 时间码字符串。"""
    m = int(total_seconds // 60)
    s = int(total_seconds % 60)
    return f"{m:02d}:{s:02d}"


def _inject_references(content: str, scene_name: str, characters: list) -> str:
    """
    在画面内容中自动插入 @角色名 引用。
    保护 Seedance 音频符号（{} <> ()）内的文本不被 @ 注入破坏。

    规则：
    - 每个角色名的第一次出现（且不在{}<>()音频标记内）替换为 @角色名
    - 同一角色在同一镜头内多次出现时，仅第一次加@
    """
    result = content

    for char in characters:
        if not char or char not in result:
            continue
        # 保护音频标记内的文本：先用占位符替换{}<>()内容，注入后再恢复
        audio_blocks = []
        def _mask_audio(m):
            audio_blocks.append(m.group(0))
            return f"\x00AUDIO{len(audio_blocks)-1}\x00"
        masked = re.sub(r'\{[^}]*\}|<[^>]*>|（[^）]*）', _mask_audio, result)
        # 在 mask 后的文本中做 @注入
        if char in masked:
            masked = masked.replace(char, f"@{char}", 1)
        # 恢复音频块
        for i, block in enumerate(audio_blocks):
            masked = masked.replace(f"\x00AUDIO{i}\x00", block)
        result = masked

    return result


def _extract_character_brief(chars: list, content: str) -> dict:
    """
    为 Section 1「主体与特征锚定」提取角色的 2-3 个关键视觉特征。
    从画面内容中提取首次出现该角色时的前后文字作为简要特征描述。
    返回 {角色名: "2-3个关键特征"} 的映射。
    """
    briefs = {}
    for char in chars:
        if not char:
            continue
        idx = content.find(char)
        if idx >= 0:
            # 取角色名后 30 字作为特征描述上下文
            ctx = content[idx + len(char):idx + len(char) + 30].strip()
            # 找最近的第一个自然断点（6 字以上才有意义）
            cut = ctx
            best_pos = len(ctx)
            for sep in ['。', '，', '；', '、', '\n']:
                pos = ctx.find(sep)
                if 6 < pos < best_pos:
                    best_pos = pos
            if best_pos < len(ctx):
                cut = ctx[:best_pos]
            cut = cut.replace('@', '').strip()
            if len(cut) >= 2:
                # 最多保留 30 字
                briefs[char] = cut[:30].strip()
    return briefs


def _extract_scene_brief(scene_desc: str) -> str:
    """
    从完整场景描述中提取简要标识（时间 + 地点），用于 Section 1。
    避免硬截断导致残破文本。
    """
    if not scene_desc:
        return ""
    # 从 | 分隔的场景定义中提取 时间 和 地点 字段
    parts = {}
    for segment in scene_desc.replace("｜", "|").split("|"):
        segment = segment.strip()
        for sep_char in ("：", ":"):
            if sep_char in segment:
                key, val = segment.split(sep_char, 1)
                key = key.strip()
                if key in ("时间", "地点"):
                    parts[key] = val.strip()[:20]
                break
    if "地点" in parts:
        time_part = f"{parts['时间']}，" if "时间" in parts else ""
        return f"{time_part}{parts['地点']}"
    # 回退：安全截断
    return scene_desc.split("|")[0].strip()[:40]


def assemble_seedance_prompt(shot_data: dict, time_offset_seconds: float = 0.0) -> tuple:
    """
    v4.1 核心组装函数：按 Seedance 2.0 四段式格式生成提示词。

    四段式结构（纯文本工作流，无 <主体N> 占位符）：
      1. 主体与特征锚定 — 角色名 + 2-3 个视觉特征，场景名 + 时间/地点
      2. 参考关系和子任务判断 — 任务类型 + 故事概要（自然语言）
      3. 动态描述 — 时序分段的动作/镜头/台词{}/音效<>/BGM（）
      4. 静态描述 — 光线/色彩/画质/风格（不重复第3段已有内容）

    参数:
      shot_data: Director/QA 输出的 JSON dict
      time_offset_seconds: 跨切块时间码偏移

    返回:
      (shot_list, total_seconds, global_atmosphere)
    """
    shot_list = []
    accumulated = time_offset_seconds
    global_atmosphere = shot_data.get("全局氛围画质", "")
    scene_defs = shot_data.get("场景定义", {})
    shots = shot_data.get("分镜列表", [])

    if not shots:
        return [], time_offset_seconds, global_atmosphere

    # 预计算全局氛围摘要（用于 Section 4 静态描述注入）
    global_atmo_summary = ""
    if global_atmosphere:
        atmo = global_atmosphere.strip()
        # 取前 200 字作为风格/画质摘要
        if len(atmo) > 200:
            cut_pos = atmo[:200].rfind('。')
            if cut_pos > 50:
                global_atmo_summary = atmo[:cut_pos + 1]
            else:
                global_atmo_summary = atmo[:200] + '…'
        else:
            global_atmo_summary = atmo

    for shot in shots:
        # ── 基本字段提取 ──
        shot_num = shot.get("镜头号", len(shot_list) + 1)
        scene_name = str(shot.get("场景名", "")).strip()
        duration = max(float(shot.get("时长秒", 4)), 1.0)
        shot_type = str(shot.get("景别", "")).strip()
        camera_pos = str(shot.get("机位", "")).strip()
        composition = str(shot.get("构图", "")).strip()
        camera_move = str(shot.get("运镜", "")).strip()
        content = str(shot.get("画面内容", "")).strip()
        characters = shot.get("出场角色", [])
        if isinstance(characters, str):
            characters = [c.strip() for c in characters.replace("、", ",").split(",") if c.strip()]

        # ── 时间码计算 ──
        start_sec = accumulated
        end_sec = accumulated + duration
        timecode = f"{_format_timecode(start_sec)}~{_format_timecode(end_sec)}"
        accumulated = end_sec

        # ── 景别机位运镜摘要列（不变）──
        camera_parts = [p for p in [shot_type, camera_pos, camera_move] if p]
        camera_summary = "，".join(camera_parts)

        # ── 场景描述提取 ──
        scene_desc = ""
        if isinstance(scene_defs, dict) and scene_name in scene_defs:
            scene_desc = str(scene_defs[scene_name]).strip()

        # ── 角色特征简要提取 ──
        char_briefs = _extract_character_brief(characters, content)

        # ════════════════════════════════════════
        # Section 1: 主体与特征锚定（纯文本，无占位符）
        # ════════════════════════════════════════
        # 格式：缩进列表，角色写关键特征，场景写时间+地点
        section1_lines = []
        for char in characters[:5]:
            brief = char_briefs.get(char, "")
            if brief:
                section1_lines.append(f"  · {char}：{brief}")
            else:
                section1_lines.append(f"  · {char}")
        if scene_name:
            scene_brief = _extract_scene_brief(scene_desc)
            section1_lines.append(f"  · {scene_name}：{scene_brief}" if scene_brief else f"  · {scene_name}")

        # ════════════════════════════════════════
        # Section 2: 参考关系和子任务判断（自然语言，简洁概要）
        # ════════════════════════════════════════
        char_names = "、".join(characters[:5]) if characters else "角色"
        section2 = f"任务类型：参考。根据剧本设定，生成 {char_names} 在 {scene_name or '场景'} 中的视频。"

        # ════════════════════════════════════════
        # Section 3: 动态描述
        # ════════════════════════════════════════
        # 注入 @引用
        content_with_refs = _inject_references(content, scene_name, characters)

        # 构建镜头参数行
        camera_line_parts = []
        if shot_type:
            camera_line_parts.append(f"景别：{shot_type}")
        if camera_pos:
            camera_line_parts.append(f"机位：{camera_pos}")
        if composition:
            camera_line_parts.append(f"构图：{composition}")
        if camera_move:
            camera_line_parts.append(f"运镜：{camera_move}")
        camera_line = "，".join(camera_line_parts)

        # 组装 Section 3：镜头参数行 + 画面内容
        section3 = f"@{scene_name}\n\n{camera_line}。\n{content_with_refs}"

        # ════════════════════════════════════════
        # Section 4: 静态描述
        # ════════════════════════════════════════
        section4_parts = []
        # 场景环境信息（光线/色彩部分）
        if scene_desc:
            section4_parts.append(f"场景环境：{scene_desc}")
        # 全局画质/风格（取摘要，不重复第3段已有的动作描述）
        if global_atmo_summary:
            section4_parts.append(f"画质与风格参考：{global_atmo_summary}")
        # 如果都为空，给出默认提示
        if not section4_parts:
            section4_parts.append("（与第3段动态描述保持一致，无额外静态元素需要补充）")

        section4 = "\n".join(section4_parts)

        # ════════════════════════════════════════
        # 组装最终提示词
        # ════════════════════════════════════════
        header_line = f"═══════════════════════════════════════\n分镜{shot_num}：{timecode}（{duration}秒）\n═══════════════════════════════════════"

        final_prompt = (
            f"{header_line}\n\n"
            f"1. 主体与特征锚定\n"
            + "\n".join(section1_lines) + "\n\n"
            f"2. 参考关系和子任务判断\n"
            f"{section2}\n\n"
            f"3. 动态描述\n"
            f"{section3}\n\n"
            f"4. 静态描述\n"
            f"{section4}"
        )

        shot_list.append({
            "镜头号": str(shot_num),
            "时间码": timecode,
            "景别机位运镜": camera_summary,
            "终极Seedance提示词": final_prompt
        })

    total_seconds = accumulated - time_offset_seconds
    return shot_list, total_seconds, global_atmosphere


# ═════════════════════════════════════════════════════════════════════════════
# Crew 工厂 — v4.0（2 Agent）
# ═════════════════════════════════════════════════════════════════════════════

def create_crew(agents: dict, tasks: dict) -> Crew:
    """v4.0：创建 Director + QA 双 Agent 顺序 Crew"""
    return Crew(
        agents=[agents['director'], agents['qa_reviewer']],
        tasks=[tasks['task_director'], tasks['task_qa_review']],
        process=Process.sequential,
        verbose=True
    )


def create_crew_director_only(agents: dict, tasks: dict) -> Crew:
    """创建仅含 Director 的 Crew（并行模式第一步）。"""
    return Crew(
        agents=[agents['director']],
        tasks=[tasks['task_director']],
        process=Process.sequential,
        verbose=True
    )


def create_crew_qa_only(agents: dict, tasks: dict) -> Crew:
    """创建仅含 QA 的 Crew（并行模式 QA 单独跑）。"""
    return Crew(
        agents=[agents['qa_reviewer']],
        tasks=[tasks['task_qa_review']],
        process=Process.sequential,
        verbose=True
    )


# ═════════════════════════════════════════════════════════════════════════════
# JSON 解析 — v4.0（适配新 Schema）
# ═════════════════════════════════════════════════════════════════════════════

def parse_structured_json(raw_text: str) -> dict:
    """
    v4.0：从 LLM 输出中提取结构化分镜 JSON（全局氛围画质 + 场景定义 + 分镜列表）。
    返回 dict 或 None。
    """
    import json as _json
    
    if not raw_text or not raw_text.strip():
        return None
    
    text = raw_text.strip()
    
    # 尝试1：直接解析整个文本
    try:
        data = _json.loads(text)
        if isinstance(data, dict) and "分镜列表" in data:
            return data
    except _json.JSONDecodeError:
        pass
    
    # 尝试2：提取 JSON 块（可能被 markdown 包裹）
    json_start = text.find('{')
    json_end = text.rfind('}')
    if json_start != -1 and json_end != -1 and json_end > json_start:
        try:
            data = _json.loads(text[json_start:json_end + 1])
            if isinstance(data, dict) and "分镜列表" in data:
                return data
        except _json.JSONDecodeError:
            pass
    
    # 尝试3：寻找 ```json 块
    md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if md_match:
        try:
            data = _json.loads(md_match.group(1).strip())
            if isinstance(data, dict) and "分镜列表" in data:
                return data
        except _json.JSONDecodeError:
            pass
    
    return None


# ═════════════════════════════════════════════════════════════════════════════
# 核心适配器：供 ui_production.py 分块调用
# ═════════════════════════════════════════════════════════════════════════════

def _parse_timecode_end(tc: str) -> float:
    """解析时间码字符串的结束秒数（用于跨切块时间码累积）。"""
    parts = tc.split('~')
    if len(parts) < 2:
        return 0.0
    end_part = parts[-1].strip()
    end_clean = re.sub(r'[+＋]\s*\d+.*$', '', end_part).strip()
    
    match = re.match(r'(\d{1,2}):(\d{2}):(\d{2})', end_clean)
    if match:
        return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
    
    match = re.match(r'(\d{1,2}):(\d{2})', end_clean)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    
    return 0.0


def _validate_min_content(shot_list: list):
    """代码层标注画面内容过短的镜头（v4.0: 适配四段式格式解析）。遍历全部镜头，逐个检查。"""
    for shot in shot_list:
        prompt = str(shot.get("终极Seedance提示词", ""))
        # 尝试从四段式格式中提取「3. 动态描述」段的内容
        section3_match = re.search(r'3\.\s*动态描述\s*\n(.+?)(?:\n\n4\.|\Z)', prompt, re.DOTALL)
        if section3_match:
            section3_text = section3_match.group(1).strip()
            # 去掉镜头参数行，取纯画面描述
            # 镜头参数行格式: "@场景名\n\n景别：xxx，机位：xxx，构图：xxx，运镜：xxx。\n..."
            pure_content = re.sub(r'^@\S+\s*\n+', '', section3_text)
            pure_content = re.sub(r'^[^\n]*?(?:景别|机位|构图|运镜)[^\n]*?\n', '', pure_content)
            pure_content = pure_content.strip()
            if len(pure_content) < 50:
                shot["终极Seedance提示词"] = prompt + f"\n\n⚠️ [画面描述仅{len(pure_content)}字，可能不够丰富]"
            continue

        # 回退：兼容旧格式（v3.0 扁平提示词）
        content_match = re.search(r'画面内容：(.+)$', prompt, re.DOTALL)
        if content_match:
            content_text = content_match.group(1).strip()
            if len(content_text) < 50:
                shot["终极Seedance提示词"] = prompt + f"\n⚠️[画面描述仅{len(content_text)}字，可能不够丰富]"


def run_crew_on_chunk(
    chunk: str,
    global_chars: str,
    style_tokens: str,
    engine_choice: str,
    api_base: str,
    api_key: str,
    model_name: str,
    time_offset_seconds: float = 0.0
) -> tuple:
    """
    v3.0: 对单个剧本切块运行 2-Agent 工作流（Director → QA），
    然后由代码层组装 Seedance 提示词。

    返回 (list of dict, total_seconds_float, global_atmosphere_str)：
      - list: 每个 dict 含 4 列（镜头号/时间码/景别机位运镜/终极Seedance提示词）
      - total_seconds: 本切块累计总时长（秒）
      - global_atmosphere: 全局氛围画质文本（首个切块的展示给用户）
    """
    # ── 构建输入 ──
    chars_prefix = f"{global_chars}\n\n" if global_chars.strip() else ""
    
    if time_offset_seconds > 0:
        offset_min = int(time_offset_seconds // 60)
        offset_sec = int(time_offset_seconds % 60)
        time_hint = (
            f"⚠️ 本切块不是剧本开头！前序已累计 {offset_min} 分 {offset_sec} 秒。"
            f"请从 {offset_min:02d}:{offset_sec:02d} 开始分配时间码。\n\n"
        )
    else:
        time_hint = ""
    
    script_input = f"{time_hint}{chars_prefix}{chunk}"
    effective_style = style_tokens.strip() if style_tokens.strip() else "（自动模式：完全根据剧本内容推断视觉风格）"
    
    # ── 代码预提取：角色列表 ──
    char_injection = ""
    try:
        from shared.script_preprocessor import generate_character_list_for_storyboard
        character_list_text = generate_character_list_for_storyboard(script_input)
        if character_list_text and "检测到角色" not in character_list_text:
            char_injection = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【角色列表 — 代码已预提取】
{character_list_text}
注意：以上角色由代码自动提取，请直接使用。如有遗漏请自行补充。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    except Exception:
        pass
    
    # ── 代码预计算：体量分析 ──
    duration_guide = ""
    try:
        from shared.script_preprocessor import generate_duration_guide
        duration_guide = generate_duration_guide(script_input)
    except Exception:
        pass
    
    # ── 运行 CrewAI 2-Agent 工作流 ──
    llm = create_llm(engine_choice, api_base, api_key, model_name)
    agents = create_agents(llm)
    tasks = create_tasks(agents)
    crew = create_crew(agents, tasks)
    
    result = crew.kickoff(inputs={
        'script': script_input,
        'style': effective_style,
        'char_injection': char_injection,
        'duration_guide': duration_guide
    })
    
    # ── 提取 QA 输出 ──
    qa_raw = ""
    if hasattr(result, 'tasks_output') and len(result.tasks_output) >= 2:
        qa_raw = result.tasks_output[-1].raw
    elif hasattr(result, 'raw'):
        qa_raw = result.raw
    else:
        qa_raw = str(result)
    
    if not qa_raw:
        return [], 0.0, ""
    
    # ── 解析结构化 JSON ──
    shot_data = parse_structured_json(qa_raw)
    if not shot_data:
        # 回退：尝试从 Director 输出解析（如果 QA 输出不可解析）
        if hasattr(result, 'tasks_output') and len(result.tasks_output) >= 1:
            director_raw = result.tasks_output[0].raw
            shot_data = parse_structured_json(director_raw)
    
    if not shot_data:
        return [], 0.0, ""
    
    # ── 代码组装：结构化 JSON → 4列分镜数据 ──
    shot_list, total_seconds, global_atmosphere = assemble_seedance_prompt(
        shot_data, time_offset_seconds
    )
    
    # ── 代码后验证 ──
    _validate_min_content(shot_list)
    
    return shot_list, total_seconds, global_atmosphere


# ═════════════════════════════════════════════════════════════════════════════
# 完整流程入口（独立测试用）
# ═════════════════════════════════════════════════════════════════════════════

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
    """
    v3.0：完整流程入口（2-Agent + 代码组装）。
    返回: (display_data, csv_path, log_str)
    """
    try:
        if not script_content or not script_content.strip():
            return [], "错误：请输入剧本内容！", None
        
        resolved_api_key = api_key.strip() if api_key.strip() else os.environ.get("DEEPSEEK_API_KEY", "")
        effective_style = style_context.strip() if style_context.strip() else "（自动模式：完全根据剧本内容推断视觉风格）"
        
        log_capture = io.StringIO()
        print(f"\n{'='*60}")
        print(f"Seedance 2.0 结构参数化分镜工作流 v3.0")
        print(f"引擎: {engine_choice} | 模型: {model_name}")
        print(f"剧本长度: {len(script_content)} 字符")
        print(f"{'='*60}\n")
        
        # ── 代码预计算 ──
        duration_guide = ""
        try:
            from shared.script_preprocessor import generate_duration_guide
            duration_guide = generate_duration_guide(script_content)
        except Exception:
            pass
        
        llm = create_llm(engine_choice, api_base, resolved_api_key, model_name)
        agents = create_agents(llm)
        tasks_obj = create_tasks(agents)
        
        # ── 日志捕获 ──
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
                print("\n并行模式：Director → QA‖(后续代码组装)\n")
                
                director_crew = create_crew_director_only(agents, tasks_obj)
                director_result = director_crew.kickoff(inputs={
                    'script': script_content,
                    'style': effective_style,
                    'char_injection': '',
                    'duration_guide': duration_guide
                })
                
                qa_result = [None]
                def run_qa():
                    try:
                        qa_crew = create_crew_qa_only(agents, tasks_obj)
                        qa_result[0] = qa_crew.kickoff(inputs={
                            'script': script_content,
                            'style': effective_style,
                            'char_injection': '',
                            'duration_guide': duration_guide
                        })
                    except Exception as e:
                        print(f"QA Agent 异常: {e}")
                
                t_qa = threading.Thread(target=run_qa, name="crew-qa")
                t_qa.start()
                t_qa.join()
                
                # 合并结果
                from crewai import CrewOutput
                class ParallelCrewOutput:
                    def __init__(self, director, qa):
                        self.tasks_output = []
                        if director and hasattr(director, 'tasks_output'):
                            self.tasks_output.extend(director.tasks_output)
                        if qa and hasattr(qa, 'tasks_output'):
                            self.tasks_output.extend(qa.tasks_output)
                        self.raw = qa.raw if qa and hasattr(qa, 'raw') else str(qa or director)
                result = ParallelCrewOutput(director_result, qa_result[0])
            else:
                print("\n串行模式：Director → QA → 代码组装\n")
                crew = create_crew(agents, tasks_obj)
                result = crew.kickoff(inputs={
                    'script': script_content,
                    'style': effective_style,
                    'char_injection': '',
                    'duration_guide': duration_guide
                })
        finally:
            root_logger.removeHandler(capture_handler)
            root_logger.removeHandler(console_handler)
            capture_handler.close()
            console_handler.close()
        
        captured_log = log_capture.getvalue()
        log_capture.close()
        
        # ── 提取原始输出 ──
        qa_raw = ""
        if hasattr(result, 'tasks_output') and len(result.tasks_output) >= 2:
            qa_raw = result.tasks_output[-1].raw
        elif hasattr(result, 'tasks_output') and len(result.tasks_output) >= 1:
            qa_raw = result.tasks_output[-1].raw
        elif hasattr(result, 'raw'):
            qa_raw = result.raw
        else:
            qa_raw = str(result)
        
        # ── 解析 + 组装 ──
        shot_data = parse_structured_json(qa_raw)
        
        csv_path = output_file
        display_data = []
        
        if shot_data:
            shot_list, total_seconds, global_atmosphere = assemble_seedance_prompt(shot_data)
            _validate_min_content(shot_list)
            
            if shot_list:
                header = ["镜头号", "时间码", "景别机位运镜", "终极Seedance提示词"]
                rows = [[s[h] for h in header] for s in shot_list]
                
                with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(header)
                    writer.writerows(rows)
                
                total_min = int(total_seconds // 60)
                total_sec = int(total_seconds % 60)
                print(f"\n✓ Seedance 2.0 分镜矩阵已保存: {csv_path} ({len(rows)} 镜 / {total_min}分{total_sec}秒)")
                display_data = [header] + rows
            else:
                print("\n⚠️ 组装后无有效分镜数据")
        else:
            fallback_path = '分镜_原始输出.txt'
            with open(fallback_path, 'w', encoding='utf-8') as f:
                f.write(qa_raw)
            print(f"\n⚠️ JSON 解析失败，原始输出已保存: {fallback_path}")
        
        return display_data, csv_path if os.path.exists(csv_path) else None, captured_log
    
    except Exception as e:
        error_msg = f"错误:\n{type(e).__name__}: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return [], error_msg, None
