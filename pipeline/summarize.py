#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTT 看板 · LLM 全站总结（DeepSeek / 任意 OpenAI 兼容接口）

流程（对应「先清洗，再总结」的原则）：
  1) 从 data.js 选出候选条目（按日期精度 + 热度，限制每源条数保证多样性）
  2) requests 抓取详情页 → trafilatura 抽取纯正文（省 80%+ token）
     失败时降级用抓列表页时已有的 summary 片段，绝不编造
  3) 调用 OpenAI 兼容 /chat/completions，要求输出严格 JSON
  4) 把模型输出映射回真实条目（标题/链接/来源/日期可溯源），写 summary.json

密钥读取顺序：环境变量 LLM_API_KEY → pipeline/llm_key.txt（私有仓库内）
无密钥 / 调用失败：不写 summary.json（前端自动回退规则版总结，主管道不受影响）
"""
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent
ROOT = BASE.parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ---------- 可调参数 ----------
N_CANDIDATES = 16      # 送入模型的条目数
PER_SOURCE = 3         # 单个信源最多几条（保证覆盖面）
MAX_TEXT = 1000        # 单条正文截断（字符）
TIMEOUT = 12           # 抓详情页超时（秒）
WORKERS = 6
API_TIMEOUT = 180      # 模型调用超时（秒）
API_RETRY = 2

BJT = timezone(timedelta(hours=8))


def log(msg):
    print("[summarize] " + msg, flush=True)


def load_data():
    """读取 data.js（管道产物优先，其次仓库根），返回 (cards, meta)。
    CI 里仓库根的 data.js 是上次部署的旧版本，与刚抓的新数据时间戳不一致，
    会导致前端按「数据不匹配」回退规则版——所以必须优先读本次抓取的产物。"""
    for p in (BASE / "data" / "data.js", ROOT / "data.js"):
        if p.is_file():
            txt = p.read_text(encoding="utf-8")
            m = re.search(r"=\s*(\{[\s\S]*\})\s*;?\s*$", txt)
            if m:
                d = json.loads(m.group(1))
                return d.get("cards", []), d.get("meta", {})
    return [], {}


def pick_candidates(cards):
    """全站去重（同标题留热度最高）→ 日期精度优先、热度次之 → 限量选取"""
    seen = {}
    for c in cards:
        for it in c.get("items", []):
            key = re.sub(r"\s+", "", it.get("t", ""))
            prev = seen.get(key)
            if prev is None or (it.get("h", 0) > prev.get("h", 0)):
                it = dict(it)
                it["_src"] = c.get("name", "")
                it["_src_cat"] = c.get("cat", "")
                seen[key] = it
    items = list(seen.values())

    def grade(d):
        if not d:
            return 3
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)):
            return 0
        if re.fullmatch(r"\d{4}-\d{2}", str(d)):
            return 1
        return 2

    items.sort(key=lambda x: (grade(x.get("d")), -(x.get("h") or 0)))
    out, cnt = [], {}
    for it in items:
        n = cnt.get(it["_src"], 0)
        if n >= PER_SOURCE:
            continue
        if not it.get("u") or it["u"].startswith("#") or it["u"] == "待补充":
            continue
        out.append(it)
        cnt[it["_src"]] = n + 1
        if len(out) >= N_CANDIDATES:
            break
    return out


def fetch_fulltext(url):
    """抓详情页并抽取正文；失败返回空串（调用方降级）"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read(400_000)
        for enc in ("utf-8", "gb18030"):
            try:
                html = raw.decode(enc)
                break
            except UnicodeDecodeError:
                html = None
        if not html:
            html = raw.decode("utf-8", "ignore")
        try:
            import trafilatura
            text = trafilatura.extract(html, output_format="txt",
                                       include_comments=False,
                                       include_tables=False,
                                       favor_recall=True) or ""
        except Exception:
            text = ""
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception:
        return ""


def gather_material(cands):
    """并发抓正文；抓不到的用已有 summary 片段降级"""
    jobs = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_fulltext, it["u"]): i for i, it in enumerate(cands)}
        for f in as_completed(futs):
            jobs[futs[f]] = f.result()
    blocks, full = [], 0
    for i, it in enumerate(cands):
        text = jobs.get(i, "")
        excerpt = it.get("summary") or ""
        if len(text) >= 80:
            full += 1
            body = text[:MAX_TEXT]
            body_src = "正文"
        elif excerpt:
            body = excerpt[:MAX_TEXT]
            body_src = "摘要"
        else:
            body = "（正文抓取失败，仅标题）"
            body_src = "仅标题"
        head = f"[{i+1}] {it['t']}｜{it['_src']}｜{it.get('d') or '日期待补充'}｜{it.get('cat') or it['_src_cat']}"
        blocks.append(f"{head}\n（{body_src}）{body}")
    return blocks, full


