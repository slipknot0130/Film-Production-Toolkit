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
    st.markdown("## 🎭 工作模式")
    active_tab = st.radio(
        "选择当前工作模式",
        [
            "📝 剧本创作",
            "🎬 剧本分析",
            "💰 预算审计",
            "📋 场景拆解",
            "🎥 分镜工作台",
        ],
        captions=[
            "创意 → 大纲 → 剧本全流程（Showrunner/Writer/Doctor）",
            "好莱坞剧本医生（Ghost/Lie/Flaw + Save the Cat 15节拍）",
            "执行制片人成本审计 + AI降本替代方案",
            "强迫症场记统筹（物理空间场景解构）",
            "CrewAI 4-Agent工业级分镜矩阵",
        ],
        index=["📝 剧本创作", "🎬 剧本分析", "💰 预算审计", "📋 场景拆解", "🎥 分镜工作台"].index(
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
        uploaded_file = st.file_uploader("导入文本文档 (.docx / .txt)", type=["docx", "txt"],
                                          key="production_file_upload")

        # 美术风格词（分镜工作流需要）
        if active_tab == "🎥 分镜工作台":
            st.markdown("---")
            st.markdown("### 🎨 全局美术风格")
            style_tokens_file = os.path.join(os.path.dirname(__file__), "StyleTokens.txt")
            default_style = ""
            try:
                with open(style_tokens_file, "r", encoding="utf-8") as f:
                    default_style = f.read().strip()
            except Exception:
                pass
            style_tokens_input = st.text_area(
                "StyleTokens（AI 生图提示词专用后缀）",
                value=default_style,
                placeholder="例如：AI漫剧, 古装, 写实, cinematic lighting, 8k, ...",
                height=100,
                help="会追加到每个镜头的英文生图提示词末尾"
            )
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
