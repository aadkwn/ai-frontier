# AI Frontier · 极简 AI 前沿资讯网站

一套**能真正运行、能自动更新的静态 AI 新闻网站**：HTML + CSS + 原生 JavaScript 前端，Python 标准库采集，GitHub Actions 每小时运行，GitHub Pages 免费部署。**无需数据库、无需常驻服务器、无需付费 API Key。**

## 已实现的功能

- 四大栏目：**AI 公司动态、全球行业新闻、最新 AI 论文、开源生态**。
- 17 个数据源：OpenAI、Google DeepMind、Google AI、Mistral AI；TechCrunch、The Verge、Ars Technica、MIT News；arXiv cs.AI / cs.LG / cs.CV；Hugging Face Blog / Model Hub；GitHub vLLM / Transformers / Ollama / llama.cpp 发布动态。
- 每小时 **UTC 第 17 分钟**自动采集与部署；点击网页的刷新按钮只检查已经发布的 JSON，不会单独启动采集。静态网页每 5 分钟自动轮询一次数据。
- 根据**原文提供的发布时间**排序；使用更新时间（Atom `updated`）的文章会明确显示为“来源更新”，Hugging Face 模型使用创建时间并标注为“仓库创建”。没有可信时间的内容不会进入“最新新闻”。
- 来源链接追溯、去重、按时间/关键词/分类筛选、展示 24 小时发布量、数据源健康状态和失败原因。
- 首次访问建立浏览基准；以后出现未读新闻时显示站内消息提醒，支持标记已读。记录保存在**当前浏览器 localStorage**，不跨设备同步；关闭网页不会有推送。
- 支持深浅主题、响应式布局和 GitHub Pages 子路径。
- 无演示假新闻：首次启动时允许页面显示空状态，执行采集后才展示真实内容。

## 目录

```text
ai-frontier/
├─ site/                       # 部署此文件夹即可成为网页
│  ├─ index.html
│  ├─ styles.css
│  ├─ app.js
│  ├─ favicon.svg
│  ├─ .nojekyll
│  └─ data/news.json           # 脚本生成的真实数据，初始为空
├─ scripts/fetch_news.py       # 并发采集、日期核对、去重、错误处理、缓存
├─ tests/test_fetch_news.py    # 无网络单元测试
├─ .github/workflows/update.yml
├─ run_local.bat                # Windows 本地预览
└─ collect_local.bat            # Windows 手动采集
```

## A：先在 Windows 电脑本地运行

1. 安装 Python 3.10 或更新版本，确认 `py --version` 可用。
2. 解压项目文件夹，双击 `collect_local.bat`（需要网络）。它会将真实新闻写入 `site/data/news.json`。也可以在终端运行：

   ```powershell
   python scripts/fetch_news.py
   ```

3. 双击 `run_local.bat`，打开浏览器访问 **http://localhost:8000**。

   如果没有 `.bat`，在项目根目录运行：

   ```powershell
   python -m http.server 8000 --directory site
   ```

4. 如果只想查看页面结构，可以不采集，首页将如实显示「等待首次采集」的空状态。

**不要直接双击 `index.html` 打开**：浏览器会限制 `file://` 页面读取 JSON，因此应使用本地 HTTP 服务。

## B：部署到 GitHub Pages（推荐）

1. GitHub 创建一个**公开**仓库，例如 `ai-frontier`。将本目录中的所有文件上传到仓库 `main` 分支的根目录（确保 `.github/workflows/update.yml` 也上传）。命令行操作示例：

   ```bash
   git init
   git add .
   git commit -m "Initial AI Frontier website"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/ai-frontier.git
   git push -u origin main
   ```

