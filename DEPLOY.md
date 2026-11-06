# 自动发布到 GitHub Pages（"打开即最新"方案）

## 为什么要换发布目标

原来的 `workbuddy.host` 链接由沙箱里的 `publish.js` 发布，它依赖沙箱专属的
`agentos` 运行时（`requireRuntimeId` / `createArtifactRelease`）——**外部 CI
（GitHub Actions）无法复刻这一步**，也没有对应凭证。因此"每天自动抓取并发布到
`workbuddy.host`"在纯外部调度下做不到。

OT T看板本身是纯静态站（`index.html` + `data.js` + 图标），天然适合托管在
**GitHub Pages**。把抓取调度放进去后，站点每天清晨由 Actions 自己更新，
不依赖沙箱、不依赖人工——这才是真正"打开即最新"。

抓取采用**状态驱动的自愈调度**：一天有多个触发机会，每次先检查 `data.js` 是否
已是「北京时间今天」，是则秒跳，否则立即补抓。GitHub 的定时任务是尽力而为的
（官方明确说明高负载时排队任务可能被丢弃），单靠一个 cron 无法保证准点。

> `workbuddy.host` 链接仍保留为**手动镜像**：需要时喊我（`publish.js`）重新发布一次即可，
> 但它不会再自动更新。

## 首次接入（一次性）

1. 在 GitHub 新建一个空仓库（如 `ott-dashboard`）。
2. 在本项目目录执行：
   ```bash
   git init
   git add -A
   git commit -m "init: OTT 看板 + 每日自动抓取工作流"
   git remote add origin git@github.com:<你的用户名>/ott-dashboard.git
   git push -u origin main
   ```
3. 仓库 → **Settings → Pages → Build and deployment → Source** 选择
   **GitHub Actions**。
4. 完成。此后每天清晨自动抓取、漏跑自动补抓；也可在 Actions 页面点
   **Run workflow** 手动触发测试。

## 工作流做了什么

| 步骤 | 说明 |
|---|---|
| 触发机会 | 北京时间 06:17 主任务；06:43～11:43 每小时看门狗；14:23 下午兜底，共 8 次/天 |
| 守卫 | 读 `data.js` 的 `generated_at`，已是「北京时间今天」→ 跳过全部重步骤（约 10 秒）；否则补抓。`workflow_dispatch` / 配置 push 强制抓取 |
| 安装依赖 | `requirements.txt`（bs4 + playwright）+ `playwright install chromium` |
| 跑管道 | `pipeline/run_pipeline.sh` → 抓取 → 正文摘录 → 内容摘要 → 导出 `data.js` |
| 组装站点 | `pipeline/build_site.sh` → 产出 `site/`（并替换 `@@BUILD@@` 强制刷新缓存） |
| 提交历史 | 仅当 `data.js` 变化时才提交，保留每日数据快照 |
| 部署 | `upload-pages-artifact` + `deploy-pages`；跳过抓取时 deploy 一并跳过，不覆盖旧产物 |
| 失败告警 | 抓取失败时自动开 Issue（不部署，保留上一版正常数据） |
| 漏跑告警 | 数据超过 30 小时未更新时自动开 Issue，覆盖「任务根本没启动」的静默漏跑 |

## 订阅源管理（零令牌 · 只读）

页面是**纯只读**的：不携带任何凭证、不调用 GitHub API。配置唯一权威来源是仓库里的
`pipeline/sources.json`，`build_site.sh` 在构建时生成 `site/sources.js` 供前端读取。

需要新增、停用或修改信源时，在 GitHub 网页编辑 `pipeline/sources.json` 并提交到
`main`（或提 PR 评审）。工作流配了 `on: push: paths: ['pipeline/sources.json']`，
**推上去就自动重抓并重建站点**，全程无需令牌、有 commit 记录、可 Revert。

行为约定：

- 面板展示每个源的真实抓取状态与最近抓取时间，不提供写回入口。
- 抓取频率只有**每日一档**（清晨主任务 + 漏跑补抓）；面板不提供每小时 / 实时监控等无法落地的选项。
- **关键词规则目前仅作本地备注**，管道不读取（要生效需扩展 `ai_process.py`）。
- **新增源 ≠ 一定抓得到**：管道用通用链接解析器，SPA / 反爬 / 特殊 DOM 可能返回
  `empty`，需人工验收；复杂站点要在 `crawl.py` 里补 adapter。
- 不采用「共用 PAT」方案：classic `repo` 是账号级全部仓库读写权限，静态 Pages
  的前端代码谁都能查看，写进去等于公开整个 GitHub 账号。

## 已知风险

- **网络可达性**：GitHub 托管 Runner 位于境外，访问部分国内站点
  （广电总局、工信部、量子位等）可能偏慢或被限。若某次抓取失败，工作流
  **不会部署坏数据**，GitHub Pages 保留上一版正常内容；失败当天会开 Issue 提醒。
  若长期拉不动，可考虑换成境内 Runner 或放开来源白名单。
- **调度语义**：GitHub 官方写明 `schedule` 在 Actions 高负载时可能延迟数小时，
  排队任务甚至可能被直接丢弃（"some queued jobs may be dropped"）。实测 2026-11-05
  晚 3h52m，2026-11-06 整天未启动。现在的自愈调度把「一次命中」变成「一天 8 次机会 +
  抓过就跳过」，正常当天只真正抓一次；只有连续漏跑才会出现多条运行记录。
- **仍非 100%**：这是 GitHub 平台内的最优解，但平台级故障理论上仍可能让所有定时同时失效。
  需要 SLA 级保证时，可在外部加一个定时触发器（如 Cloudflare Workers Cron）调用
  `workflow_dispatch`，凭证只放在服务端环境变量，用户与页面均不接触。
- **60 天规则**：GitHub 对 60 天无活动的仓库会暂停定时任务；本项目长期有人看，不受影响。
- **时区**：cron 用 UTC，已换算为北京时间；`generated_at` 统一 UTC 带 `Z`，
  守卫按北京时间日期判断「今天」。
