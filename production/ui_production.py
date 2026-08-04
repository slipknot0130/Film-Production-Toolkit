"""
production/ui_production.py — 制片流UI渲染
==========================================

从 storyboard_local.py 提取的4个制片流UI渲染函数：
1. render_analysis          — 智能剧本分析（格式感知双轨引擎）
2. render_budget            — 预算审计 + 专业制片主任预算（新增）
3. render_scene_breakdown   — 场景拆解
4. render_storyboard        — 分镜工作台

每个函数接收 uploaded_file 和可选参数，独立渲染完整的工作流UI。
"""

import streamlit as st
import pandas as pd
import io
import json

from production.llm_utils import (
    call_llm_json,
    split_script_smart,
    read_uploaded_file,
    get_llm_client,
    get_llm_kwargs,
    ensure_ollama_model,
)
from production.analysis_engine import (
    run_analysis_mode,
    run_budget_mode,
    run_pro_budget_global,
    run_pro_budget_scene,
    extract_scenes,
    extract_characters,
)
from shared.llm_config import get_default_model, detect_script_format_by_volume
from shared.script_preprocessor import (
    SAFE_CAP as _SAFE_CAP,
    TARGET_CHARS_PER_SHOT as _CHARS_PER_SHOT,
    DEFAULT_AVG_SHOT_SEC as _AVG_SHOT_SEC,
    compute_dynamic_safe_cap,
    compute_adaptive_chunk_size,
    compute_realistic_estimate,
    plan_storyboard_chunks,
    force_min_chunks,
)


# =============================================================================
# 辅助：获取当前LLM参数（制片流使用）
# =============================================================================

def _get_production_llm():
    """获取当前配置的LLM client, model_name, kwargs"""
    provider = st.session_state.llm_provider
    base_url = st.session_state.base_url
    api_key = "ollama" if provider == "本地 Ollama" else (
        st.session_state.api_key or "sk-local"
    )
    model_name = st.session_state.get("selected_model", get_default_model(provider))
    client = get_llm_client(provider, base_url, api_key)
    kwargs = get_llm_kwargs(provider)
    return provider, client, model_name, kwargs


# =============================================================================
# 格式类别中文标签
# =============================================================================

_FORMAT_LABELS = {
    "emotion": "情绪导向审核（微短剧/短剧）",
    "structure": "结构导向审核（中剧/长剧）",
    "movie": "好莱坞工业审核（电影长片）",
}


# =============================================================================
# 渲染1：智能剧本分析（格式感知双轨引擎）
# =============================================================================

def render_analysis(uploaded_file):
    """智能剧本分析完整UI — 自动检测格式，双轨审核"""
    st.markdown("## 🎬 剧本分析（智能格式感知）")
    st.caption("自动检测剧本类型 → 微短剧/短剧走情绪导向 · 中剧/长剧走结构导向 · 电影走好莱坞工业标准")

    # ── 获取剧本内容 ──
    # 优先级1：来自创作流的自动加载（创作→分析跳转时设置）
    if st.session_state.get("analysis_auto_load", False):
        creator_script = st.session_state.get("creator_script_content", "")
        if creator_script:
            st.session_state.analysis_loaded_script = creator_script
            st.session_state.analysis_auto_trigger = True  # 标记需要自动触发分析
        st.session_state.analysis_auto_load = False  # 用完清除

    # 优先级2：手动上传的文件
    if uploaded_file is not None:
        uploaded_content = read_uploaded_file(uploaded_file)
        if uploaded_content:
            st.session_state.analysis_loaded_script = uploaded_content

    # 优先级3：创作流已有剧本（手动加载按钮）
    if not st.session_state.get("analysis_loaded_script"):
        creator_script = st.session_state.get("creator_script_content", "")
        if creator_script:
            if st.button("📥 从创作流加载已生成的剧本", type="primary"):
                st.session_state.analysis_loaded_script = creator_script
                st.rerun()

    # 取出当前已加载的剧本
    script_content = st.session_state.get("analysis_loaded_script", "")

    if not script_content:
        st.info("📭 请在侧边栏上传剧本文件（.docx / .txt / .md），或在「剧本创作」中生成后转入分析")
        return

    # 区分来源用于提示
    is_auto = st.session_state.get("analysis_auto_trigger", False)
    st.success(f"✅ 已加载剧本，共 **{len(script_content):,}** 字符" +
               ("（来自创作流，自动启动分析中...）" if is_auto else ""))

    # ── 保存当前分析剧本（供跨模式传递使用） ──
    st.session_state.analysis_current_script = script_content

    # ── 自动格式检测 ──
    format_info = detect_script_format_by_volume(script_content)

    # 显示检测结果
    col_info1, col_info2, col_info3 = st.columns(3)
    col_info1.metric("检测到的类型", format_info["display_name"])
    col_info2.metric("总字数", f"{format_info['total_chars']:,}")
    if format_info["episode_count"] > 0:
        col_info3.metric("集数", format_info["episode_count"])
        avg = format_info["avg_chars_per_episode"]
        st.caption(f"📊 单集平均字数：{avg:,.0f} 字 | 检测置信度：{format_info['confidence']}")
    else:
        col_info3.metric("集数", "未检测到分集标记")
        st.caption(f"📊 未检测到分集标记，按总字数推断 | 检测置信度：{format_info['confidence']}")

    # 确定分类
    auto_category = format_info["category"]
    if format_info["display_name"] == "电影长片":
        auto_category = "movie"

    # ── 手动覆盖格式（可选） ──
    override = st.session_state.get("analysis_format_override", None)
    if override is None:
        selected_category = auto_category
    else:
        selected_category = override

    st.markdown("---")
    st.markdown("### ⚙️ 审核模式选择")
    st.caption("系统已自动检测剧本类型并推荐审核模式，你也可以手动切换")

    col_mode1, col_mode2, col_mode3 = st.columns(3)
    with col_mode1:
        is_emotion = st.toggle(
            "🎭 情绪导向审核",
            value=(selected_category == "emotion"),
            help="微短剧/短剧：审核情绪爽感、多巴胺节奏、台词冲击力，不苛求逻辑严密性"
        )
    with col_mode2:
        is_structure = st.toggle(
            "📐 结构导向审核",
            value=(selected_category == "structure"),
            help="中剧/长剧：审核起承转合、逻辑自洽、人物弧光、反转伏笔"
        )
    with col_mode3:
        is_movie = st.toggle(
            "🎬 好莱坞工业审核",
            value=(selected_category == "movie"),
            help="电影长片：Save the Cat 15节拍 + Ghost/Lie/Flaw + McKee价值审计"
        )

    # 互斥选择：只能选一个
    if is_emotion + is_structure + is_movie > 1:
        st.warning("⚠️ 请只选择一种审核模式")
        return

    if is_emotion:
        format_category = "emotion"
    elif is_movie:
        format_category = "movie"
    elif is_structure:
        format_category = "structure"
    else:
        format_category = auto_category

    st.session_state.analysis_format_override = format_category

    st.markdown(f"**当前审核模式**：{_FORMAT_LABELS.get(format_category, '自动')}")

    # ── 启动分析按钮（手动 or 自动触发） ──
    auto_trigger = st.session_state.pop("analysis_auto_trigger", False)
    if st.button("🚀 启动剧本医生分析", type="primary", use_container_width=True) or auto_trigger:
        provider, client, model_name, kwargs = _get_production_llm()

        if "Ollama" in provider:
            if not ensure_ollama_model(model_name):
                return

        spinner_text = {
            "emotion": "🧠 情绪导向剧本医生就位...（多巴胺节奏 + 情绪爽感 + 台词冲击力）",
            "structure": "🧠 结构导向剧本医生就位...（起承转合 + 逻辑自洽 + 人物弧光 + 反转伏笔）",
            "movie": "🧠 好莱坞剧本医生就位...（Save the Cat 15节拍 + Ghost/Lie/Flaw + McKee）",
        }.get(format_category, "🧠 剧本医生就位...")

        with st.spinner(spinner_text):
            res = run_analysis_mode(script_content, client, model_name, kwargs, format_category=format_category)

        if res:
            st.session_state.last_analysis_result = res
            st.session_state.last_analysis_format = format_category
            _render_analysis_result(res, format_category)

    # ── 显示上次分析结果（如果有） ──
    elif st.session_state.get("last_analysis_result"):
        res = st.session_state.last_analysis_result
        fmt = st.session_state.get("last_analysis_format", auto_category)
        with st.expander("📋 查看上次分析结果", expanded=True):
            _render_analysis_result(res, fmt)

    # ── 跨模式导航：转入剧本创作修改 ──
    st.markdown("---")
    has_result = bool(st.session_state.get("last_analysis_result"))
    col_nav1, col_nav2 = st.columns([1, 1])
    with col_nav1:
        btn_label = "✏️ 带审查意见转入创作流修改" if has_result else "✏️ 转入剧本创作进行修改"
        btn_type = "primary" if has_result else "secondary"
        if st.button(btn_label, use_container_width=True, type=btn_type):
            # 携带剧本文本 + 分析反馈 → 创作模式
            st.session_state.active_tab = "📝 剧本创作"
            st.session_state.cross_mode_script_text = st.session_state.analysis_current_script
            st.session_state.cross_mode_source = "analysis"
            st.session_state.cross_mode_analysis_feedback = st.session_state.get("last_analysis_result")
            st.rerun()
    with col_nav2:
        if has_result:
            st.caption("💡 将携带剧本文本 + 审查意见跳转到创作流，可直接一键AI修改后返回二次审查")
        else:
            st.caption("💡 切换到创作模式后，剧本内容将自动携带，可直接编辑后返回分析")