def call_llm(blocks, api_key, base_url, model):
    """调用 OpenAI 兼容接口，返回 dict；失败抛异常"""
    system = (
        "你是 OTT/IPTV 行业日报的资深编辑。只基于用户提供的材料写作，"
        "禁止引入材料之外的事实、数字或判断；材料里「日期待补充」的条目不得推断日期。"
        "输出严格 JSON（不要 markdown 代码块），结构：\n"
        '{"overview":"100字内的导语，点明本批资讯的核心脉络",'
        '"highlights":[{"idx":1,"why":"30字内为什么值得重点看"},...3条],'
        '"sections":[{"title":"行业大势","text":"200-400字的连贯分析，2-3个自然段，用\\n分段"},...3-5个分节]}\n'
        "sections 是行业早报风格：不要罗列标题，直接以事实与数据成文，"
        "像给决策者写简报一样有观点、有取舍、成段叙述。"
        "引用某条材料时在对应句末加方括号编号角标，如「激活家庭3.47亿户[1]」；"
        "编号必须是材料编号，不得虚构，同一句可引多个如[1][5]。"
        "分节标题建议：行业大势、市场格局 / 竞品、国内大屏、政策与监管；可按材料实际内容调整。"
    )
    user = "材料如下：\n\n" + "\n\n".join(blocks)
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.3,
        "max_tokens": 2200,
        "response_format": {"type": "json_object"},
    }
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(payload).encode()
    last_err = None
    for attempt in range(1 + API_RETRY):
        try:
            req = urllib.request.Request(url, data=body, method="POST", headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            content = data["choices"][0]["message"]["content"]
            m = re.search(r"\{[\s\S]*\}", content)
            if not m:
                raise ValueError("模型输出中没有 JSON")
            out = json.loads(m.group(0))
            out["_usage"] = data.get("usage", {})
            return out
        except Exception as e:
            last_err = e
            log(f"调用失败（第 {attempt + 1} 次）：{e}")
            time.sleep(3)
    raise RuntimeError("LLM 调用最终失败：" + str(last_err))


def resolve_meta(it, idx):
    """把编号映射回真实条目（供前端溯源展示）"""
    return {
        "idx": idx,
        "t": it.get("t", ""),
        "u": it.get("u", "#"),
        "src": it.get("_src", ""),
        "d": it.get("d", ""),
        "cat": it.get("cat") or it.get("_src_cat", ""),
    }


def main():
    api_key = (os.environ.get("LLM_API_KEY") or "").strip()
    key_file = BASE / "llm_key.txt"
    if not api_key and key_file.is_file():
        # 只取第一行；以 # 开头视为注释（未填 key）
        first = key_file.read_text(encoding="utf-8").strip().splitlines()
        if first and not first[0].strip().startswith("#"):
            api_key = first[0].strip()
    if not api_key:
        log("未发现 LLM_API_KEY / pipeline/llm_key.txt，跳过（前端回退规则版总结）")
        return 0

    base_url = (os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com").strip()
    model = (os.environ.get("LLM_MODEL") or "deepseek-chat").strip()

    cards, meta = load_data()
    if not cards:
        log("data.js 为空，跳过")
        return 0
    cands = pick_candidates(cards)
    if not cands:
        log("无可用候选条目，跳过")
        return 0
    log(f"候选 {len(cands)} 条 / 全站 {(sum(len(c.get('items', [])) for c in cards))} 条")

    blocks, full = gather_material(cands)
    log(f"正文抓取成功 {full}/{len(cands)} 条，开始调用 {model} …")

    out = call_llm(blocks, api_key, base_url, model)

    def attach(lst, keep_keys):
        """映射编号回条目；过滤模型编造的 idx"""
        res = []
        for p in lst or []:
            try:
                idx = int(p.get("idx"))
            except (TypeError, ValueError):
                continue
            if not (1 <= idx <= len(cands)):
                continue
            it = cands[idx - 1]
            row = resolve_meta(it, idx)
            for k in keep_keys:
                v = (p.get(k) or "").strip()
                row[k] = v if v else it.get("t", "")
            res.append(row)
        return res

    sections = [
        {"title": (s.get("title") or "").strip(),
         "text": re.sub(r"\s*\n\s*\n\s*", "\n", (s.get("text") or "").strip())}
        for s in (out.get("sections") or []) if (s.get("title") or "").strip() and (s.get("text") or "").strip()
    ]
    highlights = attach(out.get("highlights"), ["t", "why"])[:3]
    # 角标引用表：正文 [n] → 原文链接（含 highlights 引用的编号）
    cited = set()
    for sg in sections:
        cited.update(int(n) for n in re.findall(r"\[(\d+)\]", sg["text"]))
    for h in highlights:
        cited.add(h["idx"])
    refs = [resolve_meta(cands[n - 1], n) for n in sorted(cited) if 1 <= n <= len(cands)]
    summary = {
        "provider": base_url.split("//")[-1].split("/")[0],
        "model": model,
        "generated_at": datetime.now(BJT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "data_stamp": meta.get("generated_at", ""),
        "n_candidates": len(cands),
        "n_fulltext": full,
        "n_pool": sum(len(c.get("items", [])) for c in cards),
        "usage": out.get("_usage", {}),
        "overview": (out.get("overview") or "").strip(),
        "highlights": highlights,
        "sections": sections,
        "refs": refs,
    }
    if not summary["overview"] and not summary["sections"]:
        raise RuntimeError("模型输出缺少 overview/sections，视为失败不写文件")

    dst = BASE / "summary.json"
    dst.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"已写入 {dst}：分节 {len(summary['sections'])}，"
        f"角标引用 {len(summary['refs'])} 个，"
        f"usage={json.dumps(summary['usage'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
