"""comment_analyze 的提取 / 聚合 / 缓存逻辑。"""

import webui.comment_analyze as ca


def test_extract_comments_filters_noise(tmp_path):
    col = tmp_path / "c"
    note_dir = col / "exp" / "note1"
    note_dir.mkdir(parents=True)
    (note_dir / "note.md").write_text(
        "# 标题\n\n## 评论\n\n"
        "- **A**（2026-01-01 10:00:00，赞 0）有效评论内容\n"
        "- **B**（2026-01-02 10:00:00，赞 0）\n"
        "- **C**（2026-01-03 10:00:00，赞 0）好\n"
        "- **D**（2026-01-04 10:00:00，赞 0）👍🏻\n",
        encoding="utf-8",
    )
    cs = ca.extract_comments(str(col))
    assert len(cs) == 1
    assert cs[0]["username"] == "A"
    assert cs[0]["content"] == "有效评论内容"


def test_extract_comments_fallback_jsonl(tmp_path):
    col = tmp_path / "c2"
    col.mkdir()
    (col / "notes.jsonl").write_text(
        '{"title":"t","comments":[{"nickname":"X","upload_time":"2026-01-01 10:00:00","content":"内容"},'
        '{"nickname":"Y","content":""}]}\n',
        encoding="utf-8",
    )
    cs = ca.extract_comments(str(col))
    assert len(cs) == 1
    assert cs[0]["username"] == "X"


def test_aggregate():
    comments = [{"username": "u", "dt": "2026-01-01", "content": "c", "note_title": "n"}]
    labeled = [{**comments[0], "category": "负面舆情", "sentiment": "负面", "topic": "安全"}]
    d = ca.aggregate(labeled, comments)
    assert d["kpi"] == {"total": 1, "analyzed": 1}
    assert d["category_count"]["负面舆情"] == 1
    assert d["sentiment_count"]["负面"] == 1
    assert len(d["negative_list"]) == 1
    assert len(d["representative"]["负面舆情"]) == 1


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "ANALYSIS_DIR", str(tmp_path))
    ca.save_cache("测试", {"kpi": {"analyzed": 1}})
    assert ca.load_cache("测试")["kpi"]["analyzed"] == 1
    assert ca.load_cache("没有") is None


def test_parse_batch_output_handles_fences():
    out = ca._parse_batch_output(
        '```json\n{"items":[{"id":0,"category":"问题咨询","sentiment":"中性","topic":"HMO"}]}\n```'
    )
    assert len(out) == 1
    assert out[0]["id"] == 0
    assert out[0]["category"] == "问题咨询"