def _render_analysis_result(res, format_category):
    """根据格式类别分发到对应的结果渲染器"""
    if not res:
        st.warning("⚠️ 未返回有效分析数据")
        return

    if format_category == "emotion":
        _render_emotion_analysis_result(res)
    else:
        _render_structure_analysis_result(res, is_movie=(format_category == "movie"))


# -----------------------------------------------------------------------------
# 情绪导向结果渲染（微短剧/短剧）
# -----------------------------------------------------------------------------

def _render_emotion_analysis_result(res):
    """渲染情绪导向分析结果"""
    # 绿灯会立项陈述
    greenlight = res.get("greenlight_decision", {})
    slogan = greenlight.get("slogan", "")
    if slogan:
        st.markdown(
            f"<h3 style='color: #E50914; text-align: center; margin-bottom: 20px;'>"
            f"'{slogan}'</h3>",
            unsafe_allow_html=True
        )
    st.markdown("### 🚦 绿灯会立项陈述")
    col_a, col_b = st.columns([1, 1])
    col_a.info(f"**🎯 受众画像与情绪价值**：\n{greenlight.get('target_audience_and_emotion', '暂无数据')}")
    col_b.success(f"**⚖️ 商业价值与立项风险**：\n{greenlight.get('production_value_and_risk', '暂无数据')}")
    st.markdown("---")

    # 多巴胺节奏审计
    rhythm = res.get("dopamine_rhythm_audit", [])
    if rhythm and isinstance(rhythm, list):
        st.markdown("### 🔥 多巴胺节奏审计（逐集情绪诊断）")
        df_rhythm = pd.DataFrame(rhythm)
        if not df_rhythm.empty:
            col_map = {
                "episode": "集数", "emotion_crush": "情绪压迫点",
                "payoff": "反击打脸点", "hook": "结尾钩子",
                "satisfaction": "爽感评级", "verdict": "判定"
            }
            df_display = df_rhythm.rename(columns={k: v for k, v in col_map.items() if k in df_rhythm.columns})
            st.dataframe(df_display, use_container_width=True, hide_index=True)
    st.markdown("---")

    # 整体情绪弧线
    arc = res.get("emotion_arc_overview", {})
    if arc:
        st.markdown("### 📈 整体情绪弧线评估")
        col_arc1, col_arc2 = st.columns([1, 1])
        col_arc1.info(f"**情绪弧线**：{arc.get('arc_description', '暂无')}")
        col_arc2.info(f"**最高潮集数**：{arc.get('climax_episode', '暂无')}")

        overall = arc.get("overall_satisfaction", "")
        if overall:
            if any(kw in overall for kw in ["强", "优秀", "高", "极佳"]):
                st.success(f"**整体满意度**：{overall}")
            elif any(kw in overall for kw in ["弱", "不足", "低", "差"]):
                st.warning(f"**整体满意度**：{overall}")
            else:
                st.info(f"**整体满意度**：{overall}")

        charm = arc.get("character_charm_index", "")
        if charm:
            st.info(f"**角色魅力指数**：{charm}")

        weak = arc.get("weak_sections", [])
        if weak:
            st.warning(f"⚠️ 情绪塌陷段**：{' / '.join(weak)}")
    st.markdown("---")

    # 台词冲击力
    dialogue = res.get("dialogue_impact_check", [])
    if dialogue and isinstance(dialogue, list):
        st.markdown("### 💬 台词冲击力检查")
        for i, item in enumerate(dialogue, 1):
            with st.expander(f"📝 问题台词 #{i}"):
                st.markdown(f"**❌ 原句**：{item.get('original', '')}")
                st.markdown(f"**🧠 问题**：{item.get('issue', '')}")
                rw = item.get("rewrite", "")
                if rw:
                    st.markdown(f"**✅ 改写建议**：{rw}")
    st.markdown("---")

    # 写作红线
    violations = res.get("writing_violations", [])
    if violations and isinstance(violations, list):
        st.markdown("### 🚨 写作红线扫描")
        st.warning("⚠️ 以下为剧本中发现的写作违规")
        for i, v in enumerate(violations, 1):
            with st.expander(f"🚨 违规 #{i} — {v.get('location', '未知')} [{v.get('type', '')}]"):
                st.markdown(f"**❌ 原文**：{v.get('original', '')}")
                st.markdown(f"**🧠 问题**：{v.get('issue', '')}")
                rw = v.get("rewrite", "")
                if rw:
                    st.markdown(f"**✅ 重写建议**：{rw}")
    st.markdown("---")

    # 广电红线雷达
    censor = res.get("censorship_risk", {})
    if censor:
        st.markdown("### 🚨 广电/电影局送审红线雷达")
        risk_level = censor.get("risk_level", "未知")
        if "极高" in risk_level:
            st.error(f"**送审风险等级**：🔴 {risk_level}")
        elif "中等" in risk_level:
            st.warning(f"**送审风险等级**：🟡 {risk_level}")
        else:
            st.success(f"**送审风险等级**：🟢 {risk_level}")
        sensitive = censor.get("sensitive_elements", [])
        for item in sensitive:
            st.markdown(f"- 🚩 **涉险情节**：{item.get('element', '')}")
            st.markdown(f"      *触犯红线*：{item.get('risk', '')}")
            st.markdown(f"      *合规建议*：{item.get('advice', '')}")


