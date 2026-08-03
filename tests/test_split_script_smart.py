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

# 桩：production.llm_utils 顶层 import streamlit / openai；
# split_script_smart 是纯文本函数，不该因为这两个重型 SDK 装不上就跑不了测试。
_fake_st = types.ModuleType("streamlit")
_fake_st.toast = lambda *a, **k: None
_fake_st.error = lambda *a, **k: None
_fake_st.warning = lambda *a, **k: None
_fake_st.info = lambda *a, **k: None
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


# ─────────────────────────────────────────────────────────────────────────────
# 回归：空行不得触发强制切块（2026-07-30 二次事故）
# ─────────────────────────────────────────────────────────────────────────────
# 上一版修复引入了「遇空行即 _flush()」，导致「场标 + 空行 + 台词 + 空行」这种
# 最常规的剧本排版被打碎成几十上百个十几字的碎块。下游对每个碎块各跑一次
# Director+QA，既极慢又产出垃圾镜头。首版测试全部用 "\n".join 构造，
# 没有任何空行用例，所以完全没抓到 —— 这里补齐。

_SCREENPLAY = """\
第1场 深夜 内景 林晚的公寓 雨

林晚站在窗前，雨点砸在玻璃上。

林晚：（声音发颤）这些年，你到底瞒了我什么？

陈默沉默半晌，缓缓转过身来。

陈默：那个雨夜的事，我一直没敢说。

远处传来一声闷响，门被人推开。

第2场 同夜 内景 走廊

一个意想不到的身影出现在门口，逆光看不清脸。

林晚猛地后退一步，撞翻了身后的花瓶。
"""


def test_blank_lines_do_not_shatter_into_tiny_chunks():
    """常规剧本排版（段落之间有空行）不得被打碎成大量碎块。"""
    chunks = split_script_smart(_SCREENPLAY, max_chars=MAX_CHARS)
    assert chunks, "应至少切出 1 块"
    assert all(len(c) <= MAX_CHARS for c in chunks)

    total_chars = sum(len(c) for c in chunks)
    avg_len = total_chars / len(chunks)
    # 该剧本约 200 余字，max_chars=550 → 合理结果是 1 块。
    # 出 bug 时会切出 10+ 块、平均长度不到 20 字。
    assert len(chunks) <= 2, f"被切成 {len(chunks)} 块（应 ≤2）：{[len(c) for c in chunks]}"
    assert avg_len > 100, f"平均块长仅 {avg_len:.1f} 字，说明空行触发了错误的强制切块"


def test_blank_line_script_chunk_count_scales_with_length():
    """放大到 5000 字的带空行剧本：块数应由 max_chars 决定，而非由空行数量决定。"""
    long_script = (_SCREENPLAY + "\n") * 25          # ≈ 5000+ 字，含大量空行
    chunks = split_script_smart(long_script, max_chars=MAX_CHARS)

    assert all(len(c) <= MAX_CHARS for c in chunks)
    expected = len(long_script) / MAX_CHARS          # 理论块数
    # 允许 2.5 倍冗余（边界对齐会产生一些未填满的块），
    # 但出 bug 时块数会是理论值的 20 倍以上。
    assert len(chunks) <= expected * 2.5, (
        f"切出 {len(chunks)} 块，理论仅需约 {expected:.0f} 块 —— 空行导致过度切块"
    )
    assert sum(len(c) for c in chunks) / len(chunks) > MAX_CHARS * 0.3, "平均块长过低"


def test_blank_lines_preserve_paragraph_separation():
    """空行应作为段落分隔保留在块内，不能把相邻段落粘成一行。"""
    text = "第1场 内景 客厅\n\n林晚：你回来了。\n\n陈默点头。"
    chunks = split_script_smart(text, max_chars=MAX_CHARS)
    assert len(chunks) == 1
    joined = chunks[0]
    assert "第1场 内景 客厅" in joined
    assert "林晚：你回来了。" in joined
    assert "陈默点头。" in joined
    # 段落之间必须仍有换行，不能退化成 "客厅林晚：你回来了。"
    assert "客厅林晚" not in joined


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
