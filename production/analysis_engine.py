"""
production/analysis_engine.py — 制片流业务逻辑
==============================================

从 storyboard_local.py 提取的4大业务流核心函数：
1. run_analysis_mode    — 智能剧本分析（自动检测格式 → 情绪/结构双轨审核）
2. run_budget_mode      — 执行制片人预算审计（烧钱点 + AI降本）
3. extract_scenes       — 强迫症场记统筹（物理场景拆解）
4. extract_characters   — 人物视觉档案提取（分镜前处理）
5. extract_storyboard   — 简易分镜提取（非CrewAI方案）

格式感知分析引擎：
- 微短剧/短剧 → 情绪导向分析（多巴胺节奏 + 情绪爽感 + 台词冲击力）
- 中剧/长剧 → 结构导向分析（起承转合 + 逻辑自洽 + 人物弧光 + 反转伏笔）
- 电影长片 → 好莱坞工业分析（Save the Cat 15节拍 + Ghost/Lie/Flaw + McKee）

v0.3 代码预扫描优化：
所有"统计/搜索/计数/查找"任务改为 Python 正则+字符串算法执行，
LLM 仅基于预扫描结果做语义级定性判断。
"""

import streamlit as st

from production.llm_utils import call_llm_json
from shared.llm_config import detect_script_format_by_volume
from shared.script_preprocessor import (  # v0.3 代码预扫描
    generate_preflight_report,
    count_scenes_code,
    count_internal_external_scenes,
    scan_writing_violations,
    scan_dialogue_length,
    extract_characters as code_extract_characters,
    split_episodes,
    scan_emotion_indicators,
)


# =============================================================================
# 辅助：截断文本（保留最多 50000 字符）
# =============================================================================

def _truncate(text: str, max_chars: int = 50000) -> str:
    return text if len(text) < max_chars else text[:max_chars] + "\n...(节选，全文过长已截断至前50000字符)..."


# =============================================================================
# 业务流1：智能剧本分析（格式感知双轨引擎）
# =============================================================================

def run_analysis_mode(text, client, model_name, kwargs, format_category="auto"):
    """
    智能剧本分析：根据 format_category 分发到对应分析轨道。

    Args:
        text: 剧本文本
        client: OpenAI client
        model_name: 模型名称
        kwargs: LLM调用参数
        format_category: "auto" | "emotion" | "structure" | "movie"
    """
    eval_text = _truncate(text)

    if format_category == "auto":
        info = detect_script_format_by_volume(text)
        if info["category"] == "emotion":
            format_category = "emotion"
        elif info["display_name"] == "电影长片":
            format_category = "movie"
        else:
            format_category = "structure"

    if format_category == "emotion":
        return run_analysis_emotion_mode(eval_text, client, model_name, kwargs)
    elif format_category == "movie":
        return run_analysis_movie_mode(eval_text, client, model_name, kwargs)
    else:
        return run_analysis_structure_mode(eval_text, client, model_name, kwargs)


# -----------------------------------------------------------------------------
# 轨道A：情绪导向分析（微短剧 / 短剧）
# -----------------------------------------------------------------------------

