#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 processed.json 转成前端可直接消费的 data.js（卡片视图 + 溯源元数据）"""
import json, re
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
ROOT = BASE.parent
SRC = BASE / "data" / "processed.json"
OUT = BASE / "data" / "data.js"

PALETTE = {
    "政策": "#ef4444",
    "竞品": "#ff5c5c",
    "数据": "#22c55e",
    "行业": "#3b82f6",
}
SRC_COLOR = {
    "流媒体网": "#3b82f6",
    "流媒体网·OTT 频道": "#06b6d4",
    "流媒体网·厂商": "#ff5c5c",
    "流媒体网·政策": "#ef4444",
    "流媒体网·数据": "#22c55e",
    "依马狮广电网": "#8b5cf6",
    "奥维云网": "#0ea5e9",
    "广电总局·公告公示": "#ef4444",
    "广电总局·政策解读": "#f97316",
    "工信部·政策文件": "#f59e0b",
    "量子位": "#a855f7",
}

def _read_prev_payload():
    """上一版已发布的 data.js → dict（读失败返回 {}）。供骤降守卫与抓取历史复用。"""
    p = ROOT / "data.js"
    if not p.is_file():
        return {}
    try:
        txt = p.read_text(encoding="utf-8")
        m = re.search(r"=\s*(\{[\s\S]*\})\s*;?\s*$", txt)
        return json.loads(m.group(1)) if m else {}
    except Exception:
        return {}

def prev_snapshot():
    """上一版已发布的 data.js → (条目总数, 原文)，用于数据骤降守卫。"""
    p = ROOT / "data.js"
    if not p.is_file():
        return 0, ""
    try:
        txt = p.read_text(encoding="utf-8")
        m = re.search(r"=\s*(\{[\s\S]*\})\s*;?\s*$", txt)
        if not m:
            return 0, ""
        return int(json.loads(m.group(1))["meta"]["total"]), txt
    except Exception:
        return 0, ""

# 抓取历史：每次真正产出 data.js 时追加一条，最多保留 HISTORY_MAX 条（按 generated_at 去重）
HISTORY_MAX = 60

def build_fetch_history(meta, sources):
    """把本次抓取摘要并入历史（新记录置顶，按 generated_at 去重，截断到 HISTORY_MAX）。"""
    prev = _read_prev_payload()
    hist = prev.get("fetch_history") or []
    if not isinstance(hist, list):
        hist = []
    policy = [s for s in sources if s.get("type") == "policy"]
    rec = {
        "at": meta.get("generated_at", ""),
        "total": meta.get("total", 0),
        "with_date": meta.get("with_date", 0),
        "pending_date": meta.get("pending_date", 0),
        "source_ok": meta.get("source_ok", 0),
        "source_total": meta.get("source_total", 0),
        "policy_ok": sum(1 for s in policy if s.get("status") == "ok"),
        "policy_total": len(policy),
        "stale_filtered": meta.get("stale_filtered", 0),
        "dup_merged": meta.get("dup_merged", 0),
    }
    if not rec["at"]:
        return hist[:HISTORY_MAX]
    hist = [h for h in hist if (h or {}).get("at") != rec["at"]]
    hist.insert(0, rec)
    return hist[:HISTORY_MAX]


