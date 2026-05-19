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


# 使用命名空间的快捷访问
def _ss(key):
    """快速访问 creator_ 前缀的 session_state"""
    return st.session_state[f"creator_{key}"]

def _set_ss(key, value):
    """快速设置 creator_ 前缀的 session_state"""
    st.session_state[f"creator_{key}"] = value


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

    try:
        context = run_scripts_phase(
            client=create_openai_client(base_url, api_key),
            model=model,
            creative_idea=creative_idea,
            script_format=script_format,
            outline=outline,
            total_episodes=total_episodes,
            log_callback=creator_add_log,
            progress_callback=on_progress
        )

        _set_ss("script_content", context.script_content)
        _set_ss("memory_snapshot", context.memory_snapshot)
        creator_add_log("✅ 阶段二执行完成", "success")

    except Exception as e:
        creator_add_log(f"❌ 阶段二执行出错：{str(e)}", "error")

    finally:
        _set_ss("workflow_running", False)


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

    creator_add_log(f"🎯 启动第 {episode_num} 集定向精修（编剧→医生审核）...", "system")
    creator_add_log(f"   修改意见：{user_feedback[:80]}...", "info")

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


# =============================================================================
# 跨模式修改工作流 — 修改报告生成（LLM 调用）
# =============================================================================

def _generate_modification_report(script_text: str, analysis_feedback: dict,
                                 provider: str, base_url: str, api_key: str, model: str) -> dict:
    """
    根据分析反馈，调用 LLM 生成结构化修改报告。
    返回 dict，包含：direction / summary / suggestions / episodes_to_modify / estimated_impact
    """
    from shared.llm_config import create_openai_client

    feedback_str = json.dumps(analysis_feedback, ensure_ascii=False, indent=2) if analysis_feedback else "（无分析反馈）"

    prompt = f"""你是一个专业的剧本修改顾问。请根据给定的剧本内容和剧本医生分析报告，生成一份结构化的修改报告。

# 剧本内容（全文）
{script_text[:4000]}

# 剧本医生分析报告
{feedback_str}

请生成修改报告，必须以纯JSON格式返回（不要有多余文字、不要用markdown代码块包裹）：

{{"direction": "修改方向总结（200字以内，说明整体修改思路）",
  "summary": "修改报告详细总结（500字以内，逐项说明主要修改点）",
  "suggestions": [
    {{"priority": "高",
      "category": "类别（如：结构、人物、台词、节奏、情绪等）",
      "episode": "涉及集数（如：第3集、第5-8集、全剧）",
      "issue": "具体问题描述",
      "suggestion": "修改建议",
      "expected_effect": "预期效果"
    }}
  ],
  "episodes_to_modify": [1, 2, 3],
  "estimated_impact": "预计修改影响（小幅调整 / 中等修改 / 大幅重构）"
}}

要求：
1. suggestions 按优先级（高→中→低）排序
2. 修改建议必须具体、可操作，直接对应分析报告中指出的问题
3. 如果分析报告为空，请基于剧本内容本身提出改进建议
4. 只返回纯JSON，不要返回任何解释性文字
"""

    try:
        client = create_openai_client(base_url, api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = resp.choices[0].message.content.strip()
        # 去除可能的 markdown 代码块包裹
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json") or content.startswith("JSON"):
                content = content[4:].strip()
        report = json.loads(content)
        return report

    except Exception as e:
        # 返回最小可用报告
        return {
            "direction": f"根据分析报告进行针对性修改（生成报告时出错：{str(e)[:100]}）",
            "summary": "请手动参考分析报告中的具体问题逐一修改",
            "suggestions": [],
            "episodes_to_modify": [],
            "estimated_impact": "待评估"
        }


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
        if st.session_state.get("cross_mode_modified_script"):
            st.rerun()
        else:
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
                        _update_progress(20, "正在准备修改策略...", f"📝 剧本长度：{script_length} 字符，准备修改策略")

                        # Step 3: 构建智能修改Prompt（支持局部修改）
                        _update_progress(25, "正在构建AI修改指令...", "🔧 构建AI修改指令...")

                        # 判断剧本长度，决定使用全文修改还是局部修改策略
                        use_partial_mode = script_length > 8000  # 超过8000字符使用局部修改

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
        col_order = ["priority", "category", "episode", "issue", "suggestion", "expected_effect"]
        df = df[[c for c in col_order if c in df.columns]]
        df.columns = ["优先级", "类别", "涉及集数", "问题", "建议", "预期效果"]
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

        if _ss("workflow_running"):
            time.sleep(2)
            st.rerun()

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
                st.download_button(
                    "📥 下载剧本", script,
                    file_name="剧本正文.md", mime="text/markdown",
                    use_container_width=True
                )
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
