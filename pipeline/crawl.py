#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTT 行业资讯聚合 · 抓取器
合规原则：
  1. 仅抓取公开列表页 / 公开接口，不登录、不绕付费墙、不采集个人隐私
  2. 遵守 robots 协议（robots 禁止的路径自动跳过）
  3. 每条记录保留原始链接 + 真实发布时间，抓不到时间就标「待补充」，绝不编造
"""
import json, re, ssl, time, hashlib, urllib.request, urllib.robotparser
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from pathlib import Path


def utc_stamp():
    """统一输出 UTC 绝对时刻（带 Z），避免浏览器把无时区的时间串按本地时区误读。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

import asyncio
from bs4 import BeautifulSoup

BASE = Path(__file__).parent
OUT = BASE / "data"
OUT.mkdir(exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# ---------- robots 缓存 ----------
_rp_cache = {}
def _load_rp(origin):
    """自己拉 robots.txt：404 / 非纯文本 / 空内容 均视为「无规则」→ 允许"""
    try:
        raw = http_get(origin + "/robots.txt", timeout=12)
        text = raw.decode("utf-8", "ignore")
        if "<html" in text.lower()[:200] or "Disallow" not in text and "User-agent" not in text:
            return None
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(text.splitlines())
        return rp
    except Exception:
        return None

def robots_allowed(url):
    try:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in _rp_cache:
            _rp_cache[origin] = _load_rp(origin)
        rp = _rp_cache[origin]
        if rp is None:
            return True
        return rp.can_fetch(UA, url)
    except Exception:
        return True

def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()

# ---------- 工具 ----------
DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")

def norm_date(s):
    """把各种日期串规范为 YYYY-MM-DD；失败返回 None（→ 待补充）"""
    if not s:
        return None
    m = DATE_RE.search(str(s))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (2020 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"

def fingerprint(title, url):
    key = (re.sub(r"\s+", "", title) + "|" + (url or ""))[:200]
    return hashlib.md5(key.encode("utf-8")).hexdigest()

AD_RE = re.compile(r"(广告|推广|赞助|优惠券|领红包|下载APP|点击下载|抽奖|福利|报名通道|立即购买|招商加盟)")

def is_ad(title):
    return bool(AD_RE.search(title or ""))

def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

# 导航 / 栏目类噪声链接（不是资讯正文）
NAV_RE = re.compile(r"^(首页|登录|注册|更多|详情|查看|上一页|下一页|返回|关于我们|联系我们|"
                    r"备案公示查询|版权声明|网站地图|广告服务|招聘|下载|客户端)")
NAV_CONTAIN = re.compile(r"(备案公示查询|京ICP|公网安备|ICP备|Copyright|©|登录|注册|返回顶部)")

def is_nav(title):
    if NAV_RE.match(title):
        return True
    if NAV_CONTAIN.search(title):
        return True
    return False

def find_date_near(a, max_up=4):
    """从链接自身或其祖先容器里找日期；返回 YYYY-MM-DD 或 None"""
    d = norm_date(a.get_text(" ", strip=True))
    if d:
        return d
    p = a
    for _ in range(max_up):
        p = p.parent
        if p is None:
            break
        txt = clean(p.get_text(" ", strip=True))
        if len(txt) > 400:      # 容器太大，说明是整页，停止
            break
        d = norm_date(txt)
        if d:
            return d
    return None

def collect_links(html, base, min_len=12, same_host=True):
    """列表页抽取：优先锁定「文章列表容器」，避免把导航栏当资讯"""
    soup = BeautifulSoup(html, "html.parser")
    bhost = urlparse(base).netloc
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        title = clean(a.get_text(" ", strip=True))
        # 去掉列表项自带的角标文字
        title = re.sub(r"^(NEW|新|更新|置顶|热点|推荐|Top Story|调查)\s*[：:｜|]?\s*", "", title)
        title = clean(title)
        if len(title) < min_len:
            continue
        if len(re.findall(r"[\u4e00-\u9fa5]", title)) < 6:
            continue
        if is_nav(title):
            continue
        title_date = norm_date(title)
        if title_date:
            title = clean(DATE_RE.sub("", title)).strip(" -|·,，")
            if len(title) < 8:
                continue
        href = urljoin(base, a["href"])
        if not href.startswith("http"):
            continue
        if same_host and urlparse(href).netloc.replace("www.", "") != bhost.replace("www.", ""):
            continue
        # 只收「详情页」形态的链接：路径含长串数字 ID
        if not re.search(r"(\d{5,}\.s?html?|detail/id/\d+|/article/\d+|art_\w+)", href):
            continue
        if href in seen:
            continue
        seen.add(href)
        # URL 里内嵌日期（如 /202610/ 或 /2026/10/）是可靠的发布年月来源
        url_date = None
        m = re.search(r"/(20\d{2})[-/]?(\d{2})[-/]", href)
        if m:
            ym = f"{m.group(1)}-{m.group(2)}-01"
            url_date = ym  # 精确到月，日标待补充
        out.append({
            "title": title,
            "url": href,
            "published_at": title_date or find_date_near(a) or url_date or "待补充",
            "date_precision": "day" if (title_date or find_date_near(a)) else ("month" if url_date else "none"),
        })
    return out

# ---------- 各引擎 ----------
async def fetch_browser(url):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await b.new_context(user_agent=UA, locale="zh-CN")
        pg = await ctx.new_page()
        try:
            await pg.goto(url, timeout=45000, wait_until="networkidle")
        except Exception:
            try:
                await pg.goto(url, timeout=45000, wait_until="domcontentloaded")
            except Exception:
                pass
        await pg.wait_for_timeout(3000)
        html = await pg.content()
        await b.close()
        return html

def fetch_avc(src):
    """奥维云网 JSON 接口"""
    raw = http_get(src["list_url"])
    d = json.loads(raw.decode("utf-8"))
    items = d.get("data") or []
    out = []
    for it in items:
        title = clean(it.get("title"))
        if not title:
            continue
        out.append({
            "title": title,
            "url": src["detail_url"].format(id=it["id"]),
            "published_at": norm_date(it.get("createTime")) or "待补充",
            "heat_raw": it.get("realCnt") or it.get("showCnt") or 0,
            "author": it.get("author") or "",
        })
    return out

def crawl_paged_static(src):
    """栏目翻页抓取：index_2.html / index_3.html ...（adapter 见 sources.json 的 pages 字段）"""
    base_url = src["list_url"].rstrip("/")
    pages = int(src.get("pages", 1))
    all_items, seen = [], set()
    for p in range(1, pages + 1):
        url = base_url if p == 1 else f"{base_url}/index_{p}.html"
        if not robots_allowed(url):
            break
        try:
            html = http_get(url).decode("utf-8", "ignore")
        except Exception:
            break
        items = collect_links(html, url)
        added = 0
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            all_items.append(it)
            added += 1
        if added == 0:      # 没有新内容，停止翻页
            break
    return all_items

# ---------- 主流程 ----------
async def crawl_source(src):
    res = {"id": src["id"], "name": src["name"], "cat": src["cat"],
           "type": src["type"], "freq": src["freq"],
           "list_url": src["list_url"], "items": [],
           "status": "ok", "error": "", "fetched_at": utc_stamp()}
    if not src.get("enabled"):
        res["status"] = "paused"
        res["error"] = "已停用"
        return res
    if not robots_allowed(src["list_url"]):
        res["status"] = "blocked"
        res["error"] = "robots.txt 不允许抓取，已跳过"
        return res
    try:
        eng = src.get("engine", "static")
        if eng == "json":
            items = fetch_avc(src)
        elif eng == "browser":
            html = await fetch_browser(src["list_url"])
            items = collect_links(html, src["list_url"])
        elif eng == "static" and int(src.get("pages", 1)) > 1:
            items = crawl_paged_static(src)
        else:
            html = http_get(src["list_url"]).decode("utf-8", "ignore")
            items = collect_links(html, src["list_url"])
        # 过滤广告与过短标题
        items = [x for x in items if not is_ad(x["title"])]
        res["items"] = items[: int(src.get("max_items", 40))]
        if not items:
            res["status"] = "empty"
            res["error"] = "页面可访问但未解析到条目（可能改版，需更新选择器）"
    except Exception as e:
        res["status"] = "error"
        res["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return res

async def main():
    cfg = json.loads((BASE / "sources.json").read_text(encoding="utf-8"))
    srcs = cfg["sources"]
    # 并发但有节流：静态/JSON 并发跑，browser 串行（吃内存）
    light = [s for s in srcs if s.get("engine") != "browser"]
    heavy = [s for s in srcs if s.get("engine") == "browser"]
    tasks = [crawl_source(s) for s in light]
    results = await asyncio.gather(*tasks)
    for s in heavy:
        results.append(await crawl_source(s))
    payload = {
        "generated_at": utc_stamp(),
        "source_count": len(results),
        "ok_count": sum(1 for r in results if r["status"] == "ok"),
        "total_items": sum(len(r["items"]) for r in results),
        "sources": list(results),
    }
    (OUT / "raw.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"抓取完成 {payload['generated_at']}")
    print(f"成功 {payload['ok_count']}/{payload['source_count']}，共 {payload['total_items']} 条\n")
    for r in results:
        flag = "OK " if r["status"] == "ok" else "ERR"
        print(f"[{flag}] {r['name']:16} {len(r['items']):3} 条  {r['error']}")
        for it in r["items"][:2]:
            print(f"       · {it['published_at']}  {it['title'][:52]}")

if __name__ == "__main__":
    asyncio.run(main())
