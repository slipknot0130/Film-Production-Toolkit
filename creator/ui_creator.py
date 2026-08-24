"""
creator/ui_creator.py — 创作流UI渲染
======================================

从 AI_Screenwriter_Studio/app.py 提取的创作流完整UI。
适配 session_state 命名空间（creator_ 前缀）和统一 LLM 配置。

新增：跨模式修改工作流（分析→生成修改报告→确认→多智能体执行修改→保存/继续）
"""

import streamlit as st
import time
import threading
import re
import json
from streamlit.runtime.scriptrunner import add_script_run_ctx

from creator.agents_engine import (
    run_showrunner_phase,
    run_showrunner_revision_phase,
    run_scripts_phase,
    run_episode_revision_phase,
    is_micro_drama_mode,
)
from shared.session import (
    CREATOR_IDLE, CREATOR_OUTLINE, CREATOR_SCRIPTS,
    creator_add_log, creator_clear_outputs,
)
from shared.llm_config import (
    SCRIPT_FORMATS, create_openai_client, get_default_model,
)

# Harness 工程化集成
try:
    from harness.checkpoint import CheckpointManager, WorkflowContext
    from harness.config import HarnessConfig
    from harness.memory_store import StructuredMemoryStore
    _HARNESS_AVAILABLE = True
except ImportError:
    _HARNESS_AVAILABLE = False


# 使用命名空间的快捷访问
def _ss(key):
    """快速访问 creator_ 前缀的 session_state"""
    return st.session_state[f"creator_{key}"]

def _set_ss(key, value):
    """快速设置 creator_ 前缀的 session_state"""
    st.session_state[f"creator_{key}"] = value


# =============================================================================
# Harness Checkpoint 工具函数
# =============================================================================

def _get_checkpoint_dir() -> str:
    """获取 checkpoint 存储目录（项目相对路径）"""
    import os
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), ".checkpoints")


def _get_cm() -> CheckpointManager:
    """获取 CheckpointManager 实例（session_state 缓存，避免重复创建）"""
    cached = _ss("_harness_cm")
    if cached is not None:
        return cached
    cp_dir = _get_checkpoint_dir()
    cfg = HarnessConfig(checkpoint_dir=cp_dir)
    cm = CheckpointManager(config=cfg)
    _set_ss("_harness_cm", cm)
    return cm


def _auto_save_checkpoint(name: str = ""):
    """自动保存当前创作流状态到 checkpoint"""
    if not _HARNESS_AVAILABLE:
        return
    try:
        cm = _get_cm()
        ctx = cm.save_current(name=name, prefix="creator_")
        if ctx and ctx.has_content:
            pass  # 保存成功
    except Exception:
        pass  # 静默失败，不影响主流程


def _has_checkpoints() -> bool:
    """检查是否有可恢复的 checkpoint"""
    if not _HARNESS_AVAILABLE:
        return False
    try:
        cm = _get_cm()
        cps = cm.list_checkpoints(workflow_type="creator")
        return len(cps) > 0
    except Exception:
        return False


def _get_latest_checkpoint() -> dict:
    """获取最新 checkpoint 的摘要信息"""
    if not _HARNESS_AVAILABLE:
        return {}
    try:
        cm = _get_cm()
        cps = cm.list_checkpoints(workflow_type="creator", limit=1)
        if not cps:
            return {}
        ctx = cps[0]
        from datetime import datetime
        ts = ctx.timestamp
        try:
            readable_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError, OverflowError):
            readable_time = ""
        return {
            "checkpoint_id": ctx.checkpoint_id,
            "name": ctx.name,
            "current_episode": ctx.current_episode,
            "total_episodes": ctx.total_episodes,
            "timestamp": ts,
            "readable_time": readable_time,
        }
    except Exception:
        return {}


def _restore_latest_checkpoint():
    """恢复最新 checkpoint 到 session_state"""
    if not _HARNESS_AVAILABLE:
        return False
    try:
        cm = _get_cm()
        cps = cm.list_checkpoints(workflow_type="creator", limit=1)
        if not cps:
            return False
        ctx = cm.restore(cps[0].checkpoint_id, prefix="creator_")
        return ctx is not None
    except Exception:
        return False


def _delete_all_checkpoints():
    """清理所有 checkpoint"""
    if not _HARNESS_AVAILABLE:
        return
    try:
        cm = _get_cm()
        cm.delete_all(workflow_type="creator")
    except Exception:
        pass


# =============================================================================
# 进度回调
# =============================================================================

def on_progress(stage: str, content: str, current: int, total: int):
    """进度回调 - 实时更新创作流 UI"""
    _set_ss("current_stage", stage)
    _set_ss("progress_current", current)
    _set_ss("progress_total", total)

    if stage == "outline":
        _set_ss("global_outline", content)
        _set_ss("workflow_stage", CREATOR_OUTLINE)
        _set_ss("stage1_outline", content)

    elif stage == "script_episode":
        existing = _ss("script_content")
        if existing:
            _set_ss("script_content", existing + "\n\n\n" + content)
        else:
            _set_ss("script_content", content)
        _set_ss("current_episode", current)
        _set_ss("total_episodes", total)
        _set_ss("workflow_stage", CREATOR_SCRIPTS)

    elif stage == "episode_revised_ok":
        _replace_episode_in_script(current, content)
        _set_ss("current_episode", current)
        _set_ss("total_episodes", total)
        _set_ss("workflow_stage", CREATOR_SCRIPTS)

    elif stage == "episode_rejected":
        _set_ss("current_episode", current)
        _set_ss("total_episodes", total)
        rejections = _ss("last_doctor_rejection")
        rejections[current] = content
        _set_ss("last_doctor_rejection", rejections)

    elif stage == "episode_progress":
        _set_ss("current_episode", current)
        _set_ss("total_episodes", total)

    elif stage == "script":
        _set_ss("script_content", content)

    elif stage == "memory":
        _set_ss("memory_snapshot", content)
        _set_ss("workflow_stage", CREATOR_SCRIPTS)


def _replace_episode_in_script(episode_num: int, new_content: str):
    """替换指定集数的剧本内容"""
    script = _ss("script_content")
    if not script:
        _set_ss("script_content", new_content)
        return

    separator = "\n\n" + "=" * 40 + "\n\n"
    episodes = script.split(separator)

    replaced = False
    for i, ep in enumerate(episodes):
        match = re.search(r'#?\s*第\s*' + str(episode_num) + r'\s*集', ep.strip())
        if match:
            episodes[i] = new_content
            replaced = True
            break

    if replaced:
        _set_ss("script_content", separator.join(episodes))
    else:
        _set_ss("script_content", script + separator + new_content)


# =============================================================================
# 子线程执行函数
# =============================================================================

def _execute_showrunner_thread(creative_idea, script_format, provider, base_url, api_key, model):
    """阶段一：在子线程中运行架构师生成大纲"""
    _set_ss("workflow_running", True)
    creator_clear_outputs()

    creator_add_log("🚀 启动多智能体编剧工坊（阶段一：生成大纲）...", "system")
    creator_add_log(f"   服务商：{provider}", "info")
    creator_add_log(f"   模型：{model}", "info")

    if is_micro_drama_mode(script_format):
        creator_add_log("🔥 检测到竖屏微短剧模式，注入多巴胺爽剧规则", "system")

    if not api_key and provider != "本地 Ollama":
        creator_add_log("❌ 请先在侧边栏配置 API Key", "error")
        _set_ss("workflow_running", False)
        return

    try:
        context = run_showrunner_phase(
            client=create_openai_client(base_url, api_key),
            model=model,
            creative_idea=creative_idea,
            script_format=script_format,
            log_callback=creator_add_log,
            progress_callback=on_progress
        )

        if context.outline:
            _set_ss("global_outline", context.outline)
            _set_ss("stage1_outline", context.outline)
            _set_ss("stage1_total_episodes", context.total_episodes)
            _set_ss("stage1_creative_idea", creative_idea)
            creator_add_log("✅ 阶段一执行完成，请审核大纲后点击确认", "success")
        else:
            creator_add_log("❌ 阶段一执行失败，未生成大纲", "error")

    except Exception as e:
        creator_add_log(f"❌ 阶段一执行出错：{str(e)}", "error")

    finally:
        _set_ss("workflow_running", False)


def _execute_scripts_thread(creative_idea, script_format, outline, total_episodes, provider, base_url, api_key, model):
    """阶段二：在子线程中运行编剧+医生循环"""
    _set_ss("workflow_running", True)
    _set_ss("current_episode", 0)
    _set_ss("total_episodes", total_episodes)
    _set_ss("script_content", "")

    creator_add_log("🚀 阶段二启动：批量生成剧本...", "system")
    creator_add_log(f"   集数：{total_episodes} 集", "info")

    # Harness: 创建结构化记忆和断点管理器
    harness_memory_store = None
    harness_checkpoint_mgr = None
    if _HARNESS_AVAILABLE:
        try:
            import hashlib
            pid = hashlib.md5(creative_idea.encode()).hexdigest()[:12]
            harness_memory_store = StructuredMemoryStore(
                project_id=f"creator_{pid}",
                config=HarnessConfig(checkpoint_dir=_get_checkpoint_dir()),
            )
            creator_add_log("🧠 Harness 结构化记忆已激活", "info")
        except Exception:
            pass
        try:
            harness_checkpoint_mgr = _get_cm()
        except Exception:
            pass

    # Harness: 创建 ContextRetriever（JIT 上下文检索，降低 token 消耗）
    harness_retriever = None
    if _HARNESS_AVAILABLE and harness_memory_store is not None:
        try:
            from harness.context_retriever import ContextRetriever
            harness_retriever = ContextRetriever(
                outline=outline,
                memory_store=harness_memory_store,
                total_episodes=total_episodes,
                recent_count=3,
            )
        except Exception:
            pass

    try:
        context = run_scripts_phase(
            client=create_openai_client(base_url, api_key),
            model=model,
            creative_idea=creative_idea,
            script_format=script_format,
            outline=outline,
            total_episodes=total_episodes,
            log_callback=creator_add_log,
            progress_callback=on_progress,
            memory_store=harness_memory_store,
            checkpoint_manager=harness_checkpoint_mgr,
            context_retriever=harness_retriever,
        )

        _set_ss("script_content", context.script_content)
        _set_ss("memory_snapshot", context.memory_snapshot)
        creator_add_log("✅ 阶段二执行完成", "success")

        # Harness: 持久化结构化记忆
        if harness_memory_store is not None:
            try:
                harness_memory_store.save()
                stats = harness_memory_store.stats
                creator_add_log(
                    f"📊 记忆统计：角色×{stats['characters']}，"
                    f"伏线×{stats['plot_threads_total']}（活跃{stats['plot_threads_active']}），"
                    f"索引×{stats['episodes_indexed']}",
                    "info"
                )
            except Exception:
                pass

    except Exception as e:
        creator_add_log(f"❌ 阶段二执行出错：{str(e)}", "error")

    finally:
        _set_ss("workflow_running", False)
        # Harness: 阶段二完成后自动保存 checkpoint
        if _ss("script_content"):
            _auto_save_checkpoint(name=f"自动存档-创作完成(第{total_episodes}集)")
    

def _execute_outline_revision_thread(creative_idea, script_format, previous_outline, user_feedback, provider, base_url, api_key, model):
    """大纲定向修改"""
    _set_ss("workflow_running", True)
    _set_ss("hitl_editing_episode", 0)

    creator_add_log("🎯 启动架构师定向修改（大纲）...", "system")
    creator_add_log(f"   修改意见：{user_feedback[:80]}...", "info")

    try:
        context = run_showrunner_revision_phase(
            client=create_openai_client(base_url, api_key),
            model=model,
            creative_idea=creative_idea,
            script_format=script_format,
            previous_outline=previous_outline,
            user_feedback=user_feedback,
            log_callback=creator_add_log,
            progress_callback=on_progress,
        )

        if context.outline:
            _set_ss("global_outline", context.outline)
            _set_ss("stage1_outline", context.outline)
            _set_ss("stage1_total_episodes", context.total_episodes)
            _set_ss("hitl_previous_outline", context.outline)
            _set_ss("hitl_editing_episode", 0)
            creator_add_log("✅ 大纲定向修改完成，请审核后点击确认或继续修改", "success")
        else:
            creator_add_log("❌ 大纲定向修改失败", "error")

    except Exception as e:
        creator_add_log(f"❌ 大纲定向修改出错：{str(e)}", "error")

    finally:
        _set_ss("workflow_running", False)


def _execute_episode_revision_thread(episode_num, total_episodes, script_format, outline, character_settings, previous_summary, memory_snapshot, previous_script, user_feedback, provider, base_url, api_key, model):
    """单集剧本定向精修"""
    _set_ss("workflow_running", True)
    _set_ss("hitl_editing_episode", episode_num)

    # 电影长片格式 → 电影模式（禁止拆集）；默认模式依据已有大纲判断电影/电视
    if script_format == "默认（跟随创意要求）":
        _ol = outline or ""
        work_type = "movie" if ("SCENE" in _ol or "场次" in _ol or "电影" in _ol) else "tv"
    else:
        work_type = "movie" if "电影" in (script_format or "") else "tv"

    creator_add_log(f"🎯 启动第 {episode_num} 集定向精修（编剧→医生审核）...", "system")
    creator_add_log(f"   修改意见：{user_feedback[:80]}...", "info")
    if work_type == "movie":
        creator_add_log("   ⚠️ 电影模式：精修后保持场次结构，不拆分为多集", "info")

    try:
        outline_summary = outline[:1500] if outline else "（大纲摘要）"

        context = run_episode_revision_phase(
            client=create_openai_client(base_url, api_key),
            model=model,
            episode_num=episode_num,
            total_episodes=total_episodes,
            outline_summary=outline_summary,
            character_settings=character_settings,
            previous_summary=previous_summary,
            memory_snapshot=memory_snapshot,
            script_format=script_format,
            previous_script=previous_script,
            user_feedback=user_feedback,
            log_callback=creator_add_log,
            progress_callback=on_progress,
            work_type=work_type,
        )

        if context.script_content:
            prev_scripts = _ss("hitl_previous_episode_scripts")
            prev_scripts[episode_num] = context.script_content
            _set_ss("hitl_previous_episode_scripts", prev_scripts)
            _set_ss("hitl_editing_episode", 0)

    except Exception as e:
        creator_add_log(f"❌ 第 {episode_num} 集定向精修出错：{str(e)}", "error")

    finally:
        _set_ss("workflow_running", False)


def _execute_modification_workflow(script_text: str, modification_report: dict,
                                  provider: str, base_url: str, api_key: str, model: str) -> str:
    """
    根据修改报告，调用多智能体（编剧+医生审核循环）执行剧本修改。
    返回修改后的剧本文本。
    """
    from shared.llm_config import create_openai_client

    # 构造修改指令（将所有建议合并为一段指令）
    suggestions = modification_report.get("suggestions", [])
    instruction_parts = [f"修改方向：{modification_report.get('direction', '')}"]
    for s in suggestions:
        instruction_parts.append(f"【{s.get('priority', '中')}】{s.get('issue', '')} → {s.get('suggestion', '')}")
    modification_instruction = "\n".join(instruction_parts)

    # 逐集修改模式
    episodes_to_modify = modification_report.get("episodes_to_modify", [])
    script_format = st.session_state.get("script_format", "竖屏微短剧（1-2分钟/集）")

    separator = "\n\n" + "=" * 40 + "\n\n"

    # 如果没有指定集数，则全文修改
    if not episodes_to_modify:
        prompt = f"""请根据以下修改意见，对剧本进行修订，输出修订后的完整剧本。

# 修改意见
{modification_instruction}

# 原剧本
{script_text}

请输出修订后的完整剧本，保持原有格式（包括集数标题、场景标记等）。
"""
        try:
            client = create_openai_client(base_url, api_key)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            st.session_state.cross_mode_modification_logs.append(f"❌ 全剧修改失败：{str(e)}")
            return script_text

    # 有指定集数：逐集修改后拼接
    episodes = script_text.split(separator) if separator in script_text else [script_text]
    modified_episodes = list(episodes)

    for idx, ep in enumerate(episodes):
        # 判断该集是否在修改列表中
        ep_num_match = re.search(r'第\s*(\d+)\s*集', ep)
        if ep_num_match:
            ep_num = int(ep_num_match.group(1))
            if ep_num in episodes_to_modify:
                st.session_state.cross_mode_modification_logs.append(f"🔄 正在修改第 {ep_num} 集...")
                try:
                    client = create_openai_client(base_url, api_key)
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content":
                            f"请根据以下修改意见，对这一集剧本进行修订，输出修订后的完整单集剧本。\n\n# 修改意见\n{modification_instruction}\n\n# 原剧本（第{ep_num}集）\n{ep}"}],
                        temperature=0.5,
                    )
                    modified_episodes[idx] = resp.choices[0].message.content.strip()
                except Exception as e:
                    st.session_state.cross_mode_modification_logs.append(f"❌ 第 {ep_num} 集修改失败：{str(e)}")

    return separator.join(modified_episodes)


