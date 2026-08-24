# encoding: utf-8
"""内置对话 Agent：用自然语言操作采集、达人筛选、数据库查询。

基于 DeepSeek（OpenAI 兼容接口）的 Function Calling：
用户说一句话 → LLM 理解意图 → 调用对应工具 → 把结果用自然语言总结。

工具（第一版核心三件套）：
- search_talents  达人筛选（蒲公英）
- query_talents    查数据库里已采集的达人
- crawl_user_notes 采集指定用户的全部笔记（含评论）
"""

import json
import os

import requests
from dotenv import load_dotenv

LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是「小红书运营助手」，帮用户完成数据采集和达人筛选。

你能用的工具有三个：
1. search_talents —— 筛选小红书达人（按类目、粉丝数、性别）
2. query_talents —— 查询已经采集到数据库里的达人
3. crawl_user_notes —— 采集某个用户的全部笔记（含评论）

规则：
- 用户想"找达人/筛选达人/推荐达人"时，用 search_talents
- 用户想"查已采集的数据/数据库里的达人"时，用 query_talents
- 用户想"抓取/采集某个博主的笔记"时，用 crawl_user_notes
- 工具返回结果后，用简洁的中文总结给用户
- 【重要】严格基于工具返回的真实数据回答，绝不编造数字或名字。如果工具返回错误或没有数据，如实告诉用户"查询失败/没有数据"，不要自己想象结果
- 如果用户的问题不涉及这些操作，就正常聊天回答"""


def _api_key() -> str:
    load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")), override=True)
    return os.getenv("DEEPSEEK_API_KEY", "")


# ---------------------------------------------------------------------------
# 工具定义（OpenAI function calling 格式）
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_talents",
            "description": "筛选小红书达人（蒲公英平台），按内容类目、粉丝数、性别筛选。返回达人列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "内容类目，如：母婴、美妆、美食、时尚、家居家装"},
                    "fans_min": {"type": "integer", "description": "粉丝数下限（实际人数，如 50000 表示 5 万粉）"},
                    "fans_max": {"type": "integer", "description": "粉丝数上限"},
                    "gender": {"type": "string", "enum": ["女", "男"], "description": "性别"},
                    "count": {"type": "integer", "description": "返回数量，默认 10"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_talents",
            "description": "查询数据库里已经采集到的达人数据。可按关键词、粉丝数筛选。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "关键词，匹配昵称或标签"},
                    "fans_min": {"type": "integer", "description": "粉丝数下限"},
                    "limit": {"type": "integer", "description": "返回数量，默认 10"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crawl_user_notes",
            "description": "采集指定小红书用户的全部笔记（含评论、图片、视频），保存到本地。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_url": {"type": "string", "description": "用户主页链接，如 https://www.xiaohongshu.com/user/profile/xxxx"},
                    "include_comments": {"type": "boolean", "description": "是否包含评论，默认 true"}
                }
            }
        }
    },
]


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

def tool_search_talents(category=None, fans_min=None, fans_max=None, gender=None, count=10):
    from webui import pgy_talents
    tree = pgy_talents.get_categories()
    content_tags = None
    if category:
        # 匹配一级类目名
        for first in tree:
            if first.get("taxonomy1Tag") == category:
                content_tags = [category]
                break
        if content_tags is None:
            # 匹配二级类目
            for first in tree:
                if category in (first.get("taxonomy2Tags") or []):
                    content_tags = [category]
                    break
        if content_tags is None:
            content_tags = [category]  # 直接传给接口试试
    result = pgy_talents.search_talents(
        content_tags=content_tags,
        fans_min=fans_min,
        fans_max=fans_max,
        gender=gender,
        max_pages=1,
        page_size=min(count, 20),
    )
    talents = result.get("talents", [])
    return {
        "total": result.get("total", 0),
        "talents": [
            {
                "name": t.get("name"),
                "fans": t.get("fansNum"),
                "location": t.get("location"),
                "gender": t.get("gender"),
                "tags": (t.get("personalTags") or [])[:3],
            }
            for t in talents[:count]
        ]
    }


def tool_query_talents(keyword=None, fans_min=None, limit=10):
    from webui import pg_sync
    conn = pg_sync._connect()
    cur = conn.cursor()
    sql = 'SELECT nickname, fans, "ipLocation", tags FROM "SocialCreator" WHERE platform=%s'
    params = ["xiaohongshu"]
    if keyword:
        sql += ' AND (nickname ILIKE %s OR array_to_string(tags, %s) ILIKE %s)'
        params += [f"%{keyword}%", ",", f"%{keyword}%"]
    if fans_min:
        sql += ' AND fans >= %s'
        params.append(fans_min)
    sql += ' ORDER BY fans DESC NULLS LAST LIMIT %s'
    params.append(min(limit, 50))
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return {
        "talents": [
            {"nickname": r[0], "fans": r[1], "location": r[2], "tags": r[3] or []}
            for r in rows
        ]
    }


def tool_crawl_user_notes(user_url=None, include_comments=True):
    from webui import tasks
    if not user_url:
        return {"error": "缺少用户链接"}
    import time as _t
    task_id = tasks.start_task("export", {
        "mode": "user",
        "user_url": user_url,
        "include_comments": bool(include_comments),
        "collection": "agent_" + _t.strftime("%Y%m%d_%H%M%S"),
    })
    return {"task_id": task_id, "message": "采集任务已启动，后台执行中"}


TOOL_FUNCS = {
    "search_talents": tool_search_talents,
    "query_talents": tool_query_talents,
    "crawl_user_notes": tool_crawl_user_notes,
}


# ---------------------------------------------------------------------------
# LLM 调用（流式 + function calling）
# ---------------------------------------------------------------------------

def _chat(messages, tools, stream, on_delta=None):
    """调用 DeepSeek，返回完整响应。流式时逐段回调 on_delta(text)。"""
    api_key = _api_key()
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    if not stream:
        resp = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        tcs = msg.get("tool_calls") or []
        return {
            "content": msg.get("content") or "",
            "tool_calls": [
                {
                    "id": t.get("id"),
                    "name": (t.get("function") or {}).get("name"),
                    "arguments": (t.get("function") or {}).get("arguments", "{}"),
                }
                for t in tcs
            ] or None,
        }

    # 流式
    resp = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload, stream=True, timeout=120)
    resp.raise_for_status()
    full_content = ""
    tool_calls = {}
    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content"):
            full_content += delta["content"]
            if on_delta:
                on_delta(delta["content"])
        # 累积 tool_calls
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            if idx not in tool_calls:
                tool_calls[idx] = {"id": tc.get("id"), "name": "", "arguments": ""}
            if tc.get("id"):
                tool_calls[idx]["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                tool_calls[idx]["name"] += fn["name"]
            if fn.get("arguments"):
                tool_calls[idx]["arguments"] += fn["arguments"]
    return {
        "content": full_content,
        "tool_calls": [tool_calls[i] for i in sorted(tool_calls.keys())] if tool_calls else None,
    }


def run_agent(user_input: str, on_delta=None):
    """主流程：LLM 理解 → 调用工具 → 总结。on_delta(text) 用于流式输出。"""
    api_key = _api_key()
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在 .env 中填写")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    # 第一轮：让 LLM 决定是否调工具
    first = _chat(messages, TOOLS, stream=False)
    tool_calls = first.get("tool_calls")

    if not tool_calls:
        # 不需要工具，直接流式回答
        _chat(messages, None, stream=True, on_delta=on_delta)
        return

    # 有工具调用：执行工具
    assistant_msg = {"role": "assistant", "content": first.get("content") or None}
    # 构造 tool_calls 消息
    assistant_tool_calls = []
    tool_results = []
    for tc in tool_calls:
        name = tc.get("name")
        try:
            args = json.loads(tc.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        func = TOOL_FUNCS.get(name)
        assistant_tool_calls.append({
            "id": tc.get("id", ""),
            "type": "function",
            "function": {"name": name, "arguments": tc.get("arguments", "{}")},
        })
        if func:
            try:
                result = func(**args)
            except Exception as exc:
                result = {"error": str(exc)}
        else:
            result = {"error": f"未知工具 {name}"}
        tool_results.append(result)

    messages.append({"role": "assistant", "content": assistant_msg.get("content"), "tool_calls": assistant_tool_calls})
    for i, r in enumerate(tool_results):
        messages.append({
            "role": "tool",
            "tool_call_id": tool_calls[i].get("id", ""),
            "content": json.dumps(r, ensure_ascii=False),
        })

    # 第二轮：LLM 根据工具结果总结（流式）
    _chat(messages, None, stream=True, on_delta=on_delta)
