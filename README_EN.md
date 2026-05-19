# 🎬 Film Production Toolkit

**Multi-Agent Driven Film Industry AI Workbench** — Built-in writers' room SOP, format-aware review & long-text deep processing, from inspiration to storyboard in one place.

中文 | [English](./README_EN.md)

---

## 📖 Overview

Film Production Toolkit is a multi-agent collaboration system for professional screenwriting and production management. It combines a **Creative Engine** (3-Agent screenwriting studio) with a **Production Engine** (analysis, budgeting, scene breakdown, and storyboarding), delivering a complete pipeline from idea to storyboard. Through episode-level memory checkpoints and summary propagation, it solves the context-breakage problem that plagues long-script generation in standard LLM chats.

### 🎯 Core Philosophy

> **Code = SOP(Team)** — Bringing Hollywood writers' room industrial workflows to everyone's desk as an AI team.

---

## ✨ Key Features

### 📝 Screenwriting Engine (3-Agent Collaboration)

| Agent | Role | Responsibility |
|-------|------|---------------|
| 🏗️ Showrunner | Architect | Generate global outline, character bios, episode planning & pacing |
| ✍️ Writer | Screenwriter | Write complete episode scripts with visual storytelling |
| 🩺 Doctor | Script Doctor | QA review, reject & rewrite, generate memory checkpoints |

- **Two-Phase Approval**: Showrunner generates outline → User approves → Batch script generation
- **HITL Targeted Revision**: Submit revision notes for outline/episodes — Agents refine specifically, not rewrite everything
- **5 Script Formats**: Vertical micro-drama / Short drama / Mid-length drama / Long drama / Feature film

### 🎬 Script Analysis Engine (Format-Aware Dual-Track Review)

The system **automatically detects** the drama type based on text volume and applies differentiated review standards:

| Drama Type | Review Focus | Core Standards |
|-----------|-------------|---------------|
| Micro-drama / Short | 🎭 Emotion-oriented | Dopamine pacing, emotional payoff, face-slap intensity, hook strength |
| Mid-length / Long drama | 📐 Structure-oriented | Four-act structure, logical consistency, character arcs, twists & foreshadowing |
| Feature Film | 🎥 Hollywood Industry | Save the Cat 15 beats, Ghost/Lie/Flaw, McKee scene value transition |

### 💰 Budget Audit Engine

- **Executive Producer Audit**: Line-by-line cost burning detection + AI replacement strategies
- **Professional Production Budget**: Crew scale, daily rates, per-scene cost breakdowns, location recommendations

### 📋 Scene Breakdown Engine

OCD-level continuity supervision — Deconstruct every scene by physical space, extract prop lists and wardrobe requirements.

### 🎥 Storyboard Workbench

- **CrewAI 4-Agent Industrial Storyboard Matrix**: Storyboard Director → Art Director → QA Director → Output
- **9-Column Industrial Storyboard Table**: Shot size / Angle / Description / Chinese prompt / English prompt / Dialogue / Sound / Duration / Notes
- **Global Art Style Tokens**: Customizable StyleTokens automatically appended to every shot's English prompt

### 🔄 Create-Analyze-Modify Closed Loop

```
Script Creation → One-click Analysis → Differentiated Review → AI One-click Modification → Return to Analysis
```

---

## 🆚 Key Differences from Online LLMs (ChatGPT/Claude/Doubao etc.)

| Dimension | Online LLM Chat | This Tool |
|-----------|----------------|-----------|
| **Workflow** | Single-turn conversation, manual context management | Built-in 3-Agent pipeline: Showrunner→Writer→Doctor, auto-looping |
| **Professionalism** | General chat, lacks industry constraints | Embedded Hollywood standards (Save the Cat / Ghost-Lie-Flaw / McKee) |
| **Format Adaptation** | One prompt fits all | 5 formats × 3 agents = 15 specialized prompts with dynamic routing |
| **Quality Control** | Output is final, no QA | Doctor Agent reviews each episode, rejects & rewrites (up to 3 rounds) |
| **Long-Text Processing** | Token-window limited, long dramas inevitably break & forget | Episode-level memory checkpoints + summary propagation, 10K-line scripts never break or forget |
| **Review Standards** | No differentiation, same for micro-drama and film | Format-aware dual-track engine: micro-drama emphasizes emotion, film emphasizes structure |
| **HITL Collaboration** | Every modification = rewrite from scratch | Targeted refinement: only fix what user points out, preserve the good parts |
| **Production Management** | None | Budget audit / Scene breakdown / Storyboard matrix, all-in-one |
| **Model Access** | Locked to a single platform, no alternatives | 12+ providers freely switchable (cloud APIs + local models), pick what fits |
| **Cost Flexibility** | Single pricing model, long-drama costs spiral | Multi-provider comparison + local model option, costs under your control |