def _build_modification_instruction_from_feedback(analysis_feedback: dict) -> str:
    """从剧本医生分析反馈中提取关键修改指令，供 LLM 直接执行剧本修改。"""
    if not analysis_feedback or not isinstance(analysis_feedback, dict):
        return "请全面优化剧本的质量、节奏、台词和结构。"

    parts = []

    # 1. 绿灯会 — 受众与情绪定位
    greenlight = analysis_feedback.get("greenlight_decision", {})
    target = greenlight.get("target_audience_and_emotion", "")
    if target:
        parts.append(f"【受众与情绪定位】{target}")

    # 2. 情绪弧线问题
    arc = analysis_feedback.get("emotion_arc_overview", {})
    if arc:
        weak = arc.get("weak_sections", [])
        satisfaction = arc.get("overall_satisfaction", "")
        if weak:
            parts.append(
                f"【情绪弧线修复】整体满意度：{satisfaction}，情绪塌陷段：{'、'.join(weak)}，"
                f"需要加强这些段落的多巴胺节奏和情绪张力"
            )

    # 3. 结构审计
    structure = analysis_feedback.get("story_structure_audit", {})
    if structure:
        for phase_key, phase_label in [("opening", "起"), ("development", "承"),
                                       ("climax", "转"), ("resolution", "合")]:
            phase = structure.get(phase_key, {})
            verdict = phase.get("verdict", "")
            if verdict and any(w in verdict for w in ("不足", "缺失", "弱", "问题")):
                parts.append(
                    f"【起承转合 - {phase_label}】{phase.get('description', '')}（{verdict}），需要重点加强"
                )
        logic = structure.get("logic_consistency", {})
        if logic:
            for h in logic.get("plot_holes", []):
                parts.append(f"【逻辑漏洞】{h}")

    # 4. 结构痛点
    flaws = analysis_feedback.get("structure_flaws", "")
    if flaws:
        parts.append(f"【结构痛点】{flaws}")

    # 5. 反转与伏笔
    tf = analysis_feedback.get("twist_and_foreshadowing", {})
    if tf:
        for t in tf.get("key_twists", []):
            eff = t.get("effectiveness", "")
            if eff in ("中", "低"):
                parts.append(f"【反转增强】{t.get('twist', '')}（有效性：{eff}），需要加强铺垫和冲击力")
        dem = tf.get("deus_ex_machina_risk", "")
        if dem and any(w in dem for w in ("高", "存在")):
            parts.append(f"【机械降神】{dem}，需要用合理的因果链条替代")

    # 6. 人物弧光
    for arc_item in analysis_feedback.get("character_arc_diagnosis", []):
        char = arc_item.get("character", "未知")
        ghost = arc_item.get("ghost", "")
        verdict = arc_item.get("arc_verdict", "")
        if ghost.startswith("❌"):
            parts.append(f"【人物缺陷】{char}：前史创伤(Ghost)缺失，纸片人风险！需要补充背景故事和深层动机")
        elif verdict and any(w in verdict for w in ("不足", "弱")):
            parts.append(f"【人物弧光】{char}：弧光{verdict}，需要加强成长转变的铺垫")

    # 7. 写作违规
    violations = analysis_feedback.get("writing_violations", [])
    if violations:
        v_strs = [f"[{v.get('location', '')}] {v.get('type', '')}" for v in violations[:10]]
        parts.append(f"【写作红线 - 共{len(violations)}项】{'；'.join(v_strs)}，必须逐一修正")

    # 8. 台词优化
    dialogue = analysis_feedback.get("dialogue_impact_check", [])
    if dialogue:
        d_strs = []
        for d in dialogue[:8]:
            rw = d.get("rewrite", "")
            if rw:
                d_strs.append(f"原台词：{d.get('original', '')} → 建议改为：{rw}")
        if d_strs:
            parts.append(f"【台词优化 - 共{len(dialogue)}项】" + "；".join(d_strs))

    # 9. 送审风险
    censor = analysis_feedback.get("censorship_risk", {})
    if censor:
        risk = censor.get("risk_level", "")
        sensitive = censor.get("sensitive_elements", [])
        if risk and any(w in risk for w in ("极高", "中等")):
            c_strs = [f"{item.get('element', '')}（建议：{item.get('advice', '')}）" for item in sensitive]
            parts.append(f"【送审风险 - {risk}】{'；'.join(c_strs)}，必须修改以降低送审风险")

    # 10. Save the Cat 节拍（电影模式）
    beats = analysis_feedback.get("beat_mapping_sheet", [])
    if beats and isinstance(beats, list):
        weak_beats = []
        for b in beats:
            diag = b.get("rhythm_diagnosis", "")
            if any(w in diag for w in ("弱", "不足", "缺失", "未达标")):
                weak_beats.append(f"{b.get('beat_name', '')}（{diag}）")
        if weak_beats:
            parts.append(f"【节拍修复】以下节拍需要加强：{'；'.join(weak_beats)}")

    # 11. McKee 场景价值审计（电影模式）
    mckee = analysis_feedback.get("mckee_value_audit", [])
    if mckee and isinstance(mckee, list):
        weak_scenes = [f"场景{m.get('scene', '')}（{m.get('verdict', '')}）"
                       for m in mckee if "无" in m.get("verdict", "") or "弱" in m.get("verdict", "")]
        if weak_scenes:
            parts.append(f"【场景价值转变】以下场景缺乏价值转变：{'；'.join(weak_scenes)}")

    if not parts:
        return "请全面优化剧本的质量、节奏、台词和结构。"

    return "\n".join(parts)


def _clear_modification_state():
    """清除跨模式修改工作流的所有状态，回到初始状态"""
    st.session_state.cross_mode_modified_script = ""
    st.session_state.cross_mode_modification_report = None
    st.session_state.cross_mode_show_report = False
    st.session_state.cross_mode_report_confirmed = False
    st.session_state.cross_mode_modifying = False
    st.session_state.cross_mode_modification_logs = []
    st.session_state.cross_mode_modification_progress = 0
    st.session_state.cross_mode_modification_current_step = ""
    st.session_state.cross_mode_modification_start_time = 0
    st.session_state.cross_mode_modification_error = ""
    st.session_state.cross_mode_show_bridge = False


# =============================================================================
# 剧本调整功能
# =============================================================================

# ═════════════════════════════════════════════════════════════════════════════
# 电影专用改编 Prompt（work_type = 'movie'）
# 核心区别：电影不分集，按「幕 / 场次(SCENE)」组织，禁止输出「第X集」
# ═════════════════════════════════════════════════════════════════════════════

# 电影改编 System Prompt（单次调用 / 全局约束版）
_REWRITE_MOVIE_PROMPT = """你是一位专业的电影编剧，负责根据用户指令将剧本调整为电影文学剧本（screenplay）。

## ⛔ 最高红线（绝对不可违反，优先级高于一切）
- **这是电影，必须全篇整体输出；绝对禁止输出「第X集」格式，也绝对禁止把剧本拆分为多集。**
- 电影剧本统一按「幕(Act) / 场次(SCENE)」组织；即使原稿是电视剧「第X集」结构，
  你也必须在改编时把多集内容重新整合为一条完整的电影叙事线（单部电影），不得保留任何「第X集」标题。
- 若因上下文长度截断无法一次写完，必须在文末注明"（待续）"，绝不伪造成「已完成的多集」。

## 第一准则：改编方向由【改编指令】决定
- 严格、逐条遵循用户在【改编指令】中给出的命令；指令里包含的具体修改意见，必须全部落实。
- 改编的风格 / 结构 / 基调（如情绪导向、三幕式、特定类型片套路等）一律以改编指令为准：
  指令指定了就照做，指令未指定则保持原剧本的原有风格与基调，不要自作主张改变。
- 只改指令要求改的地方；原本没有问题的内容保持不动。

## 核心原则（电影工业通用标准，按指令取舍）
1. **结构完整**：建置 → 对抗 → 解决 的节奏清晰（具体幕数 / 结构以指令为准）
2. **人物弧光**：主角要有内在成长或蜕变，动机充分
3. **逻辑自洽**：情节转折有因果关系，禁用机械降神
4. **视觉化写作**：用镜头语言思考，场景描写服务银幕呈现

## 输出格式
请输出**完整、连续**的改编后电影剧本，使用「幕/场次」结构。
每场用 "SCENE N - 内景/外景 地点 - 时间" 标注，N 为全局连续场次编号。

## ⚠️ 格式约束（最高优先级，绝对不可违反）
{episode_constraint}
"""

# 电影分块改编专用 System Prompt（不含全局约束，避免与每块指令冲突）
_CHUNK_MOVIE_PROMPT = """你是一位专业的电影编剧，负责根据用户指令将剧本调整为电影文学剧本（screenplay）。

## ⛔ 最高红线：这是电影，必须全篇整体输出
- **绝对禁止输出「第X集」格式，绝对禁止拆分为多集。**
- 电影按「幕(Act) / 场次(SCENE)」组织，每场用 "SCENE N - 内景/外景 地点 - 时间" 标注。

## 第一准则：改编方向由【改编指令】决定
- 严格遵循用户消息中的改编指令；指令中的具体修改意见必须落实。
- 风格 / 结构以指令为准，未指定则保持原剧本基调。

## 核心原则
1. 结构完整、人物弧光清晰、逻辑自洽、视觉化写作
2. 只改指令要求改的地方，不动原本没问题的内容

## 输出格式
每场用 "SCENE N - 内景/外景 地点 - 时间" 标注，N 为全局连续场次编号。
你必须严格遵守用户消息中的【场次要求】，不得输出「第X集」格式或拆分为多集。"""

# 电视剧改编 Prompt（改编方向由用户指令决定，不绑定任何固定风格）
_REWRITE_TV_PROMPT = """你是一位专业的电视剧编剧，负责根据用户指令调整电视剧剧本。

## 第一准则：改编方向由【改编指令】决定
- 严格、逐条遵循用户在【改编指令】中给出的命令；指令里包含的具体修改意见，必须全部落实。
- 改编的风格 / 结构 / 基调（如情绪导向、多巴胺爽剧、特定类型套路等）一律以改编指令为准：
  指令指定了就照做，指令未指定则保持原剧本的原有风格与基调，不要自作主张改变。

## 单集 / 全剧本 处理规则（关键）
{input_mode_rule}

## 核心原则（按指令取舍）
1. 节奏与情绪到位，钩子清晰，逻辑自洽
2. 人物动机充分，情节转折有因果关系
3. 视觉化、可拍摄

## 输出格式
请输出完整的调整后剧本，格式与原剧本保持一致。
每集用"========================================"分隔，开头标注"第X集"。

## ⚠️ 集数约束（最高优先级，绝对不可违反）
{episode_constraint}
"""

# ═════════════════════════════════════════════════════════════════════════════
# 分块改编专用 System Prompt（不含全局集数约束，避免与每块指令冲突）
# ═════════════════════════════════════════════════════════════════════════════
_CHUNK_TV_PROMPT = """你是一位专业的电视剧编剧，负责根据用户指令调整电视剧剧本。

## 第一准则：改编方向由【改编指令】决定
- 严格遵循用户消息中的改编指令；指令中的具体修改意见必须落实。
- 风格 / 结构以指令为准，未指定则保持原剧本基调。

## 合并策略（压缩时减少集数）
- **必须合并**：将相邻的铺垫集合并，保留核心情绪爆点
- **合并公式**：N集原文 → M集目标 = 每 (N/M) 集原文合并为1集目标
- **示例**：15集原文→10集目标：将第1+2集合并为新第1集，第3+4集合并为新第2集，第5集保留为新第3集...以此类推
- **保留原则**：核心反转、爽点、钩子必须保留；纯过渡、重复冲突可删除或压缩
- **禁止行为**：不得将每集原文简单复制为一集目标——必须真正合并内容
- **只按指令合并**：原本已符合要求的集不要为了"整齐"而强行改动

## 拆分策略（扩充时增加集数）
- 每个情绪高潮前增加铺垫集，新增副线穿插
- 严格按指令要求拆分，不乱加无关内容

## 输出格式
每集用"========================================"分隔，开头标注"第X集"。
你必须严格遵守用户消息中的【集数要求】，一集不多，一集不少。"""

def _parse_episode_numbers(instruction: str, source_text: str) -> tuple[int, int]:
    """
    从改编指令和原始剧本中解析：原始集数 src_ep、目标集数 tgt_ep。
    返回 (src_ep, tgt_ep)，无法解析时返回 (0, 0)。
    """
    # 匹配"X集改成Y集"、"X集压缩为Y集"、"X集扩充到Y集"等各种表述
    # 注意：正则顺序很重要——更具体的模式放前面
    patterns = [
        # 标准格式：60集改成/压缩/扩充/精简/缩减/调整 成/为/到/至 40集
        r'(\d+)\s*集\s*(?:改(?:成|编|写|为)|压缩(?:为|到|成|至)|扩充(?:为|到|成|至)|精简(?:为|到|成|至)|缩减(?:为|到|成|至)|调整(?:为|到|成|至))\s*(\d+)\s*集',
        # 从X集改/变/到/压缩/扩充 为/成/到/至 Y集
        r'从\s*(\d+)\s*集\s*(?:改|变|到|压缩|扩充|缩减|精简|调整)\s*(?:为|成|到|至)?\s*(\d+)\s*集',
        # X集 →/-/-> Y集
        r'(\d+)\s*集\s*(?:→|-|->)\s*(\d+)\s*集',
        # 目标: Y集 原始: X集
        r'目标\s*[:：]?\s*(\d+)\s*集.*?原(?:始|始剧本)?\s*[:：]?\s*(\d+)\s*集',
        # 原始: X集 目标: Y集
        r'原(?:始|剧本)?\s*[:：]?\s*(\d+)\s*集.*?目标\s*[:：]?\s*(\d+)\s*集',
        # 宽泛匹配：把/将X集剧本...到/为/成Y集
        r'(?:把|将|把这个|将这个|把该|将该|把原有|将原有)\s*(\d+)\s*集.*?(?:扩充|压缩|改编|改成|改写|精简|缩减|调整|扩展|延伸|拉长).*?(?:到|为|成|至)\s*(\d+)\s*集',
        # 宽泛匹配：...X集...到/为/成Y集
        r'(?:扩充|压缩|改编|改成|改写|精简|缩减|调整|扩展|延伸|拉长|改).*?(\d+)\s*集.*?(?:到|为|成|至)\s*(\d+)\s*集',
        # 数字范围：X集 - Y集、X集~Y集
        r'(\d+)\s*集\s*(?:[-~～])\s*(\d+)\s*集',
    ]
    for p in patterns:
        m = re.search(p, instruction)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            # 智能判断哪个是原始哪个是目标：
            # 如果 a > b，大概率是压缩（a是原始，b是目标）
            # 如果 a < b，大概率是扩充（a是原始，b是目标）
            # 但用户也可能说"目标40集，原始60集"，这时需要看pattern
            return (a, b)

    # ═══════════════════════════════════════════════════════════════
    # 兜底逻辑：正则没匹配到，从指令和正文中提取数字
    # ═══════════════════════════════════════════════════════════════
    single = re.findall(r'(\d+)\s*集', instruction)

    # 从剧本正文统计集数（最大集号）
    ep_nums = re.findall(r'第\s*(\d+)\s*集', source_text)
    src_ep = max((int(x) for x in ep_nums), default=0) if ep_nums else 0

    if not single:
        # 指令中完全没有"X集"格式
        return (src_ep, 0)

    if len(single) >= 2:
        # 指令中有两个及以上数字，取较大的当原始、较小的当目标
        # 原因："60集缩减到40集"里，60和40都会匹配到
        # 原始集数通常 >= 目标集数（压缩场景更常见）
        nums = sorted([int(x) for x in single])
        # 如果正文统计的src_ep和其中一个接近，就用另一个当目标
        if src_ep > 0:
            # 找离 src_ep 最近的数字当原始，另一个当目标
            closest = min(nums, key=lambda x: abs(x - src_ep))
            tgt = [n for n in nums if n != closest]
            if tgt:
                return (closest, tgt[0])
        # 默认：较大的当原始，较小的当目标
        return (nums[-1], nums[0])
    else:
        # 只有一个数字：把它当目标集数
        tgt_from_instruction = int(single[0])
        return (src_ep, tgt_from_instruction)


