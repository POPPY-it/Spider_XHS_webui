# Spider_XHS · WebUI 工作台

一个基于 [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS) 的本地小红书数据工作台，把采集、评论、内容分析、达人筛选等能力封装成可视化界面。主打**让数据变成可用的运营洞察**：不只是抓数据，还能自动算爆款潜力、用 AI 读懂评论、生成可复刻的选题。

> 仅供学习交流使用，请勿用于任何商业用途。
> 感谢原作者 [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS) 的开源工作。

## 功能一览

| 页面 | 功能 |
|------|------|
| **采集** | 按关键词 / 用户主页 / 单篇笔记抓取，保存图片视频 + Excel，实时进度条 |
| **导出** | 导出 Markdown + JSONL，可含评论，方便喂给 AI / 知识库 |
| **评论补抓** | 对已导出但缺评论的笔记，只补评论（自动跳过已有，含楼中楼） |
| **达人** | 蒲公英 KOL 筛选（类目 / 粉丝 / 性别 / 报价），看详情，导出 Excel / 写库 |
| **助手** | 内置对话 Agent，用自然语言驱动采集 / 达人查询 |
| **历史** | 查看 / 打开 / 删除历次采集的 Excel、媒体、导出文件 |
| **浏览** | 在线预览笔记、评论、用户主页，不落盘 |
| **热点分析** | 多词下钻候选爆文 → 低粉爆款优先 → 爆款潜力评分卡 → AI 拆解"为什么爆" + 跨品类迁移建议 |
| **数据仪表盘** | 笔记 / 评论 / 达人数据的可视化看板（可切换账号集合） |
| **评论洞察** | 用 DeepSeek 分批分析评论：分类 / 情绪 / 高频话题 / 负面舆情列表 |
| **账号** | 查看登录态、粘贴 Cookie / 扫码登录 / **从本机 Chrome 一键导入**（会话过期快速续期） |

## 核心亮点

- **可解释的爆款潜力分**：特征工程（互动率 / 收藏率 / 评论率 / 分享率 / 标题钩子 / 爆发信号 / 标签数）在批次内归一为百分位加权求和，给每条候选 0-100 分，取代 LLM"感觉"打分，可复现。
- **低粉爆款优先**：自动取作者粉丝，按"互动/粉丝比"排序并打标，优先找到粉丝少但数据高、可复制的内容。
- **多词下钻 + 跨品类迁移**：一次用多个细分词聚合候选；目标品类想找却没爆款时，AI 给出"这批爆款结构怎么迁到你的品类"。
- **AI 评论洞察**：把评论批量读懂，输出用户高频问题、情绪分布、负面舆情清单（最值得品牌回应）。
- **一键续期登录**：会话过期后从本机 Chrome 一键导入新 Cookie，不用手动复制。

## 环境要求

- Python 3.10+
- Node.js 20+（签名算法运行时需要）
- 需要能访问 `github.com` 或本机网络代理（见常见问题）

## 安装

```bash
pip install -r requirements.txt
npm install
```

## 配置

在项目根目录创建 `.env`（复制 `.env.example`）：

```bash
# 小红书 PC 端登录 Cookie（采集 / 浏览用）
COOKIES='你的完整Cookie'

# 热点分析、评论洞察用的大模型 API key
DEEPSEEK_API_KEY=''

# 可选：达人数据写 PostgreSQL 时用
DATABASE_URL='postgresql://user:password@host:5432/dbname'
```

> `.env` 已被 gitignore，不会上传。
> `COOKIES` 可在「账号」页粘贴、扫码登录，或点「从 Chrome 一键导入」（读取本机 Chrome 的小红书 Cookie，需先在 Chrome 登录）。

## 启动

```bash
python -m uvicorn webui.app:app --port 8000
```

打开浏览器访问 http://127.0.0.1:8000

## 各页面用法

### 采集
1. 侧边栏进「采集」，选来源：关键词搜索 / 用户全部笔记 / 单篇笔记
2. 填关键词或链接，选保存方式（全部 / 仅媒体 / 仅 Excel）
3. 点「开始采集」，进度条实时显示
4. 结果在 `datas/excel_datas/`、`datas/media_datas/`

### 评论补抓
对已导出但评论为空的笔记，只补评论（自动跳过已有、含楼中楼）：
```bash
python -m webui.backfill_comments 集合名
```
默认集合：`datas/exports/Friso美素佳儿香港版`（也可在脚本里指定其他集合）。评论接口有限频，脚本带自适应退避 + 会话过期自动中止。

