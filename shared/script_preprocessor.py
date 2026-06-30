"""
shared/script_preprocessor.py — 剧本代码层预处理器
===================================================
核心原则：LLM 做判断，代码做执行。

本模块用纯正则/字符串算法完成所有"统计/搜索/对比/查找"任务，
将结构化预扫描结果注入 LLM prompt，让 LLM 仅做语义级定性判断。

功能：
1. 写作红线预扫描（心理描写/括号暗示/解释性台词）
2. 台词字数统计
3. 出场角色提取
4. 场景标记提取
5. 情绪指标预提取
6. 集数切割
7. 预飞报告生成（整合全部预扫描结果）
"""

import re
from dataclasses import dataclass, field
from collections import Counter
from typing import List, Dict, Optional


# =============================================================================
# 常量 — 违规模式库
# =============================================================================

# 心理描写关键词（含常见变体）
PSYCHOLOGICAL_PATTERNS = re.compile(
    r'(?:(?:他|她)\s*(?:意识到|感到|觉得|心想|心中|念头|思绪|脑海中|'
    r'内心|心底|灵魂深处|潜意识|不自觉|本能地)\s*.{0,30})|'
    r'(?:不禁想到|暗想|寻思|琢磨着|盘算着)',
    re.MULTILINE
)

# 括号暗示模式（含暗示性词汇）
PARENTHETICAL_HINT_PATTERN = re.compile(
    r'[（(][^）)]*(?:其实|实际上|暗示|掩盖|掩饰|假装|伪装|隐藏|'
    r'表面.*实际|口中.*心里|嘴上.*内心)[^）)]*[）)]',
    re.MULTILINE
)

# 解释性台词模式（角色说出主题/设定/内心独白式解释）
EXPLANATORY_DIALOGUE_PATTERN = re.compile(
    r'(?:[^\n：]+)：[^\n]{0,60}'
    r'(?:其实|意思是|也就是说|换句话说|说白了|反正|'
    r'你也知道|你要明白|你知道吗|重要的是|关键是)[^\n]{0,40}',
    re.MULTILINE
)

# 说教台词语段
PREACHING_PATTERN = re.compile(
    r'(?:[^\n：]+)：[^\n]{0,80}'
    r'(?:你应该|你不能|你必须|你不该|人生|命运|'
    r'这世上|真正的|永远都是|从来都是)[^\n]{0,60}',
    re.MULTILINE
)

# 高冲击物理动作关键词
IMPACT_ACTION_KEYWORDS = [
    '耳光', '扇', '打脸', '耳光', '一巴掌', '挥拳', '一脚', '踹',
    '摔门', '撞门', '砸', '掀桌', '掀翻', '推倒', '掐住', '扼住',
    '跪下', '跪在', '磕头', '甩', '冷笑', '怒视', '握拳', '咬紧',
    '冲上去', '抓住衣领', '壁咚', '逼近', '俯视', '抽刀', '拔枪',
    '流血', '倒地', '昏倒', '晕倒', '推开', '坠落', '跳下',
]

# 钩子关键词（结尾悬念模式）
HOOK_KEYWORDS = [
    '突然', '竟然', '居然', '没想到', '却发现', '就在这时',
    '门外传来', '身后传来', '门被推开', '手机响了', '屏幕上显示',
    '下一秒', '怔住', '愣住', '瞪大', '瞳孔', '缓缓', '背后',
    '到底是谁', '怎么可能是', '他怎么会', '为什么是他',
]

# 情绪关键词映射（弱→中→强→极强）
EMOTION_KEYWORDS = {
    'weak': ['微笑', '点头', '答应', '答应', '平静', '坐着'],
    'medium': ['皱眉', '着急', '站起来', '转头', '紧张', '犹豫', '咬唇'],
    'strong': ['拍案', '握拳', '怒吼', '泪水', '抽泣', '砸', '挥手', '推', '瞪眼'],
    'extreme': ['耳光', '捅', '流血', '倒下', '狂喊', '爆发', '嚎叫', '撕心', '跪下', '磕头'],
}

# 场景标记模式（支持多种剧本格式）
SCENE_MARKERS = re.compile(
    r'(?:【场景[：:]|场景[：:]|#\s*场景|##\s*场景|'
    r'INT\.|EXT\.|INT/EXT|INT/|EXT/|'
    r'内景[：:]|外景[：:]|日内|夜内|日外|夜外)',
    re.MULTILINE | re.IGNORECASE
)