def _build_episode_constraint(src_ep: int, tgt_ep: int, instruction: str) -> str:
    """根据解析到的集数生成强约束文字。"""
    if tgt_ep > 0 and src_ep > 0:
        action = "压缩" if tgt_ep < src_ep else "扩充"
        return (
            f"- 原始剧本共 **{src_ep} 集**，目标改编为 **{tgt_ep} 集**（{action}）\n"
            f"- 你**必须**输出恰好 **{tgt_ep} 集**，不得多也不得少\n"
            f"- 从第1集写到第{tgt_ep}集，每集都要有完整的场景和对白\n"
            f"- 如果内容被截断导致写不完，必须在截断前输出已完成的集数，并在末尾注明'已完成前X集，后续待续'\n"
            f"- 绝对禁止：输出少于 {tgt_ep} 集后就停止，且不做任何说明"
        )
    elif tgt_ep > 0:
        return (
            f"- 目标集数：**{tgt_ep} 集**（绝对约束）\n"
            f"- 你**必须**输出恰好 **{tgt_ep} 集**，从第1集写到第{tgt_ep}集\n"
            f"- 每集都要有完整的场景和对白，不得只写标题或摘要"
        )
    else:
        # 无法解析集数，返回通用约束
        return (
            f"- 严格按照改编指令执行集数要求，不得随意增减集数\n"
            f"- 必须输出指令中明确要求的目标集数，不得提前结束"
        )


def _detect_tv_input_mode(source_text: str) -> str:
    """判断电视剧输入是单集还是全剧本。返回 'single' 或 'full'。"""
    ep_markers = re.findall(r'第\s*(\d+)\s*集', source_text)
    unique_eps = set(ep_markers)
    if len(unique_eps) <= 1:
        return "single"
    return "full"


def _build_tv_mode_rule(input_mode: str) -> str:
    """根据电视剧输入模式（单集/全剧本）生成硬性处理规则。"""
    if input_mode == "single":
        return (
            "- 用户提交的是【单集】剧本：请仅针对该集按改编指令调整，"
            "不要自行扩展或补全出其他集；输出保持单集结构。\n"
            "- 若指令要求改写该集内容，在原有单集框架内完成，保留「第X集」标题。\n"
        )
    return (
        "- 用户提交的是【全剧本】（含多集）：请**逐集**按照各自的标准进行修改和校验，"
        "保留原有「第X集」标题与顺序，确保每集内容与改编指令一一对应。\n"
        "- **只按改编指令中的修改意见改动**：对于原本已经符合要求的集 / 段落，"
        "保持原样，**不得为「优化」而擅自修改没有问题的内容**。\n"
        "- 若指令未针对某一集提出意见，则该集原样保留，不做任何改写。\n"
    )


# ═════════════════════════════════════════════════════════════════════════════
# 电影模式：场次(SCENE)解析与约束
# ═════════════════════════════════════════════════════════════════════════════

def _parse_movie_scenes(instruction: str, source_text: str) -> tuple[int, int]:
    """
    电影模式：从改编指令和原始剧本中解析「原始场次 / 目标场次」。
    电影没有「集」的概念，统一用 SCENE 场次计数。
    返回 (src_sc, tgt_sc)，无法解析时返回 (0, 0)。

    兼容输入：
    - "将30场扩充为50场" / "压缩到40场"
    - 原剧本统计 SCENE 标记数量作为 src_sc 兜底
    """
    # 匹配「X场改成Y场」等表述（电影用"场"而非"集"）
    patterns = [
        r'(\d+)\s*场\s*(?:改(?:成|编|写|为)|压缩(?:为|到|成|至)|扩充(?:为|到|成|至)|精简(?:为|到|成|至)|缩减(?:为|到|成|至)|调整(?:为|到|成|至))\s*(\d+)\s*场',
        r'从\s*(\d+)\s*场\s*(?:改|变|到|压缩|扩充|缩减|精简|调整)\s*(?:为|成|到|至)?\s*(\d+)\s*场',
        r'(\d+)\s*场\s*(?:→|-|->)\s*(\d+)\s*场',
        r'(?:把|将|把这个|将这个)\s*(\d+)\s*场.*?(?:扩充|压缩|改编|改成|改写|精简|缩减|调整|扩展|延伸|拉长).*?(?:到|为|成|至)\s*(\d+)\s*场',
        r'(?:扩充|压缩|改编|改成|改写|精简|缩减|调整|扩展|延伸|拉长|改).*?(\d+)\s*场.*?(?:到|为|成|至)\s*(\d+)\s*场',
    ]
    for p in patterns:
        m = re.search(p, instruction)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            return (a, b)

    # 兜底：从指令中提取所有"X场"
    single = re.findall(r'(\d+)\s*场', instruction)
    # 从剧本正文统计场次（SCENE N / 场N）
    sc_nums = re.findall(r'(?:SCENE|场)\s*(\d+)', source_text, re.IGNORECASE)
    src_sc = max((int(x) for x in sc_nums), default=0) if sc_nums else 0

    if not single:
        return (src_sc, 0)

    if len(single) >= 2:
        nums = sorted([int(x) for x in single])
        if src_sc > 0:
            closest = min(nums, key=lambda x: abs(x - src_sc))
            tgt = [n for n in nums if n != closest]
            if tgt:
                return (closest, tgt[0])
        return (nums[-1], nums[0])
    else:
        return (src_sc, int(single[0]))


def _build_movie_constraint(src_sc: int, tgt_sc: int, instruction: str) -> str:
    """电影模式：根据解析到的场次生成强约束文字（禁止出现「第X集」）。"""
    constraint = (
        "- **这是电影剧本，绝对禁止输出「第X集」格式**，必须按幕/场次(SCENE)组织。\n"
    )
    if tgt_sc > 0 and src_sc > 0:
        action = "压缩" if tgt_sc < src_sc else "扩充"
        constraint += (
            f"- 原始剧本约 **{src_sc} 场**，目标改编为 **{tgt_sc} 场**（{action}）\n"
            f"- 你**必须**输出恰好 **{tgt_sc} 场**（SCENE 1 到 SCENE {tgt_sc}），不得多也不得少\n"
            f"- 场次用连续编号标注：SCENE 1, SCENE 2, ... SCENE {tgt_sc}\n"
            f"- 若原剧本是「第X集」电视剧结构，必须重新整合为电影场次线，不得保留集标题"
        )
    elif tgt_sc > 0:
        constraint += (
            f"- 目标场次：**{tgt_sc} 场**（绝对约束）\n"
            f"- 你**必须**输出恰好 **{tgt_sc} 场**（SCENE 1 到 SCENE {tgt_sc}）\n"
            f"- 每场都要有完整的场景描写和对白"
        )
    else:
        constraint += (
            "- 严格按照改编指令执行，输出完整电影剧本（幕/场次结构），不得拆分为多集\n"
            "- 若原剧本是「第X集」结构，必须转换为电影场次线"
        )
    return constraint


def _split_source_by_scenes(source_text: str) -> list[dict]:
    """
    电影模式：按场次标记切分原始剧本，返回 [{sc_start, sc_end, content}, ...]
    兼容「第X集」电视剧结构（转为单部电影处理，不按集拆分）。
    """
    # 优先按 SCENE / 场 标记切分
    scene_pattern = r'((?:SCENE|场)\s*\d+\s*[-—–]?\s*(?:内景|外景|INT|EXT)?[^\\n]*)'
    splits = re.split(scene_pattern, source_text, flags=re.IGNORECASE)
    if len(splits) > 2:
        blocks = []
        i = 1
        while i < len(splits):
            label = splits[i].strip()
            nums = re.findall(r'(\d+)', label)
            sc_num = int(nums[0]) if nums else 0
            content_parts = []
            while i + 1 < len(splits):
                nxt = splits[i + 1]
                if re.match(r'(?:SCENE|场)\s*\d+', nxt.strip(), re.IGNORECASE):
                    break
                content_parts.append(nxt)
                i += 1
            content = label + "".join(content_parts)
            blocks.append({"sc_start": sc_num, "sc_end": sc_num, "content": content.strip()})
            i += 1
        if blocks:
            return blocks

    # 退而求其次：按「第X集」切分后再合并为单部电影（电影模式不保留集结构）
    sep = "========================================"
    if sep in source_text:
        parts = [p.strip() for p in source_text.split(sep) if p.strip()]
        if parts:
            return [{"sc_start": 0, "sc_end": 0, "content": "\n\n".join(parts)}]

    # 兜底：按段落均分
    paragraphs = [p for p in source_text.split('\n') if p.strip()]
    if not paragraphs:
        return [{"sc_start": 0, "sc_end": 0, "content": source_text}]
    chunk_size = max(5, len(paragraphs) // max(1, len(paragraphs) // 15))
    blocks = []
    for i in range(0, len(paragraphs), chunk_size):
        chunk = "\n".join(paragraphs[i:i + chunk_size])
        blocks.append({"sc_start": 0, "sc_end": 0, "content": chunk})
    return blocks


# =============================================================================
# 分块调整流水线核心函数
# =============================================================================

def _split_source_by_episodes(source_text: str) -> list[dict]:
    """
    按集数标记切分原始剧本，返回 [{ep_start, ep_end, content}, ...]
    无集数标记时按段落均分。
    """
    # 尝试按 "第X集" 切分
    sep = "========================================"
    # 优先用分隔线切分
    if sep in source_text:
        parts = source_text.split(sep)
        blocks = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # 提取本段集号
            ep_nums = re.findall(r'第\s*(\d+)\s*集', part)
            ep_start = int(ep_nums[0]) if ep_nums else 0
            ep_end = int(ep_nums[-1]) if ep_nums else 0
            blocks.append({"ep_start": ep_start, "ep_end": ep_end, "content": part})
        if blocks:
            return blocks

    # 退而求其次：按 "第X集" 标记切分
    pattern = r'(第\s*\d+\s*集)'
    splits = re.split(pattern, source_text)
    if len(splits) > 2:
        blocks = []
        i = 1  # splits[0] 是分隔前的文本
        while i < len(splits):
            ep_label = splits[i].strip()
            ep_nums = re.findall(r'(\d+)', ep_label)
            ep_num = int(ep_nums[0]) if ep_nums else 0
            # 收集内容直到下一个标记
            content_parts = []
            while i + 1 < len(splits):
                next_part = splits[i + 1]
                # 检查下一部分是否包含新的集标记
                if re.match(r'第\s*\d+\s*集', next_part.strip()):
                    break
                content_parts.append(next_part)
                i += 1
            content = ep_label + "".join(content_parts)
            blocks.append({"ep_start": ep_num, "ep_end": ep_num, "content": content.strip()})
            i += 1
        if blocks:
            return blocks

    # 没有集数标记：按段落均分为若干块
    paragraphs = [p for p in source_text.split('\n') if p.strip()]
    if not paragraphs:
        return [{"ep_start": 0, "ep_end": 0, "content": source_text}]

    # 每15个段落一块（兜底）
    chunk_size = max(5, len(paragraphs) // max(1, len(paragraphs) // 15))
    blocks = []
    for i in range(0, len(paragraphs), chunk_size):
        chunk = "\n".join(paragraphs[i:i + chunk_size])
        blocks.append({"ep_start": 0, "ep_end": 0, "content": chunk})
    return blocks


def _generate_story_summary(client, model, provider, source_text: str,
                            rewrite_instruction: str,
                            extra: dict) -> str:
    """
    Phase 0：分析原始剧本，生成结构摘要（人物/情节线/设定/关键伏笔）。
    此摘要将作为后续每块改写的"全局记忆"传入。
    """
    summary_prompt = f"""你是一位资深剧本分析师。请对以下原始剧本进行全面分析，输出一份结构化摘要。

## 分析要求
1. **主要人物**：列出所有重要角色，包括姓名、身份、性格特征、关键关系
2. **核心情节线**：列出主线和所有重要支线的起承转合
3. **世界观/设定**：故事背景、核心设定、特殊规则
4. **关键伏笔与悬念**：已埋下的伏笔和未解决的悬念
5. **情感弧线**：主角及核心配角的情感变化轨迹
6. **改编方向提示**：根据改编指令「{rewrite_instruction}」，指出哪些内容必须保留、哪些可以删减/合并/扩充

## 输出格式
用结构化列表，每个条目不超过2行，力求精简但信息完整。"""

    user_msg = f"{summary_prompt}\n\n---\n\n## 原始剧本\n\n{source_text}"

    # 非流式调用——摘要不需要流式展示
    is_ollama = "Ollama" in provider
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": "你是专业的剧本分析师，输出精简准确的结构化摘要。"},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        stream=False,
    )
    if is_ollama:
        kwargs["extra_body"] = {"options": {"num_ctx": 131072, "num_predict": 8192}}
    else:
        kwargs["max_tokens"] = 8192

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _generate_rewrite_report(client, model, provider, source_text: str,
                             modified_text: str, instruction: str, work_type: str) -> str:
    """
    调整完成后生成「建议修改报告」：对比【原始剧本】与【调整后剧本】，
    列出关键改动、一致性核查、优化建议与风险提醒，辅助用户决策。
    """
    unit = "场" if work_type == "movie" else "集"
    system = (
        "你是一位资深的剧本审读编辑与制片统筹。用户刚对剧本做了一次改编，"
        "你需要对比【原始剧本】与【调整后剧本】，产出一份简明、可执行的「建议修改报告」。\n\n"
        "报告必须严格使用以下 Markdown 五段结构：\n"
        "## 一、改编概要\n用 2-3 句话说明本次改编依据用户指令完成了哪些核心改动"
        "（扩集/缩集/人物调整/情节增删/类型转换等）。\n"
        "## 二、关键改动清单\n用无序列表逐条列出 5-10 条关键改动（保留/新增/删除/调整），每条一句话。\n"
        "## 三、一致性核查\n检查人物动机、时间线、逻辑链是否存在明显前后矛盾或漏洞，"
        "没有则明确写「未发现明显一致性问题」。\n"
        "## 四、优化建议\n给出 2-4 条具体、可执行的下一步修改建议（每条一句话）。\n"
        "## 五、风险提醒\n如存在集数/场次未达标、节奏拖沓、情绪点不足等风险，明确标出；"
        "无则写「暂无重大风险」。\n\n"
        "使用简体中文，条理清晰，直接输出报告，不要额外寒暄。"
    )
    src_excerpt = source_text[:6000]
    mod_excerpt = modified_text[:6000]
    user = (
        f"## 用户改编指令\n{instruction}\n\n"
        f"## 原始剧本（节选前6000字）\n{src_excerpt}\n\n"
        f"## 调整后剧本（节选前6000字）\n{mod_excerpt}\n\n"
        f"## 任务\n请基于上述材料生成「建议修改报告」。注意：原始与调整后剧本可能较长，"
        f"请基于用户指令和节选合理推断整体改动，并按要求的五段结构输出。"
    )
    is_ollama = "Ollama" in provider
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.4,
        stream=True,
    )
    if is_ollama:
        kwargs["extra_body"] = {"options": {"num_ctx": 131072, "num_predict": 4096}}
    else:
        kwargs["max_tokens"] = 4096
    report = ""
    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if delta:
                report += delta
    except Exception:
        report = ""
    return report.strip()