### 🔑 One-Line Summary

> **Online LLMs are "general chat"; this tool is a "multi-agent writers' room" — it doesn't chat, it executes film industry SOPs.**

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|-----------|
| Web Framework | [Streamlit](https://streamlit.io/) |
| LLM Calls | OpenAI SDK (compatible with multiple providers) |
| Storyboard Agent | [CrewAI](https://github.com/crewAIInc/crewAI) (optional) |
| Data Rendering | Pandas DataFrame + st.data_editor |
| File Parsing | python-docx |

### Supported LLM Providers

| China | International | Local |
|-------|--------------|-------|
| DeepSeek | OpenAI (GPT-4o) | Ollama |
| SiliconFlow | Claude (Anthropic) | vLLM |
| Alibaba Qwen | Gemini (Google) | |
| Kimi (Moonshot) | Groq | |
| GLM (Zhipu) | Mistral | |
| Yi (01.AI) | | |

---

## 🚀 Quick Start

### Requirements

- Python 3.10+
- pip
- (Optional) Ollama for local LLM

### Option 1: One-Click Setup Script (Recommended)

#### Windows

Double-click `setup_and_run.bat` or run from the project directory:

```cmd
setup_and_run.bat
```

The script will automatically: check Python version → install dependencies → launch app → open browser.

#### macOS / Linux

Since this project was developed on Windows, the macOS launch script may not be as convenient as a native setup. Please follow these manual steps:

```bash
# 1. Clone the repository
git clone https://github.com/slipknot0130/Film-Production-Toolkit.git
cd Film-Production-Toolkit

# 2. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Launch the application
python start.py
```

The browser will automatically open at `http://localhost:8501`.

> 💡 **macOS users note**: For the CrewAI storyboard feature, install additionally:
> ```bash
> pip install crewai langchain-openai
> ```

### Option 2: Manual Installation

```bash
# 1. Clone the repository
git clone https://github.com/slipknot0130/Film-Production-Toolkit.git
cd Film-Production-Toolkit

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch
python start.py
```

### Configure API

1. Select an LLM provider in the sidebar
2. Enter the corresponding Base URL and API Key
3. Click "Test Connection" to verify
4. Start creating!

For local Ollama, ensure the Ollama service is running. The tool will auto-detect installed models.

---

## 📁 Project Structure

```
Film-Production-Toolkit/
├── app.py                    # Main entry, sidebar + mode routing
├── start.py                 # Launcher (auto dependency check + port)
├── setup_and_run.bat        # Windows one-click setup script
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template (API keys etc.)
├── StyleTokens.txt          # Global art style tokens (for storyboard)
│
├── creator/                 # 🎬 Creative Engine
│   ├── agents_engine.py     # Multi-agent core (Showrunner/Writer/Doctor)
│   └── ui_creator.py        # Creative UI + cross-mode bridge
│
├── production/              # 🎥 Production Engine
│   ├── analysis_engine.py   # Format-aware dual-track analysis
│   ├── crew_storyboard.py   # CrewAI 4-Agent storyboard module
│   ├── llm_utils.py         # LLM utilities (forced JSON output + auto-retry)
│   └── ui_production.py     # Production UI (analysis/budget/scenes/storyboard)
│
└── shared/                  # 🔧 Shared Layer
    ├── llm_config.py        # LLM provider config + dynamic prompt routing engine
    └── session.py           # Session state namespace management
```

---

## 🎮 Work Modes

| Mode | Function | Use Case |
|------|----------|----------|
| 📝 Script Creation | 3-Agent full pipeline | Write scripts from scratch |
| 🎬 Script Analysis | Format-aware dual-track review | Audit existing script quality |
| 💰 Budget Audit | Executive producer cost analysis | Evaluate production budget |
| 📋 Scene Breakdown | Physical space deconstruction | Continuity supervision / prop lists |
| 🎥 Storyboard | CrewAI 4-Agent storyboard matrix | Generate industrial-grade storyboards |

---

## 📜 License

MIT License

---

## 🙏 Acknowledgments

- [Streamlit](https://streamlit.io/) — Elegant web application framework
- [CrewAI](https://github.com/crewAIInc/crewAI) — Multi-agent collaboration framework
- [OpenAI](https://openai.com/) — LLM API ecosystem
- [Ollama](https://ollama.ai/) — Local LLM runtime
- [Save the Cat](https://savethecat.com/) — Screenplay structure theory
- [Robert McKee](https://en.wikipedia.org/wiki/Robert_McKee) — Story value transition theory