# -----------------------------------------------------------------------------
# 结构导向结果渲染（中剧/长剧/电影长片）
# -----------------------------------------------------------------------------

def _render_structure_analysis_result(res, is_movie=False):
    """渲染结构导向分析结果（中剧/长剧/电影长片共用）"""
    # 绿灯会立项陈述
    greenlight = res.get("greenlight_decision", {})
    slogan = greenlight.get("slogan", "")
    if slogan:
        st.markdown(
            f"<h3 style='color: #E50914; text-align: center; margin-bottom: 20px;'>"
            f"'{slogan}'</h3>",
            unsafe_allow_html=True
        )
    st.markdown("### 🚦 绿灯会立项陈述")
    col_a, col_b = st.columns([1, 1])
    col_a.info(f"**🎯 受众画像与情绪价值**：\n{greenlight.get('target_audience_and_emotion', '暂无数据')}")
    col_b.success(f"**⚖️ 商业价值与立项风险**：\n{greenlight.get('production_value_and_risk', '暂无数据')}")
    st.markdown("---")

    if is_movie:
        # 电影专属：Save the Cat 15 节拍 + McKee
        beats = res.get("beat_mapping_sheet", [])
        if beats and isinstance(beats, list):
            st.markdown("### 🎬 Save the Cat 15 节拍工业映射")
            structure_flaws = res.get("structure_flaws", "")
            if structure_flaws:
                st.error(f"**📐 原剧本结构致命伤**：{structure_flaws}")
            df_beats = pd.DataFrame(beats)
            if not df_beats.empty:
                col_map = {
                    "beat_number": "节拍号", "beat_name": "节拍名称",
                    "standard_function": "标准功能",
                    "actual_plot": "当前实际情节（❌=缺失）",
                    "ideal_plot_reference": "理想剧情示范",
                    "rhythm_diagnosis": "节奏诊断"
                }
                df_display = df_beats.rename(columns={k: v for k, v in col_map.items() if k in df_beats.columns})
                st.dataframe(df_display, use_container_width=True, hide_index=True)
        st.markdown("---")

        # McKee价值转变审计
        mckee = res.get("mckee_value_audit", [])
        if mckee and isinstance(mckee, list):
            st.markdown("### ⚖️ McKee 场景价值转变审计")
            df_mckee = pd.DataFrame(mckee)
            if not df_mckee.empty:
                col_map_m = {
                    "scene": "场次", "value_at_start": "开场价值",
                    "value_at_end": "结束价值", "verdict": "翻转 / 废场景"
                }
                df_mckee_d = df_mckee.rename(columns={k: v for k, v in col_map_m.items() if k in df_mckee.columns})
                st.dataframe(df_mckee_d, use_container_width=True, hide_index=True)
        st.markdown("---")
    else:
        # 中剧/长剧专属：起承转合 + 反转伏笔
        structure_audit = res.get("story_structure_audit", {})
        if structure_audit:
            st.markdown("### 📐 起承转合结构审计")
            phases = [
                ("opening", "起 — 建置"),
                ("development", "承 — 发展"),
                ("climax", "转 — 高潮/反转"),
                ("resolution", "合 — 解决"),
            ]
            for key, label in phases:
                phase = structure_audit.get(key, {})
                desc = phase.get("description", "暂无评估")
                verdict = phase.get("verdict", "未知")
                if "优秀" in verdict:
                    st.success(f"**{label}**：{desc}（{verdict}）")
                elif "需改进" in verdict:
                    st.error(f"**{label}**：{desc}（{verdict}）")
                else:
                    st.info(f"**{label}**：{desc}（{verdict}）")

            # 逻辑自洽
            logic = structure_audit.get("logic_consistency", {})
            if logic:
                st.markdown("---")
                st.markdown("### 🔍 故事逻辑自洽检验")
                st.info(f"**整体评价**：{logic.get('overall', '暂无')}")
                holes = logic.get("plot_holes", [])
                if holes:
                    st.warning("**⚠️ 逻辑漏洞**：")
                    for h in holes:
                        st.markdown(f"- 🕳️ {h}")
        st.markdown("---")

        # 反转与伏笔
        tf = res.get("twist_and_foreshadowing", {})
        if tf:
            st.markdown("### 🔄 反转与伏笔检验")
            twists = tf.get("key_twists", [])
            if twists:
                for i, t in enumerate(twists, 1):
                    eff = t.get("effectiveness", "")
                    color = "✅" if eff == "高" else ("⚠️" if eff == "中" else "❌")
                    st.markdown(f"{color} **反转 #{i}**：{t.get('twist', '')}（有效性：{eff}）")
                    issue = t.get("issue", "")
                    if issue:
                        st.caption(f"   ⚠️ 问题：{issue}")
            foreshadowing = tf.get("foreshadowing", [])
            if foreshadowing:
                st.markdown("**伏笔追踪**：")
                for f in foreshadowing:
                    v = f.get("verdict", "")
                    icon = "✅" if v == "自然" else ("⚠️" if v == "突兀" else "❌")
                    st.markdown(f"{icon} 埋设：{f.get('planted', '')} → 回扣：{f.get('payoff', '')}（{v}）")
            dem = tf.get("deus_ex_machina_risk", "")
            if dem:
                if "无" in dem or "低" in dem:
                    st.success(f"**机械降神风险**：{dem}")
                else:
                    st.error(f"**⚠️ 机械降神风险**：{dem}")
        st.markdown("---")

    # 人物弧光诊断
    arc_list = res.get("character_arc_diagnosis", [])
    if arc_list and isinstance(arc_list, list):
        st.markdown("### 👤 人物弧光诊断 (Ghost / Lie / Flaw)")
        for arc in arc_list:
            character = arc.get("character", "未知角色")
            ghost = arc.get("ghost", "❌ 缺失")
            if ghost.startswith("❌"):
                st.error(f"**👤 {character}** — 前史创伤缺失（纸片人风险！）")
            else:
                st.success(f"**👤 {character}** — 前史创伤：{ghost}")
            for field, icon in [("lie", "🔸"), ("flaw", "⚠️"), ("want", "🎯"), ("need", "💎"), ("arc_verdict", "📋")]:
                val = arc.get(field, "")
                if val:
                    st.markdown(f"      {icon} **{field}**：{val}")
    st.markdown("---")

    # 直白心理描写抓捕
    crimes = res.get("psychological_description_crime_scene", [])
    if crimes and isinstance(crimes, list):
        st.markdown("### 🔍 直白心理描写抓捕 & 重写方案")
        st.warning("⚠️ 以下为剧本中发现的'直白心理描写'")
        for i, crime in enumerate(crimes, 1):
            with st.expander(f"🚨 罪证 #{i} — {crime.get('crime_location', '未知')} [{crime.get('crime_type', '')}]"):
                st.markdown(f"**❌ 原句**：{crime.get('original_text', '')}")
                rw_sub = crime.get("rewrite_subtext", "")
                rw_phy = crime.get("rewrite_physical_action", "")
                if rw_sub:
                    st.markdown(f"**🔹 潜台词重写**：{rw_sub}")
                if rw_phy:
                    st.markdown(f"**🔸 物理动作重写**：{rw_phy}")
    st.markdown("---")

    # 结构痛点（非电影模式）
    if not is_movie:
        structure_flaws = res.get("structure_flaws", "")
        if structure_flaws:
            st.markdown("### ⚠️ 结构痛点总结")
            st.error(f"**{structure_flaws}**")
        st.markdown("---")

    # 广电红线雷达
    censor = res.get("censorship_risk", {})
    if censor:
        st.markdown("### 🚨 广电/电影局送审红线雷达")
        risk_level = censor.get("risk_level", "未知")
        if "极高" in risk_level:
            st.error(f"**送审风险等级**：🔴 {risk_level}")
        elif "中等" in risk_level:
            st.warning(f"**送审风险等级**：🟡 {risk_level}")
        else:
            st.success(f"**送审风险等级**：🟢 {risk_level}")
        sensitive = censor.get("sensitive_elements", [])
        for item in sensitive:
            st.markdown(f"- 🚩 **涉险情节**：{item.get('element', '')}")
            st.markdown(f"      *触犯红线*：{item.get('risk', '')}")
            st.markdown(f"      *合规建议*：{item.get('advice', '')}")