# 角色台词模式
CHARACTER_DIALOGUE_PATTERN = re.compile(
    r'([\u4e00-\u9fa5A-Za-z0-9]+)[：:]([^\n]+)',
    re.MULTILINE
)

# 集数切分模式
EPISODE_SPLIT_PATTERN = re.compile(
    r'(?:#\s*第\s*\d+\s*集|第\s*\d+\s*集[：:])',
    re.MULTILINE
)


# =============================================================================
# 数据结构
# =============================================================================

@dataclass
class ViolationHit:
    """写作违规命中记录"""
    type: str           # 违规类型：心理描写/括号暗示/解释性台词/说教
    location: int       # 字符偏移位置
    match: str          # 命中的原文片段（截断到80字）
    suggestion: str = ""  # 修改建议（可选）


@dataclass
class DialogueLengthHit:
    """台词字数超标记录"""
    character: str      # 角色名
    dialogue: str       # 台词原文（截断到50字）
    length: int         # 纯台词字数
    limit: int          # 字数限制
    line_number: int    # 大致行号


@dataclass
class CharacterInfo:
    """出场角色信息"""
    name: str           # 角色名
    dialogue_count: int # 台词条数
    total_words: int    # 台词总字数
    first_appearance: int  # 首次出场位置（字符偏移）


@dataclass
class SceneInfo:
    """场景信息"""
    marker: str         # 场景标记原文
    location: int       # 字符偏移位置
    scene_type: str     # 内景/外景/未知


@dataclass
class EpisodeEmotionSnapshot:
    """单集情绪快照"""
    episode_label: str      # 如"第1集"
    total_chars: int        # 总字数
    dialogue_ratio: float   # 对白占比
    weak_hits: int = 0
    medium_hits: int = 0
    strong_hits: int = 0
    extreme_hits: int = 0
    conflict_keyword_hits: list = field(default_factory=list)
    hook_keyword_hits: list = field(default_factory=list)


@dataclass
class PreflightReport:
    """预飞综合报告 — 所有代码层预扫描结果汇总"""
    script_length: int                # 剧本总字数
    total_episodes: int               # 总集数
    total_scenes: int                 # 总场景数
    characters: List[CharacterInfo]   # 出场角色
    scenes: List[SceneInfo]           # 场景列表
    violations: List[ViolationHit]    # 写作违规
    dialogue_issues: List[DialogueLengthHit]  # 台词字数问题
    episode_snapshots: List[EpisodeEmotionSnapshot]  # 逐集情绪快照

    def to_injection_text(self) -> str:
        """将报告转为可注入 LLM prompt 的紧凑文本格式"""
        lines = []
        lines.append(f"## 📊 代码预扫描结果")
        lines.append(f"- 剧本总字数：{self.script_length} 字 | "
                     f"预估 {self.total_episodes} 集 | "
                     f"约 {self.total_scenes} 个场景")

        # 违规摘要
        if self.violations:
            vc = Counter(v.type for v in self.violations)
            lines.append(f"- ⚠️ 写作红线命中：{', '.join(f'{k}×{v}' for k, v in vc.items())}")
        else:
            lines.append("- ✅ 写作红线：代码层无命中（仍需你做语义确认）")

        # 台词问题
        if self.dialogue_issues:
            lines.append(f"- ⚠️ 台词字数超标：{len(self.dialogue_issues)} 处")
            for d in self.dialogue_issues[:5]:
                lines.append(f"  · {d.character}「{d.dialogue[:30]}」={d.length}字（限{d.limit}字）")

        # 角色摘要
        if self.characters:
            char_list = [f"{c.name}({c.dialogue_count}句)" for c in self.characters[:8]]
            lines.append(f"- 出场角色：{', '.join(char_list)}"
                         f"{'...' if len(self.characters) > 8 else ''}")

        # 场景摘要
        if self.scenes:
            scene_types = Counter(s.scene_type for s in self.scenes)
            lines.append(f"- 场景类型分布：{', '.join(f'{k}×{v}' for k, v in scene_types.items())}")

        # 逐集情绪快照（简表）
        if self.episode_snapshots:
            lines.append("\n### 逐集情绪指标预扫描")
            for ep in self.episode_snapshots:
                emotion_score = ep.weak_hits + ep.medium_hits * 2 + ep.strong_hits * 3 + ep.extreme_hits * 5
                hook_str = f" | 结尾钩子 {len(ep.hook_keyword_hits)}个" if ep.hook_keyword_hits else ""
                conflict_str = f" | 冲突词 {len(ep.conflict_keyword_hits)}个" if ep.conflict_keyword_hits else ""
                lines.append(
                    f"- {ep.episode_label}：{ep.total_chars}字 | 对白比{ep.dialogue_ratio:.1%} | "
                    f"情绪分{emotion_score}{conflict_str}{hook_str}"
                )

        return "\n".join(lines)

    def to_character_list_text(self) -> str:
        """输出角色列表（供分镜导演使用）"""
        if not self.characters:
            return "（未检测到角色台词，请从剧本中手动提取）"
        lines = []
        for c in self.characters:
            lines.append(f"- {c.name}：{c.dialogue_count}句台词，首现于第{c.first_appearance}字符处")
        return "\n".join(lines)


