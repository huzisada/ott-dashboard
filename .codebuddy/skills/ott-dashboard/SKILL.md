---
name: ott-dashboard
description: "OTT 行业资讯看板的发版 / 排障 / 早报运维。当用户要求改前端、上线、发布、修数据、查抓取、开关 LLM、配企业微信推送时使用。关键词：看板上线、发版、改动发布、数据丢失、竞品数据、早报、企业微信、DeepSeek"
version: "1.0.0"
author: "WorkBuddy"
created: "2026-11-17"
---

# OTT 看板发版与运维

> 项目根：`/workspace/ott-dashboard-src`　线上：https://huzisada.github.io/ott-dashboard/
> 本 skill 只记录**这套项目特有的约束和流程**，通用能力不重复描述。

## 铁律（每条都踩过坑）

1. **`git push` 在本沙箱 443 不通**。所有改动必须走 GitHub API 推送脚本：
   `cd /tmp && python3 push_api.py "提交信息" <相对路径>…`
   脚本内部走 blobs → trees → commits → PATCH refs。
2. **PAT 只有 `repo` scope，没有 `workflow` scope**。任何对
   `.github/workflows/daily.yml` 的写入都会被 API 返回 404。
   工作流改动只能由用户在仓库网页手工粘贴，或由用户另给带 `workflow` 权限的令牌。
3. **仓库是公开的**。Webhook、CorpSecret、API key 一律不写入仓库，
   只从环境变量 / GitHub Secret 注入。`pipeline/llm_key.txt` 已在历史中，
   提醒用户作废重发。
4. **纯前端改动不会自动触发部署**。`daily.yml` 的 push.paths 只匹配
   `pipeline/sources.json`，推完 `index.html` 后必须手动 dispatch：
   `curl -s -X POST -H "Authorization: token $PAT" -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/huzisada/ott-dashboard/actions/workflows/daily.yml/dispatches -d '{"ref":"main"}'`
5. **LLM 默认暂停**。`pipeline/llm_config.json` 的 `enabled` 由用户单独控制，
   未得到明确「开启」指令不得改为 true。改 key 不等于开启。
6. **数据戳一致性**：`summary.json` 的 `data_stamp` 必须等于 `data.js` 的
   `meta.generated_at`，否则前端回退规则版总结。这是刻意设计，不要「修掉」。
7. **别在 CI 抓取运行期间用 API 推同一个 ref**。`daily.yml` 最后一步会把新
   `data.js` 用 `git commit && git push` 回写 main；如果期间 API 推过 main，
   CI 本地仓库落后远端，这一步会 `[rejected] (fetch first)` 导致整个 run 报
   `failure`。但抓取 / 构建 / Pages 部署往往已经成功，线上 `data.js` 是新的。
   判别方法：拉线上 `data.js` 的 `generated_at` 和各源条数，若为新数据则只是
   「内部记账步骤失败」，看板不受影响，向用户如实说明即可，不要盲目重跑。
   要么等 workflow 完成后再推配置，要么推完立刻重新 dispatch，宁可多跑一次。

## 前端改动标准流程

```
1. 改 index.html
2. 抽出内联 script 校验语法：
   python3 -c "import re;h=open('index.html',encoding='utf-8').read(); \
     open('/tmp/app.js','w').write('\n'.join(re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>',h,re.S)))"
   node --check /tmp/app.js
3. bash pipeline/build_site.sh
4. python3 -m http.server -d site 8099 起预览，用 Playwright 验三态：
   1440 宽屏 / 1024 中屏 / 390 手机，检查 pageerror、横向溢出、
   右栏展开与收起、各弹窗开关
5. cd /tmp && python3 push_api.py "…" index.html
6. 手动 dispatch 工作流，轮询到 conclusion=completed
7. 拉线上 index.html / data.js 复核，确认缓存已刷新
```

## 数据异常排查顺序

