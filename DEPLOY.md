# 自动发布到 GitHub Pages（"打开即最新"方案）

## 为什么要换发布目标

原来的 `workbuddy.host` 链接由沙箱里的 `publish.js` 发布，它依赖沙箱专属的
`agentos` 运行时（`requireRuntimeId` / `createArtifactRelease`）——**外部 CI
（GitHub Actions）无法复刻这一步**，也没有对应凭证。因此"每天自动抓取并发布到
`workbuddy.host`"在纯外部调度下做不到。

OT T看板本身是纯静态站（`index.html` + `data.js` + 图标），天然适合托管在
**GitHub Pages**。把抓取调度放进去后，站点每天 06:17（北京时间）由 Actions
自己更新，不依赖沙箱、不依赖人工——这才是真正"打开即最新"。

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
4. 完成。此后每天 06:17（北京时间）自动跑；也可在 Actions 页面点
   **Run workflow** 手动触发测试。

## 工作流做了什么

| 步骤 | 说明 |
|---|---|
| `schedule: '17 22 * * *'` | UTC 22:17 = 北京时间次日 06:17（刻意避开整点排队） |
| 安装依赖 | `requirements.txt`（bs4 + playwright）+ `playwright install chromium` |
| 跑管道 | `pipeline/run_pipeline.sh` → 抓取 → AI 处理 → 导出 `data.js` |
| 组装站点 | `pipeline/build_site.sh` → 产出 `site/`（并替换 `@@BUILD@@` 强制刷新缓存） |
| 提交历史 | 仅当 `data.js` 变化时才提交，保留每日数据快照 |
| 部署 | `upload-pages-artifact` + `deploy-pages` |
| 失败告警 | 抓取失败时自动开一个 Issue 告警（不部署，保留上一版正常数据） |

## 已知风险

- **网络可达性**：GitHub 托管 Runner 位于境外，访问部分国内站点
  （广电总局、工信部、量子位等）可能偏慢或被限。若某次抓取失败，工作流
  **不会部署坏数据**，GitHub Pages 保留上一版正常内容；失败当天会开 Issue 提醒。
  若长期拉不动，可考虑换成境内 Runner 或放开来源白名单。
- **调度静默**：GitHub 对 60 天无活动的仓库会暂停定时任务。本项目长期有人看，
  一般不受影响；若发现停止，进 Actions 页手动触发一次即恢复。
- **时区**：cron 用 UTC，已换算为北京时间 06:17；如需调整改 `daily.yml` 里的
  `cron` 表达式即可。
