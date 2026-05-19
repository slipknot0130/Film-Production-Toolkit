# 🎬 影视创作制片综合工具 (Film Production Toolkit)

**多智能体协同驱动的影视工业化 AI 工作台** — 内置编剧室 SOP、格式感知审核与长文本深度处理，从灵感到分镜一站覆盖。

[English](./README_EN.md) | 中文

---

## 📖 项目简介

影视创作制片综合工具是一个基于多智能体协作的影视工业文本管线，将**剧本创作**与**制片管理**合为一体。系统内置三组专业AI Agent（架构师、编剧、剧本医生）模拟真实编剧室工作流，通过集数级记忆快照与摘要传递机制解决长剧本上下文断裂问题；同时提供剧本分析、预算审计、场景拆解、分镜工作台四大制片模块，实现从创意到分镜的全流程工具链。

### 🎯 核心理念

> **代码 = SOP(团队)** — 把好莱坞编剧室的工业化流程，变成每个人桌上的AI团队。

---

## ✨ 功能亮点

### 📝 剧本创作引擎（3-Agent 协作）

| Agent | 角色 | 职责 |
|-------|------|------|
| 🏗️ Showrunner | 总架构师 | 生成全局大纲、人物小传、规划集数与节奏曲线 |
| ✍️ Writer | 执行编剧 | 按集撰写完整剧本，严格视觉化写作 |
| 🩺 Doctor | 剧本医生 | QA审查、驳回重写、生成记忆快照 |

- **两阶段审批流**：架构师生成大纲 → 用户确认 → 批量生成正文
- **HITL 定向修改**：对大纲/单集剧本提交修改意见，Agent 定向精修而非全盘重写
- **5种剧本格式全覆盖**：竖屏微短剧 / 短剧 / 中剧 / 长剧 / 电影长片

### 🎬 剧本分析引擎（格式感知双轨审核）

系统根据剧本文本体量**自动识别**剧集类型，并选用差异化审核标准：

| 剧集类型 | 审核导向 | 核心审核标准 |
|---------|---------|------------|
| 微短剧 / 短剧 | 🎭 情绪导向 | 多巴胺节奏、情绪爽感、打脸力度、钩子强度 |
| 中剧 / 长剧 | 📐 结构导向 | 起承转合、逻辑自洽、人物弧光、反转伏笔 |
| 电影长片 | 🎥 好莱坞工业 | Save the Cat 15节拍、Ghost/Lie/Flaw、McKee场景价值翻转 |

### 💰 预算审计引擎

- **执行制片人预算审计**：逐行抓捕烧钱点 + AI降本替代方案
- **专业制片主任预算**：剧组规模/日均费率/逐场景费用明细/场地推荐

### 📋 场景拆解引擎

强迫症场记统筹 — 按物理空间解构每场戏，提取道具清单与服装要求。

### 🎥 分镜工作台

- **CrewAI 4-Agent 工业级分镜矩阵**：分镜导演 → 美术指导 → 质检总监 → 输出
- **9列工业风分镜表格**：景别/角度/画面描述/中文提示词/英文提示词/对白/音效/时长/备注
- **全局美术风格词**：自定义StyleTokens，自动追加到每个镜头英文提示词末尾

### 🔄 创作-审核-修改闭环

```
剧本创作 → 一键转入分析 → 差异化审核 → AI一键修改 → 返回分析验证
```

---

## 🆚 与在线LLM（ChatGPT/Claude/豆包等）的核心区别

| 维度 | 在线LLM聊天 | 本工具 |
|------|-----------|-------|
| **工作流** | 单轮对话，需手动管理上下文 | 内置3-Agent流水线：架构师→编剧→医生，自动循环 |
| **专业度** | 通用对话，缺乏行业规范约束 | 嵌入好莱坞工业标准（Save the Cat/Ghost-Lie-Flaw/McKee） |
| **格式适配** | 一套Prompt打天下 | 5种格式×3个Agent=15套专属Prompt动态路由 |
| **质量控制** | 输出即最终，无质检环节 | 医生Agent逐集审核，驳回重写（最多3轮） |
| **长文本处理** | 受Token窗口限制，长剧必断裂遗忘 | 集数级记忆快照 + 摘要传递，万行长剧不断裂、不遗忘 |
| **审核标准** | 无差异，微短剧和电影用同一套 | 格式感知双轨引擎：微短剧重情绪满足，电影重结构逻辑 |
| **HITL人机协作** | 每次修改等于从头重写 | 定向精修：只改用户指出的问题，保留优秀部分 |
| **制片管理** | 无 | 预算审计/场景拆解/分镜矩阵，一条龙 |
| **模型接入** | 绑定单一平台，无选择权 | 12+ 服务商自由切换（国内外云端 API + 本地模型），按需选型 |
| **成本灵活** | 单一计费，长剧成本失控 | 多服务商比价切换 + 本地模型可选，成本自主可控 |

