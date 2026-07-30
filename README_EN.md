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

#### Creation Workbench UI

Enter core concept and creative direction in the left-side **Inspiration & Control** panel. After clicking "Launch Multi-Agent Writers' Room", the right-side **Script Output** area dynamically generates:

| Output Tab | Content |
|-----------|---------|
| 🗺️ **Global Outline** | Story spine, episode summaries, pacing curve, core conflict nodes |
| 👤 **Character Profiles** | Major character bios, goals, Ghost/Lie/Flaw, relationship network |
| 📄 **Script Body** | Full episode script in selected format, supports continuous generation |
| 💾 **Memory Snapshot** | Current creation checkpoint; can rollback or resume anytime |

![Script Creation UI](assets/images/剧本创作.png)

### 🎬 Script Analysis Engine (Format-Aware Dual-Track Review)

The system **automatically detects** the drama type based on text volume and applies differentiated review standards:

| Drama Type | Review Focus | Core Standards |
|-----------|-------------|---------------|
| Micro-drama / Short | 🎭 Emotion-oriented | Dopamine pacing, emotional payoff, face-slap intensity, hook strength |
| Mid-length / Long drama | 📐 Structure-oriented | Four-act structure, logical consistency, character arcs, twists & foreshadowing |
| Feature Film | 🎥 Hollywood Industry | Save the Cat 15 beats, Ghost/Lie/Flaw, McKee scene value transition |

#### Smart Format Detection UI

After importing a script, the system automatically displays recognition results at the top:

| Detection Dimension | Example Output |
|--------------------|----------------|
| **Detected Type** | Feature Film / Short Drama / Micro-Drama / Mid-length Drama / Long Drama |
| **Total Characters** | 25,777 chars |
| **Episodes** | No episode markers detected / N episodes total |

#### Review Mode Selection

Users can manually switch or accept the system recommendation:

| Mode | Toggle | Best For |
|------|:------:|:---------|
| 🎭 Emotion-oriented Review | Toggle | Micro-drama / Short drama |
| 📐 Structure-oriented Review | Toggle | Mid-length / Long drama |
| 🎥 Hollywood Industry Review | Toggle | Feature film |

Click "Launch Script Doctor Analysis" and the Doctor Agent outputs a structured diagnosis based on the active review mode.

![Script Analysis UI](assets/images/剧本分析.png)

### 💰 Budget Audit Engine

- **Executive Producer Audit**: Line-by-line cost burning detection + AI replacement strategies
- **Professional Production Budget**: Crew scale, daily rates, per-scene cost breakdowns, location recommendations

#### Budget Workbench UI

After loading a script, the system shows "Script loaded, X characters" and offers two independent pipelines:

| Pipeline | Button | Output |
|----------|--------|--------|
| **Executive Producer Audit** | "Launch Budget Audit Pipeline" | Cost-burning points list, AI cost-saving alternatives, cuttable items |
| **Professional Production Budget** | "Launch Professional Production Budget Pipeline" | Chinese film-industry crew budget table, scene difficulty analysis, domestic location recommendations, full executable budget |

![Budget Audit UI](assets/images/预算审计.png)

### 📋 Scene Breakdown Engine

OCD-level continuity supervision — Deconstruct every scene by physical space, extract prop lists and wardrobe requirements.

#### Scene Breakdown Master Table (Physical Space Deconstruction)

Click "Launch Continuity Supervision Pipeline" and the system deconstructs the script into physical scenes, outputting switchable breakdown tables:

| Table View | Sort Order |
|------------|-----------|
| 📜 **Sequential Scene List** | Story order |
| 🏠 **By Scene Location** | Grouped by scene name |

**Example row fields:**

| # | Scene Name | Int/Ext | Day/Night | Characters | Physical Props List | Special Wardrobe |
|:-:|:----------:|:-------:|:---------:|:----------:|:-------------------:|:----------------:|
| 1 | Outside Building | Ext | Night | Protagonist | Building, backpack, smartwatch, street, scattered cars | Coder plaid shirt |
| 2 | Brain Command Room | Int | Night | Brain | Nutrient fluid, neural cables, pearl-shaped brain model | None |
| 3 | Protagonist's Home | Int | Night | Protagonist | Door, backpack, sofa | Coder plaid shirt |

