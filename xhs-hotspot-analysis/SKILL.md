---
name: xhs-hotspot-analysis
description: 小红书品类热点分析。用 Spider_XHS 采集某品类/关键词下的候选爆文，按用户自定义条件（时间范围、排序、互动门槛、排除词）筛选，再由 LLM 逐条拆解爆因（人群/场景/痛点/情绪/钩子/结构）并产出该品类的爆款公式与可复刻选题。Use this when the user wants to know "某个品类最近有什么热点"、"为什么这些笔记爆了"或"给我几个能追的选题"。
---

# 小红书热点分析 (xhs-hotspot-analysis)

把「某品类有什么热点 + 为什么爆 + 有什么能追」变成一条可重复的流水线：

```
配置筛选条件 → 采集候选爆文 → LLM 爆因拆解 → 品类爆款公式 + 选题
```

## 前置条件

- 项目已按 Spider_XHS 要求装好依赖（`pip install -r requirements.txt`，Node 依赖如需签名验证）。
- 有小红书 PC Cookie（浏览器登录后复制的完整 Cookie，需含 `a1` 与 `web_session`）。
  脚本参数缺省时从环境变量 `COOKIES` 读取，也可以用 `--cookies` 直接传。

## 使用流程

### 1) 采集

把用户意图翻译成采集参数，运行采集脚本：

```bash
cd <Spider_XHS 仓库根>
python xhs-hotspot-analysis/scripts/hotspot_collect.py \
  --query "AI工具" --count 30 --sort popularity --days week \
  --min "liked_count>=500,collected_count>=100" \
  --exclude "广告,代运营" \
  --detail --detail-count 10 --comments-count 5 \
  --max-results 20 \
  --cookies "$COOKIES"
```

参数对照用户意图：

| 用户说 | 对应参数 | 说明 |
|---|---|---|
| "最近一周爆的" | `--days week` | 时间范围 |
| "按点赞排" | `--sort popularity` | 排序方式 |
| "只看视频" | `--note-type video` | 笔记类型 |
| "互动要超过 xxx" | `--min "liked_count>=500,..."` | 本地互动门槛 |
| "不要广告/带货" | `--exclude "广告,..."` | 标题/正文排除词 |
| "要看正文和评论区" | `--detail --detail-count 10` | 逐条补齐详情与评论 |

产出：`data/<日期>-<关键词>/sources.jsonl`。

### 2) 分析

分析脚本 `hotspot_analyze.py` 直接调用配置的大模型 API（DeepSeek / GPT / Kimi / Claude），**不需要跳转 Claude**：

```bash
# 第一次使用：复制配置模板并填写 API Key 环境变量名
cp xhs-hotspot-analysis/ai_config.example.json xhs-hotspot-analysis/ai_config.json
# 然后设置对应 key（以 DeepSeek 为例）
export DEEPSEEK_API_KEY="sk-..."

python xhs-hotspot-analysis/scripts/hotspot_analyze.py \
  --sources data/2026-08-05-AI工具/sources.jsonl \
  --context "账号画像：科技博主，粉丝10w"   # 可选，让分析回扣'适不适合我'
```

切换模型：`--provider gpt|kimi|claude|deepseek`（配置文件里可加任意 provider），`--model` 覆盖模型名。
输出 `analysis.md`（`--json` 时额外输出 `analysis.json`）。

### 3) 选题与行动

把品类爆款公式和 3–5 个可复刻选题整理给用户。如果用户提供了账号画像（粉丝画像/调性），
分析要回扣"适不适合我"；没提供就只做客观拆解。

## 工作流建议

- 搜索排序与时间范围是**平台搜索参数**（在采集层生效）；互动门槛和排除词是**本地过滤**（在采集脚本里生效）。
  两者都是"用户要求"的落点，先问清楚用户要什么，再组合。
- 采集默认不抓详情/评论（快）；要深入分析爆因时再开 `--detail`。
- 脚本退出码：0 成功，1 搜索失败/无结果，2 登录态无效。登录态无效时提示用户更新 Cookie。

## 已知边界

- 数据来自公开搜索接口，互动数字为接口返回值；部分笔记可能缺字段（如 `xsec_token` 时无法拉评论），分析时按"该字段未采集"处理，不要脑补。
- 详情接口（正文全文）可能被风控返回"当前笔记暂时无法浏览"，此时采集脚本会在 `detail` 字段标 `detail_unavailable: true`。**爆因分析在详情缺失时，只用 标题 + desc 摘要 + 互动结构 + 评论区 做拆解**，不要编造正文内容。
- 评论区接口通常可用，是"为什么爆"的最直接证据；采集 `--detail` 时会一并抓取。
- 仅供学习交流，请遵守小红书用户协议，控制采集频率与数量。
