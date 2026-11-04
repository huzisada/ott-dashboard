#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTT 资讯 · AI 处理层（规则引擎版，无需外部 API）

职责：
  1. 去重（指纹 + 标题相似度）
  2. 过滤广告水稿
  3. 生成一句话摘要
  4. 按 政策 / 竞品 / 数据 / 行业 分类
  5. 溯源校验：无链接、无发布时间的记录如实标注，绝不编造

设计原则（对应项目「溯源防幻觉」要求）：
  - 摘要只做「原文标题的压缩/重组」，不引入标题之外的任何事实与数字
  - 原文明说「待补充」的字段，摘要里不允许出现具体数值
"""
import json, re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

BASE = Path(__file__).parent
CFG = json.loads((BASE / "sources.json").read_text(encoding="utf-8"))
KW = CFG["keywords"]

# ---------- 分类词典 ----------
# 说明：按「优先级 + 权重」打分，政策类要求更强的证据，避免把「通知」二字误判为政策
CAT_RULES = [
    ("政策", [
        (12, "广电总局"), (12, "工业和信息化部"), (10, "工信部"),
        (8, "管理办法"), (8, "套娃收费"), (8, "征求意见"), (7, "法规"), (7, "条例"),
        (6, "治理"), (6, "开机广告"), (6, "许可"), (5, "规划"), (5, "监管"),
        (5, "备案"), (4, "通知"), (4, "公示"), (4, "规范"), (4, "政策"),
    ]),
    ("竞品", [
        (10, b) for b in ["小米", "海信", "创维", "酷开", "芒果超媒", "新媒股份",
                          "银河奇异果", "极光TV", "云视听", "华为", "荣耀",
                          "爱奇艺", "腾讯视频", "优酷", "B站", "哔哩哔哩"]
    ] + [(3, "财报"), (3, "裁员")]),
    ("数据", [
        (8, "数据"), (8, "报告"), (7, "同比"), (7, "环比"), (7, "份额"),
        (7, "零售量"), (7, "零售额"), (7, "收视"), (6, "出货"), (6, "渗透率"),
        (6, "季报"), (6, "盘点"), (6, "监测"), (6, "榜单"), (6, "指数"),
        (5, "规模"), (5, "用户"), (5, "增长"), (5, "市场总结"), (4, "Top"),
    ]),
]

def classify(title):
    scores = {"政策": 0, "竞品": 0, "数据": 0}
    for cat, rules in CAT_RULES:
        for score, w in rules:
            if w in title:
                scores[cat] += score
    best = max(scores, key=scores.get)
    # 竞品必须由「品牌名」本身触发（品牌权重 >=10），避免「某会议+新品」误入竞品
    if best == "竞品" and scores["竞品"] < 10:
        best = "数据" if scores["数据"] >= 7 else "行业"
    return best if scores[best] >= 4 else "行业"

# ---------- 广告/水稿过滤 ----------
AD_PATTERNS = [
    r"(优惠券|红包|限时抢购|立即购买|招商加盟|代理招募|免费领取)",
    r"^(广告|推广)[:：]",
    r"(招聘|诚聘|招贤纳士)",
    r"(点击下载|扫码关注|关注公众号)$",
]
def is_spam(title):
    return any(re.search(p, title) for p in AD_PATTERNS)

# ---------- 摘要生成 ----------
# 去掉标题里的来源前缀，如「【奥维云网 2025-10】」
PREFIX_RE = re.compile(r"^【[^】]{1,20}】\s*")
TRAIL_RE = re.compile(r"\s*[-—|｜]\s*[^-—|｜]{0,12}$")

def make_summary(title, cat):
    """一句话摘要：只重组原标题信息，不添加新事实"""
    t = PREFIX_RE.sub("", title).strip()
    t = t.rstrip("？?！!。.，,")
    # 数字类标题保留原数字（来自原文），只做结构压缩
    if cat == "政策":
        issuer = ""
        for k in ("广电总局", "工业和信息化部", "工信部", "国务院"):
            if k in title:
                issuer = "工信部" if k == "工业和信息化部" else k
                break
        core = PREFIX_RE.sub("", title)
        # 剥掉机构名与「关于」，避免摘要变成「X发布：X关于…」的重复
        core = re.sub(r"^(国家广播电视总局|工业和信息化部|工信部)"
                      r"(办公厅|科技司|人事司|电视剧司|传媒机构管理司|规划司)?", "", core)
        core = re.sub(r"^关于", "", core).strip()
        core = re.sub(r"的通知$", "", core).strip()
        if issuer and issuer not in core:
            s = f"{issuer}：{core}"
        else:
            s = core or title
        return s[:78]
    if cat == "数据":
        return f"数据观察：{t}"[:78]
    if cat == "竞品":
        brand = next((b for b in KW["brands"] if b in title), "")
        return f"{brand + '相关：' if brand else '竞品动态：'}{t}"[:78]
    return f"{t}"[:78]

# ---------- 竞品「与我方差异」 ----------
DIFF_RULES = {
    "小米": "生态协同（人车家）与硬件性价比是其核心壁垒，我方需在单品体验上做差异化",
    "海信": "显示技术（ULED/MiniLED）与海外渠道领先，我方宜避开画质军备竞赛",
    "创维": "主打 AI 与健康电视概念，属于概念营销差异化，可对标其话术设计",
    "酷开": "系统与内容运营能力强、硬件成本可控，与运营变现路径直接竞争",
    "芒果超媒": "自制内容能力强、女性用户占比高，会员+广告双轮驱动",
    "新媒股份": "区域 IPTV 资源深厚，增值业务稳健",
    "银河奇异果": "内容库规模大，会员体系成熟",
    "极光TV": "绑定智能硬件生态，社交与游戏协同",
    "云视听小电视": "二次元社区调性强，年轻用户黏性高",
    "华为": "鸿蒙生态与高端品牌溢价",
    "荣耀": "性价比与年轻化渠道",
}
def make_diff(title):
    for brand, d in DIFF_RULES.items():
        if brand in title:
            return f"与我方差异：{d}"
    return ""

# ---------- 竞品品牌识别 ----------
BRAND_ALIAS = [
    ("小米", ["小米", "REDMI", "红米"]),
    ("海信", ["海信", "Vidda"]),
    ("创维", ["创维", "STRONG"]),
    ("酷开", ["酷开", "Coocaa"]),
    ("芒果超媒", ["芒果超媒", "芒果TV"]),
    ("新媒股份", ["新媒股份"]),
    ("银河奇异果", ["银河奇异果", "奇异果"]),
    ("极光TV", ["极光TV"]),
    ("云视听小电视", ["云视听", "小电视"]),
    ("华为", ["华为", "Vision智慧屏"]),
    ("荣耀", ["荣耀"]),
    ("爱奇艺", ["爱奇艺"]),
    ("腾讯视频", ["腾讯视频"]),
    ("优酷", ["优酷"]),
]
def detect_brand(title):
    """返回命中的竞品品牌名（按配置顺序优先），无命中返回 ''"""
    for brand, alias in BRAND_ALIAS:
        if any(a in title for a in alias):
            return brand
    return ""

# ---------- 热度 ----------
# 品牌关注度权重（竞聘对标的核心关注对象）
BRAND_WEIGHT = {
    "小米": 26, "海信": 24, "创维": 22, "酷开": 22,
    "芒果超媒": 20, "新媒股份": 18, "银河奇异果": 16,
    "极光TV": 16, "云视听小电视": 14,
    "华为": 20, "荣耀": 14, "爱奇艺": 12, "腾讯视频": 12, "优酷": 10,
}

def calc_heat(item, cat, now):
    """热度 = 品类基值 + 品牌权重 + 关键词命中 + 时效衰减 + 原文阅读量"""
    base = {"政策": 60, "竞品": 40, "数据": 40, "行业": 26}.get(cat, 26)

    # 品牌权重（竞品核心度）
    brand = detect_brand(item["title"])
    if brand:
        base += BRAND_WEIGHT.get(brand, 8)

    # 原文阅读量（奥维接口提供真实阅读数）
    raw = item.get("heat_raw") or 0
    if raw:
        base += min(45, (raw ** 0.5) * 0.8)

    # 关键词命中
    hit = 0
    for grp in ("brands", "actions", "data", "policy"):
        for w in KW[grp]:
            if w in item["title"]:
                hit += 3
    base += min(hit, 30)

    # 时效：7 天内加权，越新越热；超过 30 天后缓慢衰减
    d = item.get("published_at")
    if d and d != "待补充":
        try:
            days = (now - datetime.strptime(d[:10], "%Y-%m-%d")).days
            if days <= 7:
                base += 12
            elif days > 30:
                base *= max(0.5, 1 - (days - 30) * 0.002)
        except Exception:
            pass
    return round(base, 1)

# ---------- 主处理 ----------
def process(raw):
    now = datetime.now()
    all_items = []
    for src in raw["sources"]:
        for it in src["items"]:
            all_items.append({**it, "source_id": src["id"], "source_name": src["name"],
                              "src_cat": src["cat"], "type": src["type"]})

    # 1) 广告过滤
    before = len(all_items)
    all_items = [x for x in all_items if not is_spam(x["title"])]
    spam_cut = before - len(all_items)

    # 1.5) 陈旧内容过滤
    #      不同品类时效要求不同：政策/行业资讯要新（180 天），
    #      竞品动向（财报/战略/新品）一年内仍具对标价值 → 放宽到 400 天
    #      日期一律如实保留，不因放宽而编造，用户可自行判断新旧
    STALE_DAYS = 180
    STALE_DAYS_COMP = 400
    CY = now.year
    fresh = []
    stale_cut = 0
    for it in all_items:
        d = it.get("published_at", "待补充")
        is_comp = bool(detect_brand(it["title"]))
        limit = STALE_DAYS_COMP if is_comp else STALE_DAYS
        is_stale = False
        if d and d != "待补充":
            try:
                is_stale = (now - datetime.strptime(d[:10], "%Y-%m-%d")).days > limit
            except Exception:
                is_stale = False
        else:
            years = [int(y) for y in re.findall(r"(20\d{2})", it["title"])]
            years = [y for y in years if 2010 <= y <= CY]
            if years and max(years) < CY - 1:
                is_stale = True
        if is_stale:
            stale_cut += 1
            continue
        fresh.append(it)
    all_items = fresh

    # 2) 去重：URL 优先；不同源的相同标题合并（保留先出现的，记录多源）
    uniq, seen_url, seen_title = [], set(), {}
    for it in all_items:
        if it["url"] in seen_url:
            continue
        norm_t = re.sub(r"[\s\W]", "", it["title"])[:40]
        dup = None
        for k, v in seen_title.items():
            if norm_t[:20] == k[:20] or SequenceMatcher(None, norm_t, k).ratio() > 0.88:
                dup = v
                break
        if dup is not None:
            if it["source_name"] not in dup["also_in"]:
                dup["also_in"].append(it["source_name"])
            continue
        seen_url.add(it["url"])
        it["also_in"] = []
        seen_title[norm_t] = it
        uniq.append(it)

    # 3) 摘要 / 分类 / 热度 / 溯源
    for it in uniq:
        cat = classify(it["title"])
        it["cat"] = cat
        it["summary"] = make_summary(it["title"], cat)
        it["heat"] = calc_heat(it, cat, now)
        it["brand"] = detect_brand(it["title"])
        # 只要命中竞品品牌，就升级为竞品类并附「与我方差异」
        if it["brand"] and cat != "政策":
            cat = "竞品"
            it["cat"] = "竞品"
        it["diff"] = make_diff(it["title"]) if cat == "竞品" else ""
        # 溯源字段
        # 月精度日期（来自 URL 内嵌年月）不作为「发布时间」展示，只作归月参考
        pub = it["published_at"]
        if it.get("date_precision") == "month" and pub != "待补充":
            it["month"] = pub[:7]
            pub = "待补充"
        it["published_at"] = pub
        it["trace"] = {
            "url": it["url"] if it["url"].startswith("http") else "",
            "published_at": pub,
            "has_url": it["url"].startswith("http"),
        }
        if not it["trace"]["has_url"]:
            it["summary"] = "【待补充】原文链接缺失，本条仅作线索记录，未生成摘要"
        it["quotable"] = ""   # 由前端从原文提取，禁止在此凭空生成

    # 4) 按分类 + 热度排序
    order = {"政策": 0, "竞品": 1, "数据": 2, "行业": 3}
    uniq.sort(key=lambda x: (order.get(x["cat"], 9), -x["heat"]))

    stats = {
        "generated_at": raw["generated_at"],
        "processed_at": now.isoformat(timespec="seconds"),
        "raw_count": before,
        "spam_filtered": spam_cut,
        "stale_filtered": stale_cut,
        "dup_merged": len(all_items) - len(uniq),
        "final_count": len(uniq),
        "by_cat": {},
        "by_source": {},
        "date_coverage": {
            "with_date": sum(1 for x in uniq if x["published_at"] != "待补充"),
            "pending": sum(1 for x in uniq if x["published_at"] == "待补充"),
        },
    }
    for it in uniq:
        stats["by_cat"][it["cat"]] = stats["by_cat"].get(it["cat"], 0) + 1
        stats["by_source"][it["source_name"]] = stats["by_source"].get(it["source_name"], 0) + 1
    return uniq, stats

if __name__ == "__main__":
    raw = json.loads((BASE / "data" / "raw.json").read_text(encoding="utf-8"))
    items, stats = process(raw)
    (BASE / "data" / "processed.json").write_text(
        json.dumps({"stats": stats, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    s = stats
    print(f"原始 {s['raw_count']} → 广告 {s['spam_filtered']} / 陈旧 {s['stale_filtered']} / 重复 {s['dup_merged']} → 保留 {s['final_count']} 条")
    print(f"有日期 {s['date_coverage']['with_date']} 条，待补充 {s['date_coverage']['pending']} 条")
    print("分类分布:", s["by_cat"])
    print()
    for it in items[:8]:
        print(f"[{it['cat']}] 热度{it['heat']:5}  {it['published_at']:10}  {it['summary'][:56]}")
