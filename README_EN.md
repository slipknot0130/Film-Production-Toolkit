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

### 🎥 AI Video Storyboard Prompt Engine (Seedance 2.0 Compatible · Industrial-Grade Multi-Agent Generation)

This is not your average storyboard breakdown — we've built a complete **AI video generation lens logic system** from the ground up, so LLM outputs can be fed directly into video tools like Kling and Jimeng without manual re-processing.

#### 20 Scenario Mapping Engine

Pre-defined 20 industrial-grade scenarios (E01–E20), each locking in focal length + aperture + camera position + motion core combo, preventing AI free-styling from causing perspective conflicts or style drift:

| Scenario ID | Typical Scene | Core Combo |
|------------|--------------|-----------|
| E01 | Protagonist Awakening | Mid 50-85mm + f/4 + low-angle mid-shot + slow track-in |
| E02 | Villain Entrance | Wide 24-35mm + f/2.0 + low-angle static + subtle push |
| E06 | Rage Outburst | Wide + large aperture + handheld fast shake |
| E13 | Kubrickian Alienation | Strong symmetrical center + wide + slow push |
| E15 | Divine Epiphany | Backlit silhouette + overexposed background + slow crane-up |
| E19 | Object Parabolic Tracking | Mid 85mm + f/4 + side-level + whip pan Catch |

#### 80/15/5 Weight Mechanism

| Weight | Type | Constraint |
|--------|------|-----------|
| **80%** | Core Combo (locked) | From Scenario ID, all mandatory, no substitution or deletion |
| **15%** | Auxiliary Anchors | Enhance emotional details, pick 1–2 items |
| **5%** | Enhancer | Only at emotional hit points, max 1 shot per scene |

#### 6+1 Required Storyboard Fields

Every shot must output 6 required fields + 1 optional constraint field:

| Field | Description |
|------|-------------|
| **Focal Length** | Ultra-wide / Wide / Standard / Mid / Long / Macro |
| **Aperture** | Ultra-large f/1.2–f/1.8 / Large f/2.0–f/2.8 / Medium f/4–f/5.6 / Small f/8+ |
| **Camera Position** | **5-Element Template**: camera position + height + angle + subject action + shot size |
| **Composition** | Composition rule (rule of thirds / golden ratio / framing / diagonal / negative space / symmetry) + spatial zone content (foreground / left / right / background) |
| **Camera Motion** | Bilingual professional terms (Dolly In / Steadicam / Hitchcock Zoom / handheld breathing) |
| **Subject Action & Expression** | Dialogue must be embedded in this line, no separate field |
| **Constraint (optional)** | AI error-prone constraints (e.g. "no subtitles" "costume identical to previous shot") |

#### 5-Dimensional Visual Continuity

5 continuity rules enforced between adjacent shots:

| Dimension | Rule |
|-----------|------|
| **A. 180° Axis** | Camera never crosses imaginary axis in dialogue scenes (except intentional break) |
| **B. Eyeline Match** | Character looks right in Shot A → Character enters from left in Shot B and looks left |
| **C. Action Continuity 60%** | End action of Shot A = 60–80% continuation at start of Shot B, no action jumps |
| **D. Prop State Continuity** | Water level / cigarette length / costume consistency across same scene |
| **E. Shot Size Variation** | No 3+ consecutive shots of same shot size (same-size cuts = jump-cut anxiety) |

#### Perspective Shielding Rule (Fixes AI Video "Face on Back of Head")

When camera position is **behind / over-shoulder / rear-side**, facial expression descriptions are forcibly removed:
- ❌ "frowning, tears rolling, glaring" → ✓ "shoulders trembling, back stiff, clenched fists"
- ❌ "eyes burning with anger" → ✓ "brows furrowed, jaw clenched, fists shaking slightly"
- Prevents AI video models from generating facial features on the back of heads

#### Abstract Description Translation Engine

Automatically converts literary abstract emotions into **shootable physical actions**:

| Literary Description | Translated Result |
|---------------------|-------------------|
| "His heart collapsed" | Fingers pinching other hand under table, breathing short but face remains calm |
| "Burning with rage" | Brows furrowed, jaw clenched, clenched fists trembling slightly |
| "She summoned courage" | Straw stirs milk tea one beat slower, head lifts 0.5s later than opponent |

#### Prop Physical Perspective Rule

- **Item back facing camera**: When character reads letter, paper back faces camera, no text visible
- **Prop dimensional reduction**: "Conscription notice" → "a piece of rough paper"; "secret letter" → "a folded letter in hand"
- **No physics violations**: Seal face never faces camera (unless specifically shooting item close-up)

#### Drama/Action Rhythm Engine

| Type | Motion Style | Shot Density | Shot Size |
|------|-------------|-------------|-----------|
| Drama | Static or slow motion | 1–3 per segment (sparse) | Close-up / ECU |
| Action | Handheld fast shake + jump cuts | 2–3× drama density (dense) | Rapid alternation |

