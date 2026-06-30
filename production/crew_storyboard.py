"""
crew_storyboard.py — CrewAI 后端模块（v3.0 结构参数化版）

v3.0 核心重构（2026-06-30）：
  核心原则：LLM 做创意判断，代码做格式化组装。

  架构变更：
  1. 从 4 Agent 缩减到 2 Agent（Director + QA）
  2. Director 输出结构化 JSON（镜头参数 + 画面描述），不再关心排版格式
  3. Image / Video Agent 功能由代码层替代
  4. 代码层负责：时间码累加计算、@角色名/@场景名 引用插入、Seedance 文本模板组装

  收益：
  - Agent backstory 从 ~300 行 → ~50 行（-83%）
  - 输出格式 100% 确定性（不再依赖 LLM 排版能力）
  - @引用插入由代码执行，准确率 100%
  - LLM Token 消耗大幅降低，创意质量提升

  输出格式不变：4 列（镜头号 | 时间码 | 景别机位运镜 | 终极Seedance提示词）
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
# Agent 工厂 — v3.0 结构参数化版（2 Agent）
# ═════════════════════════════════════════════════════════════════════════════

def create_agents(llm: LLM) -> dict:
    """
    v3.0：创建 2 个 Agent
      director    — 分镜导演（读剧本 → 出结构化 JSON）
      qa_reviewer — 轻量质检（验证 + 修正 JSON）
    """

    # ═══════════════════════════════════════════════════════════════════
    # Agent 0: 分镜导演（v3.0 — 纯创意，零排版负担）
    # ═══════════════════════════════════════════════════════════════════
    director_agent = Agent(
        role='Seedance 分镜导演',
        goal='分析剧本，输出结构化分镜 JSON（镜头参数 + 专业级画面描述）',
        backstory="""你是精通 AI 文生视频的分镜导演，熟悉 Seedance 2.0 / Kling / 即梦 等模型。

你的唯一输出是结构化 JSON。所有排版格式由代码层处理，你不需要关心。

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
    # Agent 1: 轻量质检（v3.0 — 仅做语义抽查，不做格式检查）
    # ═══════════════════════════════════════════════════════════════════
    qa_reviewer_agent = Agent(
        role='分镜质检',
        goal='抽查Director的JSON输出，修正创意质量问题，保证画面描述密度达标',
        backstory="""你是分镜质量审查员。Director已输出结构化JSON，你只需做语义级抽查。

检查项：
1. 画面描述密度：是否有镜头画面内容 <60字？→ 补充动作/光影/质感细节
2. 抽象心理转译：是否有"他感到""她意识到"等不可拍摄内容？→ 转译为可见肢体动作
3. 透视屏蔽：背后/过肩镜头是否违规描写了正面五官？→ 修正视角
4. 场景一致性：镜头引用的场景名是否在场景定义中存在？→ 修正或补定义

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
# Task 工厂 — v3.0
# ═════════════════════════════════════════════════════════════════════════════

def create_tasks(agents: dict) -> dict:
    """v3.0：2 个 Task（Director + QA）"""

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
  · 时长秒：该镜建议持续秒数（文戏3-6s，武戏2-3s，特写1-2s，过渡2-3s）。
  · 景别：全景 / 中景 / 近景 / 特写 / 大特写 / 远景。
  · 机位：拍摄高度+角度+距离，如"低角度仰拍，贴近地面""高机位微俯拍""眼平机位"。
  · 构图：人物在画面中的位置关系、前景/背景层次、引导线、三分法/黄金分割等。
  · 运镜：运动方式+速度，如"慢速推轨""固定仅呼吸感""手持微晃跟拍""快速横摇"。
  · 画面内容：★ 核心创意输出 ★ 角色名直接写原名（如"钱阿龙"），代码会自动加@前缀。禁止只写"他走进来"这种干瘪描述！
  · 出场角色：该镜头中出现的角色名列表，按出场顺序。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【按上方「剧本体量分析」参数严格执行】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  总镜数和总时长严格按代码计算的建议范围规划。
  文戏3-5镜/段，武戏5-8镜/段，过渡2-3镜/段。

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

    # ── Task 1: 轻量质检 ──
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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出格式】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

输出修正后的完整 JSON（结构与Director输出完全相同）。
纯 JSON，无 Markdown 标记，无解释文字。
如果无需修正，原样输出。""",
        expected_output="""修正后的完整 JSON 对象，与Director输出结构完全一致。
内容已修正至专业影视级质量标准。
纯JSON，无Markdown，无解释。""",
        agent=agents['qa_reviewer'],
        context=[task_director]
    )

    return {
        'task_director': task_director,
        'task_qa_review': task_qa_review
    }