def run_analysis_emotion_mode(text, client, model_name, kwargs):
    """
    情绪导向剧本医生：专为微短剧和短剧设计。
    核心审核标准：观众的情绪是否得到满足，而非绝对的逻辑正确。

    v0.3 优化：先执行代码层预扫描（违规检测/台词统计/情绪指标），
    将结构化报告注入 prompt，LLM 仅做语义级定性判断。
    """
    # v0.3：代码层预扫描
    preflight = generate_preflight_report(text, max_dialogue_chars=15)
    preflight_text = preflight.to_injection_text()

    sys_prompt = (
        "你是短视频/短剧领域的资深剧本医生，专精于'情绪价值'分析。"
        "你的审核标准与电影/长剧完全不同——微短剧和短剧的核心使命是："
        "**满足观众的情绪需求，而非追求绝对的逻辑正确。**\n\n"
        "【情绪优先审核原则】\n"
        "1. 情绪满足感 > 逻辑严密性\n"
        "2. 节奏紧凑 > 结构完整性\n"
        "3. 反转冲击力 > 伏笔回扣精度\n"
        "4. 角色魅力 > 角色弧光深度\n\n"
        "你严格禁止'直白的心理描写'，"
        "强制要求所有情感通过'潜台词和物理动作'传达。"
        "你的诊断犀利直接，一针见血，绝不八股。"
    )

    user_prompt = f"""
你是短视频/短剧领域的资深剧本医生，请对以下剧本进行情绪价值导向的专业诊断。

{preflight_text}

【任务一：多巴胺节奏审计】
逐集（或逐段）检查以下要素：
1. 情绪压迫点：开场是否有强有力的情绪刺激（被嘲讽/被打压/被误解/危机降临）
2. 多巴胺释放：被打压后是否迅速反击打脸（30秒内/合理时间内）
3. 钩子强度：结尾是否有吸引继续看的悬念（更大危机/身份反转/致命误解/关键证据）
4. 每集（段）爽感评级：弱/中/强/极强
（注意：代码已预扫描情绪关键词分布，请基于这些数据做定性判断，不要重复统计）

【任务二：整体情绪弧线评估】
1. 全剧情绪曲线是否递进（不能越来越平淡）
2. 大结局是否有最高潮（情绪峰值 > 前面所有集）
3. 是否存在"情绪塌陷"（连续多集平淡无爽点）
4. 角色魅力指数评估

【任务三：台词与动作冲击力】
1. 台词是否短促有力（微短剧每句<15字，短剧每句<20字）
2. 是否有高冲击物理动作（耳光/掀桌/摔门/冷笑/握拳）
3. 是否存在废话/水话/解释性台词

【任务四：写作红线审核（基于预扫描结果）】
代码层已经预扫描了以下违规模式并给出命中列表，你的任务：
1. 逐条确认命中项是否真的是违规（代码可能误判，需你做语义判断）
2. 判断是否遗漏了代码没找到的违规
3. 对确认的每个违规给出潜台词+物理动作重写方案
（不要再逐行扫描文本找违规！代码已经做了这件事。）

【任务五：绿灯会立项陈述】
Slogan / 受众画像与情绪价值 / 项目商业价值与立项风险

【任务六：广电/电影局红线雷达】
严格排雷，指出触线情节及合规修改建议。

【输出 JSON 格式】：
{{
    "dopamine_rhythm_audit": [{{"episode": "第1集", "emotion_crush": "描述情绪压迫点", "payoff": "描述反击打脸点", "hook": "描述结尾钩子", "satisfaction": "极强/强/中/弱", "verdict": "通过/需改进"}}],
    "emotion_arc_overview": {{
        "arc_description": "整体情绪弧线描述",
        "climax_episode": "最高潮集数",
        "weak_sections": ["平淡段落描述"],
        "overall_satisfaction": "评分或评价",
        "character_charm_index": "角色魅力评估"
    }},
    "dialogue_impact_check": [{{"original": "原句", "issue": "问题类型", "rewrite": "改写建议"}}],
    "writing_violations": [{{"location": "位置", "type": "心理描写/括号暗示/解释性台词", "original": "原文", "rewrite": "重写建议"}}],
    "greenlight_decision": {{ "slogan": "...", "target_audience_and_emotion": "...", "production_value_and_risk": "..." }},
    "censorship_risk": {{ "risk_level": "...", "sensitive_elements": [{{"element": "...", "risk": "...", "advice": "..."}}] }}
}}

【输入文本】：
{text}
"""
    return call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0)


# -----------------------------------------------------------------------------
# 轨道B：结构导向分析（中剧 / 长剧）
# -----------------------------------------------------------------------------