def _rewrite_single_chunk(client, model, provider, style_prompt: str,
                          chunk_content: str, story_summary: str,
                          rewrite_instruction: str,
                          src_ep_start: int, src_ep_end: int,
                          tgt_ep_start: int, tgt_ep_end: int,
                          prev_tail: str, extra: dict,
                          status_container, progress_text) -> str:
    """
    单块改写。流式输出，实时更新UI。

    参数：
      chunk_content  : 本块原始剧本片段
      story_summary  : Phase 0 生成的全局摘要
      rewrite_instruction : 用户改编指令
      src_ep_start/end : 本块包含的原始集数范围
      tgt_ep_start/end : 本块应输出的目标集数范围
      prev_tail      : 上一块改写结果的末尾（用于衔接）
      extra          : LLM调用参数（max_tokens/num_predict）
      status_container / progress_text : UI更新用

    返回：本块改写后的完整文本（已校验/截断至目标集数）
    """
    src_count = src_ep_end - src_ep_start + 1
    tgt_count = tgt_ep_end - tgt_ep_start + 1

    # ═══════════════════════════════════════════════════════════════
    # 生成显式合并映射指导（告诉模型具体怎么合并）
    # ═══════════════════════════════════════════════════════════════
    ratio = src_count / tgt_count if tgt_count > 0 else 1.0
    if ratio > 1.0:
        # 压缩：生成合并建议
        merge_lines = []
        src_idx = src_ep_start
        for t_i in range(tgt_count):
            # 每集目标分配 ratio 集原文（向上取整/向下取整交替）
            base = src_count // tgt_count
            rem = src_count % tgt_count
            take = base + (1 if t_i < rem else 0)
            end_src = min(src_idx + take - 1, src_ep_end)
            if src_idx == end_src:
                merge_lines.append(f"  新第{tgt_ep_start + t_i}集 = 原文第{src_idx}集（单独保留）")
            else:
                merge_lines.append(f"  新第{tgt_ep_start + t_i}集 = 原文第{src_idx}-{end_src}集（合并）")
            src_idx = end_src + 1
        merge_guide = "\n".join(merge_lines)
        action_desc = f"压缩：{src_count}集原文 → {tgt_count}集目标（压缩比 {ratio:.1f}:1）"
    elif ratio < 1.0:
        # 扩充
        action_desc = f"扩充：{src_count}集原文 → {tgt_count}集目标（扩充比 1:{1/ratio:.1f}）"
        merge_guide = f"  将每集原文拆分为约 {tgt_count/src_count:.0f} 集，增加铺垫和细节。"
    else:
        action_desc = f"等比改写：{src_count}集原文 → {tgt_count}集目标（1:1）"
        merge_guide = "  逐集改写，保持集数不变。"

    # 构造上下文
    context_parts = []
    if story_summary:
        context_parts.append(f"## 全剧摘要（全局参考）\n{story_summary}")
    if prev_tail:
        context_parts.append(
            f"## 前情衔接（上一段改写结果的末尾，必须与此衔接）\n{prev_tail}"
        )
    context_block = "\n\n".join(context_parts)

    # ═══════════════════════════════════════════════════════════════
    # 重组 User Msg：集数要求放在最前面、最醒目
    # ═══════════════════════════════════════════════════════════════
    user_msg = f"""【🚨 集数要求 — 最高优先级，绝对不可违反】

{action_desc}
你必须输出恰好 {tgt_count} 集，从第 {tgt_ep_start} 集到第 {tgt_ep_end} 集。
一集不多，一集不少。每集必须有完整的场景和对白。

【合并/拆分映射参考】（必须按此执行）
{merge_guide}

⚠️ 警告：如果你简单复制原文集数而不合并，输出会超出要求并被截断丢弃。

---

## 改编指令
{rewrite_instruction}

---

{context_block}

---

## 本段原始剧本（{src_count}集，参考用）

{chunk_content}

---

## 输出要求
1. 输出第 {tgt_ep_start} 集到第 {tgt_ep_end} 集，共 {tgt_count} 集
2. 如果这是第一段（第{tgt_ep_start}集起），开头必须与全剧开头一致
3. 如果不是第一段，开头必须与前情衔接自然，不得突兀跳转
4. 每集用"========================================"分隔，开头标注"第X集"
5. 每集必须有完整的场景和对白，不得只写标题或摘要"""

    is_ollama = "Ollama" in provider
    # 每块改写的 max_tokens = 集数 × 2500，最低 8192，最高 32768
    chunk_max_tokens = max(8192, min(32768, tgt_count * 2500))
    if not is_ollama:
        # 云端服务商必须钳制：超上限不是被截断，而是整个请求 400 失败。
        # DeepSeek 上限 8192，tgt_count ≥ 4 时这里就会算出 10000+ 直接打挂。
        from shared.llm_config import clamp_max_tokens
        chunk_max_tokens = clamp_max_tokens(chunk_max_tokens, provider, model)
    if is_ollama:
        chunk_kwargs = dict(
            model=model,
            messages=[
                {"role": "system", "content": style_prompt},
                {"role": "user", "content": user_msg},
            ],
            stream=True,
            temperature=0.8,
            extra_body={"options": {"num_ctx": 131072, "num_predict": chunk_max_tokens}},
        )
    else:
        chunk_kwargs = dict(
            model=model,
            messages=[
                {"role": "system", "content": style_prompt},
                {"role": "user", "content": user_msg},
            ],
            stream=True,
            temperature=0.8,
            max_tokens=chunk_max_tokens,
        )

    import time as _time
    chunk_result = ""
    start = _time.time()

    try:
        stream = client.chat.completions.create(**chunk_kwargs)
        last_ui = _time.time()
        for c in stream:
            if not c.choices:
                continue
            choice = c.choices[0]
            delta = choice.delta.content or ""
            if not delta:
                if choice.finish_reason:
                    break
                continue
            chunk_result += delta
            now = _time.time()
            if now - last_ui >= 0.5:
                last_ui = now
                try:
                    chars = len(chunk_result)
                    done = len(re.findall(r'第\s*\d+\s*集', chunk_result))
                    progress_text.markdown(
                        f"✍️ 第{tgt_ep_start}-{tgt_ep_end}集改写中... "
                        f"已输出 **{chars:,}** 字 | 已完成约 **{done}/{tgt_count}** 集"
                    )
                except Exception:
                    pass
    except Exception as e:
        if chunk_result:
            pass
        else:
            raise

    # ═══════════════════════════════════════════════════════════════
    # 后处理：校验集数，超限则截断
    # ═══════════════════════════════════════════════════════════════
    ep_markers = list(re.finditer(r'第\s*(\d+)\s*集', chunk_result))
    actual_ep_count = len(ep_markers)

    if actual_ep_count > tgt_count and tgt_count > 0:
        # 找到第 tgt_count+1 个集标记的位置，从那里截断
        cutoff = ep_markers[tgt_count].start()
        chunk_result = chunk_result[:cutoff].strip()
        progress_text.markdown(
            f"⚠️ 本块模型输出了 {actual_ep_count} 集（超限），"
            f"已自动截断至 {tgt_count} 集"
        )
    elif actual_ep_count < tgt_count and tgt_count > 0:
        progress_text.markdown(
            f"⚠️ 本块仅输出 {actual_ep_count} 集，"
            f"后续将尝试补写缺失的 {tgt_count - actual_ep_count} 集"
        )

    return chunk_result


def _compute_chunk_plan(src_ep: int, tgt_ep: int, source_blocks: list[dict]) -> list[dict]:
    """
    计算分块改编计划：将原始集数块分组，映射到目标集数范围。

    返回: [{
        src_blocks: [原始块索引],    # 本轮要处理的原始块
        src_ep_range: (start, end),  # 原始集数范围
        tgt_ep_range: (start, end),  # 目标集数范围
    }, ...]
    """
    if not source_blocks:
        return []

    total_src = src_ep if src_ep > 0 else len(source_blocks)
    total_tgt = tgt_ep if tgt_ep > 0 else total_src

    # 决定分几块：每块目标 8-12 集为宜（微短剧每集短，块可以多些）
    # 原则：块数 = ceil(tgt / 12)，但至少 1 块，最多 8 块
    import math
    num_chunks = max(1, min(8, math.ceil(total_tgt / 12)))

    # 如果原始块少于目标块数，每个原始块就是一个 chunk
    num_chunks = min(num_chunks, len(source_blocks)) if len(source_blocks) > 1 else max(1, num_chunks)

    # 将原始块平均分为 num_chunks 组
    src_groups = []
    per_group = len(source_blocks) / num_chunks
    for i in range(num_chunks):
        start_idx = int(i * per_group)
        end_idx = int((i + 1) * per_group)
        src_groups.append(list(range(start_idx, end_idx)))

    # 计算每组对应的目标集数范围
    tgt_per_chunk = total_tgt / num_chunks
    plan = []
    for i, group in enumerate(src_groups):
        tgt_start = int(i * tgt_per_chunk) + 1
        tgt_end = int((i + 1) * tgt_per_chunk)
        if i == num_chunks - 1:
            tgt_end = total_tgt  # 最后一块兜底确保精确

        # 原始集数范围
        src_start = source_blocks[group[0]]["ep_start"] if group else 0
        src_end = source_blocks[group[-1]]["ep_end"] if group else 0

        plan.append({
            "src_blocks": group,
            "src_ep_range": (src_start, src_end),
            "tgt_ep_range": (tgt_start, tgt_end),
        })

    return plan


