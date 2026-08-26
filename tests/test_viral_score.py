"""爆款潜力评分卡：特征计算、百分位归一、velocity 降级、加权分。"""

from datetime import datetime

from webui.viral_score import compute_features, score_notes


def _mk(**kw):
    base = {
        "title": "新手妈妈必备的5个奶粉避坑清单！绝对干货",
        "liked_count": 7704, "collected_count": 1200, "comment_count": 504, "share_count": 90,
        "fans": 68, "tags": ["奶粉", "育儿", "母婴"], "upload_time": "2026-08-26 10:00:00",
    }
    base.update(kw)
    return base


NOW = datetime(2026, 8, 26, 12, 0, 0)


def test_compute_features_interact_rate_and_velocity():
    f = compute_features(_mk(), NOW)
    assert f["interact_rate"] > 100  # 68 粉 9000+ 互动
    assert f["velocity"] > 0


def test_compute_features_title_score():
    f = compute_features(_mk(), NOW)
    assert f["title_score"] >= 3  # 数字 + 人群词(妈妈) + 钩子词(避坑/必备/清单)


def test_compute_features_velocity_missing_without_upload_time():
    f = compute_features(_mk(upload_time=None), NOW)
    assert f["velocity"] is None


def test_score_notes_ranks_lowfan_highest():
    notes = [
        _mk(title="低粉爆款", fans=68, liked_count=7704),
        _mk(title="大号普通", fans=50000, liked_count=8000),
        _mk(title="小透明", fans=200, liked_count=50),
    ]
    score_notes(notes, NOW)
    assert notes[0]["viral_score"] >= notes[1]["viral_score"]
    assert notes[0]["viral_score"] >= notes[2]["viral_score"]


def test_score_notes_velocity_absent_no_crash():
    notes = [_mk(upload_time=None), _mk(upload_time=None)]
    score_notes(notes, NOW)
    # velocity 全缺失 → 该特征不参与，权重分摊，不报错
    assert "velocity" not in notes[0]["viral_features"]
    assert "velocity" not in notes[0]["viral_breakdown"]
    assert isinstance(notes[0]["viral_score"], int)


def test_score_notes_returns_breakdown():
    notes = [_mk(), _mk(title="另一篇", fans=5000, liked_count=100)]
    score_notes(notes, NOW)
    assert "viral_breakdown" in notes[0]
    assert "interact_rate" in notes[0]["viral_breakdown"]
