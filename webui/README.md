# Spider_XHS WebUI

给 [Spider_XHS](https://github.com/cv-cat/Spider_XHS) 加的一个本地 Web 工作台，把小红书数据采集、达人筛选、内容发布等能力封装成可视化界面，无需改代码。

## 功能一览

| 页面 | 功能 |
|------|------|
| **采集** | 按关键词 / 用户主页 / 单篇笔记链接抓取内容，保存图片视频 + Excel，实时进度条 |
| **导出** | 把笔记导出为 Markdown + JSONL，方便喂给 AI / 知识库 |
| **达人** | 蒲公英 KOL 达人筛选（类目 / 粉丝数 / 性别 / 报价），看详情，导出 Excel / 写数据库 |
| **热点** | 采集候选爆文 + 调用大模型做热点分析（可选） |
| **历史** | 查看 / 打开 / 删除历次采集的 Excel、媒体、导出文件，支持批量删除 |
| **浏览** | 在线预览笔记、评论、用户主页，不落盘 |
| **账号** | 查看登录状态、粘贴 Cookie、扫码登录 |

## 环境要求

- Python 3.10+
- Node.js 20+（签名算法运行时需要）

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

# 可选：热点分析用的大模型 API key
DEEPSEEK_API_KEY=''

# 可选：达人数据写 PostgreSQL 时用
DATABASE_URL='postgresql://user:password@host:5432/dbname'
```

> `.env` 已被 gitignore，不会上传。蒲公英 Cookie 不需要手动填，在「达人」页面粘贴即可（存到本地 `datas/pgy_cookie.json`）。

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
4. 结果在 `datas/excel_datas/`（Excel）和 `datas/media_datas/`（图片视频）

### 导出（AI 知识库格式）

1. 进「导出」，选来源，填集合名称，勾选是否含评论
2. 点「开始导出」
3. 输出到 `datas/exports/<集合名>/`，含 `note_*.md` 和 `notes.jsonl`

### 达人筛选（蒲公英）

1. 登录 https://pgy.xiaohongshu.com 复制 Cookie（F12 → Network → 请求头里的 Cookie）
2. 进「达人」页，粘贴 Cookie → 「保存并验证」
3. 选内容类目（点一级类目展开子类目）、设粉丝数区间 / 性别等
4. 点「开始筛选」，自动抓取达人的阅读 / 互动中位数
5. 点「导出当前结果 Excel」或「只写数据库」

### 数据库同步（可选）

数据库需存在 `SocialCreator`、`SocialNote` 两张表（多平台达人 / 笔记通用表）。达人页勾选「只写数据库」即可把达人 + 笔记正文直接写入，按 `platformUserId` 去重更新。

### 账号

- 粘贴 Cookie 保存并验证
- 或点「生成二维码」用小红书 App 扫码登录

## 目录结构

```
webui/
├── app.py              # FastAPI 入口 + 路由
├── tasks.py            # 后台任务（采集 / 导出 / 写库 / 补全）+ 进度
├── login_bridge.py     # 账号状态 / Cookie / 扫码登录
├── pgy_talents.py      # 蒲公英达人筛选、详情、导出
├── pgy_routes.py       # 蒲公英相关 API 路由
├── pg_sync.py          # 达人 / 笔记写 PostgreSQL
├── pg_convert.py       # 蒲公英原始数据 → 数据库格式转换
├── pg_backfill.py      # 补拉缺失的笔记正文
├── hotspot_routes.py   # 热点采集 + LLM 分析
├── datas_api.py        # 数据目录浏览 / 删除
├── exporters.py        # Markdown + JSONL 导出
└── static/index.html   # 单页前端（内嵌 CSS/JS）
```

## 常见问题

- **采集返回空 / 报错**：`xsec_token` 会过期，重新从网页复制笔记链接；或 Cookie 失效，重新登录。
- **蒲公英搜索返回空**：平台接口偶发限流，等十几分钟再试，或重新登录蒲公英刷新 Cookie。
- **推送 / 写入报权限错误**：检查 `.env` 里的 `COOKIES` 或 `DATABASE_URL` 是否正确。

## 说明

本项目基于 [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS)，仅供学习交流使用，请勿用于任何商业用途。