> Continuity rule: list only physical props and special wardrobe. No plot summaries.

The table supports Excel export and can be handed directly to the production team.

![Scene Breakdown UI](assets/images/场景表拆解.png)

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

#### Storyboard Workbench UI

After loading a script and launching the CrewAI 4-Agent pipeline, the workbench outputs:

| Area | Content |
|------|---------|
| 🎨 **Global Atmosphere & Image Quality Setup** | Expandable panel: style tone, color theme, lighting style, unified image-quality tokens — the visual bible for the entire storyboard |
| 🎬 **Seedance 2.0 Storyboard Matrix** | Standard table: Shot # / Timecode / Shot Size · Position · Motion / Final Seedance Prompt, with one-click Excel download |

![Storyboard Workbench UI](assets/images/分镜工作台.png)

#### 5-Column Seedance 2.0 Final Prompt Output

Final output is standard JSON array, directly renderable as DataFrame table:

| Column | Content |
|--------|---------|
| Shot # / Timecode / Shot Size · Position · Motion (fused description) / Base Setup Tag |
| **Final Seedance Prompt** | A complete text block ready to paste directly into Seedance 2.0. Structure: [Director Intent] + [Subject & Feature Anchoring] + [Reference Relation & Sub-task] + [Dynamic Description] + [Static Description]. Professional case-level density, no manual post-processing needed |

#### 🎯 Storyboard Target Duration (Density) Control (v4.6 NEW)

A new "🎯 Storyboard Target Duration (Density)" sub-option in the storyboard workbench sidebar lets the same script be broken down into shots at different densities according to the target episode length:

| Option | Target Episode Length | Use Case |
|--------|:---:|----------|
| Auto (by script word count density) | Derived from word count (~1 shot / 24 chars) | Let the program adapt to script volume |
| Short Drama · 2 min/ep | 2 min | Short drama: fewer, longer shots |
| Vertical Short · 3 min/ep | 3 min | Vertical micro-drama |
| Standard · 10 min/ep | 10 min | Regular web series episode |
| Long Drama · 45 min/ep | 45 min | Long drama: many, dense shots |
| Custom | 0.5–180 min | Any target length |

**How it works:**
- Once a target is selected, the program derives the **shot count** from `target seconds ÷ average shot seconds` (average shot seconds is a fixed reference assumption: 4.5s dialogue-heavy / 5.0s balanced / 4.0s action-heavy) and enforces it as a hard floor for the Director — under-splitting is forbidden.
- In chunked mode, each chunk receives a share of the target duration **proportional to its character count**, ensuring overall density is met for long scripts; each chunk stays within the safe cap of 28 shots (prevents 8K token output truncation).
- **Reference duration ≠ forced duration**: the program only outputs the reference duration and the corresponding shot count; the actual length of each shot in Jimeng (Seedance) is set by you. For a short script (~5000 chars), the 45-min preset yields at most ~252 shots (~17 min reference); the UI warns "script too short" and will not pretend to hit the target — you can then lengthen individual shots in Jimeng to fill the final runtime.

**QA safety net:** the QA Agent adds a "shot-count floor review" — if the actual output falls below the hard floor, it is flagged as failed and sent back for re-splitting.

#### 🎯 Director Intent Engine `felt_intent` (v4.3 NEW)

Each shot carries an independent director intent field that drives the global choice of shot size, camera position, and motion — informed by Seedance 2.0 Skill OS `directing-engine` + `felt-intent`:

| Intent Type | Example | Driven Visual Settings |
|------------|---------|----------------------|
| **Reveal** | "Make the audience notice the scar on his hand" | Mid-shot → slow push to close-up + side light for texture |
| **Oppression** | "Make her appear small and helpless in frame" | High-angle wide shot + disproportionate environment scale |
| **Intimacy** | "Close the unspoken distance between them" | Shallow DOF two-shot + slow rack focus + warm diffused light |

> "A reveal is not lit, framed, blocked, or performed like a farewell." — Seedance 2.0 core principle