def run_analysis_structure_mode(text, client, model_name, kwargs):
    """
    结构导向剧本医生：专为中剧和长剧设计。
    核心审核标准：故事的起承转合、逻辑自洽、人物弧光、反转与伏笔。

    v0.3 优化：代码层预扫描违规+台词统计，LLM 做定性判断。
    """
    # v0.3：代码层预扫描
    preflight = generate_preflight_report(text, max_dialogue_chars=20)
    preflight_text = preflight.to_injection_text()

    sys_prompt = (
        "你是殿堂级剧本医生，深谙电视剧工业标准与长篇叙事结构。"
        "你精通起承转合的四段式结构、人物弧光理论（Ghost/Lie/Flaw）、"
        "反转伏笔设计、以及叙事逻辑自洽性检验。"
        "你的诊断极其犀利刻薄、一针见血，绝不放水、绝不八股。"
        "你严格禁止'直白的心理描写'，"
        "强制要求所有情感必须通过'潜台词和物理动作'传达。"
        "你对叙事逻辑漏洞零容忍——前后矛盾、人物降智、伏笔遗忘一律驳回。"
    )

    user_prompt = f"""
你是殿堂级剧本医生，请对以下剧本进行结构导向的工业级诊断。

{preflight_text}

【任务一：故事起承转合审计】
严格按起承转合四段式结构逐一检验：
1. 起（建置）：角色、世界观、核心冲突是否在合理篇幅内清晰建立
2. 承（发展）：冲突是否层层递进升级，而非原地踏步
3. 转（高潮/反转）：是否有足够强有力的转折和反转，反转是否意外但合理
4. 合（解决）：结局是否有力且留有余味，不能烂尾或虎头蛇尾
5. 故事逻辑自洽检验：是否存在逻辑漏洞、前后矛盾、人物行为动机不一致

【任务二：人物弧光诊断（Ghost / Lie / Flaw）】
逐个人物检查：
1. Ghost（前史创伤）2. Lie（角色相信的谎言）3. Flaw（性格缺陷）
4. Want vs Need 5. 弧光检验
→ 纸片人直接点名批判

【任务三：反转与伏笔检验】
1. 关键反转是否有效（意外但合理，不能机械降神）
2. 伏笔是否埋设自然（不能突兀）
3. 每个伏笔是否有回扣（埋而不揭是叙事欺诈）
4. 是否存在"机械降神"（突然出现的巧合解决问题）

【任务四：写作红线审核（基于预扫描结果）】
代码层已预扫描违规命中列表，你的任务：
1. 确认命中项是否为真违规
2. 检查是否有遗漏
3. 对确认的违规给出潜台词+物理动作重写方案

【任务五：结构痛点与节奏诊断】
1. 节奏诊断：是否存在"塌陷段"（连续多集无有效推进）
2. 废场景检验：哪些场景对故事无实质推动
3. 高潮强度评估

【任务六：绿灯会立项陈述】
Slogan / 受众画像与情绪价值 / 项目商业价值与立项风险

【任务七：广电/电影局红线雷达】
严格排雷，指出触线情节及合规修改建议。

【输出 JSON 格式】：
{{
    "story_structure_audit": {{
        "opening": {{"description": "起-建置评估", "verdict": "优秀/合格/需改进"}},
        "development": {{"description": "承-发展评估", "verdict": "优秀/合格/需改进"}},
        "climax": {{"description": "转-高潮评估", "verdict": "优秀/合格/需改进"}},
        "resolution": {{"description": "合-解决评估", "verdict": "优秀/合格/需改进"}},
        "logic_consistency": {{"overall": "整体逻辑评价", "plot_holes": ["逻辑漏洞描述"]}}
    }},
    "character_arc_diagnosis": [{{"character": "...", "ghost": "...", "lie": "...", "flaw": "...", "want": "...", "need": "...", "arc_verdict": "..."}}],
    "twist_and_foreshadowing": {{
        "key_twists": [{{"twist": "反转描述", "effectiveness": "高/中/低", "issue": "问题描述（如有）"}}],
        "foreshadowing": [{{"planted": "伏笔描述", "payoff": "回扣描述", "verdict": "自然/突兀/未回扣"}}],
        "deus_ex_machina_risk": "是否存在机械降神风险"
    }},
    "psychological_description_crime_scene": [{{"crime_location": "...", "original_text": "...", "crime_type": "...", "rewrite_subtext": "...", "rewrite_physical_action": "..."}}],
    "structure_flaws": "结构痛点总结",
    "greenlight_decision": {{ "slogan": "...", "target_audience_and_emotion": "...", "production_value_and_risk": "..." }},
    "censorship_risk": {{ "risk_level": "...", "sensitive_elements": [{{"element": "...", "risk": "...", "advice": "..."}}] }}
}}

【输入文本】：
{text}
"""
    return call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0)


# -----------------------------------------------------------------------------
# 轨道C：电影工业分析（电影长片 — Save the Cat + Ghost/Lie/Flaw + McKee）
# -----------------------------------------------------------------------------