```
1. 拉线上与本地 data.js，比 meta.total / by_cat / source_ok / source_total
2. 逐源看 sources[] 的 status + error，定位是超时还是解析为空
3. 用 crawl.py 的 http_get + collect_links 直接探测列表页，
   判断「站点改版」还是「偶发抖动」
4. 本地重跑管道：cd pipeline && bash run_pipeline.sh /workspace/ott-dashboard-src
5. 推 data.js + 触发部署
```
已有防护：`crawl.py` 单源失败重试 3 次（2s/4s 退避）；
`export.py` 骤降守卫（低于上版 60% 则沿用旧 data.js 并打 `::warning::`）。
竞品卡片是按品牌关键词从媒体源聚合的，不是独立抓取——源挂了竞品会先清零。

## 全站总结分类（用户 2026-11-18 定稿）

- 四类固定为 **政策 / 数据 / 竞品 / 热点**，按此顺序展示。
- 规则版（前端 `index.html`）：`_dailySectionTitle()` 把 `item.cat` 映射为
  政策→政策、数据→数据、竞品→竞品、**行业→热点**（其余也归热点）；
  `AI_SECTION_ORDER=['政策','数据','竞品','热点']`。
  D 简报式标签配色 `data-cat` 用这四个新值，别改回旧的「行业数据/行业」。
  `title.split(' / ')` 兼容旧分类名；新名无斜杠时不重复显示标题文字。
- AI 版（`pipeline/summarize.py` 的 system prompt）：分节标题固定这四类按顺序，
  无材料则跳过、不自创分类。
- 数据里 `item.cat` 只有政策/数据/行业/竞品四种；card.cat 是另一套
  （政策/竞品/数据机构/行业媒体），不要用 card.cat 做总结分类。

## 每日早报 / 企业微信

- 生成：`python3 pipeline/daily_brief.py --out <path>`（DeepSeek 暂停时为规则版）
- 推送：`WECOM_WEBHOOK=… python3 pipeline/push_wecom.py --message <path>`
- 支持群机器人（Webhook URL）与应用消息（`WECOM_CORPID`/`CORPSECRET`/`AGENTID`）双通道，
  同批数据按 `push_state.json` 去重，`--force` 可重推
- 未配凭据时静默跳过，不阻断发布；CI 侧注入需要改 `daily.yml`（见铁律 2）

## 顶部横向导航布局（2026-11-18，左侧栏已删除）

- 用户要求「把左侧栏整个去掉」，确认方案「导航移到顶部」。
- `index.html` 已删除整个 `<aside class="sidebar">`，顶栏加 `.brand-mini`（OTT Insight），
  顶栏下方加 `<nav class="nav topnav" id="nav">` 横向标签栏（sticky top:64px，内部横向滚动）。
- 导航 JS 完全复用（id 仍是 `nav`）。当前 5 项：主页/竞品动态/行业数据/热点节目/政策动态。
  2026-11-18 用户框选要求删掉「AI 助手」「设置」两个导航项，以及顶栏右上角「公告」「设置」
  两个图标按钮——已删除。顶栏现只剩刷新 + 通知两个按钮。
- AI 助手全屏对话面板：桌面端唯一入口本是导航「AI 助手」，删掉后桌面端无入口；
  但首页右侧「AI 助手·全站总结」面板（dailySide）仍常驻，日常 AI 总结不受影响。
  窄屏（≤860px）右下角竖排飞标 `.ai-tab` 仍可打开全屏面板。
  若要恢复桌面端入口，往 NAV 加回 `{id:'assistant',label:'AI 助手',icon:'bot'}` 即可。
- **不要删 `--sidebar-w` 变量**：已置 0px，被趋势弹窗（`.modal-trend`）和日报面板定位复用
  （`left:var(--sidebar-w)`、`width:calc(100vw - var(--sidebar-w))`），保留即全宽。
- 已清理死代码：`body.nav-mini{--sidebar-w:72px}`、`@media(860px){.sidebar{display:none}}`、
  JS 里的 `.sidebar .collapse` 收起逻辑。