#### 🚫 Systematic Anti-Slop Lexicon (v4.3 NEW)

Informed by `anti-slop-lexicon.md`. 4 categories of banned words + specific alternative guides. Double-locked by both Director and QA:

| Category | Banned Examples | Correct Approach |
|----------|----------------|-----------------|
| **Inflated Words** | cinematic, epic, stunning, breathtaking | Provide concrete visual sources and light/shadow details |
| **Empty Boosters** | high quality, masterpiece, 8k, 4k | Describe material texture, light direction, resolution causation |
| **Abstract Labels** | emotional, beautiful, atmospheric | List visible evidence: color, light, action |
| **Vague Words** | warm, oppressive, ambiguous, cheap, terrifying, romantic | Transcribe as color temp, spatial scale, character distance |

#### 🎥 Enhanced Lens · Motion · Lighting Vocabulary (v4.3 NEW)

Extracted from Seedance 2.0 `seedance-camera` + `seedance-motion` + `seedance-lighting` references, injected into Director Agent:

| Vocabulary Type | Before | v4.3 | New Capabilities |
|----------------|:---:|:---:|-----------------|
| **Shot Size** | 6 | **11** | Dutch Angle, OTS, Subjective POV, ECU, Establishing Shot |
| **Camera Motion** | 8 | **11** | Parallax Slide, Dolly Zoom, Reaction Shot, Discovery Shot |
| **Camera Position** | Basic | **6** | Each annotated with emotional meaning (low angle = authority/threat, high angle = insignificance, eye level = empathy) |
| **Light Sources** | — | **6** | Key, Fill, Rim, Ambient, Practical, Bounce |
| **Color Temp** | — | **4 families** | Cool (6500K+) / Neutral (4500–5500K) / Warm (2700–3500K) / Ultra-warm (<2000K), with time-of-day cues |

#### 🧠 Model Mechanics Injection (v4.3.1 NEW)

Adapted from Seedance 2.0 `model-mechanics.md`. Agents now understand **why** rules work, not just what they are:

| Mechanism | What's Injected |
|-----------|----------------|
| **Fidelity Budget** | Gen-1 allocates limited fidelity — don't waste it on non-critical regions; concentrate on frame core |
| **Positional Weight** | Prompt opening > middle > end → place critical features first in Section 1 subject anchoring |
| **Capability Map** | Strengths: material textures, light interaction, fluid motion, micro detail. Weaknesses: precise text, fingers, complex spatial relations |
| **Consistency > Complexity** | Prefer simplified settings with solid character consistency over complex environments with character drift |

#### 🔄 Reshoot Decision Protocol (v4.3.1 NEW)

QA upgraded from binary pass/fail to 4-tier quality grading + targeted retake strategy:

| Quality Tier | Threshold | Action |
|-------------|:---:|--------|
| **Tier A** | ≥90% | Pass directly, minor tweaks only |
| **Tier B** | 80–89% | Pass, flag improvement points for next round |
| **Tier C** | 60–79% | **Single-variable retake**: fix only the biggest problem, don't touch other dimensions |
| **Tier D** | <60% | Full retake, preserve scene definition and character info |

- **Single-Variable Principle**: Change only one dimension at a time (light / composition / action) to avoid cascade damage
- **Attempt Budget**: Max 2 retakes per shot; exceeding triggers human review flag, no infinite loops

#### 📊 Event Density Firewall (v4.3 NEW)

QA Agent enforces a mathematical model:

```
Independent Events / Shot Duration (sec) > 0.5  →  Overloaded → Split shot or extend duration
```

Eliminates the common AI issue: cramming multiple independent actions + camera changes into a 4-5 second shot.

#### 🔌 Multimodal Reference Extension Points (v4.3.1 Reserved)

Reserved `@Image` / `@Video` / `@Audio` reference syntax interface (`_resolve_multimodal_references()` stub function). Future I2V / V2V integration won't require refactoring the core storyboard logic. Zero impact in current text-only T2V mode.

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
├── assets/                   # 📸 UI screenshots & static resources
│   └── images/               # README showcase screenshots
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