def run_analysis_movie_mode(text, client, model_name, kwargs):
    """
    电影长片工业分析：Save the Cat 15 节拍 + Ghost/Lie/Flaw + McKee 价值审计。
    最严格的审核标准，要求三幕结构对齐、场景价值翻转、节拍精确映射。

    v0.3 优化：代码层预扫描违规+台词统计，LLM 做定性判断。
    """
    # v0.3：代码层预扫描
    preflight = generate_preflight_report(text, max_dialogue_chars=25)
    preflight_text = preflight.to_injection_text()

    sys_prompt = (
        "你是殿堂级好莱坞剧本医生，深谙人物弧光理论体系"
        "（Ghost 前史创伤 / Lie 角色相信的谎言 / Flaw 性格缺陷）"
        "与 Save the Cat 15 节拍工业结构。"
        "你的诊断极其犀利刻薄、一针见血，绝不放水、绝不八股。"
        "你严格禁止'直白的心理描写'（如'他意识到…'、'她感到…'、括号心理暗示），"
        "强制要求所有情感必须通过'潜台词和物理动作'传达。"
        "你精通 McKee 价值转变理论——每个场景结束时核心价值必须翻转。"
    )

    user_prompt = f"""
你是好莱坞剧本医生，请对以下电影长片剧本进行工业级诊断。

{preflight_text}

【任务一：人物弧光诊断（Ghost / Lie / Flaw 强制核验）】
逐个人物检查：
1. Ghost（前史创伤）2. Lie（角色相信的谎言）3. Flaw（性格缺陷）
4. Want vs Need 5. 弧光检验
→ 若人物是纸片人，直接点名批判。

【任务二：Save the Cat 15 节拍强制映射】
严格按以下 15 个节拍顺序逐一映射，不得跳拍：
1. Opening Image  2. Theme Stated  3. Set-Up  4. Catalyst  5. Debate
6. Break into Two  7. B Story  8. Fun and Games  9. Midpoint
10. Bad Guys Close In  11. All Is Lost  12. Dark Night of the Soul
13. Break into Three  14. Finale  15. Final Image
每个节拍输出：标准功能 / 剧本实际（❌若缺失）/ 理想示范 / 节奏诊断

【任务三：写作红线审核（基于预扫描结果）】
代码层已预扫描违规命中列表，你的任务：确认+补漏+给出重写方案。

【任务四：结构痛点与节奏诊断】
1. 节奏致命伤  2. 未发生价值转变的废场景（McKee检验）  3. 高潮是否足够

【任务五：绿灯会立项陈述】
Slogan / 受众画像与情绪价值 / 项目商业价值与立项风险

【任务六：广电/电影局红线雷达】
严格排雷，指出触线情节及合规修改建议。

【输出 JSON 格式】：
{{
    "character_arc_diagnosis": [{{"character": "...", "ghost": "...", "lie": "...", "flaw": "...", "want": "...", "need": "...", "arc_verdict": "..."}}],
    "beat_mapping_sheet": [{{"beat_number": 1, "beat_name": "...", "standard_function": "...", "actual_plot": "...", "ideal_plot_reference": "...", "rhythm_diagnosis": "..."}}],
    "psychological_description_crime_scene": [{{"crime_location": "...", "original_text": "...", "crime_type": "...", "rewrite_subtext": "...", "rewrite_physical_action": "..."}}],
    "mckee_value_audit": [{{"scene": "...", "value_at_start": "...", "value_at_end": "...", "verdict": "..."}}],
    "greenlight_decision": {{ "slogan": "...", "target_audience_and_emotion": "...", "production_value_and_risk": "..." }},
    "structure_flaws": "...",
    "censorship_risk": {{ "risk_level": "...", "sensitive_elements": [{{"element": "...", "risk": "...", "advice": "..."}}] }}
}}

【输入文本】：
{text}
"""
    return call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0)


# =============================================================================
# 业务流2：预算审计
# =============================================================================