2. 打开仓库 **Settings → Pages → Build and deployment → Source → GitHub Actions**。这里要选择 **GitHub Actions**，不要选择“Deploy from a branch”，因为定时任务使用 GITHUB_TOKEN 自动提交的数据不会触发分支模式的 Pages 构建。
3. 进入 **Actions → Update AI News → Run workflow**，手动触发第一次采集（上传后 push 触发也可以，但建议手动确认）。成功后检查 **Deploy to GitHub Pages** 步骤。
4. 网页地址一般为 **`https://YOUR_USERNAME.github.io/ai-frontier/`**。GitHub Pages 初次开启发布可能有短暂延迟。
5. 此后工作流在每小时 **17 分**（UTC，适用于任意时区的每小时一次）自动执行、采集、提交 `site/data/news.json`，并**在同一工作流中主动重新部署**网页。网页打开期间每 5 分钟检查更新后的 JSON。

如果仓库的 Actions token 不具备写入权限，检查 **Settings → Actions → General → Workflow permissions → Read and write permissions**（组织策略可能有额外限制）。即使数据提交失败，当前工作流仍会尝试部署采集结果，不过以后就不能依赖仓库中保存的旧新闻进行缓存恢复。

## C：运行自动测试

无需安装任何额外 Python 库：

```bash
python -m unittest discover -s tests -v
```

测试覆盖 RSS、Atom、日期格式、HTML 清洗、追踪参数去除、重复新闻、源失败后的缓存、Hugging Face 模型许可证筛选。

## 数据源、采集方法及限制

| 类别 | 采集范围 | 来源方式 |
|---|---|---|
| 公司动态 | OpenAI / DeepMind / Google AI / Mistral | 官方 RSS |
| 行业新闻 | TechCrunch / The Verge / Ars / MIT News | 媒体 AI 专栏 RSS |
| AI 论文 | arXiv cs.AI / cs.LG / cs.CV | arXiv RSS，假期可能没有新增 |
| 开源生态 | Hugging Face Blog / Models、GitHub 四个仓库的 Releases | RSS + 官方公开 API |

**重要区别**：GitHub 关注的是**选定项目的版本发布信息**，不是全 GitHub 的实时热榜。Hugging Face Models 通过官方公开 API 检索热门候选，只保留**模型创建时间可核实、近期创建、公开未门控且有常见开放许可证**的仓库；这并不表示本站对模型安全性或性能做过审核。博客中的文章标题保持原文，不自动机器翻译或凭空生成解读。

某些网站可能更改 RSS 地址、限制 GitHub Actions IP、使用反爬策略、出现 403/429、取消公开 feed。一个来源失败不会中断其他来源，状态面板会显示失败原因和已保存的文章。**每60分钟触发一次不代表在全球新闻发布后60分钟内必然收录**；延迟还取决于 RSS 更新和 GitHub 任务队列。

在 GitHub 的免费公开仓库，**60 天没有仓库活动时计划工作流可能会被自动禁用**。请偶尔进入 Actions 确认任务仍在运行。如所有来源连续失效，历史文章只保留设定的期限，页面会显示状态警告，不会伪装成新资讯。

### 维护与可修改项

- **添加新闻源**：编辑 `scripts/fetch_news.py` 的 `SOURCES` 列表，填入来源 id、名称、栏目、kind (`rss`/`hf_models`)、url。
- **改变抓取频率**：修改 `.github/workflows/update.yml` 的 `cron`（当前 `'17 * * * *'`，每小时一次）。
- **改变数据保留期限**：修改 `MAX_AGE_DAYS` 和 `CATEGORY_LIMIT`。
- **页面轮询间隔**：修改 `site/app.js` 的 `CHECK_EVERY_MS`（当前5分钟）。
- **自定义页面**：直接编辑 `site/index.html` 和 `site/styles.css`。

### 安全与版权

项目仅保存并展示标题、简短摘要和来源链接，不复制全文、也不下载媒体图片。外部链接使用 `noopener noreferrer`，使用 `textContent` 渲染 RSS 内容以避免脚本注入，不使用任何 API 密钥。数据源声明的发表时间可能被上游错误填写，本项目能校验格式与极端未来时间，但无法独立证明每条新闻内容的真实性。

## 当前交付的验证范围

**本地已运行代码和无网络单元测试**；真实 RSS/API 连通性需要首次在具有网络访问能力的本机或 GitHub Actions 环境执行。仓库上线前没有伪造实时采集结果。访问失败、限流和仓库策略权限都必须根据首次工作流日志处理。
