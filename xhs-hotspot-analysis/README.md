# xhs-hotspot-analysis — 小红书品类热点分析 Skill

给 Spider_XHS 增加一层"热点分析"能力：**抓什么（可配置筛选）→ 为什么爆（LLM 拆解）→ 能追什么（爆款公式 + 选题）**。

```
Spider_XHS（数据底座，未被改动）
    └── xhs-hotspot-analysis/（本 skill，纯增量）
            ├── SKILL.md                         # 工作流入口
            ├── scripts/hotspot_collect.py       # 采集 + 筛选，产出 sources.jsonl
            ├── scripts/hotspot_analyze.py       # 调用大模型 API 做爆因分析，产出 analysis.md
            ├── references/viral_analysis.md     # LLM 爆因拆解框架（六维 + 评分 + 品类总结）
            ├── ai_config.json                   # 大模型 API 配置（DeepSeek/GPT/Kimi/Claude 等）
            ├── ai_config.example.json           # 配置模板
            └── examples/config.example.json     # 采集配置示例
```

## 为什么这样做

- **复用现成数据层**：Spider_XHS 的 `search_some_note` 已支持排序、笔记类型、时间范围等搜索参数，skill 只需要把用户意图映射成这些参数；互动门槛、排除词等"自定义要求"在本地过滤层做。
- **分析层独立于 Claude**：`hotspot_analyze.py` 用 `requests` 直接调用配置的大模型 API（DeepSeek / GPT / Kimi / Claude 都支持），**整个链路不再依赖 Claude**，可配置多 provider 自由切换。
- **不动本体、不搭平台**：skill 只是调用 Spider_XHS 的接口，与 XHS_ALL_IN_ONE 互不冲突。

## 使用

1. 装依赖：`pip install -r requirements.txt`（在 Spider_XHS 仓库根，含本 skill 的脚本）。
2. 准备 Cookie：浏览器登录 xiaohongshu.com 后复制完整 Cookie，放入环境变量 `COOKIES`，或每次用 `--cookies` 传。
3. 采集：

```bash
python xhs-hotspot-analysis/scripts/hotspot_collect.py \
  --query "AI工具" --count 30 --sort popularity --days week \
  --min "liked_count>=500" --detail --max-results 20
```

4. 分析：

```bash
# 首次：复制配置模板，设置对应 API Key 环境变量
cp xhs-hotspot-analysis/ai_config.example.json xhs-hotspot-analysis/ai_config.json
export DEEPSEEK_API_KEY="sk-..."

# 调用配置的大模型分析（无需 Claude）
python xhs-hotspot-analysis/scripts/hotspot_analyze.py \
  --sources data/2026-08-05-AI工具/sources.jsonl \
  --context "账号画像：科技博主，粉丝10w"   # 可选
```

   输出 `analysis.md`。切换模型用 `--provider gpt|kimi|claude|deepseek`，`--model` 覆盖模型名。
   `ai_config.json` 里可添加任意 OpenAI 兼容 provider（base_url + api_key_env + model）。

## 参数速查（采集脚本）

| 参数 | 默认 | 说明 |
|---|---|---|
| `--query` | 必填 | 品类/关键词 |
| `--count` | 30 | 抓取数量 |
| `--sort` | popularity | general/latest/popularity/comment/collect |
| `--days` | week | day/week/half_year |
| `--note-type` | all | all/video/note |
| `--min` | 空 | 互动门槛，逗号分隔，如 `liked_count>=500,collected_count>=100` |
| `--exclude` | 空 | 标题/正文排除词，逗号分隔 |
| `--detail` | 关 | 对 Top N 补齐详情与评论 |
| `--detail-count` | 10 | 补齐详情的条数 |
| `--comments-count` | 5 | 每条保留的一级评论数 |
| `--max-results` | 20 | 筛选后最多保留条数 |
| `--cookies` | env `COOKIES` | 完整 PC Cookie |

退出码：`0` 成功，`1` 搜索失败/无结果，`2` 登录态无效。

## 参数速查（分析脚本）

| 参数 | 默认 | 说明 |
|---|---|---|
| `--sources` | 必填 | sources.jsonl 路径 |
| `--config` | `ai_config.json` | provider 配置文件路径 |
| `--provider` | 配置里的 `provider` | deepseek / gpt / kimi / claude，或配置里任意名字 |
| `--model` | 配置里的 `model` | 覆盖模型名 |
| `--api-key` | 环境变量 | 直接传 Key（优先于环境变量） |
| `--context` | 空 | 账号画像/品类背景，让分析回扣"适不适合我" |
| `--json` | 关 | 额外输出 analysis.json |

`ai_config.json` 配置说明：`provider` 指定默认模型，`providers` 里每个条目是 `base_url`（OpenAI 兼容或 Anthropic）+ `api_key_env`（环境变量名，不存明文 key）+ `model`。DeepSeek / GPT / Kimi 走 OpenAI 兼容格式，Claude 走 Anthropic Messages 格式，脚本自动识别。

## 目录产物

```
data/<日期>-<关键词>/
├── sources.jsonl    # 采集到的候选爆文（统一字段）
└── analysis.md      # LLM 生成的爆因分析报告（可选 analysis.json）
```

## 已知边界

- 数据来自公开搜索接口，互动数字为接口返回值；个别笔记可能缺字段，分析时按"该字段未采集"处理，不脑补。
- **详情接口（正文全文）可能被风控**（返回"当前笔记暂时无法浏览"），脚本会在 `detail` 字段标 `detail_unavailable: true`。爆因分析在详情缺失时，只用 标题 + desc 摘要 + 互动结构 + 评论区 拆解。
- 评论区接口通常可用，是"为什么爆"的最直接证据，`--detail` 时一并抓取。
- 仅供学习交流，请遵守小红书用户协议，控制采集频率与数量。