def run_budget_mode(text, client, model_name, kwargs):
    """执行制片人预算审计：周期精算 + 烧钱点 + AI降本替代

    v0.3 优化：场景数量由代码层预统计注入，不再让 LLM 估算。
    """
    eval_text = _truncate(text)

    # v0.3：代码预统计场景
    total_scenes = count_scenes_code(text)
    internal, external = count_internal_external_scenes(text)
    scene_stats = (
        f"【代码预统计】共 {total_scenes} 个场景（内景{internal}/外景{external}），"
        f"请基于此数据直接分析，无需重复统计场景数。\n\n"
    ) if total_scenes > 0 else ""

    sys_prompt = (
        "你是国内最精明刻薄的执行制片人，人称' budgeting 阎王'。"
        "你极其精通线下制作成本（置景、道具、群演、特效、器材、场地），"
        "且深谙 AI 视频生成技术（Sora、Runway、Pika、Kling、可灵、即梦等）的降本替代方案。"
        "你的风格：刻薄、不留情面，看到烧钱内容会直接开骂，"
        "但给出的 AI 降本方案极其专业可行。"
        "【绝对约束】：不计算演员和导演等线上价格！只评估线下制作成本。"
    )

    user_prompt = f"""
你是精打细算的执行制片人，请对以下剧本进行逐行预算审计。

{scene_stats}【任务一：周期精算】预估拍摄天数 + 推演依据 + 雨戏/夜戏/大场面标注
【任务二：烧钱点逐行抓捕】大场面/特殊道具/群演/特殊拍摄，逐条刻薄点评
【任务三：AI 视频降本替代方案】远景/空镜/不可能实拍/群演密集型，评估替代可行性和推荐工具
【任务四：线下制作成本总结】体量定调/成本区间/最高风险场次

【输出 JSON 格式】：
{{
    "shooting_schedule_audit": {{"estimated_days": "...", "schedule_verdict": "...", "special_risk_shots": ["..."]}},
    "money_burning_scenes": [{{"scene": "...", "burn_type": "...", "specific_items": ["..."], "cost_estimate": "...", "producer_comment": "..."}}],
    "ai_replacement_strategy": [{{"scene_or_shot": "...", "replacement_feasibility": "高/中/低", "recommended_ai_tool": "...", "cost_saving_analysis": "...", "limitation_warning": "..."}}],
    "production_scale_verdict": {{"scale": "...", "offline_cost_range": "...", "highest_risk_scene": "..."}}
}}

【输入文本】：
{eval_text}
"""
    return call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0)


# =============================================================================
# 业务流2.5：专业制片主任预算（新增）
# =============================================================================

