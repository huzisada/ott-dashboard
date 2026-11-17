#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成可推送到企业微信的每日早报（markdown）。

内容来源优先级：
  1) LLM 早报：仅当 llm_config.json enabled=true 且 summary.json 的 data_stamp
     与当前 data.js 一致时才复用。暂停期间不调用模型、也不冒充新数据。
  2) 规则版：按 政策 / 竞品 / 数据 / 行业 分组，按日期精度 + 热度排序，
     标题直接链到原文，绝不编造内容。

纯本地拼装：不联网、不调 API。输出按企业微信 markdown 的 4096 字节上限裁剪。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
ROOT = BASE.parent
BJT = timezone(timedelta(hours=8))
SITE_URL = os.environ.get("OTT_SITE_URL", "https://huzisada.github.io/ott-dashboard/")
MAX_BYTES = 3800  # 企业微信 markdown content 上限 4096 字节，留余量

SECTIONS = [
    ("政策", "政策 / 监管"),
    ("竞品", "竞品 / 厂商"),
    ("数据", "行业数据 / 报告"),
    ("行业", "行业动态"),
]


def load_data():
    """管道产物优先（CI 里仓库根的 data.js 可能是上一版）。"""
    for p in (BASE / "data" / "data.js", ROOT / "data.js"):
        if p.is_file():
            m = re.search(r"=\s*(\{[\s\S]*\})\s*;?\s*$", p.read_text(encoding="utf-8"))
            if m:
                return json.loads(m.group(1))
    raise RuntimeError("找不到 data.js")


def norm_cat(c):
    c = c or ""
    if "政策" in c:
        return "政策"
    if "竞品" in c:
        return "竞品"
    if "数据" in c:
        return "数据"
    return "行业"


def date_num(d):
    n = re.sub(r"\D", "", d or "")[:8]
    return int(n.ljust(8, "0")) if n else 0


def grade(d):
    if re.match(r"^20\d{2}-\d{2}-\d{2}$", d or ""):
        return 0
    if re.match(r"^20\d{2}-\d{2}", d or ""):
        return 1
    return 2


def sort_key(x):
    # 早报按「新鲜度」优先：日期精度 → 发布日期 → 热度。
    # 热度若排在日期前面，会出现 5 月旧稿压过 11 月新稿的情况。
    return (grade(x["d"]), -date_num(x["d"]), -x["h"])


def collect(d):
    """按规范化标题去重（品牌卡与源卡会重复），保留热度最高的一条。"""
    seen = {}
    for card in d.get("cards", []):
        src = card.get("name", "")
        for it in card.get("items", []):
            t = (it.get("t") or "").strip()
            u = it.get("u") or ""
            if not t or not u.startswith("http"):
                continue
            k = re.sub(r"\s+", "", t)
            h = it.get("h") or 0
            if k in seen and seen[k]["h"] >= h:
                continue
            seen[k] = {
                "t": t, "u": u, "h": h,
                "d": it.get("d") or "",
                "cat": norm_cat(it.get("cat") or card.get("cat") or ""),
                "src": src,
            }
    return list(seen.values())


def clip(s, n=34):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n] + "…"


def fmt_date(d):
    if re.match(r"^20\d{2}-\d{2}-\d{2}$", d or ""):
        return d[5:].replace("-", "-")
    if re.match(r"^20\d{2}-\d{2}", d or ""):
        return d[:7]
    return ""


def stamp(d):
    s = d["meta"]["generated_at"].replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(BJT)


def header(d, source):
    m = d["meta"]
    b = m.get("by_cat", {})
    day = stamp(d)
    tag = "DeepSeek 撰写" if source == "LLM" else "规则版速览"
    return (f"# OTT 行业早报 · {day.month}月{day.day}日\n"
            f"> {tag} · 今日抓取 {m.get('total', 0)} 条 · "
            f"政策 {b.get('政策', 0)} / 竞品 {b.get('竞品', 0)} / "
            f"数据 {b.get('数据', 0)} / 行业 {b.get('行业', 0)}\n\n")


def llm_brief(d):
    """暂停期间一律返回 None；开启后复用已生成的 summary.json。"""
    cfg = BASE / "llm_config.json"
    if cfg.is_file():
        try:
            if not json.loads(cfg.read_text(encoding="utf-8")).get("enabled", True):
                return None
        except Exception:
            return None
    p = BASE / "summary.json"
    if not p.is_file():
        return None
    try:
        S = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if S.get("data_stamp") != d["meta"].get("generated_at"):
        return None
    if not S.get("overview"):
        return None

    txt = header(d, "LLM") + re.sub(r"\s*\n\s*", "", S["overview"]) + "\n\n"
    for sec in (S.get("sections") or []):
        body = re.sub(r"\[\d+\]", "", sec.get("text") or "").strip()
        txt += f"**{sec.get('title', '行业动态')}**\n{body}\n\n"
    refs = [r for r in (S.get("refs") or []) if (r.get("u") or "").startswith("http")][:5]
    if refs:
        txt += "**今日重点原文**\n"
        for i, r in enumerate(refs, 1):
            txt += f"{i}. [{clip(r.get('t', ''), 30)}]({r['u']})\n"
        txt += "\n"
    return txt


# ---- 版式：企业微信仅支持 info(绿) / comment(灰) / warning(橙红) 三种字色 ----
STYLE_ICON = {"政策": "🏛️", "竞品": "🎯", "数据": "📈", "行业": "📰"}


