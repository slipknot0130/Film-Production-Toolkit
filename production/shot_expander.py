"""
shot_expander.py — 分镜镜头扩展与机位丰富化引擎（v5.0）

核心目标：解决"每个文字镜头仅对应一个长镜头、切换效果生硬"的问题。
策略：
  1. 时长足够的长镜头按叙事节拍拆分为多个子镜头（远景/中景/特写/过肩等），
     每个子镜头独立机位，并按 4 秒下限保护总时长不塌缩。
  2. 无法拆分的短镜头在「画面内容」中注入 [镜头时间轴]，用机位运动/内部切换
     让单条 Seedance 提示词包含多角度变化，避免"单一长镜头"感。

接入点：crew_storyboard.py 的 _result_to_shots()，在 parse_structured_json 之后、
assemble_seedance_prompt 之前调用 expand_shots_in_data()。
"""

import re
import math
from typing import List, Dict, Any

# ── 台词匹配（即梦2.0 兼容格式：说话者+语气说：“台词” + 旧格式兜底）────────────────
_DIALOGUE_RE = re.compile(
    r'(?P<speaker>[^：:”"\n]{1,20})\s*[：:]\s*“(?P<text>[^”]+)”'
)
# 兜底：旧版 {台词} / 音效<> / BGM（）
_LEGACY_DIALOGUE_RE = re.compile(r'\{[^}]+\}')

# 句子切分（保留结尾标点）
_SENTENCE_RE = re.compile(r'[^。！？；\n]+[。！？；\n]?')

# 动作 / 揭示类动词，用于内容类型判断
_ACTION_VERBS = ('跑', '追', '奔', '冲', '扑', '退', '闪', '挥', '踢', '摔', '跃', '逃',
                 '打斗', '格斗', '追逐', '奔跑', '追赶', '逃离', '扑向', '摔倒')
_REVEAL_VERBS = ('发现', '看到', '看见', '注意到', '拿起', '打开', '展开', '抽出', '揭开',
                 '找到', '掏出', '取出', '展示', '露出', '浮现', '显现')

# 默认各内容类型的机位模式（按出现顺序 = 镜头推进顺序）
_CAMERA_PATTERNS: Dict[str, List[Dict[str, str]]] = {
    "dialogue": [
        {"景别": "全景", "机位": "平视", "运镜": "缓慢推轨", "构图": "双人位置关系，环境占画面40%"},
        {"景别": "中景", "机位": "过肩", "运镜": "固定", "构图": "主体占画面60%，肩部落画框边缘"},
        {"景别": "近景", "机位": "眼平", "运镜": "微推", "构图": "面部占画面50%，浅景深"},
    ],
    "solo": [
        {"景别": "中景", "机位": "眼平", "运镜": "固定", "构图": "人物在画面中央，环境交代情绪"},
        {"景别": "近景", "机位": "低角度", "运镜": "缓慢推轨", "构图": "面部或手部细节，负空间压缩"},
    ],
    "action": [
        {"景别": "全景", "机位": "低角度", "运镜": "横移跟随", "构图": "运动主体与环境关系"},
        {"景别": "中景", "机位": "侧面", "运镜": "手持跟拍", "构图": "主体动态居中"},
        {"景别": "特写", "机位": "低角度", "运镜": "快速推镜", "构图": "关键动作细节"},
    ],
    "reveal": [
        {"景别": "中景", "机位": "眼平", "运镜": "固定", "构图": "人物与对象的空间关系"},
        {"景别": "特写", "机位": "微俯", "运镜": "微推", "构图": "对象或面部细节占据画面中心"},
    ],
    "default": [
        {"景别": "中景", "机位": "眼平", "运镜": "固定", "构图": "主体居中，前景背景层次清晰"},
        {"景别": "近景", "机位": "眼平", "运镜": "微推", "构图": "主体细节，浅景深"},
    ],
}

# 景别由远及近推进表（用于 [镜头时间轴] 内部 phase 递进）
_SHOT_SCALE_ORDER = [
    "大远景", "远景", "全景", "中全景", "中景", "中近景", "近景", "特写", "大特写", "极特写"
]


def _closer_shot_type(shot_type: str, steps: int = 1) -> str:
    """返回比当前景别更近一步（或几步）的景别。"""
    try:
        idx = _SHOT_SCALE_ORDER.index(shot_type)
    except ValueError:
        idx = _SHOT_SCALE_ORDER.index("中景")
    new_idx = min(idx + steps, len(_SHOT_SCALE_ORDER) - 1)
    return _SHOT_SCALE_ORDER[new_idx]