def run_pro_budget_global(text, client, model_name, kwargs):
    """专业制片主任：全局制片参数分析（剧组规模/日均费率/总天数）

    v0.3 优化：场景数量/内景外景比例由代码预统计注入 prompt，
    不再让 LLM '估算'场景总量。
    """
    eval_text = _truncate(text)

    # v0.3：代码层预统计场景数据
    total_scenes = count_scenes_code(text)
    internal, external = count_internal_external_scenes(text)
    scene_stats_text = (
        f"【代码预统计】共检测到 {total_scenes} 个场景标记"
        f"（内景 {internal} / 外景 {external}），"
        f"请基于此数据推算合理拍摄周期，无需重复统计。\n"
    ) if total_scenes > 0 else ""

    sys_prompt = (
        "你是中国影视行业资深制片主任，拥有20年以上剧组管理经验。"
        "你精通中国影视行业各级别制片的预算编制规范，"
        "熟悉从微短剧到院线电影的全部成本结构和人员编制。"
        "\n\n【你的专业领域】"
        "\n1. 剧组人员编制标准（导演组/摄影组/灯光组/美术组/录音组/制片组/演员组）"
        "\n2. 专业影视器材租赁市场行情（ARRI/RED/Sony电影机+蔡司/库克镜头+各类灯光）"
        "\n3. 中国境内主要影视拍摄城市及场地资源"
        "\n4. 群演/特约演员/角色演员的日薪标准"
        "\n5. 剧组伙食、交通、住宿的行规标准"
        "\n6. 置景、道具、服装、化妆、枪械（如有）的预算编制"
        "\n\n【中国影视行业2024-2025年参考基准】"
        "\n- 微短剧剧组：15-30人，日均制作费3-8万元"
        "\n- 短剧剧组：30-60人，日均制作费5-18万元"
        "\n- 中剧/网剧剧组：60-120人，日均制作费15-40万元"
        "\n- 电影剧组：100-250人，日均制作费30-120万元"
        "\n- 群演日薪：100-350元/人（普通）/ 500-1500元/人（有台词特约）"
        "\n- 餐标：早餐15-25元/人，午/晚餐40-80元/人/天"
        "\n- 工作车（考斯特中巴）：800-2000元/天"
        "\n- 住宿（剧组标准）：120-350元/人/晚"
        "\n- 轨道车/摇臂租赁：1000-3500元/天"
        "\n- 航拍（含飞手+设备）：3000-8000元/天"
        "\n- 发电车：2000-5000元/天"
        "\n- 化妆/服装师：500-1500元/天/人"
        "\n\n【绝对约束】"
        "\n- 费用以人民币(元)为单位，给出合理区间"
        "\n- 保持专业、务实、可执行的语调"
        "\n- 必须根据剧本实际内容推算，不得照搬参考基准不加以判断"
    )

    user_prompt = f"""
请对以下剧本进行全局制片参数分析，确定整体制片规格。

{scene_stats_text}
【任务一：确定制作规格】
根据剧本体量、场景数量、人物规模、特效需求，确定剧组规模和制作体量。

【任务二：核定日均基准费用】
给出各工种组的日均费用参考标准（按你确定的剧组规模给出对应区间）。

【任务三：预估总拍摄天数】
基于场景总量、场景复杂度、内外景比例、转场需求，推算合理的拍摄周期。
必须说明推算依据（如：共X场戏，内景Y场/外景Z场，日均完成A场，预计需B天）。

【任务四：特殊风险识别】
列出本剧拍摄中需要特别关注的制片风险点（如：大量夜戏、雨戏、爆破、高空作业、动物演员等）。

【输出 JSON 格式】：
{{
    "production_overview": {{
        "production_type": "微短剧/短剧/中剧/长剧/电影长片",
        "total_shooting_days": 预估总拍摄天数(int),
        "shooting_days_basis": "推算依据说明（200字内）",
        "crew_scale": "小型(20人内)/中型(20-60人)/大型(60-150人)/超大型(150人+)",
        "total_crew_count": 预估总剧组人数(int),
        "standard_daily_crew_cost": {{
            "director_team": "导演组日均费用区间（元）",
            "camera_team": "摄影组日均费用区间（元）",
            "lighting_team": "灯光组日均费用区间（元）",
            "art_team": "美术组日均费用区间（元）",
            "sound_team": "录音组日均费用区间（元）",
            "production_team": "制片组+场务日均费用区间（元）",
            "makeup_costume_team": "化妆服装组日均费用区间（元）"
        }},
        "standard_daily_rates": {{
            "meal_per_person_daily": "每人每天餐费标准（元）",
            "vehicle_daily": "工作车日均费用区间（元）",
            "hotel_per_person_night": "住宿每人每晚费用区间（元）",
            "location_rental_range": "场地费区间参考（元/天）"
        }},
        "estimated_total_budget_range": "全片线下制作总成本估算区间（元，如'80-150万'）",
        "special_risk_notes": ["风险点1", "风险点2"]
    }}
}}

【输入文本】（已截断至50000字）
{eval_text}
"""
    return call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0)