def style_header(d, style):
    """标题 + 数据概览行。三版共用，配色随风格微调。"""
    m = d["meta"]
    b = m.get("by_cat", {})
    day = stamp(d)
    total = m.get("total", 0)
    line = (f"政策 {b.get('政策', 0)} / 竞品 {b.get('竞品', 0)} / "
            f"数据 {b.get('数据', 0)} / 行业 {b.get('行业', 0)}")
    if style == "C":
        return (f"OTT 早报 · {day.month}-{day.day:02d}\n"
                f'> <font color="comment">{total} 条 · {line}</font>\n\n')
    if style == "B":
        return f"📊 OTT 早报 · {day.month}月{day.day}日\n"
    return (f"# 📊 OTT 行业早报 · {day.month}月{day.day}日\n"
            f'> <font color="info">今日抓取 {total} 条 · {line}</font>\n\n')


def grouped(items, per_section):
    out = []
    for cat, title in SECTIONS:
        group = sorted([x for x in items if x["cat"] == cat], key=sort_key)[:per_section]
        if group:
            out.append((cat, title, group))
    return out


def body_A(groups):
    """A 图标分节：图标分节 + 首条加粗 + 来源统一灰字，保留全部条目。"""
    txt = ""
    for cat, title, group in groups:
        txt += f"**{STYLE_ICON.get(cat, '•')} {title}**\n"
        for i, x in enumerate(group):
            ds = fmt_date(x["d"])
            src = clip(x["src"], 12)
            tail = f"{src}{' · ' + ds if ds else ''}"
            bold = f"**[{clip(x['t'])}]({x['u']})**" if i == 0 else f"[{clip(x['t'])}]({x['u']})"
            txt += f"{bold}\n<font color=\"comment\">{tail}</font>\n"
        txt += "\n"
    return txt


def body_B(groups):
    """B 今日焦点：顶部焦点框放全局热度最高一条，其余每节精简展示。"""
    txt = ""
    first = True
    for cat, title, group in groups:
        if first:
            x = group[0]
            txt += (f'> <font color="warning">今日焦点｜{clip(x["t"])}</font>\n'
                    f'> <font color="comment">{clip(x["src"], 14)} · 热度 {x["h"]}</font>\n\n')
            first = False
        txt += f"**{STYLE_ICON.get(cat, '•')} {title}**  <font color=\"comment\">近 30 日 {len(group)} 条</font>\n"
        for x in group[:2]:
            txt += f"> [{clip(x['t'])}]({x['u']})  <font color=\"comment\">{fmt_date(x['d'])}</font>\n"
        txt += "\n"
    return txt


def body_C(groups):
    """C 极简速读：去掉编号与日期，标题即链接，来源内联，字数最少。"""
    txt = ""
    for cat, title, group in groups:
        txt += f"<font color=\"info\">[{cat}]</font>\n"
        for x in group:
            txt += f"[{clip(x['t'], 30)}]({x['u']})  <font color=\"comment\">{clip(x['src'], 10)}</font>\n"
        txt += "\n"
    return txt


def rule_brief(d, per_section, style="A"):
    items = collect(d)
    cutoff = date_num((stamp(d) - timedelta(days=30)).strftime("%Y-%m-%d"))
    # 历史库里存着几个月前的稿件，早报不能把它们当成「今天发生的事」：
    # 近 30 天稿件足够时只用近稿；近期整体太少才回退全库，避免早报空掉。
    fresh = [x for x in items if date_num(x["d"]) >= cutoff]
    if len(fresh) >= 8:
        items = fresh
    groups = grouped(items, per_section)
    txt = style_header(d, style)
    txt += {"A": body_A, "B": body_B, "C": body_C}.get(style, body_A)(groups)
    return txt


def cap(text):
    """保留尾部看板链接，按行裁剪到 MAX_BYTES 以内。"""
    tail = f"\n[打开完整看板]({SITE_URL})\n"
    body = text.rstrip()
    if len((body + tail).encode("utf-8")) <= MAX_BYTES:
        return body + tail
    budget = MAX_BYTES - len(tail.encode("utf-8")) - 40
    lines, used = [], 0
    for line in body.splitlines():
        b = len(line.encode("utf-8")) + 1
        if used + b > budget:
            lines.append("… 更多内容见看板")
            break
        lines.append(line)
        used += b
    return "\n".join(lines) + tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BASE / "data" / "brief.md"))
    ap.add_argument("--stdout", action="store_true", help="同时把早报正文打到日志")
    ap.add_argument("--style", choices=list("ABC"), default="A",
                    help="版式：A 图标分节(默认) / B 今日焦点 / C 极简速读")
    args = ap.parse_args()

    d = load_data()
    brief = llm_brief(d)
    source = "LLM" if brief else f"规则版·{args.style}"
    if not brief:
        # 条目多时逐档减少每节条数，优先保证「不超长、链接都在」
        for n in (5, 4, 3, 2):
            brief = rule_brief(d, n, args.style)
            if len(brief.encode("utf-8")) <= MAX_BYTES:
                break
    brief = cap(brief)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(brief, encoding="utf-8")
    print(f"[brief] {out} · {source} · {len(brief.encode('utf-8'))} 字节")
    if args.stdout:
        print("--- 早报正文 ---")
        print(brief)
    return 0


if __name__ == "__main__":
    sys.exit(main())
