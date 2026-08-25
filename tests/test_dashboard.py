"""dashboard_api 的解析、分桶与聚合逻辑。"""

from datetime import datetime

import pytest

from webui import dashboard_api as da


# ---------- 基础工具 ----------


def test_parse_dt():
    assert da._parse_dt("2026-01-05 12:00:00") == datetime(2026, 1, 5, 12, 0, 0)
    assert da._parse_dt("bad") is None
    assert da._parse_dt(None) is None
    assert da._parse_dt("") is None


def test_month_key():
    assert da._month_key(datetime(2026, 1, 5)) == "2026-01"
    assert da._month_key(datetime(2025, 12, 31)) == "2025-12"


def test_fill_months_gaps():
    pairs = {(2026, 1): 2, (2026, 3): 1}
    out = da._fill_months(pairs, datetime(2026, 1, 1), datetime(2026, 3, 31))
    assert [m["month"] for m in out] == ["2026-01", "2026-02", "2026-03"]
    assert out[1]["count"] == 0  # 缺月补 0
    assert out[0]["count"] == 2


# ---------- 评论行解析 ----------


def test_comment_pattern_top_level():
    m = da._COMMENT_PAT.match("- **用户A**（2026-01-05 12:00:00，赞 3）不错")
    assert m
    assert m.group(1) == "用户A"
    assert m.group(8) == "3"
    assert m.group(9) == "不错"


def test_comment_pattern_nested_stripped():
    line = "  - **用户B**（2026-01-06 13:00:00，赞 1）回复 @用户A：同意".strip()
    m = da._COMMENT_PAT.match(line)
    assert m
    assert m.group(1) == "用户B"
    assert "回复 @用户A" in m.group(9)


def test_comment_pattern_no_match():
    assert da._COMMENT_PAT.match("## 评论") is None
    assert da._COMMENT_PAT.match("普通文本") is None


# ---------- 集合聚合 ----------


def _make_collection(tmp_path):
    col = tmp_path / "collection"
    note_dir = col / "export_1" / "note_abc"
    note_dir.mkdir(parents=True)
    (col / "notes.jsonl").write_text(
        '{"note_id":"abc","title":"测试1","type":"图集","liked_count":10,'
        '"collected_count":5,"comment_count":2,"share_count":1,'
        '"upload_time":"2026-01-01 10:00:00","note_url":"http://x"}\n'
        '{"note_id":"def","title":"测试2","type":"视频","liked_count":0,'
        '"collected_count":0,"comment_count":0,"share_count":0,'
        '"upload_time":"2026-02-01 10:00:00","note_url":"http://y"}\n',
        encoding="utf-8",
    )
    (note_dir / "note.md").write_text(
        "# 测试1\n\n正文\n\n## 评论\n\n"
        "- **用户A**（2026-01-05 12:00:00，赞 3）不错\n"
        "  - **用户B**（2026-01-06 13:00:00，赞 1）回复 @用户A：同意\n"
        "- **用户C**（2025-06-11 00:00:00，赞 0）早期\n",
        encoding="utf-8",
    )
    return str(col)


def test_aggregate_export_collection(tmp_path):
    d = da.aggregate_export_collection(_make_collection(tmp_path))
    k = d["kpi"]
    assert k["note_count"] == 2
    assert k["comment_count"] == 3  # 全部评论（含楼中楼、不限时间）
    assert k["total_likes"] == 10
    assert k["total_collects"] == 5
    assert k["total_shares"] == 1

    names = [x["name"] for x in d["user_comment_top"]]
    assert "用户A" in names

    ct = {m["month"]: m["count"] for m in d["comment_trend"]}
    assert ct.get("2026-01") == 2
    nt = {m["month"]: m["count"] for m in d["note_trend"]}
    assert nt.get("2026-01") == 1

    types = {x["name"]: x["value"] for x in d["note_type_dist"]}
    assert types.get("图集") == 1
    assert types.get("视频") == 1


def test_aggregate_comments_fallback_jsonl(tmp_path):
    """无 note.md 的集合应回退解析 notes.jsonl 的 comments[]。"""
    col = tmp_path / "collection2"
    col.mkdir(parents=True)
    (col / "notes.jsonl").write_text(
        '{"note_id":"abc","title":"测试1","type":"图集","liked_count":1,'
        '"collected_count":0,"comment_count":1,"share_count":0,'
        '"upload_time":"2026-01-01 10:00:00","note_url":"http://x",'
        '"comments":[{"nickname":"评论人","upload_time":"2026-01-02 09:00:00"}]}\n',
        encoding="utf-8",
    )
    d = da.aggregate_export_collection(str(col))
    assert d["kpi"]["comment_count"] == 1
    assert d["user_comment_top"][0]["name"] == "评论人"


# ---------- 集合名安全校验 ----------


def test_resolve_collection_valid():
    p = da.resolve_collection("测试皇家美素佳儿")
    assert p.endswith("测试皇家美素佳儿")


def test_resolve_collection_traversal_blocked():
    with pytest.raises(ValueError):
        da.resolve_collection("../../etc/passwd")
    with pytest.raises(ValueError):
        da.resolve_collection("/etc/passwd")
