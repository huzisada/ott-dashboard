#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
正文摘录增强：为每条已抓取的资讯补一段原文内容，供「内容摘要」使用。

合规与可靠性原则：
  1) 只抓公开详情页，遵守 robots.txt；沿用 crawl.py 的 UA 与超时设置
  2) 失败一律留空并标注，绝不编造内容
  3) 站点通用介绍、投稿邮箱、导航文案等模板文本必须过滤，不能当正文
  4) 本步骤失败不阻断主管道（run_pipeline.sh 中以 || 跳过）
"""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from bs4 import BeautifulSoup
import crawl

BASE = Path(__file__).parent
RAW = BASE / "data" / "raw.json"
MAX_EXCERPT = 320          # 单条摘录上限（字符）
TIMEOUT = 8
WORKERS = 8

# 明显的模板/导航/页脚文案，命中即丢弃该段落
BAD = re.compile(
    r"(欢迎投递资讯|投稿|邮箱[:：]|tougao@|版权所有|ICP备|京公网安备|"
    r"登录|注册|扫描二维码|关注我们|上一篇|下一篇|相关阅读|责任编辑|"
    r"点击量|字体[:：]|打印本页|分享到|免责声明|未经授权|转载请注明|"
    r"网站首页|关于我们|联系我们|返回顶部)"
)
# 站点自我介绍型 meta description，不是本条资讯内容
SITE_INTRO = re.compile(
    r"^(流媒体网是|奥维云网[（(]|依马狮|.{0,8}是(专注于|一家|专业的)|"
    r".{0,10}(垂直媒体平台|大数据平台为核心))"
)
CONTAINERS = [
    "article", ".article-content", ".article_content", ".article", "#article",
    ".content", "#content", ".detail", ".detail-content", ".TRS_Editor",
    ".art_con", ".news_content", ".entry-content", ".post-content",
    ".text", "#zoom", "main",
]
SENT_END = re.compile(r"[。！？!?；;]")


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def usable(s):
    return 20 <= len(s) <= 600 and not BAD.search(s) and not SITE_INTRO.search(s)


def from_meta(soup):
    for attrs in (
        {"attrs": {"property": "og:description"}},
        {"attrs": {"name": "description"}},
        {"attrs": {"name": "Description"}},
    ):
        m = soup.find("meta", **attrs)
        if not m:
            continue
        v = clean(m.get("content", ""))
        if usable(v):
            return v
    return ""


def from_body(soup):
    # 优先锁定正文容器，减少导航栏/推荐位干扰
    for sel in CONTAINERS:
        node = soup.select_one(sel)
        if not node:
            continue
        ps = [clean(p.get_text(" ", strip=True)) for p in node.find_all("p")]
        ps = [p for p in ps if len(p) >= 25 and not BAD.search(p)]
        if ps:
            return trim(" ".join(ps))
    # 兜底：全页段落，过滤模板后取前几段
    ps = [clean(p.get_text(" ", strip=True)) for p in soup.find_all("p")]
    ps = [p for p in ps if len(p) >= 40 and not BAD.search(p) and not SITE_INTRO.search(p)]
    return trim(" ".join(ps[:4])) if ps else ""


def trim(s):
    """按句截断，不切碎句子；上限 320 字。"""
    s = clean(s)
    if len(s) <= MAX_EXCERPT:
        return s
    cut = s[:MAX_EXCERPT]
    m = list(SENT_END.finditer(cut))
    if m and m[-1].end() >= 60:
        return cut[:m[-1].end()]
    return cut.rstrip("，,、 ") + "…"


def fetch_one(item):
    url = (item.get("url") or "").strip()
    if not url.startswith("http"):
        return ""
    try:
        if not crawl.robots_allowed(url):
            return ""
        html = crawl.http_get(url, timeout=TIMEOUT).decode("utf-8", "ignore")
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return from_meta(soup) or from_body(soup)
    except Exception:
        return ""


def main():
    limit = 0
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except (ValueError, IndexError):
            pass
    data = json.loads(RAW.read_text(encoding="utf-8"))
    tasks = []
    for src in data.get("sources", []):
        for it in src.get("items", []):
            tasks.append(it)
    if limit and len(tasks) > limit:
        # 跨源均匀抽样，避免样本全落在第一个信源
        step = len(tasks) / limit
        tasks = [tasks[int(i * step)] for i in range(limit)]
    # 同一 URL 只抓一次
    uniq = {}
    for it in tasks:
        uniq.setdefault(it.get("url"), []).append(it)

    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_one, {"url": u}): u for u in uniq if u and u.startswith("http")}
        for f in as_completed(futs):
            u = futs[f]
            try:
                results[u] = f.result() or ""
            except Exception:
                results[u] = ""

    ok = 0
    for u, holders in uniq.items():
        text = results.get(u, "")
        for it in holders:
            it["excerpt"] = text
            it["excerpt_ok"] = bool(text)
        if text:
            ok += 1
    RAW.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    total = len(uniq)
    print(f"[enrich] 详情URL {total} 个，成功取得内容摘录 {ok} 个"
          f"（{ok / total * 100:.1f}%）" if total else "[enrich] 无待处理条目")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
