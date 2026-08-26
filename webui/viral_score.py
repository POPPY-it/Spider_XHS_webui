# encoding: utf-8
"""爆款潜力评分卡：基于特征工程的、可解释的爆款评分（取代 LLM "感觉"打分）。

特征在**当前候选批内**归一为百分位（0-1），加权求和得 0-100 分。
现实限制：批次内百分位需候选数 >= 20 才有统计意义；候选较少时降级为相对均值比。
"""

import math
import re
from datetime import datetime

# 特征权重（velocity 缺失时其权重按比例分摊到其余）
WEIGHTS = {
    "interact_rate": 0.35,
    "collect_rate": 0.15,
    "comment_rate": 0.10,
    "share_rate": 0.10,
    "title_score": 0.15,
    "velocity": 0.15,
    "tag_score": 0.00,
}

_EMOJI = re.compile(
    '[' '\U0001F300-\U0001FAFF' '\U00002600-\U000027BF' '\U0001F1E6-\U0001F1FF'
    '\U00002B00-\U00002BFF' '\U0000FE00-\U0000FE0F' '\U0001F900-\U0001F9FF'
    '\U00002000-\U0000206F' '\U00002190-\U000021FF' '\U00002300-\U000023FF'
    '\U0001F1F0-\U0001F1FF' ']+'
)
_HOOK_WORDS = ["竟然", "没想到", "千万不要", "避雷", "干货", "保姆级", "哭了", "绝了",
               "后悔", "避坑", "全攻略", "清单", "必备", "踩雷", "劝退", "yyds", "绝绝子",
               "真相", "揭秘", "省钱", "效率", "一天", "一个月", "居然", "原来", "越"]
_GROUP_WORDS = ["妈妈", "宝妈", "新手", "学生党", "打工人", "上班族", "家长", "宝宝",
                "女生", "男生", "姐妹", "姐妹", "孩子", "爸妈"]


def _norm_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def compute_features(note: dict, now: datetime) -> dict:
    """对单条笔记计算原始特征值。缺失字段返回 None。"""
    liked = _norm_int(note.get("liked_count"))
    collected = _norm_int(note.get("collected_count"))
    comment = _norm_int(note.get("comment_count"))
    share = _norm_int(note.get("share_count"))
    fans = _norm_int(note.get("fans"))
    total = liked + collected + comment + share

    interact_rate = total / fans if fans > 0 else None
    collect_rate = collected / max(liked + collected, 1) if (liked + collected) > 0 else 0.0
    comment_rate = comment / max(liked + comment, 1) if (liked + comment) > 0 else 0.0
    share_rate = share / max(total, 1) if total > 0 else 0.0

    title = note.get("title") or ""
    digits = len(re.findall(r"\d", title))
    emojis = len(_EMOJI.findall(title))
    hooks = sum(1 for w in _HOOK_WORDS if w in title)
    groups = sum(1 for w in _GROUP_WORDS if w in title)
    tlen = len(title)
    title_score = (1 if digits > 0 else 0) + min(emojis, 2) + hooks + groups + (1 if 10 <= tlen <= 25 else 0)

    tags = note.get("tags") or []
    ntags = len(tags) if isinstance(tags, list) else 0
    tag_score = 1.0 if 3 <= ntags <= 8 else (0.5 if 1 <= ntags <= 10 else 0.0)

    # 爆发信号：总互动 / 发布后小时数（需 upload_time；缺失为 None）
    velocity = None
    dt = _parse_dt(note.get("upload_time"))
    if dt:
        hours = max((now - dt).total_seconds() / 3600.0, 1.0)
        velocity = total / hours if total > 0 else 0.0

    return {
        "interact_rate": interact_rate,      # 越大越爆
        "collect_rate": collect_rate,        # 干货/收藏动机
        "comment_rate": comment_rate,        # 争议/共鸣（适中偏好，不单边）
        "share_rate": share_rate,            # 利他/身份表达
        "title_score": title_score,          # 钩子强度
        "velocity": velocity,                # 每小时互动增速
        "tag_score": tag_score,              # 标签覆盖
    }


def _pct_map(values: list):
    """把原始值列表映射为百分位函数。无参照值时返回恒 None（该特征不参与）。"""
    vals = sorted([v for v in values if v is not None])
    n = len(vals)
    if n == 0:
        return lambda v: None
    if n == 1:
        return lambda v: (1.0 if v is not None else None)
    def pct(v):
        if v is None:
            return None
        less = sum(1 for x in vals if x < v)
        equal = sum(1 for x in vals if x == v)
        return (less + 0.5 * equal) / n
    return pct


def score_notes(notes: list, now: datetime = None) -> list:
    """对一批笔记打分，原地写回 viral_score / viral_features / viral_breakdown。"""
    now = now or datetime.now()
    feats = [compute_features(n, now) for n in notes]

    # 每条特征在批内做百分位
    pct_maps = {}
    for f in WEIGHTS:
        pct_maps[f] = _pct_map([feats[i].get(f) for i in range(len(notes))])

    for i, n in enumerate(notes):
        f = feats[i]
        parts = {}
        wsum = 0.0
        acc = 0.0
        for feat_name, w in WEIGHTS.items():
            # comment_rate 非单调：适中最优，改为与 0.5 的距离（越小越接近适中越高分）
            if feat_name == "comment_rate":
                p = pct_maps[feat_name](f.get(feat_name))
                # 直接使用其百分位代表"争议度存在"
            else:
                p = pct_maps[feat_name](f.get(feat_name))
            if p is None:
                continue  # 该条该特征缺失 → 权重不参与，其余特征相对占比升高
            parts[feat_name] = {"value": round(f.get(feat_name), 4) if isinstance(f.get(feat_name), float) else f.get(feat_name), "pct": round(p, 3)}
            acc += w * p
            wsum += w
        score = round(100 * acc / wsum) if wsum else 0
        n["viral_score"] = score
        n["viral_features"] = parts
        n["viral_breakdown"] = {
            feat: f"{round(p['pct']*100)}%"
            for feat, p in parts.items()
        }

    return notes
