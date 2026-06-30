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

# 强制本地流量绕过代理
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"

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
    st.session_state.script_format = "竖屏微短剧（主打极速反转）"
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
                            max_tokens=5
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
            "竖屏微短剧（主打极速反转）": "🔥 多巴胺爽剧 | 竖屏短视频 | 极速反转 | 情绪爆点",
            "5-10分钟短片": "Want/Need/Arc、四段式结构",
            "90分钟长片": "Ghost/Lie/Flaw、完整弧光",
            "多集剧集": "季度规划、分集大纲"
        }
        desc = format_descriptions.get(script_format, "")
        if script_format == "竖屏微短剧（主打极速反转）":
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