def _render_script_rewrite():
    """剧本调整 Tab 的完整 UI"""
    st.markdown("### ✂️ 剧本调整")
    st.caption("上传原始剧本，填写改编指令（如「10集扩充为20集」），选择剧本类型后一键调整")

    # ── 文件上传 ──
    uploaded = st.file_uploader(
        "📁 上传原始剧本文件",
        type=["docx", "txt", "md"],
        key="rewrite_file_uploader",
        help="支持 .docx / .txt / .md 格式"
    )

    if uploaded is not None:
        from production.llm_utils import read_uploaded_file
        content = read_uploaded_file(uploaded)
        if content:
            _set_ss("rewrite_source_text", content)

    source_text = _ss("rewrite_source_text")

    if source_text:
        char_count = len(source_text)
        # 简单估算集数：按约1500字/集估算
        est_episodes = max(1, round(char_count / 1500))
        st.success(f"✅ 已加载剧本，共 **{char_count:,}** 字符（约 {est_episodes} 集）")
        with st.expander("👁 预览原始剧本（前500字）", expanded=False):
            st.text(source_text[:500] + ("..." if len(source_text) > 500 else ""))
    else:
        st.info("📭 请上传剧本文件，或可直接在下方文本框中粘贴剧本内容")

    # 粘贴输入区（备选）
    paste_text = st.text_area(
        "📋 或直接粘贴剧本内容",
        value="",
        placeholder="也可以直接在这里粘贴剧本文本...",
        height=120,
        key="rewrite_paste_input"
    )
    if paste_text.strip():
        _set_ss("rewrite_source_text", paste_text.strip())
        source_text = paste_text.strip()

    st.markdown("---")

    # ── 改编指令 ──
    rewrite_instruction = st.text_area(
        "📝 改编指令",
        value="",
        placeholder=(
            "例如：\n"
            "• 将10集剧本扩充为20集，保持核心情节不变\n"
            "• 将20集剧本压缩为10集精华版\n"
            "• 将男主职业改为黑客，并相应调整剧情逻辑\n"
            "• 增加一条感情支线，第5集开始引入女配角"
        ),
        height=140,
        key="rewrite_instruction_input"
    )

    # 改编方向由用户填写的「改编指令」决定——指令里写什么，就按什么改（不再与剧本类型绑定）
    st.caption("💡 改编方向以您填写的「改编指令」为准：指令里写什么风格/结构，就按什么改；未指定则保持原剧本基调。")

    # ── 剧本类型（电影 / 电视剧）──  最高优先级开关
    st.markdown("**🎬 剧本类型**")
    wt_col1, wt_col2 = st.columns(2)
    with wt_col1:
        is_tv = st.toggle(
            "📺 电视剧",
            value=True,
            key="rewrite_worktype_tv",
            help="按「第X集」组织，支持集数扩缩"
        )
    with wt_col2:
        is_movie = st.toggle(
            "🎬 电影",
            value=False,
            key="rewrite_worktype_movie",
            help="按「幕/场次(SCENE)」组织，不分集，禁止输出「第X集」"
        )

    if is_tv and is_movie:
        st.warning("⚠️ 请只选择一种剧本类型")
        return
    if not is_tv and not is_movie:
        work_type = "tv"   # 默认电视剧
    elif is_tv:
        work_type = "tv"
    else:
        work_type = "movie"

    wt_label = "📺 电视剧（按集）" if work_type == "tv" else "🎬 电影（按场次）"
    st.caption(f"当前类型：{wt_label}")

    st.markdown("---")

    # ── 开始调整按钮 ──
    can_start = bool(source_text.strip()) and bool(rewrite_instruction.strip()) and not _ss("rewrite_running")
    if st.button(
        "✂️ 开始调整",
        type="primary",
        use_container_width=True,
        disabled=not can_start
    ):
        if not source_text.strip():
            st.warning("⚠️ 请先上传或粘贴原始剧本")
            return
        if not rewrite_instruction.strip():
            st.warning("⚠️ 请填写改编指令")
            return

        _set_ss("rewrite_running", True)
        _set_ss("rewrite_result", "")
        _set_ss("rewrite_report", "")

        # ═══════════════════════════════════════════════════════════════
        # 电影 / 电视剧 分流：解析目标单位 + 构建约束 + 选择 Prompt
        # ═══════════════════════════════════════════════════════════════
        if work_type == "movie":
            # 电影：按场次(SCENE)解析，禁止输出「第X集」，全篇整体输出（红线）
            src_ep, tgt_ep = _parse_movie_scenes(rewrite_instruction.strip(), source_text)
            episode_constraint = _build_movie_constraint(src_ep, tgt_ep, rewrite_instruction.strip())
            raw_style_prompt = _REWRITE_MOVIE_PROMPT
            chunk_style_prompt = _CHUNK_MOVIE_PROMPT
            style_prompt = raw_style_prompt.format(episode_constraint=episode_constraint)
        else:
            # 电视剧：按集数解析；改编方向由改编指令决定，不绑定任何固定风格
            src_ep, tgt_ep = _parse_episode_numbers(rewrite_instruction.strip(), source_text)
            episode_constraint = _build_episode_constraint(src_ep, tgt_ep, rewrite_instruction.strip())
            tv_input_mode = _detect_tv_input_mode(source_text)
            input_mode_rule = _build_tv_mode_rule(tv_input_mode)
            raw_style_prompt = _REWRITE_TV_PROMPT
            chunk_style_prompt = _CHUNK_TV_PROMPT
            style_prompt = raw_style_prompt.format(
                episode_constraint=episode_constraint,
                input_mode_rule=input_mode_rule,
            )

        provider, base_url, api_key, model = _get_llm_params()
        import httpx
        from openai import OpenAI
        import time as _time

        custom_http = httpx.Client(timeout=600.0, trust_env=False)
        if "Ollama" in provider:
            client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama", http_client=custom_http)
        else:
            client = OpenAI(base_url=base_url, api_key=api_key or "sk-local", http_client=custom_http)

        # ── 判断是否需要分块改编 ──
        # 规则：目标集数 > 15 或 原始文本 > 15000 字 → 自动启用分块流水线
        # 电影模式：用场次数量近似判断（tgt_ep 此处复用为场次目标）
        need_chunking = (tgt_ep > 15) or (len(source_text) > 15000 and tgt_ep > 0) or (tgt_ep == 0 and len(source_text) > 15000)

        full_result = ""
        ws_broken = False
        start_time = _time.time()

        if work_type == "movie":
            if tgt_ep > 0 and src_ep > 0:
                status_title = f"⏳ 正在调整（电影）：{src_ep}场 → {tgt_ep}场"
            elif tgt_ep > 0:
                status_title = f"⏳ 正在调整（电影），目标 {tgt_ep} 场"
            else:
                status_title = "⏳ 正在连接模型，准备调整（电影）..."
        else:
            if tgt_ep > 0 and src_ep > 0:
                status_title = f"⏳ 正在调整：{src_ep}集 → {tgt_ep}集"
            elif tgt_ep > 0:
                status_title = f"⏳ 正在调整，目标 {tgt_ep} 集"
            else:
                status_title = "⏳ 正在连接模型，准备调整..."

        status_box = st.status(status_title, expanded=True)
        progress_text = status_box.empty()
        result_area = status_box.empty()

        try:
            if not need_chunking:
                # ═════════════════════════════════════════════════════════
                # 小体量：单次调用模式（与原逻辑一致）
                # ═════════════════════════════════════════════════════════
                if work_type == "movie":
                    # 电影模式：输出按场次，禁止「第X集」
                    tgt_ep_notice = (
                        f"\n\n⚠️ **核心约束再次确认：这是电影剧本，你必须输出恰好 {tgt_ep} 场"
                        f"（SCENE 1 到 SCENE {tgt_ep}），绝对禁止输出「第X集」格式。**"
                        if tgt_ep > 0 else
                        "\n\n⚠️ **核心约束再次确认：这是电影剧本，必须按幕/场次(SCENE)结构输出，绝对禁止「第X集」格式。**"
                    )
                    unit_src = f"共 {src_ep} 场" if src_ep > 0 else "结构参考"
                    user_msg = f"""## 【改编指令（最高优先级，必须严格执行）】

{rewrite_instruction.strip()}
{tgt_ep_notice}

---

## 原始剧本（{unit_src}，仅供参考，情节可删改合并）

{source_text}

---

## 输出要求
请严格按照上述改编指令，输出完整的改编后电影剧本。
{f"目标场次：**{tgt_ep} 场**（SCENE 1 到 SCENE {tgt_ep}），必须全部输出完整内容。" if tgt_ep > 0 else "按指令要求输出完整电影剧本（幕/场次结构）。"}
使用「幕/场次」结构：每场用 "SCENE N - 内景/外景 地点 - 时间" 标注。"""
                else:
                    tgt_ep_notice = (
                        f"\n\n⚠️ **核心约束再次确认：你必须输出恰好 {tgt_ep} 集，从第1集到第{tgt_ep}集，一集不多一集不少。**"
                        if tgt_ep > 0 else ""
                    )
                    mode_word = "单集" if tv_input_mode == "single" else "全剧本（含多集）"
                    mode_notice = (
                        f"\n\n⚠️ **输入类型：{mode_word}。** "
                        "全剧本须逐集按各自的标准进行修改与校验；"
                        "只按改编指令中的修改意见改动，原本已符合要求的内容保持原样，"
                        "不得为「优化」而擅自修改没有问题的内容。"
                    )
                    user_msg = f"""## 【改编指令（最高优先级，必须严格执行）】

{rewrite_instruction.strip()}
{tgt_ep_notice}
{mode_notice}

---

## 原始剧本（共 {src_ep} 集，仅供参考，情节可删改合并）

{source_text}

---

## 输出要求
请严格按照上述改编指令，输出完整的调整后剧本。
{f"目标集数：**{tgt_ep} 集**，从第1集写到第{tgt_ep}集，必须全部输出完整内容。" if tgt_ep > 0 else "按指令要求的集数输出完整改编剧本。"}
每集用"========================================"分隔，开头标注"第X集"."""


                is_ollama = "Ollama" in provider
                if tgt_ep > 0:
                    dynamic_max_tokens = max(16384, min(131072, tgt_ep * 2500))
                else:
                    dynamic_max_tokens = 32768

                if is_ollama:
                    extra = {"extra_body": {"options": {"num_ctx": 131072, "num_predict": max(16384, min(131072, dynamic_max_tokens))}}}
                else:
                    # 云端服务商必须钳制：这里的下限是 16384，而 DeepSeek 上限只有 8192，
                    # 不钳制的话该路径对 DeepSeek **必然 400**，表现为「跑了很久毫无输出」。
                    from shared.llm_config import clamp_max_tokens
                    dynamic_max_tokens = clamp_max_tokens(dynamic_max_tokens, provider, model)
                    extra = {"max_tokens": dynamic_max_tokens}

                if tgt_ep > 0:
                    unit = "场" if work_type == "movie" else "集"
                    progress_text.info(
                        f"🎯 已识别调整目标：**{src_ep} {unit} → {tgt_ep} {unit}** | "
                        f"单次调用模式 | 输出上限：{dynamic_max_tokens:,} tokens"
                    )

                stream = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": style_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    stream=True,
                    temperature=0.8,
                    **extra
                )

                progress_text.markdown("🤖 模型已响应，正在生成调整内容...")
                last_update = _time.time()
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta.content or ""
                    if not delta:
                        if choice.finish_reason:
                            break
                        continue
                    full_result += delta
                    now = _time.time()
                    if now - last_update >= 0.3:
                        last_update = now
                        try:
                            char_count = len(full_result)
                            if work_type == "movie":
                                done_units = len(re.findall(r'SCENE\s*\d+', full_result, re.IGNORECASE))
                                unit_info = f" | 已完成 **{done_units}/{tgt_ep}** 场" if tgt_ep > 0 else ""
                            else:
                                done_units = len(re.findall(r'第\s*\d+\s*集', full_result))
                                unit_info = f" | 已完成 **{done_units}/{tgt_ep}** 集" if tgt_ep > 0 else ""
                            elapsed = now - start_time
                            progress_text.markdown(
                                f"🤖 正在生成调整内容... 已输出 **{char_count:,}** 字 | "
                                f"用时 **{elapsed:.0f}** 秒{unit_info}"
                            )
                            result_area.markdown(full_result + " ▌")
                        except Exception:
                            ws_broken = True

            else:
                # ═════════════════════════════════════════════════════════
                # 大体量：分块调整流水线
                # Phase 0 → Phase 1-N → Phase Final
                # ═════════════════════════════════════════════════════════
                unit_label = "场" if work_type == "movie" else "集"
                progress_text.info(
                    f"🎯 已识别调整目标：**{src_ep} {unit_label} → {tgt_ep} {unit_label}** | "
                    f"体量较大，启用分块调整流水线..."
                )

                # ── Phase 0：生成故事摘要 ──
                progress_text.markdown("📋 **Phase 0/3**：正在分析原始剧本，生成全局摘要...")
                story_summary = _generate_story_summary(
                    client, model, provider, source_text,
                    rewrite_instruction.strip(), {}
                )
                if story_summary:
                    progress_text.markdown(
                        f"📋 **Phase 0/3**：全局摘要已生成（{len(story_summary):,} 字）✅"
                    )

                # ── 切分原始剧本（电影按场次，电视按集）──
                if work_type == "movie":
                    source_blocks = _split_source_by_scenes(source_text)
                else:
                    source_blocks = _split_source_by_episodes(source_text)
                chunk_plan = _compute_chunk_plan(src_ep, tgt_ep, source_blocks)
                total_chunks = len(chunk_plan)

                # 电视剧全剧本模式：把单集/全剧本硬规则注入到每块改写与补写的系统 Prompt
                effective_chunk_prompt = chunk_style_prompt
                if work_type != "movie":
                    effective_chunk_prompt = (
                        chunk_style_prompt + "\n\n## 单集 / 全剧本 处理规则（关键）\n" + input_mode_rule
                    )

                progress_text.markdown(
                    f"✂️ **Phase 1/3**：已将原始剧本切分为 **{len(source_blocks)}** 段，"
                    f"计划分 **{total_chunks}** 轮改写 | "
                    f"目标：第1{unit_label}→第{tgt_ep}{unit_label}"
                )

                # ── Phase 1-N：逐块改写 ──
                chunk_results = []
                prev_tail = ""

                for ci, plan_item in enumerate(chunk_plan):
                    tgt_start, tgt_end = plan_item["tgt_ep_range"]
                    src_start, src_end = plan_item["src_ep_range"]
                    src_indices = plan_item["src_blocks"]

                    # 拼接本块的原始剧本内容
                    chunk_src = "\n\n".join(
                        source_blocks[idx]["content"] for idx in src_indices if idx < len(source_blocks)
                    )

                    # 每块单独的 status 容器
                    chunk_label = (
                        f"✍️ 第 {ci+1}/{total_chunks} 轮改写："
                        f"原始第{src_start}-{src_end}{unit_label} → 目标第{tgt_start}-{tgt_end}{unit_label}"
                    )

                    progress_text.markdown(
                        f"**Phase 1/3 — {ci+1}/{total_chunks}**：{chunk_label}"
                    )

                    # 执行单块改写（传入分块专用Prompt + 原始集数范围）
                    chunk_result = _rewrite_single_chunk(
                        client, model, provider,
                        effective_chunk_prompt,
                        chunk_src, story_summary,
                        rewrite_instruction.strip(),
                        src_start, src_end,
                        tgt_start, tgt_end,
                        prev_tail, {},
                        status_box, progress_text,
                    )

                    # 收集结果（电影用场次分隔，电视用集分隔）
                    sep = "\n\n" + "=" * 40 + "\n\n"
                    chunk_results.append(chunk_result)
                    full_result = sep.join(chunk_results)

                    # 更新前情衔接：取本块改写结果的最后800字
                    prev_tail = chunk_result[-800:] if len(chunk_result) > 800 else chunk_result

                    # 更新全局UI
                    elapsed = _time.time() - start_time
                    total_chars = len(full_result)
                    if work_type == "movie":
                        actual_units = len(set(re.findall(r'SCENE\s*(\d+)', full_result, re.IGNORECASE)))
                        unit_done_str = f"已完成约 **{actual_units}** 场"
                    else:
                        actual_units = len(set(re.findall(r'第\s*(\d+)\s*集', full_result)))
                        unit_done_str = f"已完成约 **{actual_units}** 集"
                    try:
                        result_area.markdown(full_result + " ▌")
                        progress_text.markdown(
                            f"✅ 第 {ci+1}/{total_chunks} 轮改写完成 | "
                            f"累计 **{total_chars:,}** 字 | "
                            f"{unit_done_str} | "
                            f"用时 **{elapsed:.0f}** 秒"
                        )
                    except Exception:
                        ws_broken = True

                # ── Phase Final：合并 + 衔接检查 ──
                progress_text.markdown(
                    f"🔗 **Phase 2/3**：正在合并 {total_chunks} 段改写结果，检查{unit_label}完整性..."
                )

                # 合并所有块（电影用场次分隔，电视用集分隔）
                sep = "\n\n" + "=" * 40 + "\n\n"
                full_result = sep.join(chunk_results)

                # 统计实际场次/集数
                if work_type == "movie":
                    actual_ep_nums = sorted(set(re.findall(r'SCENE\s*(\d+)', full_result, re.IGNORECASE)), key=int)
                    final_ep_count = len(actual_ep_nums)
                else:
                    actual_ep_nums = sorted(set(re.findall(r'第\s*(\d+)\s*集', full_result)))
                    final_ep_count = len(actual_ep_nums)

                # 如果场次/集数不够，尝试补写缺失的
                if tgt_ep > 0 and final_ep_count < tgt_ep:
                    missing_start = final_ep_count + 1
                    missing_count = tgt_ep - final_ep_count

                    progress_text.markdown(
                        f"🔧 **Phase 3/3**：检测到缺失 **{missing_count}** {unit_label}"
                        f"（第{missing_start}-{tgt_ep}{unit_label}），正在补写..."
                    )

                    # 补写缺失的部分
                    supplement_prompt = effective_chunk_prompt
                    if work_type == "movie":
                        supplement_user = f"""## 全剧摘要（全局参考）
{story_summary}

---

## 前情衔接（已输出的最后部分）
{prev_tail}

---

## 补写任务
前面的改写已输出 SCENE 1 到 SCENE {final_ep_count}。
你必须**紧接着**前情，输出 SCENE {missing_start} 到 SCENE {tgt_ep}，共 {missing_count} 场。
- 开头必须与前情自然衔接
- 每场用 "SCENE N - 内景/外景 地点 - 时间" 标注
- 这是电影剧本，绝对禁止「第X集」格式
- 改编指令：{rewrite_instruction.strip()}"""
                    else:
                        supplement_user = f"""## 全剧摘要（全局参考）
{story_summary}

---

## 前情衔接（已输出的最后部分）
{prev_tail}

---

## 补写任务
前面的改写已输出第1集到第{final_ep_count}集。
你必须**紧接着**前情，输出第{missing_start}集到第{tgt_ep}集，共{missing_count}集。
- 开头必须与前情自然衔接
- 每集必须有完整的场景和对白
- 每集用"========================================"分隔，开头标注"第X集"
- 改编指令：{rewrite_instruction.strip()}"""

                    is_ollama = "Ollama" in provider
                    supplement_max = max(8192, min(32768, missing_count * 2500))
                    if not is_ollama:
                        # 同上：云端服务商超上限会 400，必须钳制
                        from shared.llm_config import clamp_max_tokens
                        supplement_max = clamp_max_tokens(supplement_max, provider, model)
                    if is_ollama:
                        supp_kwargs = dict(
                            model=model,
                            messages=[
                                {"role": "system", "content": supplement_prompt},
                                {"role": "user", "content": supplement_user},
                            ],
                            stream=True,
                            temperature=0.8,
                            extra_body={"options": {"num_ctx": 131072, "num_predict": supplement_max}},
                        )
                    else:
                        supp_kwargs = dict(
                            model=model,
                            messages=[
                                {"role": "system", "content": supplement_prompt},
                                {"role": "user", "content": supplement_user},
                            ],
                            stream=True,
                            temperature=0.8,
                            max_tokens=supplement_max,
                        )

                    supplement_result = ""
                    try:
                        supp_stream = client.chat.completions.create(**supp_kwargs)
                        for c in supp_stream:
                            if not c.choices:
                                continue
                            choice = c.choices[0]
                            delta = choice.delta.content or ""
                            if not delta:
                                if choice.finish_reason:
                                    break
                                continue
                            supplement_result += delta
                    except Exception:
                        pass

                    if supplement_result.strip():
                        full_result += sep + supplement_result.strip()
                        progress_text.markdown(f"🔧 补写完成，新增约 **{len(supplement_result):,}** 字")
                    else:
                        progress_text.warning("⚠️ 补写未能生成内容，可能受模型限制")
                else:
                    progress_text.markdown(f"🔗 合并完成，{unit_label}数完整 ✅")

            # ═════════════════════════════════════════════════════════
            # 统一收尾逻辑（无论分块/单次）
            # ═════════════════════════════════════════════════════════
            elapsed = _time.time() - start_time
            if full_result:
                final_ep_count = len(set(re.findall(r'第\s*(\d+)\s*集', full_result)))
                _set_ss("rewrite_result", full_result)
                _set_ss("script_content", full_result)
                from shared.session import CREATOR_SCRIPTS
                _set_ss("workflow_stage", CREATOR_SCRIPTS)

                ep_summary = (
                    f" | 实际输出 {final_ep_count} 集"
                    + ("" if tgt_ep == 0 else
                       " ✅" if final_ep_count >= tgt_ep else
                       f" ⚠️（目标{tgt_ep}集，差{tgt_ep - final_ep_count}集）")
                ) if final_ep_count > 0 else ""

                mode_label = "分块流水线" if need_chunking else "单次调用"
                label = (
                    f"✅ 调整完成（{mode_label}）| {len(full_result):,} 字{ep_summary} | {elapsed:.0f} 秒"
                )
                status_box.update(label=label, state="complete", expanded=False)

                # ── 生成建议修改报告（对比原剧本与调整后剧本）──
                try:
                    progress_text.markdown("📝 正在生成建议修改报告...")
                    report_text = _generate_rewrite_report(
                        client, model, provider, source_text,
                        full_result, rewrite_instruction.strip(), work_type
                    )
                    _set_ss("rewrite_report", report_text)
                except Exception as _rep_e:
                    _set_ss("rewrite_report", "")
                    progress_text.warning(f"⚠️ 修改报告生成失败（不影响改编结果）：{_rep_e}")

                if not ws_broken:
                    result_area.markdown(full_result)

                # 场次/集数不足时给用户提示
                if tgt_ep > 0 and final_ep_count < tgt_ep:
                    unit = "场" if work_type == "movie" else "集"
                    st.warning(
                        f"⚠️ 调整输出 **{final_ep_count}** {unit}，未达到目标 **{tgt_ep}** {unit}。\n\n"
                        f"系统已自动尝试补写但仍未满足。可尝试：\n"
                        f"1. 缩减目标{unit}数（分步走）\n"
                        f"2. 换用支持更长上下文的模型\n"
                        f"3. 将改编指令写得更具体，减少模型自由发挥空间"
                    )
            else:
                status_box.update(label="⚠️ 模型未返回任何内容", state="error", expanded=True)
                progress_text.warning("模型未生成任何内容，请检查模型配置或重试。")

        except Exception as e:
            err_msg = str(e)
            if full_result:
                _set_ss("rewrite_result", full_result)
                _set_ss("script_content", full_result)
                from shared.session import CREATOR_SCRIPTS
                _set_ss("workflow_stage", CREATOR_SCRIPTS)
                status_box.update(
                    label=f"⚠️ 调整中断（已保存部分结果 {len(full_result):,} 字）",
                    state="error", expanded=True
                )
                progress_text.error(f"生成过程中出错：{err_msg}")
                progress_text.info("已保存的部分结果可在下方查看或下载。")
            else:
                status_box.update(label="❌ 调整失败", state="error", expanded=True)
                progress_text.error(f"调整失败：{err_msg}")
        finally:
            _set_ss("rewrite_running", False)

    # ── 显示调整结果 ──
    rewrite_result = _ss("rewrite_result")
    if rewrite_result and not _ss("rewrite_running"):
        st.markdown("---")
        st.success("✅ 调整完成！结果已同步到右侧「剧本正文」标签页")
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "📥 下载调整后剧本",
                rewrite_result,
                file_name="调整剧本.md",
                mime="text/markdown",
                use_container_width=True
            )
        with col_dl2:
            if st.button("🔄 清空重新调整", use_container_width=True, key="rewrite_clear_btn"):
                _set_ss("rewrite_source_text", "")
                _set_ss("rewrite_result", "")
                _set_ss("rewrite_report", "")
                st.rerun()

        # ── 建议修改报告 ──
        rewrite_report = _ss("rewrite_report")
        if rewrite_report:
            st.markdown("---")
            st.markdown("### 📝 建议修改报告（AI 生成）")
            st.markdown(rewrite_report)
            st.download_button(
                "📥 下载修改报告",
                rewrite_report,
                file_name="修改报告.md",
                mime="text/markdown",
                use_container_width=True
            )