### 热点分析（动作驱动单页）
1. 进「热点分析」，填**多关键词**（逗号分隔，可填多个细分词）、**目标品类**（可选，用于跨品类迁移建议）
2. 勾选「低粉爆款优先」→ 点「开始采集」
3. 采集完成自动展开结果显示，每条带「**爆款潜力分**」+ 低粉爆款标记 + 互动/粉丝比
4. 点某条看小红书样式详情（图九宫格 / 视频封面、互动条、评论）
5. 点「AI 分析」→ 报告自动展开：逐条 A/B 标签（内容形态 × 爆款机制）、三条共性分布线、三张清单（可复用 / 不可复用 / 平台适配），目标品类不同则追加跨品类迁移建议。

### 数据仪表盘
进「数据仪表盘」，顶部选要分析的账号集合 → 4 张 KPI 卡 + 多张图表（笔记/评论趋势、互动 Top、评论高频用户、达人类型/性别/地区/粉丝/报价分布）。

### 评论洞察
1. 进「评论洞察」，选集合 →「开始分析」
2. DeepSeek 分批给评论打标签（问题咨询 / 购买意向 / 产品评价 / 负面舆情 / 其他 + 正面/中性/负面 + 主题词）
3. 得到：分类分布、情绪分布、高频话题、每类代表评论、负面舆情列表（需关注回应）。结果缓存，可快速回看。

### 达人筛选（蒲公英）
1. 登录 https://pgy.xiaohongshu.com 复制 Cookie（F12 → Network → 请求头 Cookie）
2. 达人页粘贴 Cookie → 保存并验证
3. 设类目 / 粉丝区间 / 性别等 → 开始筛选（自动抓阅读 / 互动中位数）
4. 导出 Excel 或只写数据库

### 账号
- 粘贴 Cookie 保存并验证
- 或生成二维码 / 浏览器扫码登录
- 或「**从 Chrome 一键导入**」（会话过期后的最快续期方式）

## 目录结构

```
webui/
├── app.py                    # FastAPI 入口 + 路由 + /static 挂载
├── tasks.py                  # 后台任务（采集/导出/写库/热点/评论分析）+ 进度
├── login_bridge.py           # 账号状态 / Cookie / 扫码登录 / 游客会话校验
├── import_chrome_cookie.py   # 从本机 Chrome 导入小红书 Cookie
├── backfill_comments.py      # 评论补抓（限频退避 + 过期中止）
├── viral_score.py            # 爆款潜力评分卡（特征工程 + 百分位加权）
├── comment_analyze.py        # AI 评论洞察（DeepSeek 分批标签 + 聚合）
├── dashboard_api.py          # 数据仪表盘聚合（笔记/评论/达人）
├── dashboard_routes.py       # 仪表盘 API 路由
├── hotspot_routes.py         # 热点采集（多词/低粉）+ LLM 分析
├── pgy_talents.py / pgy_routes.py   # 蒲公英达人筛选、详情、导出
├── pg_sync.py / pg_convert.py / pg_backfill.py  # PostgreSQL 写库
├── datas_api.py              # 数据目录浏览 / 删除
├── exporters.py              # Markdown + JSONL 导出
├── agent.py                  # 对话 Agent
└── static/
    ├── index.html            # 单页前端（HTML）
    ├── app.js                # 前端逻辑
    ├── style.css             # 样式
    ├── echarts.min.js        # 本地化图表库（离线可用）
    └── qr_login.png
tests/                        # pytest 单元测试
xhs-hotspot-analysis/         # 热点分析脚本 + 拆解框架 + 爆款共性提取方法论
```

## 测试

```bash
python -m pytest tests/ -q
```

## 常见问题

- **采集返回空 / 报错**：`xsec_token` 会过期，重新从网页复制链接；或 Cookie 失效，重新登录（可点「一键从 Chrome 导入」）。
- **热点采集搜索无结果**：多为限频或词太刁钻，换几个细分词 / 稍等再试。
- **push 到 git 失败**：本机需能访问 `github.com`；若直连被网络限制，配置 git 走代理（`git config http.proxy http://你的代理` 或临时 `git -c http.proxy=... push`）。
- **评论洞察长时间无结果**：DeepSeek 调用量大（数千条评论分批），等 1-2 分钟；检查 `.env` 的 `DEEPSEEK_API_KEY`。
- **蒲公英搜索返回空**：平台接口偶发限流，等十几分钟再试，或重新登录蒲公英刷新 Cookie。