- 2026-11-18 用户框选要求删掉 hero 区三个按钮：「资讯日报」(`btnDaily`)、「今日趋势」
  (`btnTrend`)、「导出竞品」(`btnExportComp`)。已删除 DOM 及三处 `.onclick` 绑定
  （`openTrend` / `dailyToggle` / 导出剪贴板逻辑留作死代码无害；`syncDailyBtn` 有 `if(!b)return`
  保护可保留）。hero `.actions` 现只剩「订阅源管理」(`btnSources`)。
- **AI 总结跟随视图（2026-11-18）**：用户要「切到竞品动态，AI 总结变竞品总结」。
  `SUMMARY_FOCUS` 把 activeNav 映射到演示数据 sections 分节名：
  competitor→竞品 / data→数据 / hot→热点 / policy→政策 / home→null(全站)。
  `summaryFocus()` 返回当前聚焦；`renderLLMDaily()` 按 focus 只渲染对应那一节
  （概览段保留但去掉【演示数据】前缀），角标 [n] 照常从 refs 解析可点；
  右栏标题随视图变「AI 助手 · XX总结」。规则版 `dailyBuild()` 也按 focus 过滤 pool。
  导航 click 里 `render()` 后调 `dailyBuild()` 触发重渲染（仅面板展开时）。
  注意：这是**内容联动**，与之前的**显隐不联动**不冲突——切视图不改展开/收起态，只换内容。
- **AI 全站总结右侧飞标（2026-11-18）**：删了 `btnDaily` 后，给右栏总结加了独立飞标
  `#dailyTab`（CSS `.daily-tab`，fixed right:0、竖排「AI 总结」+绿点）。
  `dailyClose()` 里显示飞标、`dailyOpen()` 里隐藏飞标；飞标 `onclick=dailyOpen()`。
  导航切换处已删除「切非首页自动 dailyClose(false)」的联动，切任何视图都保持当前展开/收起态。
  初始化 `setTimeout` 里补了收起态显示飞标。注意别把 `#dailyTab` 和窄屏的 `.ai-tab`
  （全屏 AI 助手飞标，右下角）搞混——两者上下分开、功能不同。
- 移动端 390px 曾横向溢出 18px（根因 `.topbar` 内容挤不下）：
  在 `@media(max-width:620px)` 收紧 topbar gap/padding、brand-mini 占位、tools gap、icon-btn 尺寸，
  并给 `.search` 加 `min-width:0`。已验证 1440/1024/390/320 四档零溢出、零 pageerror。

## 抓取记录抽屉（2026-11-18）

- 用户要求把标题下的抓取状态行（`今天是X / 政策源 / 数据源 / 抓取于`）挪到顶栏箭头处，
  做成「记录每次抓取的历史面板」。方案：管道侧累积历史 + 前端读 `data.js` 展示，
  而非前端轮询记录（页面不开会漏记）。
- **管道侧**：`pipeline/export.py` 的 `build_fetch_history(meta, sources)` 把本次摘要并入历史，
  写入 `payload['fetch_history']`（最多 `HISTORY_MAX=60` 条，按 `generated_at` 去重，新的置顶）。
  读上一版历史的来源是**仓库根 `data.js`**（`_read_prev_payload()`），因为 `run_pipeline.sh`
  导出后才 `cp` 到根、CI 会提交根 `data.js`——所以跨次能累积。每条字段：
  `at / total / with_date / pending_date / source_ok / source_total / policy_ok / policy_total / stale_filtered / dup_merged`。
  骤降守卫触发时沿用上一版原文，本次不入历史（符合「抓取失败不算一次成功抓取」）。
