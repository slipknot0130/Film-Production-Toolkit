"""
分镜 v4 管线回归测试。

覆盖 shared.script_preprocessor 的规划函数（compute_dynamic_safe_cap /
plan_storyboard_chunks / compute_adaptive_chunk_size / compute_realistic_estimate /
force_min_chunks / generate_duration_guide(safe_cap_override)）以及
production.crew_storyboard 的截断抢救（_salvage_truncated_storyboard +
parse_structured_json 第4路）。

本文件替代仓库根的草稿 _test_plan.py：原草稿只是 print 模拟、无断言、不能防回归；
这里全部改为 pytest 断言，任何逻辑回退都会让测试失败。
"""

import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 桩：shared.script_preprocessor / production.llm_utils 顶层 import streamlit、openai。
# 这些都是纯算法测试，不该因为重型 SDK 未装/版本不匹配就跑不起来。
_fake_st = types.ModuleType("streamlit")
for _a in ("toast", "error", "warning", "info"):
    setattr(_fake_st, _a, lambda *a, **k: None)
_fake_st.session_state = {}
sys.modules.setdefault("streamlit", _fake_st)

if "openai" not in sys.modules:
    try:
        import openai  # noqa: F401
    except Exception:
        for _m in [k for k in sys.modules if k == "openai" or k.startswith("openai.")]:
            sys.modules.pop(_m, None)
        _fake_openai = types.ModuleType("openai")
        _fake_openai.OpenAI = object
        _fake_openai.APIError = Exception
        _fake_openai.APIConnectionError = Exception
        _fake_openai.RateLimitError = Exception
        sys.modules["openai"] = _fake_openai

# crew_storyboard 顶层 import crewai；被抢救的 parse 函数是纯算法、运行时不依赖 crewai。
# 缺失时用桩顶过导入，让截断抢救测试能在无 crewai 环境也跑起来（真实环境有 crewai 时
# setdefault 不会覆盖真模块）。
if "crewai" not in sys.modules:
    try:
        import crewai  # noqa: F401
    except Exception:
        _fake_crewai = types.ModuleType("crewai")
        for _n in ("Agent", "Task", "Crew", "Process", "LLM"):
            setattr(_fake_crewai, _n, object)
        sys.modules["crewai"] = _fake_crewai

from shared.script_preprocessor import (  # noqa: E402
    SAFE_CAP,
    compute_adaptive_chunk_size,
    compute_dynamic_safe_cap,
    compute_realistic_estimate,
    force_min_chunks,
    generate_duration_guide,
    plan_storyboard_chunks,
)


# ─────────────────────────────────────────────────────────────────────────────
# compute_dynamic_safe_cap —— 模型输出上限反推单块安全镜数
# ─────────────────────────────────────────────────────────────────────────────
def test_dynamic_safe_cap_by_model_output_limit():
    # 每镜头约 400 token（含 JSON 结构开销），安全容量 = max_tokens / 400
    assert compute_dynamic_safe_cap(8192) == 20   # DeepSeek 类
    assert compute_dynamic_safe_cap(16384) == 40  # 16K
    assert compute_dynamic_safe_cap(32768) == 81  # 32K
    assert compute_dynamic_safe_cap(4096) == 10   # GLM 类（4095 上限）
    # 未知 / 本地模型（max_tokens<=0）：极保守下限 8，绝不返回 0 或负
    assert compute_dynamic_safe_cap(0) == 8
    assert compute_dynamic_safe_cap(-1) == 8


# ─────────────────────────────────────────────────────────────────────────────
# plan_storyboard_chunks —— 体量→镜数→模型容量反推切块数→保证时长
# ─────────────────────────────────────────────────────────────────────────────
def test_plan_auto_mode_5000_chars():
    """自动模式：完全由体量决定，可达=内容可支撑，无预警。"""
    p = plan_storyboard_chunks(
        script_chars=5000, target_duration_min=0, safe_cap=compute_dynamic_safe_cap(8192)
    )
    assert p["feasible"] is True
    assert p["volume_shots"] == 250          # 5000 / 20
    assert p["achievable_shots"] == 250
    assert p["num_chunks"] == 13             # ceil(250/20)
    assert p["chunk_chars"] == 384           # max(120, 5000//13)
    assert p["warning"] == ""


def test_plan_content_insufficient_caps_and_warns():
    """内容不足以支撑目标：封顶到可支撑上限并预警，绝不虚报。"""
    p = plan_storyboard_chunks(script_chars=8000, target_duration_min=120, safe_cap=20)
    assert p["feasible"] is False
    # 内容只能支撑 400 镜，需求 1600（120分钟/4.5s），必须封顶不虚报
    assert p["volume_shots"] == 400
    assert p["demand_shots"] == 1600
    assert p["achievable_shots"] == 400
    assert p["num_chunks"] == 20             # ceil(400/20)
    assert p["warning"]                      # 必须有预警
    assert "8000" in p["warning"]            # 预警里点明实际体量