- Drama dialogue: Auto-insert **reaction shots** every 2–3 lines, focusing on listener's expression
- Action: Rapid shot-size jumps (ECU → Wide → Side) to build tension

#### 5-Column Seedance 2.0 Final Prompt Output

Final output is standard JSON array, directly renderable as DataFrame table:

| Column | Content |
|--------|---------|
| Shot # / Timecode / Shot Size · Position · Motion (fused description) / Base Setup Tag |
| **Final Seedance Prompt** | A complete text block ready to paste directly into Seedance 2.0. Structure: [Base Setup] (character appearance/costume/environment/image quality defined once) + [Frame Content] Shot N: timecode + high-density visual description (character details/environment lighting/camera trajectory/material interaction/lens simulation keywords). Professional case-level density, no manual post-processing needed |

---

### 🔧 Harness Engineering Layer (v0.2.0)

Harness is a modular engineering middleware that sits between the UI and the Agents Engine, adding production-grade **resilience, memory, and cost controls** to the 3-Agent screenwriting pipeline. All modules follow a "opt-in, backward-compatible, incremental enhancement" design principle.

#### 6 Core Modules

| Module | Problem Solved | Real Impact |
|--------|---------------|-------------|
| **CheckpointManager** | Page refresh / browser crash / power loss = all progress lost | Save or restore at any moment. Auto-save every N episodes. 100-episode series without fear of interruption |
| **StructuredMemoryStore** | Single blob memory text → character personality, location, plot threads drift badly after 50+ episodes | `CharacterState` tracks each character's position/emotion/goal/relationships/secrets precisely; `PlotThread` manages lifecycle per thread (planted→active→revealed); `EpisodeIndex` retrieves summaries by episode number |
| **ContextRetriever** (JIT) | Every Writer call injects full context (5000+ tokens), growing unbounded with episode count | Only injects minimal necessary context (current outline segment + last 3 episode summaries + active characters + active threads). **Token cost reduced 40-60%** |
| **ToolSchema + ToolRegistry** | All agent capability rules buried in long prompt text, model comprehension imprecise | OpenAI function-calling compatible structured tool definitions. Each agent gets only its own toolset, precisely injected |
| **BudgetTracker + TerminationGuard** | Infinite token-burning loops when Doctor is never satisfied or API is unstable | **6-layer termination**: safety reject → user interrupt → natural complete → budget exceeded → round limit → guardrail violation. Hard cap: 10 rounds × 5000 tokens = 50K tokens per episode |
| **Safety Guardrails** | No content safety constraints on agent output | Safety guardrails injected at highest priority in Writer's 5-layer prompt injection. Doctor upgraded to adversarial review mode |

#### Pipeline Bug Fixes

| Issue (v0.1) | Fix (v0.2) |
|-------------|-----------|
| **Writer retry dead loop**: Doctor rejection feedback never reached Writer, resulting in blind rewrites | Doctor feedback + Writer's previous draft actually passed into the retry branch, enabling **spiral refinement** |
| **Force-approved episodes skipped Harness**: No memory/character/checkpoint updates in force-approve path | Full Harness flow added: memory extraction → character state update → checkpoint auto-save |
| **CheckpointManager re-created 3-5x per page lifecycle** | `session_state` singleton cache — created once per full lifecycle |
| **Storyboard serial bottleneck**: Image and Video prompts had to wait | New `parallel=True` mode: Image ∥ Video parallel generation, **30-40% faster** |

---

- **CrewAI 4-Agent Seedance 2.0 Storyboard Matrix**: Seedance Director → Visual Archivist → Seedance Prompt Engineer → Seedance QA Reviewer
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
| **Engineering Resilience** | No checkpointing, crash = wipe | Harness CheckpointManager: save/restore anytime, auto-save at configurable intervals |
| **Long-Form Memory** | No structured mechanism, plot inconsistencies inevitable | CharacterState + PlotThread + EpisodeIndex structured tracking, 100 episodes without amnesia |
| **Token Efficiency** | Full context injection, linear growth | JIT ContextRetriever: minimal necessary context on-demand, **40-60% savings** |
| **Safety Guard** | No content constraints | Safety Guardrails at highest prompt priority + 6-layer termination to prevent infinite token burn |

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
| SiliconFlow | Claude (Anthropic) | |
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
├── harness/                  # 🔧 Harness Engineering Layer (v0.2.0)
│   ├── __init__.py           # Module entry, version v0.2.0
│   ├── checkpoint.py         # CheckpointManager: resume-from-any-episode + WorkflowContext
│   ├── memory_store.py       # StructuredMemoryStore (character state / plot threads / episode index)
│   ├── context_retriever.py  # JIT context retrieval, 40-60% token reduction
│   ├── tool_schema.py        # ToolSchema / ToolRegistry, structured agent capabilities
│   ├── termination.py        # BudgetTracker + TerminationGuard 6-layer safety net
│   └── config.py             # Unified configuration management
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
