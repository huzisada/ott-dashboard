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

## 每日早报 / 企业微信

- 生成：`python3 pipeline/daily_brief.py --out <path>`（DeepSeek 暂停时为规则版）
- 推送：`WECOM_WEBHOOK=… python3 pipeline/push_wecom.py --message <path>`
- 支持群机器人（Webhook URL）与应用消息（`WECOM_CORPID`/`CORPSECRET`/`AGENTID`）双通道，
  同批数据按 `push_state.json` 去重，`--force` 可重推
- 未配凭据时静默跳过，不阻断发布；CI 侧注入需要改 `daily.yml`（见铁律 2）

## 待办清单（用户尚未确认的开放项）

- 企业微信 Webhook 地址：用户给地址后，从沙箱推一条验证，再谈自动化
- `pipeline/test_regression.py` 已过期：仍在找 `.item-deep` 和
  `#nav a[data-nav=daily]`，这两个元素已删除；需重写或删除
- 5 个源仍 `enabled:false`：`mgtv_mango xmedia yhqyg jgtv ystxds`
- 「去掉」指令歧义未决：截图里可能是整个速览块 / 上方统计条 / 速览灰字行
- 项目命名：建议「屏观」，未采纳；三处标题（侧栏 / tab / 主标题）未统一