# =============================================================================
# 跨模式编辑桥接（分析 ↔ 创作双向互通）
# =============================================================================

def _render_cross_mode_bridge(script_text, analysis_feedback):
    """
    跨模式编辑桥接面板：从剧本分析跳转到创作时，加载剧本并支持 AI 一键修改。

    工作流状态机（3态）：
      state0 初始状态 → 可编辑剧本 + 分析反馈 + 「一键AI修改」按钮
      state1 执行多智能体修改 → 显示进度日志
      state2 修改完成 → 修改前后对比 + 返回分析 / 下载剧本
    """
    st.markdown("## ✏️ 剧本修改工作台")
    st.success("🔄 已从「剧本分析」携带剧本文本和分析反馈")

    # 读取工作流状态
    modifying = st.session_state.get("cross_mode_modifying", False)
    modified_script = st.session_state.get("cross_mode_modified_script", "")

    # =========================================================================
    # state2：修改完成 → 显示对比 + 返回分析 / 下载剧本
    # =========================================================================
    if modified_script:
        st.session_state.cross_mode_show_bridge = True
        _render_modification_result(script_text, modified_script)
        return

    # =========================================================================
    # state1：正在执行多智能体修改 → 显示实时进度
    # =========================================================================
    if modifying:
        st.session_state.cross_mode_show_bridge = True
        progress = st.session_state.get("cross_mode_modification_progress", 0)
        current_step = st.session_state.get("cross_mode_modification_current_step", "准备中...")
        start_time = st.session_state.get("cross_mode_modification_start_time", 0)

        # 计算已运行时间
        elapsed = int(time.time() - start_time) if start_time > 0 else 0
        elapsed_str = f"{elapsed // 60}分{elapsed % 60}秒" if elapsed >= 60 else f"{elapsed}秒"

        st.markdown("### 🤖 AI 正在根据分析反馈修改剧本")
        st.progress(progress / 100.0, text=f"{current_step} | 已运行 {elapsed_str}")

        # 当前步骤高亮显示
        st.info(f"**当前步骤**：{current_step}")

        # 日志显示区域
        logs = st.session_state.get("cross_mode_modification_logs", [])
        if logs:
            with st.expander("📋 查看实时工作日志", expanded=True):
                st.code("\n".join(logs[-50:]), language="bash")  # 只显示最近50条

        # 显示最新日志的最后3条作为状态卡片
        if len(logs) >= 3:
            st.caption(f"📝 {logs[-3]}")
            st.caption(f"📝 {logs[-2]}")
            st.caption(f"📝 {logs[-1]}")
        elif logs:
            for log in logs[-3:]:
                st.caption(f"📝 {log}")

        # 检查是否已修改完成（由线程设置 cross_mode_modified_script）
        _poll_key = "ui_creator_crossmode_poll_count"
        if st.session_state.get("cross_mode_modified_script"):
            # 任务完成必须清零计数：否则同一 session 内第二个长任务会继承上一次的
            # 累计轮询数，还没跑几分钟就被误判为「30分钟超时」。
            st.session_state[_poll_key] = 0
            st.rerun()
        else:
            _poll_count = st.session_state.get(_poll_key, 0) + 1
            if _poll_count > 900:  # 900 × 2s ≈ 30 分钟超时
                st.session_state[_poll_key] = 0
                st.error("⚠️ 跨模式修改等待超时（约30分钟未完成），已停止轮询。")
            else:
                st.session_state[_poll_key] = _poll_count
                time.sleep(2)
                st.rerun()

    # =========================================================================
    # state0：初始状态 → 可编辑剧本 + 分析反馈 + 一键AI修改
    # =========================================================================
    _render_initial_bridge_panel(script_text, analysis_feedback)


def _render_initial_bridge_panel(script_text, analysis_feedback):
    """state0：初始桥接面板（可编辑剧本 + 分析反馈 + 生成修改报告按钮）"""
    # 标记当前正在显示桥接面板，确保 rerun 后面板不消失
    st.session_state.cross_mode_show_bridge = True
    st.markdown("### ✏️ 剧本编辑区")

    # 可编辑文本区
    edited_script = st.text_area(
        "📝 剧本内容（可直接编辑修改）",
        value=script_text,
        height=400,
        key="cross_mode_script_editor",
        help="在此直接编辑剧本内容，或点击「生成AI修改报告」让AI根据分析反馈给出修改建议"
    )

    # 分析反馈摘要
    if analysis_feedback:
        with st.expander("📋 查看分析反馈摘要（诊断结果参考）", expanded=False):
            _render_analysis_feedback_summary(analysis_feedback)

    # 操作按钮区
    st.markdown("---")
    st.markdown("### 🚀 修改操作")

    # ── 剧本类型（电影 / 电视剧）──
    st.markdown("**🎬 剧本类型**")
    cm_wt1, cm_wt2 = st.columns(2)
    with cm_wt1:
        cm_is_tv = st.toggle(
            "📺 电视剧",
            value=True,
            key="crossmode_worktype_tv",
            help="按「第X集」组织，修改后保持集结构"
        )
    with cm_wt2:
        cm_is_movie = st.toggle(
            "🎬 电影",
            value=False,
            key="crossmode_worktype_movie",
            help="按「幕/场次(SCENE)」组织，修改后禁止拆成多集"
        )
    if cm_is_tv and cm_is_movie:
        st.warning("⚠️ 请只选择一种剧本类型")
        return
    if not cm_is_tv and not cm_is_movie:
        cm_work_type = "tv"
    elif cm_is_tv:
        cm_work_type = "tv"
    else:
        cm_work_type = "movie"
    cm_wt_label = "📺 电视剧（按集）" if cm_work_type == "tv" else "🎬 电影（按场次）"
    st.caption(f"当前类型：{cm_wt_label}")

    col_mod, col_back, col_save = st.columns([1.5, 1, 1])

    with col_mod:
        has_feedback = bool(analysis_feedback)
        if st.button(
            "🤖 一键AI修改剧本（基于分析反馈）",
            type="primary",
            use_container_width=True,
            key="btn_one_click_modify",
            disabled=not has_feedback,
        ):
            if not has_feedback:
                st.warning("⚠️ 暂无分析反馈，无法执行AI修改")
            else:
                provider, base_url, api_key, model = _get_llm_params()
                # 初始化修改工作流状态
                import time as _time
                st.session_state.cross_mode_modifying = True
                st.session_state.cross_mode_modified_script = ""
                st.session_state.cross_mode_modification_error = ""
                st.session_state.cross_mode_modification_progress = 5
                st.session_state.cross_mode_modification_current_step = "正在解析分析反馈..."
                st.session_state.cross_mode_modification_start_time = _time.time()
                st.session_state.cross_mode_modification_logs = [
                    f"[{_time.strftime('%H:%M:%S')}] 🚀 启动AI修改工作流（基于剧本分析反馈）",
                    f"[{_time.strftime('%H:%M:%S')}]    服务商：{provider} / 模型：{model}",
                    f"[{_time.strftime('%H:%M:%S')}]    剧本长度：{len(edited_script)} 字符",
                ]
                # 保存当前剧本到持久变量，供线程读取（避免被 rerun 清空）
                st.session_state.cross_mode_script_for_modification = edited_script
                # 保存剧本类型，供线程读取
                st.session_state.cross_mode_work_type = cm_work_type

                def _direct_modification_thread():
                    """在后台线程中执行AI修改，支持实时进度更新"""
                    import time as _time

                    def _update_progress(progress: int, step: str, log: str = ""):
                        """更新进度和日志的辅助函数"""
                        st.session_state.cross_mode_modification_progress = progress
                        st.session_state.cross_mode_modification_current_step = step
                        if log:
                            timestamp = _time.strftime('%H:%M:%S')
                            st.session_state.cross_mode_modification_logs.append(f"[{timestamp}] {log}")
                            # 同时打印到命令行，方便后端观察
                            print(f"[AI修改] {step} | {log}")

                    try:
                        # Step 1: 解析分析反馈
                        _update_progress(10, "正在解析剧本医生分析反馈...", "📋 开始解析分析反馈，提取修改指令...")
                        instruction = _build_modification_instruction_from_feedback(analysis_feedback)
                        instruction_lines = instruction.split('\n') if instruction else []
                        _update_progress(15, f"已提取 {len(instruction_lines)} 条修改指令", f"📋 已提取 {len(instruction_lines)} 条修改指令")

                        # Step 2: 准备剧本数据
                        script_to_modify = st.session_state.cross_mode_script_for_modification
                        script_length = len(script_to_modify)
                        work_type = st.session_state.get("cross_mode_work_type", "tv")
                        _update_progress(20, "正在准备修改策略...", f"📝 剧本长度：{script_length} 字符，准备修改策略 | 类型：{work_type}")

                        # Step 3: 构建智能修改Prompt（支持局部修改）
                        _update_progress(25, "正在构建AI修改指令...", "🔧 构建AI修改指令...")

                        # 判断剧本长度，决定使用全文修改还是局部修改策略
                        use_partial_mode = script_length > 8000  # 超过8000字符使用局部修改

                        # 电影模式：追加禁止拆集的硬约束
                        if work_type == "movie":
                            type_constraint = (
                                "\n\n# ⚠️ 电影剧本硬性约束\n"
                                "- 这是**电影**剧本，修改后必须保持「幕/场次(SCENE)」结构\n"
                                "- **绝对禁止**将电影剧本拆分为「第X集」电视剧结构\n"
                                "- 若原剧本是「第X集」格式，修改时应整合为单部电影场次线\n"
                                "- 每场用 \"SCENE N - 内景/外景 地点 - 时间\" 标注"
                            )
                        else:
                            type_constraint = ""

                        if use_partial_mode:
                            _update_progress(30, "采用局部修改模式（剧本较长）...", "🎯 剧本较长，采用局部修改模式，只修改有问题段落")
                            prompt = f"""你是一个专业的剧本编辑。请根据以下来自剧本医生的专业分析反馈，对剧本进行精准修订。

# 修改指令（来自剧本医生分析报告）
{instruction}

# 原剧本全文
{script_to_modify}

# 修改要求
1. **只修改有问题的段落**：对于没有问题的段落，原样保留，不要改动
2. **输出格式要求**：
   - 对于需要修改的段落：先输出「【修改段落】」标记，然后输出修改后的完整段落
   - 对于保留的段落：先输出「【保留段落】」标记，然后原样输出该段落
   - 确保所有段落按原文顺序排列，不遗漏任何内容
3. **修改原则**：
   - 逐条对照修改指令，确保每个问题都得到解决
   - 保持原有格式（包括集数标题、场景标记、角色对话格式等）
   - 不要删减集数或场景数量，在原有框架内优化
   - 确保修改后的剧本逻辑自洽、情绪节奏紧凑、人物弧光完整
{type_constraint}
"""
                        else:
                            _update_progress(30, "采用全文修改模式（剧本较短）...", "📝 剧本较短，采用全文修改模式")
                            prompt = f"""你是一个专业的剧本编辑。请根据以下来自剧本医生的专业分析反馈，对剧本进行全面修订。

# 修改指令（来自剧本医生分析报告）
{instruction}

# 原剧本全文
{script_to_modify}

# 修改要求
1. 逐条对照上述修改指令，确保每个问题都得到解决
2. 保持原有格式（包括集数标题、场景标记、角色对话格式等）
3. 不要删减集数或场景数量，在原有框架内优化
4. 确保修改后的剧本逻辑自洽、情绪节奏紧凑、人物弧光完整
5. 输出修订后的完整剧本
{type_constraint}
"""

                        # Step 4: 调用LLM
                        _update_progress(40, "正在调用大模型进行剧本修改...", f"🤖 调用 {model} 进行剧本修改（局部模式={use_partial_mode}）...")
                        print(f"[AI修改] 开始LLM调用 | 剧本长度={script_length} | 局部模式={use_partial_mode}")

                        from shared.llm_config import create_openai_client
                        client = create_openai_client(base_url, api_key)

                        # 使用streaming获取部分结果，更新进度
                        _update_progress(50, "大模型正在生成修改内容...", "⏳ 大模型正在生成修改内容，请耐心等待...")

                        resp = client.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.5,
                        )
                        result = resp.choices[0].message.content.strip()

                        # Step 5: 后处理（如果是局部修改模式，合并保留和修改的段落）
                        _update_progress(80, "正在处理修改结果...", "🔧 收到AI修改结果，正在处理...")

                        if use_partial_mode and "【修改段落】" in result:
                            _update_progress(85, "正在合并修改段落...", "🧩 检测到局部修改标记，正在合并段落...")
                            # 清理标记，输出纯剧本文本
                            import re
                            # 移除标记行，保留内容
                            lines = result.split('\n')
                            cleaned_lines = []
                            for line in lines:
                                if line.strip() in ("【修改段落】", "【保留段落】"):
                                    continue
                                cleaned_lines.append(line)
                            result = '\n'.join(cleaned_lines)
                            _update_progress(90, "合并完成", "✅ 段落合并完成")

                        # Step 6: 保存结果
                        result_length = len(result)
                        _update_progress(95, "正在保存修改结果...", f"💾 保存修改结果（{result_length} 字符）...")
                        st.session_state.cross_mode_modified_script = result
                        st.session_state.cross_mode_modification_progress = 100
                        st.session_state.cross_mode_modification_current_step = "修改完成！"
                        st.session_state.cross_mode_modification_logs.append(
                            f"[{_time.strftime('%H:%M:%S')}] ✅ AI修改完成！输出长度：{result_length} 字符"
                        )
                        print(f"[AI修改] 完成 | 输出长度={result_length}")

                    except Exception as e:
                        error_msg = str(e)
                        timestamp = _time.strftime('%H:%M:%S')
                        st.session_state.cross_mode_modification_logs.append(f"[{timestamp}] ❌ 修改失败：{error_msg}")
                        st.session_state.cross_mode_modification_error = error_msg
                        st.session_state.cross_mode_modification_current_step = f"修改失败：{error_msg[:50]}..."
                        st.session_state.cross_mode_modification_progress = 0
                        print(f"[AI修改] 错误：{error_msg}")

                    finally:
                        st.session_state.cross_mode_modifying = False

                t = threading.Thread(target=_direct_modification_thread, daemon=True)
                add_script_run_ctx(t)
                t.start()
                time.sleep(0.5)
                st.rerun()

    with col_back:
        if st.button("🔬 返回剧本分析", use_container_width=True,
                     key="bridge_back_to_analysis"):
            _set_ss("script_content", edited_script)
            st.session_state.analysis_auto_load = True
            st.session_state.active_tab = "🎬 剧本分析"
            _clear_modification_state()
            st.rerun()

    with col_save:
        if st.button("💾 保存到创作流", use_container_width=True,
                     key="bridge_save_to_creator"):
            _set_ss("script_content", edited_script)
            _clear_modification_state()
            st.success("✅ 已保存到创作流，可在右侧「剧本正文」标签页查看")
            st.rerun()