# =============================================================================
# 预扫描函数
# =============================================================================

def scan_writing_violations(script_text: str) -> List[ViolationHit]:
    """代码层预扫描写作红线违规（P1优化）"""
    hits = []

    # 心理描写
    for m in PSYCHOLOGICAL_PATTERNS.finditer(script_text):
        hits.append(ViolationHit(
            type="心理描写",
            location=m.start(),
            match=m.group()[:80],
        ))

    # 括号暗示
    for m in PARENTHETICAL_HINT_PATTERN.finditer(script_text):
        hits.append(ViolationHit(
            type="括号暗示",
            location=m.start(),
            match=m.group()[:80],
        ))

    # 解释性台词
    for m in EXPLANATORY_DIALOGUE_PATTERN.finditer(script_text):
        hits.append(ViolationHit(
            type="解释性台词",
            location=m.start(),
            match=m.group()[:80],
        ))

    # 说教片段
    for m in PREACHING_PATTERN.finditer(script_text):
        hits.append(ViolationHit(
            type="说教",
            location=m.start(),
            match=m.group()[:80],
        ))

    hits.sort(key=lambda h: h.location)
    return hits


def scan_dialogue_length(script_text: str, max_chars: int = 15) -> List[DialogueLengthHit]:
    """代码层检查台词字数（P2优化）"""
    issues = []
    for line_num, m in enumerate(CHARACTER_DIALOGUE_PATTERN.finditer(script_text)):
        char_name = m.group(1).strip()
        dialogue = m.group(2).strip()
        # 去除动作括号内容后计算纯台词字数
        clean = re.sub(r'[（(][^）)]*[）)]', '', dialogue)
        if len(clean) > max_chars:
            issues.append(DialogueLengthHit(
                character=char_name,
                dialogue=dialogue[:50],
                length=len(clean),
                limit=max_chars,
                line_number=line_num,
            ))
    return issues


def extract_characters(script_text: str) -> List[CharacterInfo]:
    """代码层提取所有有台词的角色（P3优化）"""
    char_data: Dict[str, Dict] = {}
    for m in CHARACTER_DIALOGUE_PATTERN.finditer(script_text):
        name = m.group(1).strip()
        dialogue = m.group(2).strip()
        if len(name) > 8:  # 过滤过长（可能误匹配）的名字
            continue
        if name not in char_data:
            char_data[name] = {
                "dialogue_count": 0,
                "total_words": 0,
                "first_appearance": m.start(),
            }
        char_data[name]["dialogue_count"] += 1
        char_data[name]["total_words"] += len(dialogue)

    return sorted(
        [CharacterInfo(name=n, **d) for n, d in char_data.items()],
        key=lambda c: c.dialogue_count,
        reverse=True,
    )


def extract_scenes(script_text: str) -> List[SceneInfo]:
    """代码层提取场景标记"""
    scenes = []
    for m in SCENE_MARKERS.finditer(script_text):
        marker = m.group()
        if any(w in marker for w in ['INT', '内', '室']):
            scene_type = "内景"
        elif any(w in marker for w in ['EXT', '外', '街', '野']):
            scene_type = "外景"
        else:
            scene_type = "内景"  # 默认
        scenes.append(SceneInfo(
            marker=marker,
            location=m.start(),
            scene_type=scene_type,
        ))
    return scenes