# =============================================================================
# 渲染2：预算审计 + 专业制片主任预算
# =============================================================================

def render_budget(uploaded_file):
    """执行制片人预算审计完整UI（含专业制片主任预算）"""
    st.markdown("## 💰 预算制作（执行制片人审计）")
    st.caption("周期精算 + 烧钱点抓捕 + AI视频降本替代方案")

    if uploaded_file is None:
        st.info("📭 请在侧边栏上传剧本文件（.docx / .txt）")
        return

    script_content = read_uploaded_file(uploaded_file)

    # 从创作流加载
    creator_script = st.session_state.get("creator_script_content", "")
    if creator_script and not script_content:
        if st.button("📥 从创作流加载已生成的剧本", type="primary"):
            script_content = creator_script

    if not script_content:
        st.warning("⚠️ 文件内容为空")
        return

    st.success(f"✅ 已加载剧本，共 {len(script_content)} 字符")

    # ── 原有预算审计（保持不变）──
    if st.button("🚀 启动预算审计流水线", type="primary", use_container_width=True):
        provider, client, model_name, kwargs = _get_production_llm()

        if "Ollama" in provider:
            if not ensure_ollama_model(model_name):
                return

        with st.spinner("💰 执行制片人（Budgeting阎王）就位... 逐行审计烧钱点"):
            res = run_budget_mode(script_content, client, model_name, kwargs)

        if res:
            _render_budget_result(res)

    # ── 显示上次审计结果（如果有）──
    elif st.session_state.get("production_last_result"):
        res = st.session_state.production_last_result
        _render_budget_result(res)

    # ── 专业制片主任预算（新增）──
    st.markdown("---")
    st.markdown("## 🎬 专业制片主任预算")
    st.caption("中国影视行业剧组制式预算表 · 场景难度分析 · 境内拍摄场地推荐 · 全片可执行预算")

    if st.button("🚀 启动专业制片预算流水线", type="primary", use_container_width=True, key="btn_pro_budget"):
        provider, client, model_name, kwargs = _get_production_llm()

        if "Ollama" in provider:
            if not ensure_ollama_model(model_name):
                return

        # 阶段1：全局制片参数分析
        with st.status("📊 阶段1/2：正在分析全局制片参数...", expanded=True) as status:
            global_data = run_pro_budget_global(script_content, client, model_name, kwargs)
            if global_data and "production_overview" in global_data:
                st.markdown("✅ 全局制片参数分析完成")
                overview = global_data["production_overview"]
                st.markdown(f"**制作规格**：{overview.get('production_type', 'N/A')} | **剧组规模**：{overview.get('crew_scale', 'N/A')} | **预估天数**：{overview.get('total_shooting_days', 'N/A')}天")
            else:
                st.warning("⚠️ 全局参数分析未返回有效数据，将使用默认值继续")
                global_data = {"production_overview": {}}

        # 阶段2：逐场景预算（分块处理）
        chunks = split_script_smart(script_content)
        all_scene_budgets = []
        progress_bar = st.progress(0.0, text="正在逐场景编制预算...")

        for i, chunk in enumerate(chunks):
            scene_budgets = run_pro_budget_scene(chunk, global_data, client, model_name, kwargs)
            if scene_budgets and isinstance(scene_budgets, list):
                all_scene_budgets.extend(scene_budgets)
            progress_bar.progress((i + 1) / len(chunks), text=f"已完成 {i+1}/{len(chunks)} 块场景预算")

        progress_bar.empty()
        st.success(f"✅ 专业制片预算编制完成！共分析 {len(all_scene_budgets)} 个场景")

        # 缓存结果
        st.session_state.production_last_pro_budget = (global_data, all_scene_budgets)
        _render_pro_budget_result(global_data, all_scene_budgets)

    # ── 显示上次专业预算结果（如果有）──
    elif st.session_state.get("production_last_pro_budget"):
        cached = st.session_state.production_last_pro_budget
        if cached and len(cached) == 2:
            _render_pro_budget_result(cached[0], cached[1])


def _render_budget_result(res):
    """渲染预算审计结果（原有功能，保持不变）"""
    if not res:
        st.warning("⚠️ 未返回有效预算数据")
        return

    # 拍摄周期精算
    schedule = res.get("shooting_schedule_audit", {})
    if schedule:
        st.markdown("### 📅 拍摄周期精算（严苛审计）")
        col1, col2 = st.columns([1, 2])
        col1.metric("预估天数", schedule.get("estimated_days", "N/A"))
        col2.info(f"**周期评估**：{schedule.get('schedule_verdict', '暂无')}")
        risk_shots = schedule.get("special_risk_shots", [])
        if risk_shots:
            st.warning(f"⚠️ 特殊风险镜头：{' / '.join(risk_shots)}")
        st.markdown("---")

    # 烧钱点抓捕
    burn_scenes = res.get("money_burning_scenes", [])
    if burn_scenes:
        st.markdown("### 🔥 烧钱点逐行抓捕（执行制片人开骂）")
        df_burn = pd.DataFrame(burn_scenes)
        if not df_burn.empty:
            col_map = {
                "scene": "场次描述", "burn_type": "烧钱类型",
                "specific_items": "具体烧钱项", "cost_estimate": "成本量级",
                "producer_comment": "刻薄点评"
            }
            df_burn_d = df_burn.rename(columns={k: v for k, v in col_map.items() if k in df_burn.columns})
            st.dataframe(df_burn_d, use_container_width=True, hide_index=True)
    st.markdown("---")

    # AI降本方案
    ai_strategy = res.get("ai_replacement_strategy", [])
    if ai_strategy:
        st.markdown("### 🤖 AI 视频降本替代方案")
        df_ai = pd.DataFrame(ai_strategy)
        if not df_ai.empty:
            col_map_ai = {
                "scene_or_shot": "可替代镜头", "replacement_feasibility": "可行性",
                "recommended_ai_tool": "推荐AI工具", "cost_saving_analysis": "降本原理",
                "limitation_warning": "局限性警告"
            }
            df_ai_d = df_ai.rename(columns={k: v for k, v in col_map_ai.items() if k in df_ai.columns})
            st.dataframe(df_ai_d, use_container_width=True, hide_index=True)
    st.markdown("---")

    # 体量定调
    verdict = res.get("production_scale_verdict", {})
    if verdict:
        st.markdown("### 💰 线下制片成本总结")
        col1, col2 = st.columns([1, 2])
        col1.metric("制作体量", verdict.get("scale", "N/A"))
        col1.caption(f"线下成本区间：{verdict.get('offline_cost_range', '暂无')}")
        col2.info(f"**最高风险场次**：{verdict.get('highest_risk_scene', '暂无')}")