def run_pro_budget_scene(chunk_text, global_params_json, client, model_name, kwargs):
    """专业制片主任：逐场景详细预算（费用分项+拍摄难度+场地推荐）"""
    sys_prompt = (
        "你是中国影视行业资深制片主任，正在为导演和制片人编制可执行的专业制片预算。"
        "\n\n【你的任务】"
        "\n对输入剧本片段中的每个场景（按物理空间切分），编制详细预算明细。"
        "\n\n【场景预算编制规则】"
        "\n1. 内景成本通常低于外景（外景涉及转场/天气/发电车等附加成本）"
        "\n2. 夜戏成本通常比日景高30-50%（灯光增强+夜间工时补贴+夜宵）"
        "\n3. 雨戏/雪戏需额外计算：人工降雨设备、防水保护、演员保暖、服装烘干"
        "\n4. 群演密集型场景（>20人）需单独列出群演费用"
        "\n5. 特殊器材（航拍/摇臂/轨道/斯坦尼康/水下摄影）需单独列出"
        "\n6. 道具/置景费用按场景复杂度分级：简（无特殊）/中（少量特殊道具）/繁（大量置景）"
        "\n\n【拍摄难度等级定义】"
        "\n- 易：内景日景，1-2个演员，无特殊道具/器材，1-4小时可完成"
        "\n- 中：内景夜景 或 外景日景，3-8个演员，少量特殊道具，4-8小时"
        "\n- 难：外景夜景/雨戏/雪戏/动作戏，多机位，8-14小时，特殊器材"
        "\n- 极高：大场面/爆破/高空/水下/大量群演(50+)/恶劣天气，需分天拍摄"
        "\n\n【中国主要影视拍摄基地参考】"
        "\n- 横店影视城（浙江东阳）：古装/年代剧/现代剧首选，场景最全"
        "\n- 象山影视城（浙江宁波）：海上场景/民国/武侠"
        "\n- 无锡影视基地（江苏）：民国/近现代/水浒城"
        "\n- 涿州影视基地（河北）：古装/大型宫廷场景"
        "\n- 青岛东方影都（山东）：科幻/现代/水下摄影棚/顶级棚拍"
        "\n- 上海车墩影视基地：民国/老上海/现代都市"
        "\n- 北京怀柔影视基地：各类场景，靠近后期公司"
        "\n- 厦门：文艺/现代都市/海滨"
        "\n- 重庆：赛博朋克夜景/山城立交/现代都市"
        "\n- 成都/昆明：市井生活/文艺/亚热带"
        "\n- 丽江/大理：风景/民族/文艺"
        "\n- 敦煌/张掖（甘肃）：大漠/丹霞/古装外景"
        "\n- 呼和浩特/赤峰（内蒙古）：草原/古装大场面"
        "\n\n【绝对约束】"
        "\n- 每个场景必须给出完整的费用分项，不能为空"
        "\n- 场地推荐必须具体到城市和区域，不能只写'横店'而要写'浙江东阳横店影视城'"
        "\n- 所有费用以人民币(元)为单位"
        "\n- 输出必须是合法JSON，禁止在JSON字符串值内使用未转义的双引号"
    )

    # 将全局参数摘要注入 prompt，保持场景预算与全局参数一致
    overview = global_params_json.get("production_overview", {})
    overview_summary = (
        f"【全局制片参数参考】\n"
        f"- 制作规格：{overview.get('production_type', 'N/A')}\n"
        f"- 剧组规模：{overview.get('crew_scale', 'N/A')}（约{overview.get('total_crew_count', 'N/A')}人）\n"
        f"- 预估总拍摄天数：{overview.get('total_shooting_days', 'N/A')} 天\n"
        f"- 日均餐标：{overview.get('standard_daily_rates', {}).get('meal_per_person_daily', 'N/A')}\n"
        f"- 工作车日租：{overview.get('standard_daily_rates', {}).get('vehicle_daily', 'N/A')}\n"
    )

    user_prompt = f"""
{overview_summary}
请对以下剧本片段中的每个场景进行详细预算编制。

【任务一：逐场景费用明细】
对每个独立场景（按物理空间切分）给出以下分项费用估算：
- 人员费：该场景涉及的各组人员费用（按场次人数折算）
- 器材费：该场景所需摄影/灯光/录音器材的日租折算
- 车辆费：该场景所需工作车/发电车/道具车的费用
- 伙食费：该场景拍摄时长对应的餐费（含夜宵如适用）
- 场地费：该场景所需拍摄场地的日租或许可费
- 置景费：该场景所需的布景/搭建/改造费用
- 道具费：该场景所需特殊道具的租赁或制作费用
- 其他费：服装/化妆/特殊处理（如人工降雨）等未涵盖项

【任务二：拍摄难度评估】
标注每个场景的拍摄难度等级（易/中/难/极高）和具体原因。

【任务三：场地推荐】
根据每个场景的描述，推荐中国境内最适合拍摄的城市和具体场地，并说明理由。

【输出 JSON 格式】：
{{
    "scene_budgets": [
        {{
            "scene_number": 场次编号(int),
            "scene_name": "场景名称（物理空间）",
            "int_ext": "内景/外景",
            "day_night": "日景/夜景",
            "episode": "所属集数（如'第1集'，如无集数概念则填'全片'）",
            "difficulty_level": "易/中/难/极高",
            "difficulty_reason": "难度原因说明（100字内）",
            "estimated_shooting_hours": 预估拍摄小时数(float),
            "required_cast_count": 主要演员人数(int),
            "required_extras_count": 群演人数(int, 无则为0),
            "special_equipment": ["器材1", "器材2"],
            "special_vehicles": ["车辆类型1（如发电车）"],
            "set_construction": "置景描述（无则为'无特殊置景'）",
            "set_construction_cost": "置景费用估算（元）",
            "props_special": "特殊道具说明（无则为'无'）",
            "location_type": "办公室/公寓/街道/商场/医院/学校/户外自然/影棚/古装场景/其他",
            "recommended_locations": [
                {{
                    "city": "推荐城市（如'浙江东阳'）",
                    "specific_area": "具体场地（如'横店影视城-明清宫苑'）",
                    "reason": "推荐理由（80字内）",
                    "estimated_daily_rent": "场地日租参考（元/天）",
                    "similar_productions": "类似作品参考"
                }}
            ],
            "scene_cost_breakdown": {{
                "crew_cost": "人员费用（元）",
                "equipment_cost": "器材费用（元）",
                "vehicle_cost": "车辆费用（元）",
                "meal_cost": "伙食费用（元）",
                "location_cost": "场地费用（元）",
                "set_cost": "置景费用（元）",
                "props_cost": "道具费用（元）",
                "other_cost": "其他费用（元）",
                "total_scene_cost": "该场总费用（元）"
            }},
            "producer_notes": "制片主任备注（拍摄注意事项，100字内）"
        }}
    ]
}}

【输入文本】：
{chunk_text}
"""
    result = call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.3)
    return result.get("scene_budgets", [])