def scan_emotion_indicators(script_text: str) -> List[EpisodeEmotionSnapshot]:
    """代码层预提取逐集情绪指标（P2优化）"""
    episodes = split_episodes(script_text)
    snapshots = []

    for ep_label, ep_text in episodes:
        total_chars = len(ep_text)
        # 对白字数
        dialogue_chars = sum(
            len(m.group(2).strip())
            for m in CHARACTER_DIALOGUE_PATTERN.finditer(ep_text)
        )
        dialogue_ratio = dialogue_chars / total_chars if total_chars > 0 else 0

        # 情绪关键词计数
        weak = sum(len(re.findall(re.escape(k), ep_text)) for k in EMOTION_KEYWORDS['weak'])
        medium = sum(len(re.findall(re.escape(k), ep_text)) for k in EMOTION_KEYWORDS['medium'])
        strong = sum(len(re.findall(re.escape(k), ep_text)) for k in EMOTION_KEYWORDS['strong'])
        extreme = sum(len(re.findall(re.escape(k), ep_text)) for k in EMOTION_KEYWORDS['extreme'])

        # 冲突/动作关键词（取最后500字符检查结尾钩子）
        tail_text = ep_text[-500:] if len(ep_text) > 500 else ep_text
        hook_hits = [kw for kw in HOOK_KEYWORDS if kw in tail_text]
        conflict_hits = [kw for kw in IMPACT_ACTION_KEYWORDS if kw in ep_text]

        snapshots.append(EpisodeEmotionSnapshot(
            episode_label=ep_label,
            total_chars=total_chars,
            dialogue_ratio=round(dialogue_ratio, 3),
            weak_hits=weak,
            medium_hits=medium,
            strong_hits=strong,
            extreme_hits=extreme,
            conflict_keyword_hits=conflict_hits[:8],
            hook_keyword_hits=hook_hits[:4],
        ))

    return snapshots


def split_episodes(script_text: str) -> List[tuple]:
    """代码层按集切分剧本（代替 LLM '逐集遍历'）"""
    split_positions = []
    for m in EPISODE_SPLIT_PATTERN.finditer(script_text):
        split_positions.append(m.start())

    if not split_positions:
        return [("全剧", script_text)]

    episodes = []
    for i, pos in enumerate(split_positions):
        ep_label_match = re.search(r'第\s*(\d+)\s*集', script_text[pos:pos + 20])
        ep_label = ep_label_match.group(0) if ep_label_match else f"第{i + 1}集"

        start = pos
        end = split_positions[i + 1] if i + 1 < len(split_positions) else len(script_text)
        episodes.append((ep_label, script_text[start:end]))

    return episodes


# =============================================================================
# 主入口：生成预飞综合报告
# =============================================================================

def generate_preflight_report(
    script_text: str,
    max_dialogue_chars: int = 15,
) -> PreflightReport:
    """
    对剧本执行全部代码层预扫描，生成结构化报告。

    将此报告的 injection_text 注入 LLM prompt 后，
    LLM 不再需要"寻找"或"数"任何东西，只需做语义判断。
    """
    report = PreflightReport(
        script_length=len(script_text),
        total_episodes=len(split_episodes(script_text)),
        total_scenes=len(extract_scenes(script_text)),
        characters=extract_characters(script_text),
        scenes=extract_scenes(script_text),
        violations=scan_writing_violations(script_text),
        dialogue_issues=scan_dialogue_length(script_text, max_dialogue_chars),
        episode_snapshots=scan_emotion_indicators(script_text),
    )
    return report


def generate_character_list_for_storyboard(script_text: str) -> str:
    """
    为分镜导演预提取角色列表（P3优化）。
    返回可直接注入 Task description 的文本。
    """
    chars = extract_characters(script_text)
    if not chars:
        return "（本剧本片段中未检测到角色台词）"

    lines = ["以下角色已由代码预提取，请直接使用无需重复寻找："]
    for i, c in enumerate(chars, 1):
        lines.append(f"  {i}. {c.name} — {c.dialogue_count}句台词，{c.total_words}字")
    return "\n".join(lines)


def count_scenes_code(script_text: str) -> int:
    """纯代码场景计数（不再让 LLM 估算）"""
    return len(SCENE_MARKERS.findall(script_text))


def count_internal_external_scenes(script_text: str) -> tuple:
    """代码统计内/外景比例"""
    scenes = extract_scenes(script_text)
    internal = sum(1 for s in scenes if s.scene_type == "内景")
    external = sum(1 for s in scenes if s.scene_type == "外景")
    return internal, external


