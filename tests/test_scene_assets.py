"""场景资产提取回归测试。"""
import sys
import types
import pytest

# Stub streamlit and openai so production.analysis_engine imports cleanly in the broken venv
if "streamlit" not in sys.modules:
    _st = types.ModuleType("streamlit")
    _st.toast = lambda *a, **k: None
    _st.error = lambda *a, **k: None
    _st.warning = lambda *a, **k: None
    _st.info = lambda *a, **k: None
    _st.session_state = {}
    sys.modules["streamlit"] = _st

if "openai" not in sys.modules:
    try:
        import openai  # noqa: F401
    except Exception:
        for _m in [k for k in list(sys.modules.keys()) if k == "openai" or k.startswith("openai.")]:
            sys.modules.pop(_m, None)
        _fake_openai = types.ModuleType("openai")
        _fake_openai.OpenAI = object
        _fake_openai.APIError = Exception
        _fake_openai.APIConnectionError = Exception
        _fake_openai.RateLimitError = Exception
        sys.modules["openai"] = _fake_openai

from production.analysis_engine import extract_scene_visual_prompts


class _FakeClient:
    """极简 fake client，只用于占位（call_llm_json 内部并不真的调用 client.chat.completions）。"""
    pass


def test_extract_scene_visual_prompts_merges_llm_assets():
    """LLM 正常返回时，visual_prompt 等字段应合并回原始 scene_list。"""
    # 临时 monkeypatch call_llm_json
    import production.analysis_engine as ae
    original = ae.call_llm_json

    def _fake_call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0):
        return {
            "scene_assets": [
                {
                    "场景名称": "老旧公寓客厅",
                    "内外景": "内",
                    "日夜": "夜",
                    "visual_prompt": "A dimly lit cramped living room, 1980s Chinese apartment...",
                    "关键视觉元素": ["做旧皮沙发", "暖黄台灯", "斑驳墙面"],
                    "光线氛围": "低色温暖光侧光",
                    "色调": "低饱和暖棕",
                },
                {
                    "场景名称": "雨夜街道",
                    "内外景": "外",
                    "日夜": "夜",
                    "visual_prompt": "Rainy neon-lit street at night, wet asphalt reflections...",
                    "关键视觉元素": ["霓虹招牌", "积水倒影", "雨伞人群"],
                    "光线氛围": "冷蓝霓虹逆光",
                    "色调": "青橙高对比",
                },
            ]
        }

    ae.call_llm_json = _fake_call_llm_json
    try:
        scenes = [
            {"场景名称": "老旧公寓客厅", "内外景": "内", "日夜": "夜", "出场人物": "林晚"},
            {"场景名称": "雨夜街道", "内外景": "外", "日夜": "夜", "出场人物": "陈默"},
        ]
        result = extract_scene_visual_prompts(scenes, "剧本正文...", _FakeClient(), "fake-model", {})

        assert len(result) == 2
        assert result[0]["visual_prompt"].startswith("A dimly lit")
        assert result[0]["关键视觉元素"] == ["做旧皮沙发", "暖黄台灯", "斑驳墙面"]
        assert result[0]["光线氛围"] == "低色温暖光侧光"
        assert result[0]["色调"] == "低饱和暖棕"
        assert result[1]["visual_prompt"].startswith("Rainy neon")
    finally:
        ae.call_llm_json = original


def test_extract_scene_visual_prompts_fallback_on_empty_response():
    """LLM 返回空 scene_assets 时，原始 scene_list 应保持顺序并补充空 visual_prompt。"""
    import production.analysis_engine as ae
    original = ae.call_llm_json

    def _fake_call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0):
        return {"scene_assets": []}

    ae.call_llm_json = _fake_call_llm_json
    try:
        scenes = [
            {"场景名称": "医院走廊", "内外景": "内", "日夜": "日"},
        ]
        result = extract_scene_visual_prompts(scenes, "剧本正文...", _FakeClient(), "fake-model", {})
        assert len(result) == 1
        assert result[0]["场景名称"] == "医院走廊"
        assert result[0].get("visual_prompt", "") == ""
    finally:
        ae.call_llm_json = original


def test_extract_scene_visual_prompts_empty_input():
    """空场景列表应安全返回空列表，不调用 LLM。"""
    import production.analysis_engine as ae
    call_count = [0]
    original = ae.call_llm_json

    def _fake_call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0):
        call_count[0] += 1
        return {"scene_assets": []}

    ae.call_llm_json = _fake_call_llm_json
    try:
        result = extract_scene_visual_prompts([], "剧本正文...", _FakeClient(), "fake-model", {})
        assert result == []
        assert call_count[0] == 0
    finally:
        ae.call_llm_json = original


def test_extract_scene_visual_prompts_graceful_on_llm_error():
    """LLM 抛异常时不应崩溃，而是返回带空 visual_prompt 的原始场景。"""
    import production.analysis_engine as ae
    original = ae.call_llm_json

    def _fake_call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0):
        raise RuntimeError("API 调用失败")

    ae.call_llm_json = _fake_call_llm_json
    try:
        scenes = [{"场景名称": "天台", "内外景": "外", "日夜": "黄昏"}]
        result = extract_scene_visual_prompts(scenes, "剧本正文...", _FakeClient(), "fake-model", {})
        assert len(result) == 1
        assert result[0]["场景名称"] == "天台"
        assert result[0].get("visual_prompt", "") == ""
    finally:
        ae.call_llm_json = original
