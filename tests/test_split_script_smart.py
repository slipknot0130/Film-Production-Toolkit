# -*- coding: utf-8 -*-
"""
回归测试：split_script_smart 的「超长单段二次切分」修复。

历史 bug（2026-07-30）：
  旧实现仅按 '\\n' 切分，当单个段落超过 max_chars 时不再二次切分，
  导致整篇几乎无换行的长剧本退化成 1 个超大块；下游被 SAFE_CAP(28 镜)
  封顶，最终 5000 字剧本只产出约 2 分钟分镜。

本测试锁定不变量：
  - 任何 chunk 都不超过 max_chars；
  - 一行 5000 字（零换行）的剧本必须切成多块，且块数明显 > 1。
"""
import os
import re
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 桩：production.llm_utils 顶层 import streamlit；本测试不依赖真实 streamlit。
_fake_st = types.ModuleType("streamlit")
_fake_st.toast = lambda *a, **k: None
_fake_st.error = lambda *a, **k: None
_fake_st.warning = lambda *a, **k: None
_fake_st.info = lambda *a, **k: None
_fake_st.session_state = {}
sys.modules.setdefault("streamlit", _fake_st)

from production.llm_utils import split_script_smart  # noqa: E402

MAX_CHARS = 550

_BASE = ("林晚猛地抓住陈默的手腕，声音发颤地质问他这些年到底隐瞒了什么，"
         "窗外暴雨倾盆，闪电照亮她苍白的脸。陈默沉默半晌，缓缓道出当年那个雨夜的真相，"
         "两人之间的空气仿佛凝固。远处传来一声闷响，门被人推开，一个意想不到的身影出现在门口。")


def _make_script(chars_per_line):
    parts, cur = [], ""
    while sum(len(p) for p in parts) + len(cur) < 5000:
        cur += _BASE
        if len(cur) >= chars_per_line:
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    return "\n".join(parts)


def test_no_chunk_exceeds_max_chars():
    """核心不变量：任一 chunk 不超过 max_chars。"""
    for cpl in (40, 110, 300, 600, 1200, 5000):
        chunks = split_script_smart(_make_script(cpl), max_chars=MAX_CHARS)
        assert chunks, "应至少切出 1 块"
        assert all(len(c) <= MAX_CHARS for c in chunks), (
            f"存在超过 {MAX_CHARS} 的块: {max(len(c) for c in chunks)}"
        )


def test_single_line_no_break_splits_into_many():
    """回归关键：整篇零换行（1 行 5000 字）必须切成多块，而非 1 块 ≈ 2 分钟。"""
    one_line = _BASE * (5000 // len(_BASE) + 1)
    one_line = one_line[:5000]
    chunks = split_script_smart(one_line, max_chars=MAX_CHARS)
    assert len(chunks) > 1, f"零换行剧本被切成 {len(chunks)} 块（应为多块）"
    # 关键：每块都不超上限，确保下游不会被 SAFE_CAP 整体封顶到 28 镜
    assert all(len(c) <= MAX_CHARS for c in chunks)
    # 估算总镜数下限应远大于 28（约 14 分钟级别），不再塌缩到 2 分钟
    sys.path.insert(0, ROOT)
    from shared.script_preprocessor import generate_duration_guide  # noqa: E402
    total_min = 0
    for c in chunks:
        g = generate_duration_guide(c, 0.0)
        m = re.search(r"本块必须产出\s*(\d+)\s*～\s*(\d+)\s*镜", g)
        if m:
            total_min += int(m.group(1))
    assert total_min > 100, f"总镜数下限仅 {total_min}（应 >100，约 14 分钟级别）"


def test_mixed_long_and_normal_segments():
    """混合用例：超长单段与普通段落混合也能正确切分。"""
    mixed = _make_script(110) + "\n" + ("无换行超长描写：" + _BASE * 8) + "\n" + _make_script(110)
    chunks = split_script_smart(mixed, max_chars=MAX_CHARS)
    assert len(chunks) > 5
    assert all(len(c) <= MAX_CHARS for c in chunks)


def test_empty_input():
    assert split_script_smart("", max_chars=MAX_CHARS) == []
    assert split_script_smart("   \n  \n", max_chars=MAX_CHARS) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
