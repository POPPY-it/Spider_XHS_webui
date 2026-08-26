#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""热点分析脚本：读 sources.jsonl，调用配置的大模型 API，产出爆因分析报告。

支持多家大模型（DeepSeek / OpenAI(GPT) / Kimi / Claude 等），全部在 ai_config.json 里配置：

    {
      "provider": "deepseek",
      "providers": {
        "deepseek": {
          "base_url": "https://api.deepseek.com/v1",
          "api_key_env": "DEEPSEEK_API_KEY",
          "model": "deepseek-chat"
        },
        ...
      }
    }

DeepSeek / OpenAI / Kimi 走 OpenAI 兼容格式；Claude 走 Anthropic Messages 格式，脚本自动识别。

用法：
    python hotspot_analyze.py --sources data/2026-08-05-AI工具/sources.jsonl
    python hotspot_analyze.py --sources ... --provider claude --model claude-sonnet-4-5
    python hotspot_analyze.py --sources ... --provider kimi --model kimi-k2.5

输出：与 sources 同目录的 analysis.md（可选 --json 输出 analysis.json）。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]  # Spider_XHS 仓库根
CONFIG_PATH = SCRIPT_DIR.parent / "ai_config.json"  # 与 ai_config.json 同层
FRAMEWORK_PATH = SCRIPT_DIR.parent / "references" / "viral_analysis.md"

# Anthropic 消息格式的 provider（其余走 OpenAI 兼容格式）
ANTHROPIC_PROVIDERS = {"claude"}


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"未找到配置文件 {path}，请先复制 ai_config.example.json 为 ai_config.json 并填写")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def resolve_api_key(provider_conf: dict, cli_key: str = "") -> str:
    """API Key 优先级：--api-key > 环境变量 > 项目 .env 里的同名变量。"""
    if cli_key.strip():
        return cli_key.strip()
    env_name = provider_conf.get("api_key_env", "")
    if env_name:
        value = os.environ.get(env_name, "")
        if not value:
            env_file = PROJECT_ROOT / ".env"
            if env_file.exists():
                try:
                    from dotenv import dotenv_values
                    value = (dotenv_values(env_file).get(env_name) or "").strip()
                except Exception:
                    pass
        if value:
            return value
    raise ValueError(
        f"provider '{provider_conf.get('name', '?')}' 未配置 API Key："
        f"请设置环境变量 {env_name}，或用 --api-key 传入"
    )


def build_prompt(notes: list[dict], framework: str, category: str, extra_context: str = "", target_category: str = "") -> str:
    """把候选爆文 + 拆解框架 + 用户补充（品类/账号画像）拼成分析 prompt。"""
    if extra_context:
        extra = f"\n用户补充背景（供回扣'适不适合我'）：\n{extra_context}\n"
    else:
        extra = "\n未提供账号画像，仅做客观拆解。\n"
    if target_category and target_category.strip() != category:
        extra += (
            f"\n# 跨品类迁移（重要）\n"
            f"本次搜索的关键词是「{category}」，但你的目标品类是「{target_category}」。"
            "在「三张清单」之后，额外输出一节「跨品类迁移建议」：按框架第 5 节可复用/不可复用的思路，"
            "分析这批爆款的【钩子】【结构】【情绪】【人群】哪些能迁移到目标品类「{target_category}」，"
            "给出 2-3 个具体迁移示例（含改写后的标题示例、套用同一结构的新选题）。\n"
        )
    notes_json = json.dumps(notes, ensure_ascii=False, indent=1)
    return f"""你是小红书品类热点分析专家。请严格按下面的拆解框架，分析这批候选爆文。

# 拆解框架
{framework}

# 本次分析的品类/关键词
{category}

# 候选爆文数据（JSON，来自 sources.jsonl）
{notes_json}

# 任务
1. 对每条候选打 A/B 双标签：内容形态（标签 A，标主形）+ 爆款机制（标签 B，取 top1-2），并给出 score/tier，**优先引用评论区原话（带赞数）作为证据**。
2. 数本批共性：输出三条分布线（形态分布 / 机制分布 / 标题高频词），按阈值判定「共性/次主流/个例」。
3. 拆三张清单：可复用 / 不可复用（身份、资源壁垒）/ 平台适配建议。
4. 输出为 Markdown，直接可作为 analysis.md。
5. 注意长度：单条每条约 3-5 行要点即可，把篇幅留给「数共性」与「三张清单」（报告最有价值部分）。务必完整输出全部 {len(notes)} 条拆解 + 三条分布线 + 三张清单，不要截断。
{extra}"""