def generate_duration_guide(script_text: str) -> str:
    """
    v2.2：代码层分析剧本体量，生成分镜时长/镜数推荐。
    纯算法计算 — 字数统计、对白密度、场景数量 — 不做任何语义判断。

    返回格式化的推荐字符串，直接注入 Director Agent 的 prompt。
    让 LLM 根据数据规划分镜，而非依赖硬编码的"1300字→8分钟"固定示例。

    核心公式：
      有效字符 ÷ 3.5 = 纯阅读秒数
      纯阅读秒数 × 表演膨胀系数 = 预估总时长
      预估总时长 ÷ 平均镜秒 = 预估镜数

    表演膨胀系数取决于对白密度：
      - 对话为主 (>60%对白行) → ×1.8（节奏快）
      - 均衡 (30-60%) → ×2.2
      - 动作为主 (<30%) → ×2.5（镜头密度高）
    """
    # ── 1. 文本量统计 ──
    stripped = script_text.strip()
    if not stripped:
        return ""

    total_chars = len(stripped)
    effective_chars = len(re.sub(r'\s+', '', stripped))

    # ── 2. 对白统计 ──
    all_dialogue = CHARACTER_DIALOGUE_PATTERN.findall(stripped)
    dialogue_lines = len(all_dialogue)

    dialogue_total_chars = 0
    for _, content in all_dialogue:
        # 去除括号内的动作提示
        clean = re.sub(r'[（(][^）)]*[）)]', '', content)
        dialogue_total_chars += len(clean.strip())

    # ── 3. 行数统计 ──
    non_empty_lines = [l for l in stripped.split('\n') if l.strip()]
    total_lines = len(non_empty_lines)
    action_lines = max(total_lines - dialogue_lines, 1)

    # ── 4. 场景统计（含第N场格式兜底）──
    scene_count = count_scenes_code(stripped) or 0
    # 兜底：count_scenes_code 只匹配 INT/EXT/内景/外景 等标记，
    # 不匹配「第X场」格式。这里用简单正则补上。
    chinese_scene_matches = re.findall(r'第\s*(?:[一二三四五六七八九十百\d]+)\s*(?:场|幕|景)', stripped)
    scene_count = max(scene_count, len(chinese_scene_matches), 1)

    # ── 5. 对白密度与膨胀系数 ──
    if dialogue_lines > 0 and total_lines > 0:
        dialogue_ratio = dialogue_lines / total_lines
    else:
        dialogue_ratio = 0.0

    if dialogue_ratio > 0.6:
        expansion = 1.8
        pace_label = "对话主导型"
        pace_hint = "节奏轻快，镜头切换频繁，镜长可偏短(3-5s)"
    elif dialogue_ratio > 0.3:
        expansion = 2.2
        pace_label = "均衡型"
        pace_hint = "文戏动作交替，标准镜长(4-6s)"
    else:
        expansion = 2.5
        pace_label = "动作主导型"
        pace_hint = "视觉密度高，需要更多镜头覆盖动作细节，镜长(3-5s)"

    # ── 6. 时长估算 ──
    # 纯阅读秒数（中文约3.5字/秒正常讲述节奏）
    reading_seconds = max(effective_chars / 3.5, 10.0)
    estimated_duration = reading_seconds * expansion

    # ── 7. 镜数估算 ──
    if dialogue_ratio > 0.5:
        avg_shot_sec = 4.5  # 对话为主，切换快
    elif dialogue_ratio > 0.3:
        avg_shot_sec = 5.0  # 均衡
    else:
        avg_shot_sec = 4.0  # 动作为主但每个镜头也更短

    estimated_shots = estimated_duration / avg_shot_sec

    # 上下浮动范围
    min_shots = max(int(estimated_shots * 0.75), scene_count * 2)
    max_shots = int(estimated_shots * 1.35)
    min_duration = int(estimated_duration * 0.8)
    max_duration = int(estimated_duration * 1.25)

    def format_dur(s: float) -> str:
        m, sec = divmod(int(s), 60)
        if m > 0:
            return f"{m}分{sec}秒"
        return f"{sec}秒"

    # ── 8. 组装推荐文本 ──
    guide = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【剧本体量分析 — 代码自动计算】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  本切块统计：{effective_chars}有效字符 / {scene_count}场 / {dialogue_lines}句对白({dialogue_total_chars}字) / {action_lines}行动作描述
  对白密度：{dialogue_ratio:.0%} → {pace_label}（{pace_hint}）
  建议总时长：{format_dur(min_duration)} ～ {format_dur(max_duration)}
  建议总镜数：{min_shots} ～ {max_shots} 镜
  平均镜长：约{avg_shot_sec:.0f}秒/镜

  以上参数基于剧本实际体量由代码精确计算，请严格按此范围规划分镜。
  文戏段落：每段3-5镜 | 武戏段落：每段5-8镜 | 过渡段落：2-3镜
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return guide
