# encoding: utf-8
"""AI 评论分析：用 DeepSeek 分批给评论打标签（分类/情感/主题）并聚合洞察。"""

import glob
import json
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

DATAS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "datas"))
ANALYSIS_DIR = os.path.join(DATAS_DIR, "comment_analysis")
LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_MODEL = "deepseek-chat"

_COMMENT_PAT = re.compile(
    r'^- \*\*(.+?)\*\*（(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})，赞 (\d+)）(.*)$'
)
_EMOJI_PAT = re.compile(
    '[' '\U0001F300-\U0001FAFF' '\U00002600-\U000027BF' '\U0001F1E6-\U0001F1FF'
    '\U00002B00-\U00002BFF' '\U0000FE00-\U0000FE0F' '\U0001F900-\U0001F9FF'
    '\U00002000-\U0000206F' '\U00002190-\U000021FF' '\U00002300-\U000023FF'
    '\U0001F1F0-\U0001F1FF' ']+'
)

CATEGORIES = ["问题咨询", "购买意向", "产品评价", "负面舆情", "其他"]
SENTIMENTS = ["正面", "中性", "负面"]
BATCH_SIZE = 60
CONCURRENCY = 4

SYSTEM_PROMPT = (
    "你是小红书母婴品牌运营分析专家。你会收到一批带 id 的评论（JSON 数组）。"
    "请为每条评论输出分类、情感和主题，严格输出 JSON 对象，格式："
    '{"items":[{"id":整数,"category":"问题咨询|购买意向|产品评价|负面舆情|其他",'
    '"sentiment":"正面|中性|负面","topic":"简短主题词(不超过8字)"}]}。'
    "分类说明：问题咨询=提问/求建议/求对比；购买意向=问购买渠道/价格/下单/求链接；"
    "产品评价=对产品或品牌的评价；负面舆情=批评/投诉/质疑/负面情绪；其他=闲聊或无关。"
    "严格基于给定评论，不编造，不要遗漏任何一条。"
)


def _api_key() -> str:
    load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")), override=True)
    return os.getenv("DEEPSEEK_API_KEY", "")


def _chat(system: str, user: str, retries: int = 2) -> str:
    key = _api_key()
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，请检查 .env")
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }
    last_exc = None
    for _ in range(retries + 1):
        try:
            resp = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"DeepSeek 调用失败：{last_exc}")


# ---------------------------------------------------------------------------
# 评论提取
# ---------------------------------------------------------------------------


def extract_comments(collection_path: str) -> list:
    """解析集合内全部评论，产出 [{username, dt, content, note_title}]；过滤空白/单字/纯表情。"""
    comments = []
    md_files = glob.glob(os.path.join(collection_path, "*", "*", "note.md"))
    if md_files:
        for md_path in md_files:
            title = ""
            info_path = os.path.join(os.path.dirname(md_path), "info.json")
            if os.path.exists(info_path):
                try:
                    title = (json.load(open(info_path, encoding="utf-8")).get("title") or "")[:40]
                except Exception:
                    pass
            in_comments = False
            try:
                f = open(md_path, encoding="utf-8")
            except OSError:
                continue
            with f:
                for line in f:
                    s = line.strip()
                    if s == "## 评论":
                        in_comments = True
                        continue
                    if not in_comments or not s.startswith("- **"):
                        continue
                    m = _COMMENT_PAT.match(s)
                    if not m:
                        continue
                    user, y, mo, d, h, mi, sec, _likes, content = m.groups()
                    comments.append({
                        "username": user,
                        "dt": f"{y}-{mo}-{d} {h}:{mi}:{sec}",
                        "content": content.strip(),
                        "note_title": title,
                    })
    else:
        jsonl = os.path.join(collection_path, "notes.jsonl")
        if os.path.isfile(jsonl):
            with open(jsonl, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        n = json.loads(line)
                    except ValueError:
                        continue
                    for c in (n.get("comments") or []):
                        comments.append({
                            "username": c.get("nickname") or "",
                            "dt": c.get("upload_time") or "",
                            "content": (c.get("content") or "").strip(),
                            "note_title": (n.get("title") or "")[:40],
                        })
    out = []
    for c in comments:
        text = c["content"].strip()
        if not text or len(text) == 1 or (text and _EMOJI_PAT.sub("", text).strip() == ""):
            continue
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# 分批分析
# ---------------------------------------------------------------------------


def _build_batch_prompt(comments: list, start_idx: int) -> str:
    items = [{"id": start_idx + i, "username": c["username"], "content": c["content"]}
             for i, c in enumerate(comments)]
    return json.dumps(items, ensure_ascii=False)


def _parse_batch_output(content: str) -> list:
    """把 DeepSeek 输出解析为 [{id, category, sentiment, topic}]。"""
    text = content.strip()
    text = re.sub(r"^```(json)?", "", text, flags=re.M).strip().strip("`").strip()
    data = None
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except ValueError:
                data = None
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            cid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        cat = it.get("category") if it.get("category") in CATEGORIES else "其他"
        sent = it.get("sentiment") if it.get("sentiment") in SENTIMENTS else "中性"
        out.append({"id": cid, "category": cat, "sentiment": sent, "topic": (it.get("topic") or "")[:12]})
    return out


def analyze_collection(collection_path: str, on_progress=None) -> dict:
    """对集合全部评论分批调 DeepSeek 打标签，返回聚合洞察。"""
    comments = extract_comments(collection_path)
    empty = {
        "kpi": {"total": 0, "analyzed": 0},
        "category_count": {}, "sentiment_count": {},
        "topic_count": [], "representative": {}, "negative_list": [],
    }
    if not comments:
        return empty

    batches = [comments[i:i + BATCH_SIZE] for i in range(0, len(comments), BATCH_SIZE)]
    total = len(batches)
    results = [None] * total
    done = 0

    def run(idx):
        batch = batches[idx]
        prompt = _build_batch_prompt(batch, idx * BATCH_SIZE)
        return _parse_batch_output(_chat(SYSTEM_PROMPT, prompt))

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for idx, parsed in enumerate(ex.map(run, range(total))):
            results[idx] = parsed
            done += 1
            if on_progress:
                on_progress(done, total)

    by_id = {}
    for parsed in results:
        if parsed:
            for r in parsed:
                by_id[r["id"]] = r
    labeled = []
    for i, c in enumerate(comments):
        r = by_id.get(i)
        if r:
            labeled.append({**c, **r})
    return aggregate(labeled, comments)


def aggregate(labeled: list, comments: list) -> dict:
    category_count = Counter(r["category"] for r in labeled)
    sentiment_count = Counter(r["sentiment"] for r in labeled)
    topic_count = Counter(r["topic"] for r in labeled if r.get("topic"))
    representative = {}
    for cat in CATEGORIES:
        representative[cat] = [r for r in labeled if r["category"] == cat][:5]
    negative_list = [r for r in labeled if r["sentiment"] == "负面"]
    return {
        "kpi": {"total": len(comments), "analyzed": len(labeled)},
        "category_count": dict(category_count),
        "sentiment_count": dict(sentiment_count),
        "topic_count": [{"name": k, "value": v} for k, v in topic_count.most_common(15)],
        "representative": {k: v for k, v in representative.items()},
        "negative_list": negative_list,
    }


# ---------------------------------------------------------------------------
# 结果缓存
# ---------------------------------------------------------------------------


def cache_path(collection: str) -> str:
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    return os.path.join(ANALYSIS_DIR, collection + ".json")


def save_cache(collection: str, data: dict) -> str:
    path = cache_path(collection)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def load_cache(collection: str):
    path = cache_path(collection)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