### 🔑 一句话总结优势

> **在线LLM是"通用对话"，本工具是"多智能体编剧室"——它不是在聊天，而是在执行影视工业化SOP。**

---

## 🛠️ 技术栈

| 组件 | 技术 |
|------|------|
| Web框架 | [Streamlit](https://streamlit.io/) |
| LLM调用 | OpenAI SDK（兼容多服务商API） |
| 分镜Agent | [CrewAI](https://github.com/crewAIInc/crewAI)（可选） |
| 数据渲染 | Pandas DataFrame + st.data_editor |
| 文件解析 | python-docx |

### 支持的LLM服务商

| 国内 | 海外 | 本地 |
|------|------|------|
| DeepSeek | OpenAI (GPT-4o) | Ollama |
| 硅基流动 SiliconFlow | Claude (Anthropic) | vLLM |
| 阿里通义 Qwen | Gemini (Google) | |
| Kimi (Moonshot) | Groq | |
| GLM (智谱) | Mistral | |
| 零一万物 Yi | | |

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- pip
- （可选）Ollama 本地运行环境

### 方式一：一键部署脚本（推荐）

#### Windows

双击 `setup_and_run.bat` 或在项目目录下执行：

```cmd
setup_and_run.bat
```

脚本将自动：检测Python版本 → 安装依赖 → 启动应用 → 自动打开浏览器。

#### macOS / Linux

由于本项目在 Windows 环境下开发，macOS 的启动脚本可能不如原生环境便捷。请按以下步骤手动部署：

```bash
# 1. 克隆仓库
git clone https://github.com/slipknot0130/Film-Production-Toolkit.git
cd Film-Production-Toolkit

# 2. 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动应用
python start.py
```

浏览器将自动打开 `http://localhost:8501`。

> 💡 **macOS用户注意**：如需使用分镜工作台的 CrewAI 功能，需额外安装：
> ```bash
> pip install crewai langchain-openai
> ```

### 方式二：手动安装

```bash
# 1. 克隆仓库
git clone https://github.com/slipknot0130/Film-Production-Toolkit.git
cd Film-Production-Toolkit

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动
python start.py
```

### 配置API

1. 在侧边栏选择 LLM 服务商
2. 输入对应的 Base URL 和 API Key
3. 点击「测试连接」验证
4. 开始使用！

如使用本地 Ollama，确保 Ollama 服务已启动，工具将自动检测已安装的模型。

---

## 📁 项目结构

```
Film-Production-Toolkit/
├── app.py                    # 主入口，侧边栏 + 模式路由
├── start.py                 # 启动器（自动检测依赖+端口）
├── setup_and_run.bat        # Windows 一键部署脚本
├── requirements.txt         # Python依赖
├── .env.example             # 环境变量模板（API Key等）
├── StyleTokens.txt          # 全局美术风格词（分镜用）
│
├── creator/                 # 🎬 创作引擎
│   ├── agents_engine.py     # 多智能体协作核心（Showrunner/Writer/Doctor）
│   └── ui_creator.py        # 创作流UI + 跨模式桥接
│
├── production/              # 🎥 制片引擎
│   ├── analysis_engine.py   # 格式感知双轨分析（情绪/结构/电影）
│   ├── crew_storyboard.py   # CrewAI 4-Agent分镜模块
│   ├── llm_utils.py         # LLM工具函数（JSON强制输出+自动重试）
│   └── ui_production.py     # 制片流UI（分析/预算/场景/分镜）
│
└── shared/                  # 🔧 共享层
    ├── llm_config.py        # LLM服务商配置 + 动态Prompt路由引擎
    └── session.py           # Session State命名空间管理
```

---

## 🎮 工作模式

| 模式 | 功能 | 适用场景 |
|------|------|---------|
| 📝 剧本创作 | 3-Agent全流程创作 | 从零开始写剧本 |
| 🎬 剧本分析 | 格式感知双轨审核 | 审查已有剧本质量 |
| 💰 预算审计 | 执行制片人成本精算 | 评估制作预算 |
| 📋 场景拆解 | 物理空间场景解构 | 统筹场记/道具清单 |
| 🎥 分镜工作台 | CrewAI 4-Agent分镜矩阵 | 生成工业级分镜 |

---

## 📜 License

MIT License

---

## 🙏 致谢

- [Streamlit](https://streamlit.io/) — 优雅的Web应用框架
- [CrewAI](https://github.com/crewAIInc/crewAI) — 多智能体协作框架
- [OpenAI](https://openai.com/) — LLM API 生态
- [Ollama](https://ollama.ai/) — 本地LLM运行时
- [Save the Cat](https://savethecat.com/) — 剧本结构理论
- [Robert McKee](https://en.wikipedia.org/wiki/Robert_McKee) — 故事价值转变理论
