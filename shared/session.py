"""
shared/session.py — Session State 命名空间管理
===============================================

使用命名空间前缀避免创作流和制片流的 session_state 变量冲突。
"""

import streamlit as st


# =============================================================================
# 创作流 Session State（来自程序A，加 creator_ 前缀）
# =============================================================================

CREATOR_IDLE = 0
CREATOR_OUTLINE = 1
CREATOR_SCRIPTS = 2


def init_creator_state():
    """初始化创作流 session_state 变量"""
    prefix = "creator_"

    # 两阶段工作流状态
    if f"{prefix}workflow_stage" not in st.session_state:
        st.session_state[f"{prefix}workflow_stage"] = CREATOR_IDLE
    if f"{prefix}workflow_running" not in st.session_state:
        st.session_state[f"{prefix}workflow_running"] = False

    # 剧本输出
    if f"{prefix}global_outline" not in st.session_state:
        st.session_state[f"{prefix}global_outline"] = ""
    if f"{prefix}character_settings" not in st.session_state:
        st.session_state[f"{prefix}character_settings"] = ""
    if f"{prefix}script_content" not in st.session_state:
        st.session_state[f"{prefix}script_content"] = ""
    if f"{prefix}memory_snapshot" not in st.session_state:
        st.session_state[f"{prefix}memory_snapshot"] = ""

    # 进度
    if f"{prefix}current_episode" not in st.session_state:
        st.session_state[f"{prefix}current_episode"] = 0
    if f"{prefix}total_episodes" not in st.session_state:
        st.session_state[f"{prefix}total_episodes"] = 0
    if f"{prefix}current_stage" not in st.session_state:
        st.session_state[f"{prefix}current_stage"] = ""
    if f"{prefix}progress_current" not in st.session_state:
        st.session_state[f"{prefix}progress_current"] = 0
    if f"{prefix}progress_total" not in st.session_state:
        st.session_state[f"{prefix}progress_total"] = 3

    # 阶段一保存的参数
    if f"{prefix}stage1_outline" not in st.session_state:
        st.session_state[f"{prefix}stage1_outline"] = ""
    if f"{prefix}stage1_total_episodes" not in st.session_state:
        st.session_state[f"{prefix}stage1_total_episodes"] = 0
    if f"{prefix}stage1_creative_idea" not in st.session_state:
        st.session_state[f"{prefix}stage1_creative_idea"] = ""

    # HITL 定向修改
    if f"{prefix}hitl_previous_outline" not in st.session_state:
        st.session_state[f"{prefix}hitl_previous_outline"] = ""
    if f"{prefix}hitl_previous_episode_scripts" not in st.session_state:
        st.session_state[f"{prefix}hitl_previous_episode_scripts"] = {}
    if f"{prefix}hitl_editing_episode" not in st.session_state:
        st.session_state[f"{prefix}hitl_editing_episode"] = 0
    if f"{prefix}last_doctor_rejection" not in st.session_state:
        st.session_state[f"{prefix}last_doctor_rejection"] = {}

    # 日志
    if f"{prefix}logs" not in st.session_state:
        st.session_state[f"{prefix}logs"] = []

    # ── 剧本改编工作流 ──
    if f"{prefix}rewrite_source_text" not in st.session_state:
        st.session_state[f"{prefix}rewrite_source_text"] = ""   # 原始上传剧本内容
    if f"{prefix}rewrite_result" not in st.session_state:
        st.session_state[f"{prefix}rewrite_result"] = ""        # 改编结果
    if f"{prefix}rewrite_running" not in st.session_state:
        st.session_state[f"{prefix}rewrite_running"] = False    # 是否正在改编中


# =============================================================================
# 制片流 Session State（加 production_ 前缀）
# =============================================================================

def init_production_state():
    """初始化制片流 session_state 变量"""
    prefix = "production_"

    if f"{prefix}logs" not in st.session_state:
        st.session_state[f"{prefix}logs"] = []
    if f"{prefix}last_result" not in st.session_state:
        st.session_state[f"{prefix}last_result"] = None
    # 专业制片预算缓存结果：(global_data, scene_budgets)
    if f"{prefix}last_pro_budget" not in st.session_state:
        st.session_state[f"{prefix}last_pro_budget"] = None


# =============================================================================
# 跨模式导航状态（创作 ↔ 分析 循环）
# =============================================================================

