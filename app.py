"""
AI 剧本创作和制片管理综合工具
==============================

合并 AI_Screenwriter_Studio（创作引擎）与 AI漫剧制片_终极融合版（制片引擎）。
统一入口，5个工作模式通过侧边栏Tab切换。

技术栈:
- Streamlit - Web 界面框架
- OpenAI SDK - LLM 调用（兼容多服务商）
- CrewAI - 分镜多智能体工作流（可选依赖）
"""

import streamlit as st
import time
import os
import sys
import subprocess as _sp

# 强制本地流量绕过代理
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"


# =============================================================================
# 本地在线更新（部署用户同步 GitHub 最新版）
# =============================================================================

def _get_local_version():
    """返回 (short_hash, date_str)，失败返回 ('unknown', '')。"""
    try:
        h = _sp.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.getcwd(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        ).stdout.strip() or "unknown"
        d = _sp.run(
            ["git", "log", "-1", "--format=%cs", "HEAD"],
            cwd=os.getcwd(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        ).stdout.strip()
        return (h, d)
    except Exception:
        return ("unknown", "")


def _run_updater(extra_args, timeout=400):
    """运行仓库根目录的 update.py，返回合并后的输出文本。"""
    try:
        r = _sp.run(
            [sys.executable, "update.py", *extra_args],
            cwd=os.getcwd(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if not out.strip():
            out = f"(命令退出码: {r.returncode})"
        return out
    except Exception as e:
        return f"执行更新失败: {e}"


def _restart_app():
    """启动新的 start.py 实例后退出当前进程（实现无缝重启加载新代码）。"""
    target = os.path.join(os.getcwd(), "start.py")
    if not os.path.exists(target):
        st.error("未找到 start.py，请手动重启应用。")
        return
    try:
        flags = 0
        kwargs = {}
        if sys.platform == "win32":
            flags = getattr(_sp, "DETACHED_PROCESS", 0) | getattr(
                _sp, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            kwargs["start_new_session"] = True
        _sp.Popen(
            [sys.executable, target], cwd=os.getcwd(),
            creationflags=flags, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, **kwargs,
        )
        time.sleep(1.5)
        os._exit(0)
    except Exception as e:
        st.error(f"自动重启失败：{e}，请手动运行 python start.py")

# =============================================================================
# 页面配置
# =============================================================================

st.set_page_config(
    page_title="AI 剧本创作和制片管理综合工具",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =============================================================================
# 初始化 Session State
# =============================================================================

from shared.session import (
    init_creator_state,
    init_production_state,
    init_cross_mode_state,
)

# 全局LLM配置状态
if "llm_provider" not in st.session_state:
    st.session_state.llm_provider = "DeepSeek"
if "base_url" not in st.session_state:
    st.session_state.base_url = "https://api.deepseek.com/v1"
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "selected_model" not in st.session_state:
    st.session_state.selected_model = "deepseek-v4-flash"
if "script_format" not in st.session_state:
    st.session_state.script_format = "默认（跟随创意要求）"
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "📝 剧本创作"

# 初始化各工作流状态
init_creator_state()
init_production_state()
init_cross_mode_state()

# =============================================================================
# 侧边栏
# =============================================================================

from shared.llm_config import (
    LLM_PROVIDERS, MODEL_OPTIONS, SCRIPT_FORMATS,
    update_base_url_placeholder, get_default_model,
    detect_ollama_models, ensure_ollama_model,
    create_openai_client, get_llm_kwargs,
)

with st.sidebar:
    st.markdown("---")
    st.markdown("## ⚙️ 模型网关配置")
    st.markdown("---")

    # 模型服务商选择
    provider = st.selectbox(
        "选择大模型服务商",
        options=list(LLM_PROVIDERS.keys()),
        index=list(LLM_PROVIDERS.keys()).index(
            st.session_state.llm_provider
        ) if st.session_state.llm_provider in LLM_PROVIDERS else 0,
        help="选择您要使用的 LLM 服务提供商"
    )

    if provider != st.session_state.llm_provider:
        st.session_state.llm_provider = provider
        st.session_state.base_url = LLM_PROVIDERS[provider]["base_url"]
        st.session_state.selected_model = LLM_PROVIDERS[provider]["default_model"]

    base_url, placeholder = update_base_url_placeholder(provider)

    # 二级联动：模型版本选择
    if provider == "本地 Ollama":
        pass  # Ollama 模型在下方动态检测
    else:
        provider_models = MODEL_OPTIONS.get(provider, [get_default_model(provider)])
        cur_model = st.session_state.get("selected_model", provider_models[0] if provider_models else get_default_model(provider))
        model_index = provider_models.index(cur_model) if cur_model in provider_models else 0
        selected_model = st.selectbox(
            "选择模型版本",
            options=provider_models,
            index=model_index,
            help="选择该服务商下的具体模型版本"
        )
        st.session_state.selected_model = selected_model

    # Base URL
    if provider == "本地 Ollama":
        st.text_input("Base URL", value=base_url, disabled=True)
    else:
        base_url_input = st.text_input(
            "Base URL",
            value=st.session_state.base_url or base_url,
            help="API 基础地址，切换服务商后自动更新"
        )
        st.session_state.base_url = base_url_input

    # API Key
    if provider == "本地 Ollama":
        st.text_input("API Key", value="ollama", type="password", disabled=True)
    else:
        api_key = st.text_input(
            "API Key",
            value=st.session_state.api_key,
            type="password",
            placeholder=placeholder,
            help="您的 API 密钥（密码形式输入）"
        )
        st.session_state.api_key = api_key

    # Ollama 本地模型自动检测
    if provider == "本地 Ollama":
        st.markdown("---")
        st.markdown("### 🔍 本地模型检测")
        with st.spinner("正在检测 Ollama 模型..."):
            ollama_models, success = detect_ollama_models()
        if success:
            if ollama_models:
                default_model = LLM_PROVIDERS["本地 Ollama"]["default_model"]
                display_models = [default_model] + [m for m in ollama_models if m != default_model]
                selected_ollama = st.selectbox("选择本地模型", options=display_models, index=0)
                st.session_state.selected_model = selected_ollama
                st.success(f"✅ 检测到 {len(ollama_models)} 个已安装模型")
            else:
                st.warning("⚠️ Ollama 已启动，但未检测到已安装的模型")
                st.info("💡 请运行 `ollama pull <model_name>` 安装模型")
        else:
            st.error("❌ 检测不到 Ollama 服务，请确保本地 Ollama 已启动。")

    # 连接测试
    if st.button("🔗 测试连接", use_container_width=True):
        if not st.session_state.api_key and provider != "本地 Ollama":
            st.warning("⚠️ 请先输入 API Key")
        else:
            with st.spinner("正在测试连接..."):
                _key = "ollama" if provider == "本地 Ollama" else (
                    st.session_state.api_key or "sk-local"
                )
                client = create_openai_client(st.session_state.base_url, _key)
                if client:
                    try:
                        test_model = st.session_state.get(
                            "selected_model", get_default_model(provider)
                        )
                        client.chat.completions.create(
                            model=test_model,
                            messages=[{"role": "user", "content": "Hi"}],
                            max_tokens=50
                        )
                        st.success(f"✅ 连接成功! (模型: {test_model})")
                    except Exception as e:
                        st.error(f"❌ 连接失败: {str(e)}")

    st.markdown("---")

    # ── 工作模式Tab（核心导航）──
    # 注意：radio 不加 key，靠 index 控制选中项；用户手动点 radio 时通过 active_tab 返回值同步 session_state
    _TAB_OPTIONS = ["📝 剧本创作", "🎬 剧本分析", "💰 预算审计", "📋 场景拆解", "🎥 分镜工作台"]
    st.markdown("## 🎭 工作模式")
    active_tab = st.radio(
        "选择当前工作模式",
        _TAB_OPTIONS,
        captions=[
            "创意 → 大纲 → 剧本全流程（Showrunner/Writer/Doctor）",
            "好莱坞剧本医生（Ghost/Lie/Flaw + Save the Cat 15节拍）",
            "执行制片人成本审计 + AI降本替代方案",
            "强迫症场记统筹（物理空间场景解构）",
            "CrewAI 4-Agent工业级分镜矩阵",
        ],
        index=_TAB_OPTIONS.index(
            st.session_state.get("active_tab", "📝 剧本创作")
        ),
    )
    st.session_state.active_tab = active_tab

    st.markdown("---")

    # ── 侧边栏底部变量初始化（确保始终有值）──
    uploaded_file = None
    style_tokens_input = ""

    # ── 制片流专属：文件上传 + 美术风格 ──
    if active_tab != "📝 剧本创作":
        # 文件上传（制片流需要）
        st.markdown("### 📁 导入剧本文件")
        uploaded_file = st.file_uploader("导入文本文档 (.docx / .txt / .md)", type=["docx", "txt", "md"],
                                          key="production_file_upload")

        # 视觉基调选择（分镜工作台专属）
        if active_tab == "🎥 分镜工作台":
            st.markdown("---")

            # ── 分镜目标时长（密度控制）── 仅分镜工作台显示
            st.markdown("### 🎯 分镜目标时长（密度）")
            st.caption("决定单集拆镜密度：短剧→镜头少而长；长剧→镜头多而密")
            _dur_options = {
                "自动（按剧本字数密度）": 0.0,
                "短剧 · 2 分钟/集": 2.0,
                "竖屏短剧 · 3 分钟/集": 3.0,
                "标准 · 10 分钟/集": 10.0,
                "长剧单集 · 45 分钟/集": 45.0,
                "自定义": -1.0,
            }
            _dur_choice = st.selectbox(
                "目标成片单集时长",
                options=list(_dur_options.keys()),
                index=0,
                key="sb_target_duration_choice",
                help="程序按目标时长反推每集镜头数。长剧需更长的剧本支撑（约 12000 字≈45 分钟）。",
            )
            if _dur_choice == "自定义":
                _custom_min = st.number_input(
                    "自定义单集时长（分钟）",
                    min_value=0.5, max_value=180.0, value=18.0, step=0.5,
                    key="sb_target_duration_custom",
                )
                st.session_state.target_duration_min = _custom_min
            else:
                st.session_state.target_duration_min = _dur_options[_dur_choice]

            st.markdown("---")
            st.markdown("### 🎨 视觉基调")
            st.caption("选择视觉参考方向，LLM 会结合剧本内容自动确定拍摄风格")

            # ── 12 种视觉基调定义 ──
            # 格式：{ "显示名": { "desc": "简介", "tokens": "英文关键词（生图提示词）" } }
            _VISUAL_TONES = {
                "🌑 极暗写实": {
                    "desc": "强对比度，深暗调，电影感光影，赤贫底层题材",
                    "tokens": "ultra-dark tone, deep shadow, high contrast, cinematic lighting, desaturated, gritty realism, 8k"
                },
                "☀️ 明快都市": {
                    "desc": "清亮自然光，现代都市感，干净构图，轻喜剧",
                    "tokens": "bright natural light, modern urban, clean composition, warm tones, contemporary style, 8k"
                },
                "🔥 古装史诗": {
                    "desc": "工笔重彩，古铜色调，宏大格局，战争与权谋",
                    "tokens": "ancient Chinese costume drama, bronze tone, epic scale, ink wash painting style, cinematic, 8k"
                },
                "💜 赛博朋克": {
                    "desc": "霓虹反光，蓝紫色调，高科技低生活，失控感",
                    "tokens": "cyberpunk, neon lights, blue-purple tones, rain-slicked streets, high-tech dystopia, cinematic, 8k"
                },
                "🌸 甜虐偶像": {
                    "desc": "柔焦滤镜，粉紫暖色，明亮背光，情感张力",
                    "tokens": "soft focus, pink-lavender palette, backlit glow, idol drama style, romantic tension, 8k"
                },
                "🧊 悬疑冷峻": {
                    "desc": "冷蓝调，平光硬打，极简构图，心理惊悚",
                    "tokens": "cold blue tone, flat hard light, minimalist composition, psychological thriller, desaturated, 8k"
                },
                "😂 诙谐荒诞": {
                    "desc": "饱和撞色，夸张景深，喜剧节奏，荒诞幽默",
                    "tokens": "saturated colors, comic composition, exaggerated depth of field, slapstick humor, warm playful tone, 8k"
                },
                "🌿 田园治愈": {
                    "desc": "柔和绿意，散射自然光，低饱和暖白，慢生活",
                    "tokens": "pastoral healing, soft green foliage, diffused sunlight, low saturation warm white, slow life aesthetic, 8k"
                },
                "⚔️ 玄幻仙侠": {
                    "desc": "粒子光效，云雾仙境，东方奇幻，神话质感",
                    "tokens": "xianxia fantasy, particle light effects, misty celestial realm, oriental mythology, ethereal glow, 8k"
                },
                "🕵️ 黑色电影": {
                    "desc": "强阴影，威尼斯百叶窗光，复古犯罪，侦探氛围",
                    "tokens": "film noir, venetian blind shadows, vintage crime, dark atmosphere, high contrast black and white-inspired, 8k"
                },
                "🎌 日系漫改": {
                    "desc": "扁平色块，二次元转译，鲜明轮廓，动漫质感",
                    "tokens": "anime adaptation style, flat color blocks, bold outlines, 2D-to-3D hybrid, manga-inspired, vivid tones, 8k"
                },
                "🌊 末世废土": {
                    "desc": "尘土飞扬，橘黄天空，破败建筑，后启示录感",
                    "tokens": "post-apocalyptic wasteland, dusty orange sky, ruined cityscape, desolate atmosphere, survival drama, 8k"
                },
            }

            # ── 多选（可选多个基调叠加） ──
            st.markdown("**🎨 视觉风格基调**（可选 · 不选则由AI自动分析剧本决定）")
            selected_tones = st.multiselect(
                "选择视觉基调（可多选叠加）",
                options=list(_VISUAL_TONES.keys()),
                default=st.session_state.get("storyboard_tones", []),
                key="storyboard_tones_select",
                help="不选择任何基调时，AI 将完全根据剧本内容自动推断视觉风格。这是推荐方式。",
                placeholder="留空 = AI自动分析剧本决定..."
            )
            st.session_state["storyboard_tones"] = selected_tones

            # 显示选中基调的描述 或 自动模式提示
            if selected_tones:
                for tone in selected_tones:
                    st.caption(f"**{tone}** — {_VISUAL_TONES[tone]['desc']}")
            else:
                st.success("🤖 自动模式：AI 会根据剧本内容自动推断最合适的视觉风格")


            # 生成 style_tokens_input：合并所有选中基调的 tokens
            if selected_tones:
                merged_tokens = ", ".join(
                    _VISUAL_TONES[t]["tokens"] for t in selected_tones
                )
                # 去重关键词（多个基调可能有共同的"8k"等）
                seen = set()
                unique_tokens = []
                for tok in merged_tokens.split(", "):
                    tok = tok.strip()
                    if tok and tok.lower() not in seen:
                        seen.add(tok.lower())
                        unique_tokens.append(tok)
                style_tokens_input = ", ".join(unique_tokens)
            else:
                style_tokens_input = ""  # 空字符串 → LLM 自动推断
    else:
        # 创作流专属：剧本格式选择
        st.markdown("## 🎬 剧本格式")
        script_format = st.selectbox(
            "选择剧本格式",
            options=list(SCRIPT_FORMATS.keys()),
            index=list(SCRIPT_FORMATS.keys()).index(st.session_state.script_format)
            if st.session_state.script_format in SCRIPT_FORMATS else 0,
        )
        st.session_state.script_format = script_format

        format_descriptions = {
            "默认（跟随创意要求）": "🎨 不套用固定模板 | 由你在创意框中指定的字数/时长/集数/类型决定",
            "竖屏微短剧（1-2分钟/集，主打极致情绪）": "🔥 多巴胺爽剧 | 竖屏短视频 | 极速反转 | 情绪爆点",
            "短剧（5-10分钟/集，情绪与逻辑并重）": "Want/Need/Arc、四段式结构",
            "中剧（10-20分钟/集，结构相对完善）": "多集叙事 | 结构完善",
            "长剧（40-60分钟/集，标准电视剧制式）": "季度规划、分集大纲",
            "电影长片（90-120分钟，工业标准与爆款节拍）": "Ghost/Lie/Flaw、完整弧光",
        }
        desc = format_descriptions.get(script_format, "")
        if script_format == "竖屏微短剧（1-2分钟/集，主打极致情绪）":
            st.success(f"📖 {desc}")
        else:
            st.info(f"📖 {desc}")

    # ── 底部状态显示 ──
    st.markdown("---")
    current_model = st.session_state.get("selected_model", get_default_model(provider))
    st.markdown(f"""
    <div style="font-size: 12px; color: gray;">
    **当前配置**<br>
    服务商: {st.session_state.llm_provider}<br>
    模型: {current_model}
    </div>
    """, unsafe_allow_html=True)

    # ── 在线更新（本地部署用户同步 GitHub 最新版）──
    st.markdown("---")
    with st.expander("🔄 在线更新（GitHub 最新版）", expanded=False):
        st.caption("本地部署后，点此即可同步我在 GitHub 推送的最新版本，无需重新下载。")
        _cur_h, _cur_d = _get_local_version()
        st.markdown(f"**当前版本**：`{_cur_h}` （{_cur_d}）")

        if st.button("🔍 检查更新", use_container_width=True, key="btn_update_check"):
            with st.spinner("正在连接 GitHub 检查更新..."):
                _out = _run_updater(["--check"], timeout=180)
            st.code(_out, language="bash")

        if st.button("⬇️ 应用更新（拉取最新代码）", use_container_width=True, key="btn_update_apply"):
            with st.spinner("正在拉取最新代码（可能需要几十秒）..."):
                _out = _run_updater([], timeout=400)
            st.code(_out, language="bash")
            if "更新完成" in _out or "已经是最新" in _out:
                st.success("更新成功！点击下方按钮重启应用以加载新代码。")
                if st.button("🔄 重启应用", use_container_width=True, key="btn_update_restart"):
                    _restart_app()

# =============================================================================
# 主区域：根据 active_tab 路由到对应工作流
# =============================================================================

st.title("🎬 AI 剧本创作和制片管理综合工具")
st.caption("创作引擎 + 制片引擎 | 从创意到分镜的全流程工具链")

if st.session_state.active_tab == "📝 剧本创作":
    from creator.ui_creator import render_creator
    render_creator()

elif st.session_state.active_tab == "🎬 剧本分析":
    from production.ui_production import render_analysis
    render_analysis(uploaded_file)

elif st.session_state.active_tab == "💰 预算审计":
    from production.ui_production import render_budget
    render_budget(uploaded_file)

elif st.session_state.active_tab == "📋 场景拆解":
    from production.ui_production import render_scene_breakdown
    render_scene_breakdown(uploaded_file)

elif st.session_state.active_tab == "🎥 分镜工作台":
    from production.ui_production import render_storyboard
    render_storyboard(uploaded_file, style_tokens_input)

# =============================================================================
# 页脚
# =============================================================================

st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: gray; font-size: 12px;">
    AI 剧本创作和制片管理综合工具 v1.0<br>
    🤖 Showrunner → Writer → Doctor | 剧本分析 → 预算审计 → 场景拆解 → 分镜工作台<br>
    合并自 AI Screenwriter Studio + 影视工业化文本统筹管线
    </div>
    """,
    unsafe_allow_html=True
)
