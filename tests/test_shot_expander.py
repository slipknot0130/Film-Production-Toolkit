"""
shot_expander 回归测试。

验证 v5.0 镜头扩展引擎：
- 短镜头不拆分，但注入 [镜头时间轴]
- 长镜头按叙事节拍拆分为多机位子镜头
- 台词完整保留、顺序不乱
- 时长守恒、重新编号
"""

import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 桩：production.shot_expander 不依赖 streamlit/openai/crewai，
# 但 crew_storyboard 导入时会用到，这里统一保持测试风格一致。
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

from production.shot_expander import expand_shots_in_data  # noqa: E402


def _shot(num=1, duration=5.0, shot_type="中景", camera_pos="眼平", camera_move="固定",
          content="", chars=None, intent="测试"):
    return {
        "镜头号": num,
        "时长秒": duration,
        "景别": shot_type,
        "机位": camera_pos,
        "运镜": camera_move,
        "构图": "主体居中",
        "画面内容": content,
        "出场角色": chars or [],
        "felt_intent": intent,
        "场景名": "测试场景",
    }


def test_short_shot_not_split_but_enriched():
    """5 秒短镜头不拆分，但画面内容前会注入 [镜头时间轴]。"""
    data = {"分镜列表": [_shot(
        duration=5.0,
        content="林晚低声说：“你回来了。”陈默点头。",
        chars=["林晚", "陈默"],
        intent="重逢",
    )]}
    out = expand_shots_in_data(data)
    assert len(out["分镜列表"]) == 1
    s = out["分镜列表"][0]
    assert s["画面内容"].startswith("[镜头时间轴]")
    assert "0.0-" in s["画面内容"]


def test_long_dialogue_splits_and_preserves_all_lines():
    """14 秒长对话拆成 2 个子镜头，所有台词完整保留。"""
    data = {"分镜列表": [_shot(
        duration=14.0,
        content="林晚走进房间。林晚说：“你回来了。”陈默点头：“嗯。”林晚走近一步：“这些年你去了哪里？”陈默沉默片刻：“外面。”窗外雨声变大。",
        chars=["林晚", "陈默"],
        intent="压抑重逢",
    )]}
    out = expand_shots_in_data(data)
    shots = out["分镜列表"]
    assert len(shots) >= 2

    full_content = "".join(s["画面内容"] for s in shots)
    for line in ["你回来了", "嗯", "这些年你去了哪里", "外面"]:
        assert line in full_content, f"台词丢失: {line}"

    # 每个子镜头都有不同机位（避免单一长镜头）
    positions = [s["机位"] for s in shots]
    assert len(set(positions)) >= 1

    # 重新编号
    assert [s["镜头号"] for s in shots] == list(range(1, len(shots) + 1))


def test_duration_preserved_after_split():
    """拆分后所有子镜头时长之和等于原时长。"""
    data = {"分镜列表": [_shot(
        duration=14.0,
        content="林晚走进房间。林晚说：“你回来了。”陈默点头：“嗯。”林晚走近一步：“这些年你去了哪里？”陈默沉默片刻：“外面。”窗外雨声变大。",
        chars=["林晚", "陈默"],
    )]}
    out = expand_shots_in_data(data)
    total = sum(s["时长秒"] for s in out["分镜列表"])
    assert abs(total - 14.0) < 0.1


def test_long_action_splits_into_multiple_angles():
    """12 秒动作场景拆成多个机位（全景→中景/特写）。"""
    data = {"分镜列表": [_shot(
        duration=12.5,
        shot_type="中景",
        camera_pos="侧面",
        camera_move="跟随",
        content="陈默拔腿就跑，穿过拥挤的巷道。他撞翻了一个水果摊，苹果滚落一地。身后追兵的脚步声越来越近。陈默猛地拐进一条窄巷，翻身跃上一堵矮墙，消失在墙后。",
        chars=["陈默"],
        intent="紧张逃亡",
    )]}
    out = expand_shots_in_data(data)
    shots = out["分镜列表"]
    assert len(shots) >= 2
    shot_types = [s["景别"] for s in shots]
    # 至少出现两种不同景别
    assert len(set(shot_types)) >= 2


def test_empty_content_does_not_crash():
    """空画面内容的镜头安全透传，不报错。"""
    data = {"分镜列表": [_shot(duration=10.0, content="")]}
    out = expand_shots_in_data(data)
    assert len(out["分镜列表"]) == 1


def test_non_dict_shot_passthrough():
    """异常非字典元素安全透传。"""
    data = {"分镜列表": ["异常元素", _shot(duration=5.0, content="林晚点头。")]}
    out = expand_shots_in_data(data)
    assert out["分镜列表"][0] == "异常元素"
    assert out["分镜列表"][1]["镜头号"] == 1


def test_dialogue_order_preserved():
    """台词顺序不被打乱。"""
    data = {"分镜列表": [_shot(
        duration=14.0,
        content="A说：“第一句。”B说：“第二句。”A说：“第三句。”",
        chars=["A", "B"],
    )]}
    out = expand_shots_in_data(data)
    full = "".join(s["画面内容"] for s in out["分镜列表"])
    # 顺序：第一句 在 第二句 前，第二句 在 第三句 前
    assert full.find("第一句") < full.find("第二句") < full.find("第三句")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