def call_openai_compatible(provider_conf: dict, prompt: str, model: str) -> str:
    """DeepSeek / OpenAI / Kimi 等 OpenAI 兼容接口。"""
    base_url = provider_conf["base_url"].rstrip("/")
    api_key = resolve_api_key(provider_conf, os.environ.get("LLM_API_KEY", ""))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个专业的小红书品类热点与爆款内容分析专家，输出严格基于输入数据，不编造。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 8192,
    }
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"API 返回格式异常：{json.dumps(data, ensure_ascii=False)[:300]}") from exc


def call_anthropic(provider_conf: dict, prompt: str, model: str) -> str:
    """Claude（Anthropic Messages 格式）。"""
    base_url = provider_conf.get("base_url", "https://api.anthropic.com").rstrip("/")
    api_key = resolve_api_key(provider_conf, os.environ.get("LLM_API_KEY", ""))
    payload = {
        "model": model,
        "system": "你是一个专业的小红书品类热点与爆款内容分析专家，输出严格基于输入数据，不编造。",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8192,
    }
    resp = requests.post(
        f"{base_url}/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"Anthropic 返回格式异常：{json.dumps(data, ensure_ascii=False)[:300]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="调用配置的大模型，对采集结果做爆因分析")
    parser.add_argument("--sources", required=True, help="sources.jsonl 路径")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="ai_config.json 路径")
    parser.add_argument("--provider", default="", help="覆盖默认 provider，如 claude/kimi")
    parser.add_argument("--model", default="", help="覆盖默认模型名")
    parser.add_argument("--api-key", default="", help="直接传 API Key（优先于环境变量）")
    parser.add_argument("--context", default="", help="用户补充背景（账号画像/品类说明），回扣'适不适合我'")
    parser.add_argument("--target-category", default="", help="目标品类（与搜索词可不同），用于跨品类迁移建议")
    parser.add_argument("--json", action="store_true", help="额外输出 analysis.json")
    args = parser.parse_args()

    sources_path = Path(args.sources)
    if not sources_path.exists():
        print(f"[analyze] ❌ 找不到 {sources_path}", file=sys.stderr)
        return 1

    notes = []
    with sources_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                notes.append(json.loads(line))
    if not notes:
        print("[analyze] ❌ sources.jsonl 为空", file=sys.stderr)
        return 1

    try:
        config = load_config(Path(args.config))
        provider_name = args.provider or config.get("provider", "")
        provider_conf = config.get("providers", {}).get(provider_name)
        if not provider_conf:
            available = ", ".join(config.get("providers", {}).keys()) or "(空)"
            print(f"[analyze] ❌ provider '{provider_name}' 未在配置中找到，可用：{available}", file=sys.stderr)
            return 1
        model = args.model or provider_conf.get("model", "")
        framework = FRAMEWORK_PATH.read_text(encoding="utf-8") if FRAMEWORK_PATH.exists() else ""
    except Exception as exc:
        print(f"[analyze] ❌ 配置读取失败：{exc}", file=sys.stderr)
        return 1

    category = sources_path.parent.name
    prompt = build_prompt(notes, framework, category, args.context, args.target_category)
    print(f"[analyze] 调用 {provider_name}/{model} 分析 {len(notes)} 条…", flush=True)

    try:
        if provider_name in ANTHROPIC_PROVIDERS:
            content = call_anthropic(provider_conf, prompt, model)
        else:
            content = call_openai_compatible(provider_conf, prompt, model)
    except Exception as exc:
        print(f"[analyze] ❌ 调用失败：{exc}", file=sys.stderr)
        return 1

    out_md = sources_path.parent / "analysis.md"
    out_md.write_text(content, encoding="utf-8")
    print(f"[analyze] ✅ 报告已写入：{out_md}")

    if args.json:
        out_json = sources_path.parent / "analysis.json"
        out_json.write_text(content, encoding="utf-8")
        print(f"[analyze] ✅ JSON 已写入：{out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