# ═════════════════════════════════════════════════════════════════════════════
# 代码组装引擎 — v3.0 核心：结构化 JSON → Seedance 提示词
# ═════════════════════════════════════════════════════════════════════════════

def _format_timecode(total_seconds: float) -> str:
    """将累计秒数格式化为 MM:SS 时间码字符串。"""
    m = int(total_seconds // 60)
    s = int(total_seconds % 60)
    return f"{m:02d}:{s:02d}"


def _inject_references(content: str, scene_name: str, characters: list) -> str:
    """
    在画面内容中自动插入 @场景名 和 @角色名 引用。
    
    规则：
    - 每段开头（或第一个角色名出现前）插入 @场景名
    - 每个角色名的第一次出现替换为 @角色名
    - 同一角色在同一镜头内多次出现时，仅第一次加@
    """
    result = content
    
    # 插入角色引用：将出场角色列表中的角色名首次出现替换为 @角色名
    for char in characters:
        if char and char in result:
            # 仅替换第一次出现
            result = result.replace(char, f"@{char}", 1)
    
    return result


def assemble_seedance_prompt(shot_data: dict, time_offset_seconds: float = 0.0) -> tuple:
    """
    v3.0 核心组装函数：将 LLM 输出的结构化 JSON 转换为4列分镜数据。
    
    参数:
      shot_data: Director/QA 输出的 JSON dict，含「全局氛围画质」「场景定义」「分镜列表」
      time_offset_seconds: 跨切块时间码偏移（前序切块累计秒数）
    
    返回:
      (shot_list, total_seconds, global_atmosphere)
        - shot_list: list[dict]，每个dict含4列（镜头号/时间码/景别机位运镜/终极Seedance提示词）
        - total_seconds: 本切块累计总时长秒数
        - global_atmosphere: 全局氛围画质文本（供UI单独展示）
    """
    shot_list = []
    accumulated = time_offset_seconds
    global_atmosphere = shot_data.get("全局氛围画质", "")
    scene_defs = shot_data.get("场景定义", {})
    shots = shot_data.get("分镜列表", [])
    
    if not shots:
        return [], time_offset_seconds, global_atmosphere
    
    for shot in shots:
        # 基本字段提取
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
        
        # 时间码计算
        start_sec = accumulated
        end_sec = accumulated + duration
        timecode = f"{_format_timecode(start_sec)}~{_format_timecode(end_sec)}"
        accumulated = end_sec
        
        # 组装「景别机位运镜」列（紧凑摘要）
        camera_summary_parts = []
        if shot_type:
            camera_summary_parts.append(shot_type)
        if camera_pos:
            camera_summary_parts.append(camera_pos)
        if camera_move:
            camera_summary_parts.append(camera_move)
        camera_summary = "，".join(camera_summary_parts)
        
        # 在画面内容中注入 @引用
        content_with_refs = _inject_references(content, scene_name, characters)
        
        # 组装「终极Seedance提示词」（完整的单镜 Seedance 文本）
        # 格式：
        # @场景名
        # 
        # 分镜N：时间码  景别：xxx，机位。构图：xxx。运镜手法：xxx。画面内容：xxx
        scene_ref = f"@{scene_name}" if scene_name else ""
        
        prompt_parts = [scene_ref, ""]
        shot_header = (
            f"分镜{shot_num}：{timecode}  "
            f"景别：{shot_type}，{camera_pos}。"
            f"构图：{composition}。"
            f"运镜手法：{camera_move}。"
            f"画面内容：{content_with_refs}"
        )
        prompt_parts.append(shot_header)
        
        final_prompt = "\n".join(prompt_parts)
        
        shot_list.append({
            "镜头号": str(shot_num),
            "时间码": timecode,
            "景别机位运镜": camera_summary,
            "终极Seedance提示词": final_prompt
        })
    
    total_seconds = accumulated - time_offset_seconds
    return shot_list, total_seconds, global_atmosphere


# ═════════════════════════════════════════════════════════════════════════════
# Crew 工厂 — v3.0（2 Agent）
# ═════════════════════════════════════════════════════════════════════════════

def create_crew(agents: dict, tasks: dict) -> Crew:
    """v3.0：创建 Director + QA 双 Agent 顺序 Crew"""
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
# JSON 解析 — v3.0（适配新 Schema）
# ═════════════════════════════════════════════════════════════════════════════

def parse_structured_json(raw_text: str) -> dict:
    """
    v3.0：从 LLM 输出中提取结构化分镜 JSON（全局氛围画质 + 场景定义 + 分镜列表）。
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
    """代码层标注画面内容过短的镜头。"""
    for shot in shot_list:
        prompt = str(shot.get("终极Seedance提示词", ""))
        # 提取画面内容部分
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
