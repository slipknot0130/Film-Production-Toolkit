# -*- coding: utf-8 -*-
"""
回归测试：分镜时长密度模型（TARGET_CHARS_PER_SHOT=20）。

锁定不变量：
  - 默认密度对齐用户成片模型：12000 字 ≈ 45 分钟（4.5s/镜），5000 字 ≈ 18.75 分钟。
  - 单块（约 550 字）指南下限应在合理区间 [15, 28]。
  - 5000 字剧本（含零换行退化情形）逐块指南下限合计应 ≥ 200 镜，
    配合 assemble 的每镜 4s 下限，保底总时长 ≥ 13 分钟（彻底告别 2 分钟塌缩）。

注意：本测试只覆盖纯算法层（generate_duration_guide）；镜头数下限的
代码层兜底（run_crew_on_chunk 补足重跑）与每镜 4s 下限（assemble_seedance_prompt）
在 production.crew_storyboard 中，需 crewai 运行时，另行验证。
"""
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 桩：shared.script_preprocessor / production.llm_utils 顶层 import streamlit、openai。
# 这两个都是纯算法测试，不该因为重型 SDK 未装/版本不匹配就跑不起来。
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

from shared.script_preprocessor import generate_duration_guide  # noqa: E402
from production.llm_utils import split_script_smart  # noqa: E402

_BASE = ("林晚猛地抓住陈默的手腕，声音发颤地质问他这些年到底隐瞒了什么，"
         "窗外暴雨倾盆，闪电照亮她苍白的脸。陈默沉默半晌，缓缓道出当年那个雨夜的真相，"
         "两人之间的空气仿佛凝固。远处传来一声闷响，门被人推开，一个意想不到的身影出现在门口。")


def _make_script(cpl):
    parts, cur = [], ""
    while sum(len(p) for p in parts) + len(cur) < 5000:
        cur += _BASE
        if len(cur) >= cpl:
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    return "\n".join(parts)


def _min_shots(guide):
    import re
    m = re.search(r'本块必须产出\s*(\d+)\s*～\s*(\d+)\s*镜', guide)
    return int(m.group(1)) if m else 0


def test_single_block_min_shots_in_range():
    chunk = _make_script(110)[:550]
    min_shots = _min_shots(generate_duration_guide(chunk, 0.0))
    assert 15 <= min_shots <= 28, f"单块下限异常: {min_shots}"


def test_zero_break_5000char_guaranteed_floor():
    zero = _BASE * (5000 // len(_BASE) + 1)
    zero = zero[:5000]
    chunks = split_script_smart(zero, max_chars=550)
    total_min = sum(_min_shots(generate_duration_guide(c, 0.0)) for c in chunks)
    # 配合每镜 4s 下限，保底总时长 = total_min * 4s
    guaranteed_min = total_min * 4.0 / 60.0
    assert len(chunks) >= 8
    assert total_min >= 200, f"指南下限合计仅 {total_min}，应≥200"
    assert guaranteed_min >= 13.0, f"保底时长仅 {guaranteed_min:.1f} 分"


def test_normal_linebreak_5000char_guaranteed_floor():
    chunks = split_script_smart(_make_script(110), max_chars=550)
    total_min = sum(_min_shots(generate_duration_guide(c, 0.0)) for c in chunks)
    assert total_min >= 200


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