def _render_modification_report(report: dict, original_script: str, analysis_feedback: dict):
    """state1：渲染修改报告确认界面"""
    st.markdown("## 📋 修改报告")
    st.info("请审阅以下修改报告，确认后点击「确认并执行修改」按钮，系统将调用多智能体进行修改")

    # 修改方向
    st.markdown("### 🎯 修改方向")
    st.markdown(report.get("direction", "暂无"))

    # 详细总结
    st.markdown("### 📝 详细总结")
    st.markdown(report.get("summary", "暂无"))

    # 修改建议表格
    suggestions = report.get("suggestions", [])
    if suggestions:
        st.markdown("### 📋 修改建议")
        import pandas as pd
        df = pd.DataFrame(suggestions)
        # 保证列顺序
        # 列名映射必须按「字段名」而非「位置」。
        # 历史 bug：用 labels[i] 按位置取名，一旦 LLM 只返回部分字段
        #（例如缺 priority），episode 就会被错标成「优先级」，展示完全串位。
        label_map = {
            "priority": "优先级",
            "category": "类别",
            "episode": "涉及集数",
            "issue": "问题",
            "suggestion": "建议",
            "expected_effect": "预期效果",
        }
        col_order = list(label_map.keys())
        present_cols = [c for c in col_order if c in df.columns]
        # 保留 col_order 之外的额外字段，避免 LLM 多返回的信息被静默丢弃
        extra_cols = [c for c in df.columns if c not in col_order]
        df = df[present_cols + extra_cols]
        df.columns = [label_map[c] for c in present_cols] + extra_cols
        st.dataframe(df, use_container_width=True, hide_index=True)

    # 预计影响
    st.markdown(f"### ⚖️ 预计影响")
    impact = report.get("estimated_impact", "待评估")
    if "大幅" in impact:
        st.warning(f"**{impact}** — 可能需要较多时间")
    else:
        st.info(f"**{impact}**")

    # 需要修改的集数
    episodes = report.get("episodes_to_modify", [])
    if episodes:
        st.markdown(f"### 🎬 需要修改的集数")
        st.markdown(f"**{episodes}**")

    # 操作按钮
    st.markdown("---")
    col_confirm, col_regenerate, col_cancel = st.columns([2, 1, 1])

    with col_confirm:
        if st.button("✅ 确认并执行修改", type="primary", use_container_width=True,
                     key="btn_confirm_modification"):
            st.session_state.cross_mode_report_confirmed = True
            # 启动修改线程
            provider, base_url, api_key, model = _get_llm_params()
            st.session_state.cross_mode_modifying = True
            st.session_state.cross_mode_modification_logs = ["🚀 启动多智能体修改工作流..."]

            def _modification_thread():
                try:
                    # 使用持久化变量获取剧本（避免 rerun 后 cross_mode_script_text 被清空）
                    script_text = st.session_state.get("cross_mode_script_for_modification", "")
                    if not script_text:
                        script_text = st.session_state.get("cross_mode_script_text", "")
                    result = _execute_modification_workflow(
                        script_text,
                        st.session_state.cross_mode_modification_report,
                        provider, base_url, api_key, model
                    )
                    st.session_state.cross_mode_modified_script = result
                    st.session_state.cross_mode_modifying = False
                    st.session_state.cross_mode_modification_logs.append("✅ 修改完成！")
                except Exception as e:
                    st.session_state.cross_mode_modification_logs.append(f"❌ 修改失败：{str(e)}")
                    st.session_state.cross_mode_modifying = False

            t = threading.Thread(target=_modification_thread, daemon=True)
            add_script_run_ctx(t)
            t.start()
            time.sleep(0.5)
            st.rerun()

    with col_regenerate:
        if st.button("🔄 重新生成报告", use_container_width=True,
                     key="btn_regenerate_report"):
            st.session_state.cross_mode_modification_report = None
            st.session_state.cross_mode_show_report = False
            st.rerun()

    with col_cancel:
        if st.button("❌ 取消", use_container_width=True,
                     key="btn_cancel_modification"):
            _clear_modification_state()
            st.rerun()


def _render_modification_result(original_script: str, modified_script: str):
    """state3：修改完成后，显示修改前后对比 + 保存/继续选项"""
    st.markdown("## ✅ 修改完成！")
    st.success("多智能体已根据修改报告完成剧本修改")

    # 修改前后对比
    st.markdown("### 📊 修改前后对比")

    col_orig, col_mod = st.columns([1, 1])

    with col_orig:
        st.markdown("#### 📄 修改前")
        st.text_area(
            "原剧本",
            value=original_script,
            height=400,
            disabled=True,
            key="orig_script_display"
        )

    with col_mod:
        st.markdown("#### ✏️ 修改后")
        # 可编辑，允许用户进一步调整
        further_edited = st.text_area(
            "修改后剧本（可进一步编辑）",
            value=modified_script,
            height=400,
            key="modified_script_display"
        )

    # 操作按钮：返回分析页重新评估 / 下载剧本
    st.markdown("---")
    st.markdown("### 💾 下一步操作")

    col_back, col_save, col_download, col_continue = st.columns([1.5, 1, 1, 1])

    with col_back:
        if st.button("🔬 返回分析页重新评估", use_container_width=True, type="primary",
                     key="btn_back_to_analysis_after_mod"):
            # 将修改后剧本设为当前创作流剧本，携带回分析页
            _set_ss("script_content", further_edited if further_edited else modified_script)
            st.session_state.analysis_auto_load = True
            st.session_state.active_tab = "🎬 剧本分析"
            _clear_modification_state()
            st.rerun()

    with col_save:
        final_script = further_edited if further_edited else modified_script
        if st.button("💾 保存到创作流", use_container_width=True,
                     key="btn_save_modified_to_creator"):
            # 将修改后的剧本保存到创作流主存储
            _set_ss("script_content", final_script)
            _set_ss("workflow_stage", CREATOR_SCRIPTS)
            _clear_modification_state()
            st.success("✅ 已保存修改后的剧本到创作流，可在右侧「剧本正文」标签页查看")
            st.rerun()

    with col_download:
        st.download_button(
            "📥 下载修改后剧本",
            data=further_edited if further_edited else modified_script,
            file_name="修改后剧本.md",
            mime="text/markdown",
            use_container_width=True,
            key="btn_download_modified"
        )

    with col_continue:
        if st.button("✏️ 继续修改", use_container_width=True,
                     key="btn_continue_modifying"):
            # 将修改后的剧本设为当前剧本，清除修改完成状态，回到初始桥接面板
            final_script = further_edited if further_edited else modified_script
            _set_ss("script_content", final_script)
            _set_ss("workflow_stage", CREATOR_SCRIPTS)
            st.session_state.cross_mode_script_for_modification = final_script
            # 清除修改完成状态，但保留桥接面板
            st.session_state.cross_mode_modified_script = ""
            st.session_state.cross_mode_modifying = False
            st.session_state.cross_mode_modification_error = ""
            st.session_state.cross_mode_modification_progress = 0
            st.session_state.cross_mode_modification_current_step = ""
            st.session_state.cross_mode_modification_logs = []
            st.session_state.cross_mode_show_report = False
            st.session_state.cross_mode_report_confirmed = False
            st.session_state.cross_mode_show_bridge = True
            st.rerun()


def _render_analysis_feedback_summary(analysis_feedback):
    """渲染分析反馈摘要（精简版，供创作修改时参考）"""
    if not analysis_feedback or not isinstance(analysis_feedback, dict):
        st.info("暂无分析反馈数据")
        return

    # 绿灯会
    greenlight = analysis_feedback.get("greenlight_decision", {})
    slogan = greenlight.get("slogan", "")
    if slogan:
        st.markdown(f"#### 💡 立项标语：'{slogan}'")
    target = greenlight.get("target_audience_and_emotion", "")
    if target:
        st.info(f"**🎯 受众与情绪价值**：{target}")

    # 情绪导向：整体情绪弧线
    arc = analysis_feedback.get("emotion_arc_overview", {})
    if arc:
        st.markdown("---")
        st.markdown("#### 📈 情绪弧线评估")
        st.markdown(f"**整体满意度**：{arc.get('overall_satisfaction', '暂无')}")
        climax = arc.get('climax_episode', '')
        if climax:
            st.markdown(f"**最高潮集数**：{climax}")
        charm = arc.get('character_charm_index', '')
        if charm:
            st.markdown(f"**角色魅力指数**：{charm}")
        weak = arc.get('weak_sections', [])
        if weak:
            st.warning(f"**⚠️ 情绪塌陷段**：{' / '.join(weak)}")

    # 结构导向：逻辑自洽
    structure = analysis_feedback.get("story_structure_audit", {})
    if structure:
        st.markdown("---")
        st.markdown("#### 📐 起承转合评估")
        for key, label in [("opening", "起"), ("development", "承"), ("climax", "转"), ("resolution", "合")]:
            phase = structure.get(key, {})
            desc = phase.get("description", "")
            verdict = phase.get("verdict", "")
            if desc or verdict:
                st.markdown(f"**{label}**：{desc}（{verdict}）")
        logic = structure.get("logic_consistency", {})
        if logic:
            st.markdown(f"**逻辑自洽**：{logic.get('overall', '暂无')}")
            holes = logic.get("plot_holes", [])
            for h in holes:
                st.markdown(f"- 🕳️ {h}")

    # 结构痛点
    flaws = analysis_feedback.get("structure_flaws", "")
    if flaws:
        st.markdown("---")
        st.error(f"**⚠️ 结构痛点**：{flaws}")

    # 反转伏笔
    tf = analysis_feedback.get("twist_and_foreshadowing", {})
    if tf:
        st.markdown("---")
        st.markdown("#### 🔄 反转与伏笔")
        twists = tf.get("key_twists", [])
        for i, t in enumerate(twists, 1):
            eff = t.get("effectiveness", "")
            icon = "✅" if eff == "高" else ("⚠️" if eff == "中" else "❌")
            st.markdown(f"{icon} **反转 #{i}**：{t.get('twist', '')}（有效性：{eff}）")
        foreshadowing = tf.get("foreshadowing", [])
        for f in foreshadowing:
            v = f.get("verdict", "")
            icon = "✅" if v == "自然" else ("⚠️" if v == "突兀" else "❌")
            st.markdown(f"{icon} 埋设：{f.get('planted', '')} → 回扣：{f.get('payoff', '')}（{v}）")
        dem = tf.get("deus_ex_machina_risk", "")
        if dem:
            st.markdown(f"**机械降神风险**：{dem}")

    # Save the Cat 节拍（电影模式）
    beats = analysis_feedback.get("beat_mapping_sheet", [])
    if beats and isinstance(beats, list):
        st.markdown("---")
        st.markdown("#### 🎬 Save the Cat 15 节拍")
        for b in beats:
            num = b.get("beat_number", "")
            name = b.get("beat_name", "")
            diag = b.get("rhythm_diagnosis", "")
            icon = "✅" if "通过" in diag else ("⚠️" if "弱" in diag else "❌")
            st.markdown(f"{icon} **{num}. {name}**：{diag}")

    # McKee 价值审计（电影模式）
    mckee = analysis_feedback.get("mckee_value_audit", [])
    if mckee and isinstance(mckee, list):
        st.markdown("---")
        st.markdown("#### ⚖️ McKee 场景价值转变")
        for m in mckee:
            st.markdown(
                f"- 场景 {m.get('scene', '')}："
                f"{m.get('value_at_start', '')} → {m.get('value_at_end', '')} "
                f"({m.get('verdict', '')})"
            )

    # 人物弧光
    arcs = analysis_feedback.get("character_arc_diagnosis", [])
    if arcs and isinstance(arcs, list):
        st.markdown("---")
        st.markdown("#### 👻 人物弧光 (Ghost/Lie/Flaw)")
        for arc_item in arcs:
            char = arc_item.get("character", "未知")
            ghost = arc_item.get("ghost", "❌ 缺失")
            lie = arc_item.get("lie", "")
            flaw = arc_item.get("flaw", "")
            want = arc_item.get("want", "")
            need = arc_item.get("need", "")
            verdict = arc_item.get("arc_verdict", "")
            if ghost.startswith("❌"):
                st.error(f"**{char}**：前史创伤缺失（纸片人风险！）")
            else:
                st.markdown(f"**{char}**：Ghost={ghost}")
            details = []
            if lie: details.append(f"Lie={lie}")
            if flaw: details.append(f"Flaw={flaw}")
            if want: details.append(f"Want={want}")
            if need: details.append(f"Need={need}")
            if verdict: details.append(f"弧光={verdict}")
            if details:
                st.markdown(f"  &nbsp;&nbsp;{' | '.join(details)}")

    # 写作违规
    violations = analysis_feedback.get("writing_violations", [])
    if violations and isinstance(violations, list):
        st.markdown("---")
        st.markdown("#### 🚨 写作红线扫描")
        st.warning(f"共发现 **{len(violations)}** 项写作违规")
        for v in violations[:8]:
            st.markdown(
                f"- 🚨 [{v.get('location', '')}] {v.get('type', '')}："
                f"{v.get('original', '')[:80]}..."
            )
        if len(violations) > 8:
            st.caption(f"... 还有 {len(violations) - 8} 项，返回分析页查看完整报告")

    # 台词问题
    dialogue = analysis_feedback.get("dialogue_impact_check", [])
    if dialogue and isinstance(dialogue, list):
        st.markdown("---")
        st.markdown("#### 💬 台词冲击力问题")
        st.warning(f"共发现 **{len(dialogue)}** 项台词问题")
        for d in dialogue[:5]:
            st.markdown(f"- ❌ {d.get('original', '')[:60]}...")
            rw = d.get("rewrite", "")
            if rw:
                st.markdown(f"  &nbsp;&nbsp;✅ 建议：{rw[:80]}...")
        if len(dialogue) > 5:
            st.caption(f"... 还有 {len(dialogue) - 5} 项")

    # 广电红线
    censor = analysis_feedback.get("censorship_risk", {})
    if censor:
        st.markdown("---")
        risk = censor.get("risk_level", "未知")
        if "极高" in risk:
            st.error(f"#### 🚨 送审风险：🔴 {risk}")
        elif "中等" in risk:
            st.warning(f"#### 🚨 送审风险：🟡 {risk}")
        else:
            st.success(f"#### 🚨 送审风险：🟢 {risk}")
        sensitive = censor.get("sensitive_elements", [])
        for item in sensitive:
            st.markdown(f"- 🚩 {item.get('element', '')} — 触犯：{item.get('risk', '')}")
            st.markdown(f"  &nbsp;&nbsp;合规建议：{item.get('advice', '')}")


# =============================================================================
# 辅助：获取当前LLM参数
# =============================================================================

def _get_llm_params():
    """获取当前侧边栏配置的LLM参数"""
    provider = st.session_state.llm_provider
    base_url = st.session_state.base_url
    api_key = "ollama" if provider == "本地 Ollama" else (
        st.session_state.api_key or "sk-local"
    )
    model = st.session_state.get("selected_model", get_default_model(provider))
    return provider, base_url, api_key, model


# =============================================================================
# UI渲染入口
# =============================================================================