# =============================================================================
# 专业制片主任预算 — 渲染 + Excel导出（新增）
# =============================================================================

def _render_pro_budget_result(global_data, scene_budgets):
    """渲染专业制片预算结果（多Tab + 下载）"""
    if not global_data and not scene_budgets:
        st.warning("⚠️ 未返回有效专业预算数据")
        return

    st.markdown("## 📊 专业制片预算报告")
    overview = global_data.get("production_overview", {})

    # ── Tab1：预算总览 ──
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 预算总览", "📋 场景预算明细", "📍 场地推荐", "📅 拍摄日程"
    ])

    with tab1:
        st.markdown("### 📊 预算总览")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("总拍摄天数", f"{overview.get('total_shooting_days', 'N/A')} 天")
        col2.metric("剧组规模", overview.get("crew_scale", "N/A"))
        col3.metric("总人数", f"{overview.get('total_crew_count', 'N/A')} 人")
        est_total = overview.get("estimated_total_budget_range", "N/A")
        col4.metric("总预算区间（元）", est_total)

        # 拍摄天数推算依据
        days_basis = overview.get("shooting_days_basis", "")
        if days_basis:
            st.info(f"**📅 拍摄天数推算依据**：{days_basis}")

        # 日均基准费用表
        st.markdown("**日均基准费用（元/天）**")
        rates = overview.get("standard_daily_crew_cost", {})
        if rates:
            df_rates = pd.DataFrame(list(rates.items()), columns=["工种组", "日均费用区间（元）"])
            st.dataframe(df_rates, use_container_width=True, hide_index=True)

        # 其他日均标准
        daily = overview.get("standard_daily_rates", {})
        if daily:
            st.markdown("**其他日均标准**")
            daily_rows = [
                {"项目": "餐标（每人每天）", "费用区间（元）": daily.get("meal_per_person_daily", "N/A")},
                {"项目": "工作车日租", "费用区间（元）": daily.get("vehicle_daily", "N/A")},
                {"项目": "住宿（每人每晚）", "费用区间（元）": daily.get("hotel_per_person_night", "N/A")},
                {"项目": "场地费参考", "费用区间（元）": daily.get("location_rental_range", "N/A")},
            ]
            df_daily = pd.DataFrame(daily_rows)
            st.dataframe(df_daily, use_container_width=True, hide_index=True)

        # 风险点
        risks = overview.get("special_risk_notes", [])
        if risks:
            st.warning("⚠️ 制片风险点：" + " / ".join(risks))

    # ── Tab2：场景预算明细 ──
    with tab2:
        st.markdown("### 📋 场景预算明细（按场次排序）")
        if scene_budgets:
            df_scenes = _build_pro_budget_scene_df(scene_budgets)
            st.dataframe(df_scenes, use_container_width=True, hide_index=True)

            # 合计行
            if "场合计（元）" in df_scenes.columns:
                total = df_scenes["场合计（元）"].replace(0, pd.NA).sum()
                st.markdown(f"**📊 场景费用合计（不含未计算项）**：{total:,.0f} 元")
        else:
            st.info("暂无场景预算明细数据")

    # ── Tab3：场地推荐 ──
    with tab3:
        st.markdown("### 📍 拍摄场地推荐")
        loc_rows = []
        for s in scene_budgets:
            scene_name = s.get("scene_name", "")
            scene_num = s.get("scene_number", "")
            for loc in s.get("recommended_locations", []):
                loc_rows.append({
                    "场次": scene_num,
                    "场景名": scene_name,
                    "场地类型": s.get("location_type", ""),
                    "推荐城市": loc.get("city", ""),
                    "具体场地": loc.get("specific_area", ""),
                    "推荐理由": loc.get("reason", ""),
                    "日租参考（元/天）": loc.get("estimated_daily_rent", ""),
                    "类似作品参考": loc.get("similar_productions", ""),
                })
        if loc_rows:
            df_loc = pd.DataFrame(loc_rows)
            st.dataframe(df_loc, use_container_width=True, hide_index=True)
        else:
            st.info("暂无场地推荐数据")

    # ── Tab4：拍摄日程参考 ──
    with tab4:
        st.markdown("### 📅 拍摄日程参考（按难度排序）")
        if scene_budgets:
            df_schedule = _build_pro_budget_schedule_df(scene_budgets, overview)
            st.dataframe(df_schedule, use_container_width=True, hide_index=True)
        else:
            st.info("暂无拍摄日程数据")

    # ── Excel 下载按钮 ──
    st.markdown("---")
    excel_bytes = _generate_pro_budget_excel(global_data, scene_budgets)
    st.download_button(
        "📥 下载专业制片预算（Excel）",
        data=excel_bytes,
        file_name="专业制片预算_全片.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )


def _build_pro_budget_scene_df(scene_budgets):
    """从场景预算JSON构建明细DataFrame"""
    rows = []
    for s in scene_budgets:
        cost = s.get("scene_cost_breakdown", {})
        rows.append({
            "场次": s.get("scene_number", ""),
            "场景名": s.get("scene_name", ""),
            "集数": s.get("episode", ""),
            "内外景": s.get("int_ext", ""),
            "日夜": s.get("day_night", ""),
            "难度": s.get("difficulty_level", ""),
            "难度原因": s.get("difficulty_reason", ""),
            "预估拍摄小时": s.get("estimated_shooting_hours", ""),
            "演员人数": s.get("required_cast_count", ""),
            "群演人数": s.get("required_extras_count", ""),
            "特殊器材": "、".join(s.get("special_equipment", [])),
            "特殊车辆": "、".join(s.get("special_vehicles", [])),
            "置景描述": s.get("set_construction", ""),
            "置景费用（元）": _parse_cost(cost.get("set_cost", "0")),
            "道具费用（元）": _parse_cost(cost.get("props_cost", "0")),
            "人员费（元）": _parse_cost(cost.get("crew_cost", "0")),
            "器材费（元）": _parse_cost(cost.get("equipment_cost", "0")),
            "车辆费（元）": _parse_cost(cost.get("vehicle_cost", "0")),
            "伙食费（元）": _parse_cost(cost.get("meal_cost", "0")),
            "场地费（元）": _parse_cost(cost.get("location_cost", "0")),
            "其他费（元）": _parse_cost(cost.get("other_cost", "0")),
            "场合计（元）": _parse_cost(cost.get("total_scene_cost", "0")),
            "制片备注": s.get("producer_notes", ""),
        })
    return pd.DataFrame(rows)


def _build_pro_budget_schedule_df(scene_budgets, overview):
    """构建拍摄日程DataFrame（按难度排序，模拟排期）"""
    # 难度排序映射
    difficulty_order = {"极高": 0, "难": 1, "中": 2, "易": 3}
    sorted_scenes = sorted(
        scene_budgets,
        key=lambda x: difficulty_order.get(x.get("difficulty_level", "中"), 2)
    )

    total_days = overview.get("total_shooting_days", 0)
    rows = []
    day_counter = 1
    hours_accumulated = 0.0

    for s in sorted_scenes:
        est_hours = s.get("estimated_shooting_hours", 4.0)
        if isinstance(est_hours, str):
            try:
                est_hours = float(est_hours)
            except:
                est_hours = 4.0

        hours_accumulated += est_hours
        # 每天按10小时拍摄计算
        if hours_accumulated > 10 and day_counter < total_days:
            day_counter += 1
            hours_accumulated = est_hours

        rows.append({
            "拍摄日": day_counter,
            "场次": s.get("scene_number", ""),
            "场景名": s.get("scene_name", ""),
            "内外景": s.get("int_ext", ""),
            "日夜": s.get("day_night", ""),
            "难度": s.get("difficulty_level", ""),
            "预估小时": est_hours,
            "特殊器材": "、".join(s.get("special_equipment", [])),
            "备注": s.get("producer_notes", ""),
        })

    return pd.DataFrame(rows)


def _parse_cost(cost_str):
    """尝试从成本字符串中解析出数值（元）"""
    if not cost_str or not isinstance(cost_str, str):
        return 0
    import re
    # 提取所有数字（支持"万"单位）
    nums = re.findall(r"[\d.]+", cost_str)
    if not nums:
        return 0
    val = float(nums[0])
    if "万" in cost_str:
        val *= 10000
    return int(val)


def _generate_pro_budget_excel(global_data, scene_budgets):
    """生成专业制片预算多Sheet Excel文件"""
    import io
    overview = global_data.get("production_overview", {})

    # Sheet1: 预算汇总
    summary_rows = [
        {"类别": "制作规格", "项目": "制作类型", "费用（元）": overview.get("production_type", ""), "备注": ""},
        {"类别": "制作规格", "项目": "剧组规模", "费用（元）": overview.get("crew_scale", ""), "备注": f"约{overview.get('total_crew_count', 'N/A')}人"},
        {"类别": "制作规格", "项目": "预估总拍摄天数", "费用（元）": overview.get("total_shooting_days", ""), "备注": overview.get("shooting_days_basis", "")[:50]},
        {"类别": "制作规格", "项目": "总预算区间（元）", "费用（元）": overview.get("estimated_total_budget_range", ""), "备注": ""},
    ]
    # 日均费率
    rates = overview.get("standard_daily_crew_cost", {})
    for k, v in rates.items():
        summary_rows.append({"类别": "日均费率（元/天）", "项目": k, "费用（元）": v, "备注": ""})
    daily = overview.get("standard_daily_rates", {})
    for k, v in daily.items():
        summary_rows.append({"类别": "日均标准（元/天）", "项目": k, "费用（元）": v, "备注": ""})
    # 风险点
    risks = overview.get("special_risk_notes", [])
    if risks:
        summary_rows.append({"类别": "风险点", "项目": " / ".join(risks), "费用（元）": "", "备注": "需重点关注"})

    df_summary = pd.DataFrame(summary_rows)

    # Sheet2: 场景预算明细
    df_scenes = _build_pro_budget_scene_df(scene_budgets)

    # Sheet3: 场地推荐
    loc_rows = []
    for s in scene_budgets:
        scene_name = s.get("scene_name", "")
        scene_num = s.get("scene_number", "")
        for loc in s.get("recommended_locations", []):
            loc_rows.append({
                "场次": scene_num,
                "场景名": scene_name,
                "场地类型": s.get("location_type", ""),
                "推荐城市": loc.get("city", ""),
                "具体场地": loc.get("specific_area", ""),
                "推荐理由": loc.get("reason", ""),
                "日租参考（元/天）": loc.get("estimated_daily_rent", ""),
                "类似作品参考": loc.get("similar_productions", ""),
            })
    df_locations = pd.DataFrame(loc_rows) if loc_rows else pd.DataFrame()

    # Sheet4: 拍摄日程
    df_schedule = _build_pro_budget_schedule_df(scene_budgets, overview)

    # Sheet5: 费用参考基准
    rate_rows = []
    crew_rates = overview.get("standard_daily_crew_cost", {})
    for k, v in crew_rates.items():
        rate_rows.append({"类别": "工种组日均费", "项目": k, "费用（元/天）": v, "说明": ""})
    daily_rates = overview.get("standard_daily_rates", {})
    for k, v in daily_rates.items():
        rate_rows.append({"类别": "日均标准", "项目": k, "费用（元/天）": v, "说明": ""})
    df_reference = pd.DataFrame(rate_rows)

    # 写入Excel
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df_summary.to_excel(writer, index=False, sheet_name="预算汇总")
        if not df_scenes.empty:
            df_scenes.to_excel(writer, index=False, sheet_name="场景预算明细")
        if not df_locations.empty:
            df_locations.to_excel(writer, index=False, sheet_name="场地推荐")
        if not df_schedule.empty:
            df_schedule.to_excel(writer, index=False, sheet_name="拍摄日程")
        if not df_reference.empty:
            df_reference.to_excel(writer, index=False, sheet_name="费用参考基准")

    return out.getvalue()


# =============================================================================
# 渲染3：场景拆解
# =============================================================================

def render_scene_breakdown(uploaded_file):
    """强迫症场记统筹完整UI"""
    st.markdown("## 📋 场景表制作（强迫症场记统筹）")
    st.caption("物理空间解构 — 只列物理实体道具和特殊服装，禁止剧情概括")

    if uploaded_file is None:
        st.info("📭 请在侧边栏上传剧本文件（.docx / .txt）")
        return

    script_content = read_uploaded_file(uploaded_file)

    creator_script = st.session_state.get("creator_script_content", "")
    if creator_script and not script_content:
        if st.button("📥 从创作流加载已生成的剧本", type="primary"):
            script_content = creator_script

    if not script_content:
        st.warning("⚠️ 文件内容为空")
        return

    st.success(f"✅ 已加载剧本，共 {len(script_content)} 字符")

    if st.button("🚀 启动场记统筹流水线", type="primary", use_container_width=True):
        provider, client, model_name, kwargs = _get_production_llm()

        if "Ollama" in provider:
            if not ensure_ollama_model(model_name):
                return

        chunks = split_script_smart(script_content)
        st.success(f"场记统筹就位，正在将文本解构为 {len(chunks)} 卷物理场景...")
        progress_bar = st.progress(0)

        global_scenes = []
        scene_num = 1
        for i, chunk in enumerate(chunks):
            scenes = extract_scenes(chunk, client, model_name, kwargs)
            for s in scenes:
                if isinstance(s, dict):
                    s["场次"] = scene_num
                    global_scenes.append(s)
                    scene_num += 1
            progress_bar.progress((i + 1) / len(chunks))

        if global_scenes:
            _render_scene_result(global_scenes)
        else:
            st.warning("⚠️ 未返回有效场景数据")


def _render_scene_result(global_scenes):
    """渲染场景统筹结果"""
    st.markdown("### 📋 场景统筹总表（物理空间解构）")
    st.caption("📌 场记单说明：只列物理实体道具和特殊服装，禁止剧情概括")

    df = pd.DataFrame(global_scenes)
    priority_cols = ["场次", "场景名称", "内外景", "日夜", "出场人物"]
    other_cols = [c for c in df.columns if c not in priority_cols]
    cols = [c for c in priority_cols if c in df.columns] + other_cols

    tab1, tab2 = st.tabs(["📋 顺场景表（按叙事顺序）", "🏷️ 分场景表（按场景名聚合）"])
    with tab1:
        st.dataframe(df[cols], use_container_width=True)
    with tab2:
        if "场景名称" in df.columns:
            df_fen = df.sort_values(by=["场景名称", "内外景", "日夜", "场次"])
        else:
            df_fen = df.copy()
        st.dataframe(df_fen[cols], use_container_width=True)

    # Excel下载
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="顺场景表")
        if "场景名称" in df.columns:
            df_fen.to_excel(writer, index=False, sheet_name="分场景表")
    st.download_button(
        "📥 下载场景表 (Excel)", data=out.getvalue(),
        file_name="场景表_场记版.xlsx"
    )