def build():
    d = json.loads(SRC.read_text(encoding="utf-8"))
    stats = d["stats"]
    items = d["items"]

    TYPE2CAT = {"policy": "政策", "competitor": "竞品", "data": "数据机构",
                "media": "行业媒体", "vendor": "竞品", "short_drama": "行业媒体",
                "integrated": "政策"}

    # 按信息源聚合为卡片（保持页面原有卡片范式）
    cards = {}
    for it in items:
        nm = it["source_name"]
        c = cards.setdefault(nm, {
            "id": it["source_id"],
            "name": nm,
            "cat": TYPE2CAT.get(it["type"], it["src_cat"]),
            "src_cat": it["src_cat"],
            "type": it["type"],
            "c": SRC_COLOR.get(nm, "#3b82f6"),
            "s": nm[0],
            "items": [],
        })
        c["items"].append({
            "t": it["title"],
            "u": it["url"],
            "h": int(it["heat"]),
            "d": (it["published_at"] if it["published_at"] != "待补充"
                  else (f"{it['month']}（月精度）" if it.get("month") else "时间待补充")),
            "summary": it["summary"],
            "kind": it.get("summary_kind", "title"),
            "cat": it["cat"],
            "also_in": it.get("also_in") or [],
            "month": it.get("month") or "",
            "brand": it.get("brand") or "",
        })

    # 竞品品牌卡：把散落在各媒体源里的竞品资讯，按品牌聚合成独立卡片
    brand_cards = {}
    for c in list(cards.values()):
        for it in list(c["items"]):
            b = it.get("brand")
            if not b:
                continue
            bc = brand_cards.setdefault(b, {
                "id": "brand_" + b,
                "name": f"竞品 · {b}",
                "cat": "竞品",
                "src_cat": "竞品追踪",
                "type": "competitor",
                "c": "#ff5c5c" if b in ("小米", "海信", "创维", "酷开") else "#f59e0b",
                "s": b[0],
                "items": [],
            })
            bc["items"].append({**it, "cat": "竞品"})
    # 品牌卡并入卡片列表（去重：同一 URL 只保留一次）
    for b, bc in brand_cards.items():
        bc["items"].sort(key=lambda x: -x["h"])
        bc["time"] = f"{len(bc['items'])} 条"
        bc["pending_date"] = sum(1 for x in bc["items"] if x["d"] == "待补充")
        bc["last_fetch"] = stats["generated_at"]
        cards[bc["id"]] = bc

    # 统一生成卡片列表（媒体源卡 + 品牌卡）
    card_list = []
    for c in cards.values():
        c["items"].sort(key=lambda x: -x["h"])
        if not c["items"]:
            continue
        total = len(c["items"])
        latest = max((x["d"] for x in c["items"] if x["d"] != "待补充"), default="")
        pending = sum(1 for x in c["items"] if x["d"] == "待补充")
        if c["id"].startswith("brand_"):
            c["time"] = f"{total} 条竞品动态"
            c["s"] = c["name"][-3:] if len(c["name"]) > 4 else c["s"]
        else:
            c["time"] = f"{total} 条 · 最新 {latest}" if latest else f"{total} 条"
        c["pending_date"] = pending
        c["last_fetch"] = stats["generated_at"]
        card_list.append(c)

    # 卡片排序：政策 → 竞品(品牌卡在前) → 数据 → 行业
    order = {"政策": 0, "竞品": 1, "数据": 2, "行业": 3}
    card_list.sort(key=lambda c: (
        order.get(c["cat"], 9),
        0 if c["id"].startswith("brand_") else 1,
        -len(c["items"]),
    ))

    # 信源健康度（供订阅源管理页展示）
    sources = []
    for s in json.loads((BASE / "data" / "raw.json").read_text(encoding="utf-8"))["sources"]:
        sources.append({
            "id": s["id"], "name": s["name"], "cat": s["cat"], "type": s["type"],
            "freq": s["freq"], "status": s["status"], "error": s["error"],
            "count": len(s["items"]), "fetched_at": s["fetched_at"],
            "list_url": s["list_url"],
        })

    payload = {
        "meta": {
            "generated_at": stats["generated_at"],
            "processed_at": stats["processed_at"],
            "total": stats["final_count"],
            "with_date": stats["date_coverage"]["with_date"],
            "pending_date": stats["date_coverage"]["pending"],
            "stale_filtered": stats.get("stale_filtered", 0),
            "dup_merged": stats.get("dup_merged", 0),
            "by_cat": stats["by_cat"],
            "source_ok": sum(1 for s in sources if s["status"] == "ok"),
            "source_total": len(sources),
        },
        "sources": sources,
        "cards": card_list,
    }
    # 抓取历史：并入本次摘要（读上一版 data.js 已有历史），追加到 payload
    payload["fetch_history"] = build_fetch_history(payload["meta"], sources)
    js = "/* 由 crawl.py + ai_process.py 自动生成，请勿手改 */\nwindow.__OTT_DATA__ = " + \
         json.dumps(payload, ensure_ascii=False) + ";\n"
    m = payload["meta"]
    # 数据骤降守卫：某次抓取大面积失败时，宁可沿用上一版完整数据，
    # 也不能把只剩几个源的残缺结果发布出去（竞品卡片会被整体抹掉）。
    prev_total, prev_js = prev_snapshot()
    if prev_total >= 30 and m["total"] < prev_total * 0.6:
        warn = (f"数据骤降守卫：本次仅 {m['total']} 条，上一版 {prev_total} 条（低于 60%），"
                f"判定为抓取异常，沿用上一版 data.js 不覆盖")
        print("::warning::" + warn, flush=True)
        print("!! " + warn, flush=True)
        OUT.write_text(prev_js, encoding="utf-8")
        return payload
    OUT.write_text(js, encoding="utf-8")
    print(f"data.js 已生成：{m['total']} 条 / {len(card_list)} 张卡片 / {m['source_ok']}/{m['source_total']} 源正常")
    print(f"有日期 {m['with_date']} 条，待补充 {m['pending_date']} 条")
    return payload

if __name__ == "__main__":
    build()