# =============================================================================
# 业务流3：场景拆解
# =============================================================================

def extract_scenes(chunk_text, client, model_name, kwargs):
    """强迫症场记统筹：物理空间场景解构"""
    sys_prompt = (
        "你是拥有强迫症的资深场记统筹，绰号'物理空间疯子'。"
        "你没有任何情感，不参与剧情讨论，只认物理空间逻辑。"
        "1. 按物理空间转换或时间跳跃切分场次。"
        "2. 每场必须标注：场次编号、内外景、日/夜。"
        "3. 禁止概括剧情。"
        "4. 强制提取每个物理实体道具和特殊服装要求。"
    )

    user_prompt = f"""
你是强迫症场记统筹，请对下文进行物理空间解构。

【绝对规则】：
- 按物理空间变化分场
- 每场必须输出：场次编号、场景名称、内外景、日/夜
- 禁止写"内容概要"或"剧情描述"
- 必须罗列该场景中每一个可以被摄影机拍到的物理实体道具
- 必须标注特殊服装要求

【输出 JSON 格式】：
{{
    "scene_list": [
        {{"场景名称": "...", "内外景": "内/外", "日夜": "日/夜", "出场人物": "...", "物理实体道具清单": ["..."], "特殊服装要求": "..."}}
    ]
}}

文本：
{chunk_text}
"""
    result = call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0)
    return result.get("scene_list", [])


# =============================================================================
# 业务流4辅助：人物视觉档案提取
# =============================================================================

def extract_characters(text, client, model_name, kwargs):
    """全篇提取人物小传与视觉档案库"""
    eval_text = text if len(text) < 50000 else text[:50000]

    sys_prompt = "你是资深的影视文学策划。"
    user_prompt = f"""
    通读提取【所有】有台词的角色，编写人物小传及生图提示词。
    【输出JSON格式】：
    {{ "global_characters": [{{"name": "...", "bio": "小传", "visual_prompt": "特征"}}] }}
    文本：{eval_text}
    """
    return call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.1).get("global_characters", [])


def extract_storyboard(chunk_text, global_chars, client, model_name, kwargs):
    """简易分镜提取（非CrewAI方案，备用）"""
    import json
    chars_str = json.dumps(global_chars, ensure_ascii=False) if global_chars else "无"
    sys_prompt = "你是一位资深分镜导演和生图提示词专家。"
    user_prompt = f"""
    极高密度切分连续镜头(5-15个/场)。英文提示词强制挂载人物外貌。
    人物档案：{chars_str}
    【输出JSON格式】：
    {{ "storyboard": [{{"景别": "...", "画面描述": "...", "中文提示词": "...", "Nano Banana 2 英文提示词": "..."}}] }}
    文本：{chunk_text}
    """
    return call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.35).get("storyboard", [])