def init_cross_mode_state():
    """初始化跨模式导航 session_state 变量"""
    # 剧本分析自动加载标记（创作→分析时设为 True）
    if "analysis_auto_load" not in st.session_state:
        st.session_state.analysis_auto_load = False

    # 剧本分析自动触发标记（创作→分析后自动启动分析）
    if "analysis_auto_trigger" not in st.session_state:
        st.session_state.analysis_auto_trigger = False

    # 分析页已加载的剧本文本（持久化，避免 rerun 后丢失）
    if "analysis_loaded_script" not in st.session_state:
        st.session_state.analysis_loaded_script = ""

    # 上次分析结果（分析→创作时作为参考）
    if "last_analysis_result" not in st.session_state:
        st.session_state.last_analysis_result = None

    # 上次分析的格式类别（"emotion" / "structure"）
    if "last_analysis_format" not in st.session_state:
        st.session_state.last_analysis_format = ""

    # 手动覆盖的格式（用户在分析页手动选择后设为 True）
    if "analysis_format_override" not in st.session_state:
        st.session_state.analysis_format_override = None

    # 跨模式剧本文本传递（分析→创作时携带剧本原文）
    if "cross_mode_script_text" not in st.session_state:
        st.session_state.cross_mode_script_text = ""

    # 跨模式来源标记（"analysis" = 从分析跳转到创作）
    if "cross_mode_source" not in st.session_state:
        st.session_state.cross_mode_source = ""

    # 跨模式分析反馈（分析→创作时携带完整分析结果供参考）
    if "cross_mode_analysis_feedback" not in st.session_state:
        st.session_state.cross_mode_analysis_feedback = None

    # 分析页当前正在分析的剧本文本（用于跨模式传递）
    if "analysis_current_script" not in st.session_state:
        st.session_state.analysis_current_script = ""

    # =========================================================================
    # 跨模式修改工作流状态（分析→创作：生成修改报告→确认→多智能体执行修改）
    # =========================================================================

    # LLM 生成的修改报告（dict，包含修改方向、具体建议、优先级）
    if "cross_mode_modification_report" not in st.session_state:
        st.session_state.cross_mode_modification_report = None

    # 是否正在执行多智能体修改（控制 loading 状态）
    if "cross_mode_modifying" not in st.session_state:
        st.session_state.cross_mode_modifying = False

    # 多智能体修改后的剧本文本
    if "cross_mode_modified_script" not in st.session_state:
        st.session_state.cross_mode_modified_script = ""

    # 是否显示修改报告确认界面
    if "cross_mode_show_report" not in st.session_state:
        st.session_state.cross_mode_show_report = False

    # 用户是否已确认修改报告（确认后触发多智能体修改）
    if "cross_mode_report_confirmed" not in st.session_state:
        st.session_state.cross_mode_report_confirmed = False

    # 修改模式："full"=全剧修改，"episode"=单集修改（预留）
    if "cross_mode_modification_mode" not in st.session_state:
        st.session_state.cross_mode_modification_mode = "full"

    # 修改工作流日志
    if "cross_mode_modification_logs" not in st.session_state:
        st.session_state.cross_mode_modification_logs = []

    # 修改工作流实时状态（用于UI进度显示）
    if "cross_mode_modification_progress" not in st.session_state:
        st.session_state.cross_mode_modification_progress = 0
    if "cross_mode_modification_current_step" not in st.session_state:
        st.session_state.cross_mode_modification_current_step = ""
    if "cross_mode_modification_start_time" not in st.session_state:
        st.session_state.cross_mode_modification_start_time = 0
    if "cross_mode_modification_error" not in st.session_state:
        st.session_state.cross_mode_modification_error = ""

    # 是否显示跨模式桥接面板（持久化标志，避免 rerun 后面板消失）
    if "cross_mode_show_bridge" not in st.session_state:
        st.session_state.cross_mode_show_bridge = False


# =============================================================================
# 创作流辅助函数
# =============================================================================

def creator_clear_outputs():
    """清空创作流所有输出"""
    prefix = "creator_"
    st.session_state[f"{prefix}global_outline"] = ""
    st.session_state[f"{prefix}character_settings"] = ""
    st.session_state[f"{prefix}script_content"] = ""
    st.session_state[f"{prefix}memory_snapshot"] = ""
    st.session_state[f"{prefix}logs"] = []
    st.session_state[f"{prefix}current_episode"] = 0
    st.session_state[f"{prefix}total_episodes"] = 0
    st.session_state[f"{prefix}workflow_stage"] = CREATOR_IDLE
    st.session_state[f"{prefix}stage1_outline"] = ""
    st.session_state[f"{prefix}stage1_total_episodes"] = 0
    st.session_state[f"{prefix}stage1_creative_idea"] = ""


def creator_add_log(message: str, level: str = "info"):
    """添加创作流日志"""
    import time
    prefix = "creator_"
    timestamp = time.strftime("%H:%M:%S")
    icons = {
        "info": "📋", "success": "✅", "warning": "⚠️",
        "error": "❌", "agent": "🤖", "system": "⚙️", "episode": "🎬"
    }
    icon = icons.get(level, "📋")
    log_entry = f"[{timestamp}] {icon} {message}"
    if f"{prefix}logs" not in st.session_state:
        st.session_state[f"{prefix}logs"] = []
    st.session_state[f"{prefix}logs"].append(log_entry)


def production_add_log(message: str, level: str = "info"):
    """添加制片流日志"""
    import time
    prefix = "production_"
    timestamp = time.strftime("%H:%M:%S")
    icons = {
        "info": "📋", "success": "✅", "warning": "⚠️",
        "error": "❌", "system": "⚙️"
    }
    icon = icons.get(level, "📋")
    log_entry = f"[{timestamp}] {icon} {message}"
    if f"{prefix}logs" not in st.session_state:
        st.session_state[f"{prefix}logs"] = []
    st.session_state[f"{prefix}logs"].append(log_entry)