- **前端**：删了 hero 下的 `.meta` 状态行（连同 `renderDataStatus()` / `hoursSince()` 死代码）。
  顶栏 tools 加 `#btnFetchLog`（时钟图标，在刷新按钮左侧）；抽屉 `#fetchLogPanel`
  复用 `.notif-panel` 骨架 + `body.fetchlog-open` 控制显隐（z-index:61 盖过通知）。
  `renderFetchLog()` 读 `window.__OTT_DATA__.fetch_history` 渲染，每条显示完整时间、
  条数、源/政策源状态（异常橙色 `.warn`）、明细；首条标「最新」。
  两个抽屉互不干涉（2026-11-19 按用户要求撤销互斥）：最初加过「开记录关通知 +
  `btnBell.addEventListener` 点铃铛关记录」，用户觉得铃铛被改、要求回退，已全部移除。
  现在铃铛走原生 `btnBell.onclick`（toggle notif-open + renderNotif + notifMarkSeen），抓取记录独立开关。
- 本地预览：`pipeline/data/data.js` 和根 `data.js` 都已注入初始 1 条历史（2026-11-15 那批）。
  以后每次 CI 抓取会继续累积。验证过 1440/390 零溢出零报错。

## 主页卡片排序（2026-11-19）

- 用户要求主体内容模块按顶部导航顺序排列。`index.html` 加 `cardCatRank(c)`，
  `render()` 里 `cards.sort()` 稳定排序，顺序：竞品动态(cat 竞品/厂商动态) → 行业数据(数据机构/报告)
  → 热点节目(cat 热点节目 或 agg 聚合卡) → 政策 → 行业媒体(导航无对应分类，rank 4 兜底置后)。
  组内保持 data.js 原顺序（JS 稳定排序）。改的是主页展示顺序，不动 `export.py` 产出顺序。

## 热点节目分模块（2026-11-18）

- 顶部导航「热点节目」视图从单一 `HOT_CARD` 改为 `HOT_MODULES_CARDS` 多模块卡。
- `buildHotModules()` 复用热点筛选/去重逻辑，按 `HOT_MODULES` 里的 `re` 从
  标题+摘要+来源识别归属；未命中的归「综合热榜」兜底，一条不丢。
- 当前真实数据（34 条热榜）**不含视频平台字段**（爱奇艺0/优酷2/易视腾1，
  且这2/1条不在热榜子集里），所以平台模块为空不显示；实际显示的是渠道模块：
  央视收视 / 卫视收视 / 大屏点播 / 电影点播 / 综艺热榜 / 演员·角色热度。
- `matchNav()` 的 hot 分支按 `cat==='热点节目'` 放行所有模块卡（含旧 hot_program）。
- 用户若真要爱奇艺/优酷/易视腾分模块，需先给能标注平台字段的数据源，
  否则模块会全是空的——不要编造平台归属去填。

## 临时状态：线上挂了假 AI 总结（2026-11-18，待用户确认后撤回）

- 用户要求「放个假数据上去」看 AI 版样式，`pipeline/summary.json` 目前是
  **编造的演示数据**，带【演示数据·非真实AI生成】标识，四类分节 + 可点角标。
- 故意**不写 `data_stamp` 字段** → 前端 `llmSummary()` 跳过数据戳校验，
  CI 每天抓取更新 data.js 也不会让假总结失效；`llm_config.json` 仍 enabled=false，
  CI 不跑 summarize.py，不会覆盖这份假数据。
- **撤回方法**：把备份的 `/tmp/summary_before_fake.json` 覆盖回
  `pipeline/summary.json`（或直接删掉该文件），推送 + 重新 dispatch，
  前端即回退规则版。备份若丢失，可造一个只有 overview 无 data_stamp 的过渡文件。
- 用户真要启用 AI 时：给有效 key → summarize.py 生成带真实 data_stamp 的正常总结，
  会自动覆盖这份假数据。

## 待办清单（用户尚未确认的开放项）

- 企业微信 Webhook 地址：用户给地址后，从沙箱推一条验证，再谈自动化
- `pipeline/test_regression.py` 已过期：仍在找 `.item-deep` 和
  `#nav a[data-nav=daily]`，这两个元素已删除；需重写或删除
- 5 个源仍 `enabled:false`：`mgtv_mango xmedia yhqyg jgtv ystxds`
- 项目命名：建议「屏观」，未采纳（顶栏品牌现为「OTT Insight」）
- 今日重点速览已彻底删除（用户最终确认），不要再放回