# =============================================================================
# 渲染4：分镜工作台
# =============================================================================

def render_storyboard(uploaded_file, style_tokens_input=""):
    """CrewAI 2-Agent 分镜工作台 v3.0 — 结构参数化 + 代码组装"""
    st.markdown("## 🎥 分镜工作台（Seedance 2.0 结构参数化 v3.0）")
    st.caption("分镜导演输出结构化JSON → 代码组装Seedance提示词 | LLM专注创意 · 代码保证格式")

    # 检测 CrewAI 可用性
    try:
        from crewai import Agent, Task, Crew, Process, LLM
        crewai_ok = True
    except ImportError:
        crewai_ok = False
        st.error("❌ 分镜工作台需要 crewai 依赖。请运行:")
        st.code("pip install crewai langchain-openai", language="bash")
        return

    if uploaded_file is None:
        st.info("📭 请在侧边栏上传剧本文件（.docx / .txt）")
        return

    script_content = read_uploaded_file(uploaded_file)

    # 从创作流加载
    creator_script = st.session_state.get("creator_script_content", "")
    if creator_script and not script_content:
        if st.button("📥 从创作流加载已生成的剧本", type="primary"):
            script_content = creator_script

    if not script_content:
        st.warning("⚠️ 文件内容为空")
        return

    st.success(f"✅ 已加载剧本，共 {len(script_content)} 字符")

    if st.button("🚀 启动 Seedance 2.0 分镜工作流（4-Agent串行）", type="primary", use_container_width=True):
        provider, client, model_name, kwargs = _get_production_llm()

        if "Ollama" in provider:
            if not ensure_ollama_model(model_name):
                return

        from production.crew_storyboard import run_crew_on_chunk

        # 第一步：提取人物小传
        with st.spinner("👤 视觉导演就位：正在全篇提取人物小传与视觉档案库..."):
            global_chars = extract_characters(script_content, client, model_name, kwargs)

        st.markdown(f"### 👤 全局角色视觉档案库 (共提取 {len(global_chars)} 名角色)")
        for char in global_chars:
            st.markdown(f"- **{char.get('name', '未知')}**：{char.get('bio', '')}\n  *Prompt*: `{char.get('visual_prompt', '')}`")

        st.markdown("---")

        # 第二步：CrewAI 2-Agent 工作流（v3.1 — 自适应切块 + 缺口补足）
        # ── 动态 SAFE_CAP：根据模型输出上限自动调整单块镜数天花板 ──
        _dynamic_cap = _SAFE_CAP  # 默认值，后续若能获取 max_tokens 可覆盖
        try:
            from production.crew_storyboard import resolve_output_cap, FALLBACK_MAX_OUTPUT
            _model_name = st.session_state.get("selected_model", "")
            _provider = st.session_state.llm_provider
            _engine = st.session_state.get("engine_choice", "")
            _output_cap = resolve_output_cap(_engine, _provider, _model_name) or FALLBACK_MAX_OUTPUT
            _dynamic_cap = compute_dynamic_safe_cap(_output_cap)
        except Exception:
            pass

        # ── v4 管线：①统计体量 → ②由体量算镜数 → ③模型容量反推切块数 → ④保证时长 ──
        _target_duration_min = float(st.session_state.get("target_duration_min", 0.0) or 0.0)
        _plan = plan_storyboard_chunks(
            script_chars=len(script_content),
            target_duration_min=_target_duration_min,
            safe_cap=_dynamic_cap,
            avg_shot_sec=_AVG_SHOT_SEC,
        )
        # 先按规划的块大小切，再用 force_min_chunks 保证块数达标（容量 ≥ 目标）
        chunks = split_script_smart(script_content, max_chars=_plan["chunk_chars"])
        chunks = force_min_chunks(chunks, _plan["num_chunks"], _plan["chunk_chars"])
        st.success(f"第二步：启动 v4 分镜工作流，对 {len(chunks)} 个切块（≈{_plan['chunk_chars']} 字/块）进行分镜...（模型 {_provider}/{_model_name} 单块上限 {_dynamic_cap} 镜，由容量反推切块数）")

        # 目标时长：从侧边栏读取（分钟）。>0 时按各块字符占比分摊到每块，反推镜数密度
        _total_script_chars = max(sum(len(c) for c in chunks), 1)

        _dur_display_map = {
            0.0: "自动（按剧本字数密度）",
            2.0: "短剧 · 2 分钟/集",
            3.0: "竖屏短剧 · 3 分钟/集",
            10.0: "标准 · 10 分钟/集",
            45.0: "长剧单集 · 45 分钟/集",
        }

        if _target_duration_min > 0:
            _mode_label = _dur_display_map.get(_target_duration_min, f"自定义 {_target_duration_min} 分钟/集")
            st.info(
                f"🎯 分镜模式：{_mode_label}｜目标 {_plan['demand_shots']} 镜 / {_target_duration_min:.0f} 分钟"
                f"｜内容可支撑 {_plan['volume_shots']} 镜｜本模型单块上限 {_dynamic_cap} 镜×{len(chunks)} 块"
                f"｜可达 {_plan['achievable_shots']} 镜 / {_plan['achievable_duration_sec']/60:.1f} 分钟"
            )
        else:
            st.info(
                f"🎯 分镜模式：自动（按剧本体量）｜预计 {_plan['achievable_shots']} 镜 "
                f"/ {_plan['achievable_duration_sec']/60:.1f} 分钟｜切块 {len(chunks)} 块"
            )

        # ④ 可行性预警：内容不足以支撑目标时长时封顶并建议扩充剧本
        if _plan["warning"]:
            st.warning("⚠️ " + _plan["warning"])

        chars_str = json.dumps(global_chars, ensure_ascii=False) if global_chars else ""
        global_shots = []
        global_atmosphere = ""  # v3.0：全局氛围画质（取第一个切块）
        shot_num = 1
        accumulated_seconds = 0.0

        with st.spinner("🤖 Seedance 2.0 工作流执行中（分镜导演 → 质检 → 代码组装）..."):
            for i, chunk in enumerate(chunks):
                status_placeholder = st.empty()
                status_placeholder.info(f"  正在处理第 {i+1}/{len(chunks)} 个切块（时间码从 {int(accumulated_seconds//60):02d}:{int(accumulated_seconds%60):02d} 开始）...")
                # 按字符占比分摊「可达时长」到本块（v4：封顶到内容可支撑范围，避免虚高）
                _chunk_target_sec = 0.0
                if _target_duration_min > 0:
                    _chunk_target_sec = _plan["achievable_duration_sec"] * (len(chunk) / _total_script_chars)
                try:
                    shots, total_secs, atmosphere = run_crew_on_chunk(
                        chunk, chars_str, style_tokens_input,
                        st.session_state.llm_provider,
                        st.session_state.base_url,
                        st.session_state.api_key or "sk-local",
                        model_name,
                        time_offset_seconds=accumulated_seconds,
                        target_duration_sec=_chunk_target_sec
                    )
                    # 保存首个切块的全局氛围画质
                    if i == 0 and atmosphere:
                        global_atmosphere = atmosphere
                    for s in shots:
                        if isinstance(s, dict):
                            s["镜头号"] = shot_num
                            global_shots.append(s)
                            shot_num += 1
                    if total_secs > 0:
                        accumulated_seconds += total_secs
                except Exception as crew_err:
                    st.warning(f"⚠️ 第 {i+1} 块处理异常：{crew_err}")
                status_placeholder.info(f"  第 {i+1}/{len(chunks)} 块完成 ✓")

        # ── v4 缺口补足重跑：产出不足「可达目标」时自动拆分重跑（封顶到内容可支撑范围）──
        if _target_duration_min > 0 and global_shots:
            _target_sec = _plan["achievable_duration_sec"]
            _gap_sec = _target_sec - accumulated_seconds
            _gap_shots = int(_target_sec / _AVG_SHOT_SEC) - len(global_shots)
            # 缺口超过目标的 30% 时触发补足
            if _gap_sec > _target_sec * 0.3 and len(global_shots) > 0:
                st.warning(
                    f"🔄 检测到分镜缺口：目标 {_target_duration_min:.0f} 分钟，"
                    f"当前仅产出 {len(global_shots)} 镜 / {accumulated_seconds:.0f} 秒。"
                    f"正在启动缺口补足（拆分重跑低产切块）..."
                )
                # 找出产出镜头数明显低于本块预期的切块（可能是被 SAFE_CAP 截断的）
                _chunk_outputs = []  # (chunk_index, shots_count, chunk_text)
                # 需要在循环中记录每块产出——用近似估算回溯：
                # 低产切块特征：该块字符占比 × 总镜数 应 > 实际产出
                _avg_per_char = len(global_shots) / max(_total_script_chars, 1)
                _reshoot_chunks = []
                for _ci, _ck in enumerate(chunks):
                    _expected_for_chunk = _avg_per_char * len(_ck) * 1.5  # 预期×1.5作为阈值
                    if _expected_for_chunk > _dynamic_cap * 0.8:
                        # 这个切块可能被截断了，加入重跑列表
                        _reshoot_chunks.append(_ci)

                if _reshoot_chunks:
                    # 将低产切块进一步拆分为更小的子块
                    _sub_chunks = []
                    for _ci in _reshoot_chunks:
                        _sub = split_script_smart(chunks[_ci], max_chars=max(_plan["chunk_chars"] // 2, 150))
                        _sub_chunks.extend(_sub)

                    if _sub_chunks:
                        st.info(f"  拆分 {len(_reshoot_chunks)} 个低产切块为 {len(_sub_chunks)} 个子块，重新生成...")
                        _sub_shot_num = shot_num
                        for _si, _sc in enumerate(_sub_chunks):
                            _sp = st.empty()
                            _sp.info(f"  补足：处理子块 {_si+1}/{len(_sub_chunks)}...")
                            try:
                                _sub_target = (_gap_sec) * (len(_sc) / max(sum(len(s) for s in _sub_chunks), 1))
                                _s_shots, _s_secs, _s_atm = run_crew_on_chunk(
                                    _sc, chars_str, style_tokens_input,
                                    st.session_state.llm_provider,
                                    st.session_state.base_url,
                                    st.session_state.api_key or "sk-local",
                                    model_name,
                                    time_offset_seconds=accumulated_seconds,
                                    target_duration_sec=max(_sub_target, 10.0)  # 至少给10秒
                                )
                                for _s in _s_shots:
                                    if isinstance(_s, dict):
                                        _s["镜头号"] = shot_num
                                        global_shots.append(_s)
                                        shot_num += 1
                                if _s_secs > 0:
                                    accumulated_seconds += _s_secs
                            except Exception as _sub_err:
                                st.warning(f"  补足子块 {_si+1} 异常：{_sub_err}")
                            _sp.info(f"  补足子块 {_si+1}/{len(_sub_chunks)} 完成 ✓")

                        _total_min2 = int(accumulated_seconds // 60)
                        _total_sec2 = int(accumulated_seconds % 60)
                        st.success(
                            f"✅ 补足完成！总计 {len(global_shots)} 镜 / "
                            f"{_total_min2} 分 {_total_sec2} 秒"
                        )

        # 第三步：展示全局氛围画质 + Seedance 2.0 分镜矩阵
        if global_shots:
            total_min = int(accumulated_seconds // 60)
            total_sec = int(accumulated_seconds % 60)

            # v3.0：展示全局氛围画质
            if global_atmosphere:
                st.markdown("### 🎨 全局氛围与画质设定")
                with st.expander("展开查看完整【氛围与画质】", expanded=False):
                    st.text_area(
                        "【氛围与画质】", global_atmosphere,
                        height=200, key="global_atmosphere_display",
                        label_visibility="collapsed"
                    )
                    st.caption("📋 以上为 LLM 根据剧本自动生成的全局视觉设定，可直接复制使用。")

            st.markdown(f"### 🎥 Seedance 2.0 分镜矩阵（总计 {len(global_shots)} 镜 / 累计时长 {total_min} 分 {total_sec} 秒）")
            st.caption("📌 每镜一行「终极Seedance提示词」—— 直接复制粘贴到 Seedance 2.0 即可使用")

            cols_order = ["镜头号"] + [c for c in global_shots[0].keys() if c != "镜头号"]
            df_shots = pd.DataFrame(global_shots)[cols_order]

            # v3.0：代码组装保证输出4列，此处仅做兜底确保
            for required_col in ["时间码", "景别机位运镜", "终极Seedance提示词"]:
                if required_col not in df_shots.columns:
                    df_shots[required_col] = ""

            display_cols = ["镜头号", "时间码", "景别机位运镜", "终极Seedance提示词"]
            df_display = df_shots[[c for c in display_cols if c in df_shots.columns]]

            st.data_editor(
                df_display,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "镜头号": st.column_config.NumberColumn(width="small", format="%d"),
                    "时间码": st.column_config.TextColumn(width="small"),
                    "景别机位运镜": st.column_config.TextColumn(width="medium"),
                    "终极Seedance提示词": st.column_config.TextColumn(width="large"),
                }
            )

            # Excel下载 — v2.0 格式
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                df_display.to_excel(writer, index=False, sheet_name="Seedance2.0分镜")
            st.download_button(
                "📥 下载 Seedance 分镜矩阵 (Excel)", data=out.getvalue(),
                file_name="分镜矩阵_Seedance2.0.xlsx"
            )
        else:
            st.warning("⚠️ CrewAI 工作流未返回有效分镜数据")