def _safe_float(value, default: float = 0.0) -> float:
    """兼容 crew_storyboard 的 _safe_float，本模块独立使用。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r'-?\d+(?:\.\d+)?', value)
        if m:
            try:
                return float(m.group())
            except ValueError:
                return default
    return default


def _detect_content_type(shot: Dict[str, Any]) -> str:
    """根据出场角色数和画面内容判断镜头内容类型。"""
    content = str(shot.get("画面内容", ""))
    characters = shot.get("出场角色", [])
    if isinstance(characters, str):
        characters = [c.strip() for c in characters.replace("、", ",").split(",") if c.strip()]

    has_dialogue = bool(_DIALOGUE_RE.search(content) or _LEGACY_DIALOGUE_RE.search(content))

    if len(characters) >= 2 and has_dialogue:
        return "dialogue"
    if any(v in content for v in _ACTION_VERBS):
        return "action"
    if any(v in content for v in _REVEAL_VERBS):
        return "reveal"
    if len(characters) == 1:
        return "solo"
    return "default"


def _select_pattern(shot: Dict[str, Any]) -> List[Dict[str, str]]:
    """选择机位模式。按内容类型返回标准推进序列（远景→中景→特写）。"""
    ctype = _detect_content_type(shot)
    return list(_CAMERA_PATTERNS.get(ctype, _CAMERA_PATTERNS["default"]))


def _extract_segments(content: str) -> List[tuple]:
    """把画面内容拆分为 'action' / 'dialogue' 原子段落，保留所有文本。"""
    segments = []
    last = 0
    for m in _DIALOGUE_RE.finditer(content):
        if m.start() > last:
            action = content[last:m.start()].strip()
            if action:
                segments.append(("action", action))
        segments.append(("dialogue", m.group(0)))
        last = m.end()
    if last < len(content):
        action = content[last:].strip()
        if action:
            segments.append(("action", action))
    return segments


def _extract_beats(content: str) -> List[str]:
    """
    把画面内容拆分为叙事节拍（beat）：
      每个 beat = 前置动作 + 台词 + 后置短动作；
      无台词的长动作按句子进一步拆成多个 action beat。
    保证按节拍切分后，每个子镜头都有完整的动作-台词上下文。
    """
    raw_segments = _extract_segments(content)
    if not raw_segments:
        return []

    # 先把长动作拆成句子级原子单元
    segments = []
    for seg_type, seg_text in raw_segments:
        if seg_type == "action":
            sentences = _SENTENCE_RE.findall(seg_text)
            for s in sentences:
                segments.append(("action", s))
        else:
            segments.append((seg_type, seg_text))

    beats = []
    i = 0
    while i < len(segments):
        beat_parts = []
        # 前置动作（如果下一个是台词，把前面动作一起纳入）
        if segments[i][0] == "action":
            beat_parts.append(segments[i][1])
            i += 1
        # 台词
        if i < len(segments) and segments[i][0] == "dialogue":
            beat_parts.append(segments[i][1])
            i += 1
            # 后置短动作（≤20 字的反应/环境描述）并入同一节拍
            if i < len(segments) and segments[i][0] == "action" and len(segments[i][1]) <= 20:
                beat_parts.append(segments[i][1])
                i += 1
        # 兜底：既没有动作也没有台词的异常情况
        if not beat_parts:
            beat_parts.append(segments[i][1])
            i += 1
        beats.append("".join(beat_parts))
    return beats


def _split_beats_ordered(beats: List[str], n: int) -> List[List[str]]:
    """
    把有序的 beats 切分成 n 个连续组，尽量平衡每组字符数。
    保持叙事顺序和对话轮次不被打乱。
    """
    if n <= 1:
        return [beats]
    if n >= len(beats):
        return [[b] for b in beats]

    best_parts = None
    best_score = float('inf')

    def _search(start: int, remaining: int, current: List[List[str]]):
        nonlocal best_parts, best_score
        if remaining == 1:
            parts = current + [beats[start:]]
            score = max(sum(len(b) for b in part) for part in parts)
            if score < best_score:
                best_score = score
                best_parts = parts
            return
        # 下一组至少 1 个 beat，后面 remaining-1 组也至少各 1 个
        max_take = len(beats) - start - (remaining - 1)
        for end in range(start + 1, start + max_take + 1):
            _search(end, remaining - 1, current + [beats[start:end]])

    _search(0, n, [])
    return best_parts if best_parts else [beats]


def _split_content(content: str, n: int) -> List[str]:
    """把画面内容按叙事节拍拆成 n 份，保证台词完整、顺序不乱、每个子镜头有上下文。"""
    if n <= 1:
        return [content]
    beats = _extract_beats(content)
    if not beats:
        return [content] * n

    parts = _split_beats_ordered(beats, n)
    result = ["".join(part).strip() for part in parts]
    # 保护：若某份过短，则放弃该 n 的拆分（调用方会尝试更小的 n）
    if any(len(p) < 20 for p in result):
        return [content]
    return result


def _distribute_duration(duration: float, n: int, min_dur: float) -> List[float]:
    """把总时长拆成 n 份，每份 ≥ min_dur（调用方需保证 duration ≥ n * min_dur）。"""
    base = duration / n
    if base < min_dur:
        base = min_dur
    parts = [round(base, 1) for _ in range(n)]
    # 修正舍入误差，保证总和精确
    parts[-1] = round(duration - sum(parts[:-1]), 1)
    return parts


def _is_rich_content(content: str) -> bool:
    """判断内容是否足够丰富到可以拆分。"""
    if not content:
        return False
    sentences = _SENTENCE_RE.findall(content)
    return len(sentences) >= 2 or bool(_DIALOGUE_RE.search(content))


def _split_shot_if_long(shot: Dict[str, Any], min_sub_duration: float = 4.0) -> List[Dict[str, Any]]:
    """
    对时长足够的长镜头进行外部拆分：
      - ≥ 3×min_sub_duration 且内容丰富 → 3 个子镜头
      - ≥ 2×min_sub_duration 且内容丰富 → 2 个子镜头
      - 否则返回原镜头
    每个子镜头独立机位，总时长 = 原时长。
    """
    duration = _safe_float(shot.get("时长秒"), 4.5)
    content = str(shot.get("画面内容", "")).strip()

    if duration < 2 * min_sub_duration or not content or not _is_rich_content(content):
        return [shot]

    max_n = 3 if duration >= 3 * min_sub_duration else 2

    pattern = _select_pattern(shot)
    # 从最大 n 开始尝试，若内容拆后过短则降级到 n-1
    for n in range(max_n, 0, -1):
        if n == 1:
            return [shot]
        content_parts = _split_content(content, n)
        if len(content_parts) != n:
            continue
        durations = _distribute_duration(duration, n, min_sub_duration)

        sub_shots = []
        felt_base = str(shot.get("felt_intent", "")).strip()
        for i, (part, dur) in enumerate(zip(content_parts, durations)):
            sub = dict(shot)
            sub["时长秒"] = dur
            sub["画面内容"] = part
            # 应用模式机位（i 超过模式长度时回退到最后一镜）
            p = pattern[min(i, len(pattern) - 1)]
            sub["景别"] = p["景别"]
            sub["机位"] = p["机位"]
            sub["运镜"] = p["运镜"]
            sub["构图"] = p["构图"]
            # felt_intent 细化
            if felt_base:
                sub["felt_intent"] = f"{felt_base} · {p['景别']}切入"
            sub_shots.append(sub)
        return sub_shots
    return [shot]


def _build_time_axis(shot: Dict[str, Any], n_phases: int, duration: float) -> str:
    """为单镜头构建 [镜头时间轴] 段落。基于当前镜头参数，内部做景别推进/运动变化。"""
    shot_type = str(shot.get("景别", "中景")).strip() or "中景"
    camera_pos = str(shot.get("机位", "眼平")).strip() or "眼平"
    camera_move = str(shot.get("运镜", "固定")).strip() or "固定"

    boundaries = []
    for i in range(1, n_phases):
        boundaries.append(round(duration * i / n_phases, 1))
    boundaries.append(round(duration, 1))

    phrases = []
    start = 0.0
    for i, end in enumerate(boundaries):
        if i == 0:
            st = shot_type
            cm = camera_move
            desc = "主体呈现"
        elif i == n_phases - 1:
            st = _closer_shot_type(shot_type, steps=min(2, n_phases - 1))
            cm = "微推" if camera_move == "固定" else camera_move
            desc = "强调情绪或动作落点"
        else:
            st = _closer_shot_type(shot_type, steps=1)
            cm = "缓慢推轨" if camera_move == "固定" else camera_move
            desc = "推进叙事主体"
        phrases.append(f"{start:.1f}-{end:.1f}s：{st}{camera_pos}，{cm}，{desc}")
        start = end

    return "[镜头时间轴] " + "；".join(phrases) + "。"


def _enrich_with_angle_sequence(shot: Dict[str, Any]) -> Dict[str, Any]:
    """
    为每个镜头（含子镜头）的画面内容前置 [镜头时间轴]，
    让 Seedance 在单条提示词内也能执行机位变化，避免全程单一长镜头。
    """
    content = str(shot.get("画面内容", "")).strip()
    if not content or content.startswith("[镜头时间轴]"):
        return shot

    duration = _safe_float(shot.get("时长秒"), 4.5)
    n_phases = 2 if duration < 7.0 else 3
    time_axis = _build_time_axis(shot, n_phases, duration)

    enriched = dict(shot)
    enriched["画面内容"] = f"{time_axis}\n\n{content}"
    return enriched


def expand_shots_in_data(shot_data: Dict[str, Any], min_sub_duration: float = 4.0) -> Dict[str, Any]:
    """
    主入口：对 Director/QA 解析后的 shot_data 做镜头扩展。

    返回新的 shot_data（含扩展后的 分镜列表），并完成重新编号。
    """
    if not isinstance(shot_data, dict):
        return shot_data

    shots = shot_data.get("分镜列表", [])
    if not isinstance(shots, list):
        return shot_data

    expanded: List[Dict[str, Any]] = []
    for shot in shots:
        if not isinstance(shot, dict):
            expanded.append(shot)
            continue
        subs = _split_shot_if_long(shot, min_sub_duration)
        for sub in subs:
            expanded.append(_enrich_with_angle_sequence(sub))

    # 重新编号，保证 UI 时间轴连续（非字典元素安全跳过）
    idx = 1
    for shot in expanded:
        if isinstance(shot, dict):
            shot["镜头号"] = idx
            idx += 1

    shot_data["分镜列表"] = expanded
    return shot_data