def render_creator():
    """渲染创作流完整UI"""

    # =========================================================================
    # Harness: 断点续传检测 — 发现上次未完成的 checkpoint 提示恢复
    # =========================================================================
    if _HARNESS_AVAILABLE and _has_checkpoints():
        current_stage = _ss("workflow_stage")
        has_content = bool(_ss("script_content") or _ss("global_outline"))
        latest_cp = _get_latest_checkpoint()
        cp_name = latest_cp.get("name", "") or latest_cp.get("checkpoint_id", "")
        cp_time = latest_cp.get("readable_time", "")
        cp_ep = latest_cp.get("current_episode", 0)
        cp_total = latest_cp.get("total_episodes", 0)

        if not has_content and current_stage == CREATOR_IDLE:
            # 有 checkpoint 但当前是空白状态 — 提示恢复
            with st.container(border=True):
                col_chk, col_btn1, col_btn2 = st.columns([2, 1, 1])
                with col_chk:
                    st.info(
                        f"💾 **发现未完成的创作存档**\n\n"
                        f"「{cp_name}」\n\n"
                        f"进度：第 {cp_ep}/{cp_total} 集"
                        + (f" | {cp_time}" if cp_time else "")
                    )
                with col_btn1:
                    if st.button("📂 恢复上次进度", type="primary", use_container_width=True,
                                 key="harness_restore_btn"):
                        if _restore_latest_checkpoint():
                            st.success("✅ 已恢复创作进度！")
                            time.sleep(0.3)
                            st.rerun()
                        else:
                            st.error("恢复失败，请手动开始新创作")
                with col_btn2:
                    if st.button("🗑️ 清除存档", use_container_width=True,
                                 key="harness_clear_btn"):
                        _delete_all_checkpoints()
                        st.rerun()

    # =========================================================================
    # 跨模式检测：从剧本分析跳转而来
    # =========================================================================
    cross_source = st.session_state.get("cross_mode_source", "")
    cross_script = st.session_state.get("cross_mode_script_text", "")
    cross_feedback = st.session_state.get("cross_mode_analysis_feedback")

    _showing_bridge = False
    if cross_source == "analysis" and cross_script:
        # 首次从分析页跳转：将剧本加载到创作流输出区
        _set_ss("script_content", cross_script)
        _set_ss("workflow_stage", CREATOR_SCRIPTS)
        # 持久化保存剧本和反馈，供修改工作流使用
        st.session_state.cross_mode_script_for_modification = cross_script
        if cross_feedback:
            st.session_state.cross_mode_analysis_feedback = cross_feedback
        # 清除跳转标记（避免 rerun 时重复触发首次加载逻辑）
        st.session_state.cross_mode_source = ""
        st.session_state.cross_mode_script_text = ""
        # 显式标记显示桥接面板，确保后续 rerun 后面板不消失
        st.session_state.cross_mode_show_bridge = True
        _showing_bridge = True
    elif st.session_state.get("cross_mode_show_bridge", False):
        # 显式标记显示桥接面板：页面刷新后面板仍然保持
        _showing_bridge = True
        # 从持久化变量恢复数据（如果参数为空）
        if not cross_script:
            cross_script = st.session_state.get("cross_mode_script_for_modification", "")
        if cross_feedback is None:
            cross_feedback = st.session_state.get("cross_mode_analysis_feedback")
    elif st.session_state.get("cross_mode_modifying") or st.session_state.get("cross_mode_modified_script"):
        # 修改工作流进行中或已完成：保持显示桥接面板
        _showing_bridge = True
        st.session_state.cross_mode_show_bridge = True
        # 从持久化变量恢复数据（如果参数为空）
        if not cross_script:
            cross_script = st.session_state.get("cross_mode_script_for_modification", "")
        if cross_feedback is None:
            cross_feedback = st.session_state.get("cross_mode_analysis_feedback")

    col_left, col_right = st.columns([1, 1], gap="large")

    # =========================================================================
    # 左半部分: 灵感与控制区
    # =========================================================================
    with col_left:
        # ── 跨模式编辑桥接面板（分析→创作） ──
        if _showing_bridge:
            _render_cross_mode_bridge(cross_script, cross_feedback)
            st.markdown("---")

        st.markdown("## 💡 灵感与控制")
        st.markdown("---")

        left_tab_create, left_tab_rewrite = st.tabs(["🎬 创意生成", "✂️ 剧本调整"])

        # =====================================================================
        # Tab A：创意生成（原有逻辑）
        # =====================================================================
        with left_tab_create:
            creative_idea = st.text_area(
                "📝 输入剧本核心创意和思路",
                value="",
                placeholder="例如：我想写一个50集的被嘲讽穷小子逆袭首富的爽剧，主角被未婚妻当众羞辱退婚后，意外发现自己原来是隐形富豪的儿子...",
                height=200,
                help="输入您想要创作的故事核心概念、主题或灵感"
            )

            stage = _ss("workflow_stage")

            # ── 阶段一：启动架构师 ──
            if stage == CREATOR_IDLE:
                st.markdown("")
                if st.button(
                    "🚀 启动多智能体编剧工坊（生成大纲）",
                    type="primary",
                    use_container_width=True,
                    disabled=_ss("workflow_running")
                ):
                    if not creative_idea.strip():
                        st.warning("⚠️ 请先输入剧本创意!")
                    else:
                        provider, base_url, api_key, model = _get_llm_params()
                        _format_name = st.session_state.script_format
                        _format_display = SCRIPT_FORMATS.get(_format_name, _format_name)

                        thread = threading.Thread(
                            target=_execute_showrunner_thread,
                            args=(creative_idea, _format_display, provider, base_url, api_key, model),
                            daemon=True
                        )
                        add_script_run_ctx(thread)
                        thread.start()
                        time.sleep(0.5)
                        st.rerun()

            # ── 阶段一完成：大纲审核 ──
            elif stage == CREATOR_OUTLINE:
                st.success("✅ 全局大纲已生成！")

                if _ss("stage1_total_episodes") > 0:
                    st.info(
                        f"🎯 识别到 **[总集数: {_ss('stage1_total_episodes')}]**，"
                        f"确认后将批量生成 {_ss('stage1_total_episodes')} 集完整剧本"
                    )

                if is_micro_drama_mode(st.session_state.script_format):
                    st.warning(
                        "🔥 检测到竖屏微短剧格式，将注入**多巴胺爽剧**规则："
                        "痛点抛出 → 迅速打脸 → 新钩子"
                    )

                st.markdown("")
                if st.button(
                    "✅ 大纲确认无误，开始批量生成正文剧本",
                    type="primary",
                    use_container_width=True,
                    disabled=_ss("workflow_running")
                ):
                    provider, base_url, api_key, model = _get_llm_params()
                    _format_display = SCRIPT_FORMATS.get(
                        st.session_state.script_format, st.session_state.script_format
                    )

                    thread = threading.Thread(
                        target=_execute_scripts_thread,
                        args=(
                            _ss("stage1_creative_idea"), _format_display,
                            _ss("stage1_outline"), _ss("stage1_total_episodes"),
                            provider, base_url, api_key, model
                        ),
                        daemon=True
                    )
                    add_script_run_ctx(thread)
                    thread.start()
                    time.sleep(0.5)
                    st.rerun()

                # HITL 大纲定向修改
                with st.expander("🎯 对大纲提出修改意见（定向精修）", expanded=False):
                    st.info(
                        "💡 请输入具体的修改意见，例如："
                        "「将男主的职业改成黑客」「结尾增加一个反转」「增加一个反派角色」"
                    )
                    outline_feedback = st.text_area(
                        "📝 大纲修改意见", value="", placeholder="请输入针对大纲的具体修改意见...",
                        height=120, key="outline_feedback_input"
                    )
                    col_revise, col_regen = st.columns([3, 1])
                    with col_revise:
                        if st.button(
                            "🎯 提交修改并让架构师精修", type="primary",
                            use_container_width=True,
                            disabled=(_ss("workflow_running") or not outline_feedback.strip())
                        ):
                            provider, base_url, api_key, model = _get_llm_params()
                            _format_display = SCRIPT_FORMATS.get(
                                st.session_state.script_format, st.session_state.script_format
                            )
                            _prev = _ss("hitl_previous_outline") or _ss("stage1_outline")

                            thread = threading.Thread(
                                target=_execute_outline_revision_thread,
                                args=(
                                    _ss("stage1_creative_idea"), _format_display,
                                    _prev, outline_feedback.strip(),
                                    provider, base_url, api_key, model
                                ),
                                daemon=True
                            )
                            add_script_run_ctx(thread)
                            thread.start()
                            time.sleep(0.5)
                            st.rerun()

                    with col_regen:
                        if st.button("🔄 全量重写", use_container_width=True,
                                     disabled=_ss("workflow_running")):
                            _set_ss("hitl_previous_outline", "")
                            creator_clear_outputs()
                            st.rerun()

            # ── 阶段二：剧本生成中/完成 ──
            elif stage == CREATOR_SCRIPTS:
                if _ss("workflow_running"):
                    st.info(f"🔄 正在生成剧本... 第 {_ss('current_episode')}/{_ss('total_episodes')} 集")
                    if _ss("total_episodes") > 0:
                        st.progress(
                            _ss("current_episode") / _ss("total_episodes"),
                            text=f"第 {_ss('current_episode')}/{_ss('total_episodes')} 集"
                        )
                else:
                    st.success("✅ 全部完成！")

                    # ── 重新进入桥接面板（如果之前有分析反馈和剧本文本）──
                    if (st.session_state.get("cross_mode_script_for_modification")
                            and st.session_state.get("cross_mode_analysis_feedback")
                            and not st.session_state.get("cross_mode_show_bridge", False)):
                        st.markdown("---")
                        st.info("📋 检测到您此前从「剧本分析」携带了分析反馈，可直接基于反馈修改剧本")
                        if st.button(
                            "✏️ 打开剧本修改工作台（基于分析反馈）",
                            type="primary", use_container_width=True,
                            key="btn_reopen_bridge"
                        ):
                            st.session_state.cross_mode_show_bridge = True
                            st.rerun()

                    # ── 跨模式导航：转入剧本分析 ──
                    if _ss("script_content"):
                        st.markdown("---")
                        col_transfer, col_download = st.columns([1, 1])
                        with col_transfer:
                            if st.button(
                                "🔬 转入剧本分析（整体评估）",
                                type="primary",
                                use_container_width=True,
                            ):
                                st.session_state.active_tab = "🎬 剧本分析"
                                st.session_state.analysis_auto_load = True
                                st.rerun()
                        with col_download:
                            st.caption("💡 转入分析后，系统将自动识别剧本类型并选用对应审核标准")

                    # HITL 单集定向修改
                    if _ss("total_episodes") > 0:
                        st.markdown("---")
                        st.markdown("### 🎯 单集剧本定向精修")

                        episode_options = list(range(1, _ss("total_episodes") + 1))
                        selected_ep = st.selectbox(
                            "📺 选择要修改的集数", options=episode_options, index=0,
                            format_func=lambda x: f"第 {x} 集", key="episode_select_for_revision"
                        )

                        # 预览该集当前内容
                        current_script = ""
                        if _ss("script_content"):
                            sep = "\n\n" + "=" * 40 + "\n\n"
                            episodes = _ss("script_content").split(sep)
                            for ep in episodes:
                                if re.search(r'第\s*' + str(selected_ep) + r'\s*集', ep):
                                    current_script = ep.strip()
                                    break

                        if current_script:
                            with st.expander(f"📄 第 {selected_ep} 集当前内容预览", expanded=False):
                                st.markdown(current_script[:500] + ("..." if len(current_script) > 500 else ""))

                        # 医生驳回提示
                        rejections = _ss("last_doctor_rejection")
                        if selected_ep in rejections:
                            st.error(f"⚠️ 医生仍需修改（第 {selected_ep} 集）：")
                            st.markdown(rejections[selected_ep][:300])

                        episode_feedback = st.text_area(
                            "📝 本集修改意见", value="",
                            placeholder=f"输入针对第 {selected_ep} 集剧本的具体修改意见...",
                            height=100, key=f"episode_feedback_{selected_ep}"
                        )

                        col_ep_revise, col_ep_new = st.columns([3, 1])
                        with col_ep_revise:
                            if st.button(
                                f"🎯 提交第 {selected_ep} 集修改（编剧精修 → 医生审核）",
                                type="primary", use_container_width=True,
                                disabled=(_ss("workflow_running") or not episode_feedback.strip())
                            ):
                                provider, base_url, api_key, model = _get_llm_params()
                                _format_display = SCRIPT_FORMATS.get(
                                    st.session_state.script_format, st.session_state.script_format
                                )
                                _prev_scripts = _ss("hitl_previous_episode_scripts")
                                _prev_script = _prev_scripts.get(selected_ep, "") or current_script

                                thread = threading.Thread(
                                    target=_execute_episode_revision_thread,
                                    args=(
                                        selected_ep, _ss("total_episodes"),
                                        _format_display, _ss("stage1_outline"),
                                        "", _ss("memory_snapshot"),
                                        _prev_script, episode_feedback.strip(),
                                        provider, base_url, api_key, model
                                    ),
                                    daemon=True
                                )
                                add_script_run_ctx(thread)
                                thread.start()
                                time.sleep(0.5)
                                st.rerun()

                        with col_ep_new:
                            if st.button("🔄 开始新一轮", use_container_width=True):
                                creator_clear_outputs()
                                st.rerun()
                    else:
                        if st.button("🔄 开始新一轮创作", use_container_width=True):
                            creator_clear_outputs()
                            st.rerun()

            # ── 日志显示 ──
            st.markdown("---")
            st.markdown("### 📋 终端日志")
            logs = _ss("logs")
            if logs:
                st.code("\n".join(logs), language="bash")
            else:
                st.info("📭 日志区域\n\n点击「启动多智能体编剧工坊」开始生成大纲")

            _poll_key = "ui_creator_workflow_poll_count"
            if _ss("workflow_running"):
                _poll_count = st.session_state.get(_poll_key, 0) + 1
                if _poll_count > 900:  # 900 × 2s ≈ 30 分钟超时
                    _set_ss("workflow_running", False)
                    st.session_state[_poll_key] = 0
                    st.error("⚠️ 工作流执行超时（约30分钟未完成），已自动停止轮询。请查看上方日志排查。")
                else:
                    st.session_state[_poll_key] = _poll_count
                    time.sleep(2)
                    st.rerun()
            elif st.session_state.get(_poll_key):
                # 工作流已结束（正常完成或手动停止）→ 计数清零。
                # 否则同一 session 内第二次启动工作流会继承上一次的累计轮询数，
                # 导致刚跑几分钟就被误判为「30分钟超时」。
                st.session_state[_poll_key] = 0

        # =====================================================================
        # Tab B：剧本调整
        # =====================================================================
        with left_tab_rewrite:
            _render_script_rewrite()

    # =========================================================================
    # 右半部分: 输出区
    # =========================================================================
    with col_right:
        st.markdown("## 📤 剧本输出")
        st.markdown("---")

        tab1, tab2, tab3, tab4 = st.tabs([
            "📋 全局大纲", "👤 人物设定", "📄 剧本正文", "💾 记忆快照"
        ])

        with tab1:
            st.markdown("### 全局大纲")
            outline = _ss("global_outline")
            if outline:
                st.markdown(outline)
                st.download_button(
                    "📥 下载大纲", outline,
                    file_name="全局大纲.md", mime="text/markdown",
                    use_container_width=True
                )
            else:
                st.info("📭 尚未生成全局大纲\n\n请在左侧输入创意并点击「启动多智能体编剧工坊」")

        with tab2:
            st.markdown("### 人物设定")
            if _ss("global_outline"):
                st.caption("人物设定已包含在全局大纲中，请查看上方大纲标签页")
            else:
                st.info("📭 尚未生成人物设定")
            char_settings = _ss("character_settings")
            if char_settings:
                st.download_button(
                    "📥 下载人物设定", char_settings,
                    file_name="人物设定.md", mime="text/markdown",
                    use_container_width=True
                )

        with tab3:
            st.markdown("### 剧本正文")
            script = _ss("script_content")
            if script:
                st.markdown(script)
                col_dl, col_save = st.columns([1, 1])
                with col_dl:
                    st.download_button(
                        "📥 下载剧本", script,
                        file_name="剧本正文.md", mime="text/markdown",
                        use_container_width=True
                    )
                with col_save:
                    if _HARNESS_AVAILABLE:
                        if st.button("💾 保存进度", use_container_width=True,
                                     key="manual_save_checkpoint",
                                     help="保存当前创作进度，刷新页面后可恢复"):
                            _auto_save_checkpoint(name=f"手动存档-第{_ss('current_episode')}/{_ss('total_episodes')}集")
                            st.success("✅ 进度已保存！")
                            time.sleep(0.8)
                            st.rerun()
            else:
                if _ss("workflow_stage") == CREATOR_OUTLINE:
                    st.info("📭 大纲已生成，请点击左侧「✅ 大纲确认无误，开始批量生成正文剧本」按钮")
                else:
                    st.info("📭 尚未生成剧本正文\n\n请先完成大纲审核")

        with tab4:
            st.markdown("### 当前记忆快照")
            st.caption("长内容创作过程中用于保持上下文连贯性的结构化摘要")
            memory = _ss("memory_snapshot")
            if memory:
                st.markdown(memory)
                st.download_button(
                    "📥 下载记忆快照", memory,
                    file_name="记忆快照.md", mime="text/markdown",
                    use_container_width=True
                )
            else:
                st.info("📭 尚未生成记忆快照\n\n请在剧本全部生成完成后查看")