def test_plan_long_script_attains_content_cap():
    """长剧本：内容可支撑 1250 镜 < 需求 1600，仍按内容封顶。"""
    p = plan_storyboard_chunks(script_chars=25000, target_duration_min=120, safe_cap=20)
    assert p["feasible"] is False
    assert p["achievable_shots"] == 1250     # 25000 / 20
    assert p["num_chunks"] == 63             # ceil(1250/20)
    assert p["chunk_chars"] == 396           # max(120, 25000//63)


# ─────────────────────────────────────────────────────────────────────────────
# compute_adaptive_chunk_size / compute_realistic_estimate
# ─────────────────────────────────────────────────────────────────────────────
def test_adaptive_chunk_size_auto_returns_default():
    """自动模式（无目标时长）用默认大切块。"""
    assert compute_adaptive_chunk_size(5000, target_duration_sec=0, safe_cap=20) == 550


def test_adaptive_chunk_size_shrinks_when_needed():
    """目标镜数远超默认块容量时，自动缩小切块以增加块数。"""
    size = compute_adaptive_chunk_size(5000, target_duration_sec=18 * 60, safe_cap=20)
    assert size < 550  # 默认 550，这里应缩小（18分钟→240镜，需≥12块）


def test_realistic_estimate_capped_by_safe_cap():
    """单块上限把可达镜数封顶：1 块 × 20 镜 = 20 镜，而非理论 240 镜。"""
    est, secs, capped, theo = compute_realistic_estimate(
        5000, target_duration_min=18, num_chunks=1, safe_cap=20
    )
    assert capped is True
    assert est == 20
    assert theo == 240
    assert secs == 20 * 4.5


# ─────────────────────────────────────────────────────────────────────────────
# force_min_chunks —— 块数不足时递归对半拆分最大块
# ─────────────────────────────────────────────────────────────────────────────
def test_force_min_chunks_noop_when_already_sufficient():
    chunks = ["a" * 100, "b" * 100, "c" * 100]
    out = force_min_chunks(chunks, min_count=2, max_chars=600)
    assert len(out) == 3  # 已≥2 且每块≤600，无需拆分


def test_force_min_chunks_stops_on_tiny_blocks_no_infinite_loop():
    """块都很小（< max_chars）无法再分：安全停止，绝不无限循环。"""
    chunks = ["小", "块"]
    out = force_min_chunks(chunks, min_count=10, max_chars=600)
    assert len(out) == 2  # 拆不动，保持原样


def test_force_min_chunks_reaches_target_when_splittable():
    """含换行的大块：能提升到目标数量，且不产生空块。"""
    line = "内容" * 50                      # 100 字一行
    big = "\n".join([line] * 8)            # ~807 字，含换行
    out = force_min_chunks([big], min_count=4, max_chars=200)
    assert len(out) >= 4
    assert all(c.strip() for c in out)     # 不出现空块


# ─────────────────────────────────────────────────────────────────────────────
# generate_duration_guide(safe_cap_override) —— 动态覆盖默认 SAFE_CAP
# ─────────────────────────────────────────────────────────────────────────────
def test_duration_guide_accepts_safe_cap_override():
    script = "第一场 日 内\n林晚走进房间。\n第二场 夜 外\n他来到天台。\n" * 20
    guide = generate_duration_guide(script, target_duration_sec=18 * 60, safe_cap_override=200)
    assert isinstance(guide, str) and guide.strip()  # 不崩溃、有产出


# ─────────────────────────────────────────────────────────────────────────────
# 截断抢救（v4.8 关键防归零特性）
#   当 LLM 输出撞上模型输出 token 上限，JSON 在「分镜列表」中途断裂时，
#   必须回收所有已完整产出的镜头，绝不整块归零。
# ─────────────────────────────────────────────────────────────────────────────
def _import_parse_structured_json():
    """懒导入：crew_storyboard 顶层 import crewai，缺失时返回 None（测试 skip）。"""
    try:
        from production.crew_storyboard import parse_structured_json
        return parse_structured_json
    except Exception:
        return None


@pytest.fixture
def parse_fn():
    fn = _import_parse_structured_json()
    if fn is None:
        pytest.skip("crewai 未安装，跳过截断抢救测试（在完整运行环境中运行）")
    return fn


_TRUNCATED_JSON = """{
  "全局氛围画质": "电影感",
  "分镜列表": [
    {"镜头号": 1, "景别": "近景", "画面内容": "林晚转身"},
    {"镜头号": 2, "景别": "中景", "画面内容": "陈默点头"},
    {"镜头号": 3, "景别": "全景", "画面内容": "雨夜街
"""


def test_salvage_recovers_complete_shots_from_truncated_json(parse_fn):
    """JSON 在分镜列表中途被截断：回收已完整的 2 个镜头 + 全局氛围，不归零。"""
    data = parse_fn(_TRUNCATED_JSON)
    assert data is not None
    shots = data.get("分镜列表", [])
    assert len(shots) == 2
    assert shots[0].get("画面内容") == "林晚转身"
    assert shots[1].get("画面内容") == "陈默点头"
    assert data.get("全局氛围画质") == "电影感"


def test_parse_returns_none_for_garbage(parse_fn):
    """完全非 JSON 文本：无任何可抢救结构，返回 None。"""
    assert parse_fn("完全不是 json 的乱码文本 一二三四五") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
