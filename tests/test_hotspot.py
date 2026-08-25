"""热点重构：多关键词拆分、低粉爆款打分排序。"""

from webui.hotspot_routes import _score_candidates, _split_queries


def test_split_queries_commas_and_newlines():
    assert _split_queries("母婴,新手妈妈") == ["母婴", "新手妈妈"]
    assert _split_queries("奶粉避坑，待产包\n红屁屁") == ["奶粉避坑", "待产包", "红屁屁"]
    assert _split_queries("") == []
    assert _split_queries("  ,  ，\n ") == []


def test_score_candidates_ratio_prioritizes_lowfan():
    cands = [
        {"note_id": "a", "liked_count": 100, "collected_count": 0, "comment_count": 0, "share_count": 0, "fans": 50, "user_id": "u1"},
        {"note_id": "b", "liked_count": 900, "collected_count": 0, "comment_count": 0, "share_count": 0, "fans": 5000, "user_id": "u2"},
        {"note_id": "c", "liked_count": 2000, "collected_count": 0, "comment_count": 0, "share_count": 0, "fans": 50000, "user_id": "u3"},
    ]
    out = _score_candidates(cands, lowfan=True)
    # a: 互动100/粉丝50=ratio 2.0 且粉丝<1万、互动>=500? 互动只有100 <500，不算低粉
    assert out[0]["note_id"] == "a"  # 无低粉时按 ratio 排（a ratio 2.0 最高）
    assert out[0]["ratio"] == 2.0
    assert out[0]["is_lowfan"] is False  # 互动 100 < 500
    assert out[2]["note_id"] == "c"


def test_score_candidates_lowfan_flag():
    cands = [
        {"note_id": "x", "liked_count": 3000, "collected_count": 0, "comment_count": 0, "share_count": 0, "fans": 800, "user_id": "u"},
        {"note_id": "y", "liked_count": 800, "collected_count": 0, "comment_count": 0, "share_count": 0, "fans": 20000, "user_id": "u2"},
    ]
    out = _score_candidates(cands, lowfan=True)
    assert out[0]["note_id"] == "x"
    assert out[0]["is_lowfan"] is True   # 互动3000>=500, 粉丝800<1万, ratio 3.75>=1
    assert out[1]["is_lowfan"] is False  # 粉丝2万>=1万


def test_score_candidates_fallback_to_interactions_no_fans():
    cands = [
        {"note_id": "a", "liked_count": 100, "collected_count": 0, "comment_count": 0, "share_count": 0},
        {"note_id": "b", "liked_count": 900, "collected_count": 0, "comment_count": 0, "share_count": 0},
    ]
    out = _score_candidates(cands, lowfan=True)
    # 无粉丝 → ratio None、is_lowfan False，按互动降序
    assert out[0]["note_id"] == "b"
    assert out[0]["ratio"] is None
    assert out[0]["is_lowfan"] is False


def test_score_candidates_lowfan_off_sorts_by_interactions():
    cands = [
        {"note_id": "a", "liked_count": 100, "collected_count": 0, "comment_count": 0, "share_count": 0, "fans": 50},
        {"note_id": "b", "liked_count": 900, "collected_count": 0, "comment_count": 0, "share_count": 0, "fans": 5000},
    ]
    out = _score_candidates(cands, lowfan=False)
    assert out[0]["note_id"] == "b"
