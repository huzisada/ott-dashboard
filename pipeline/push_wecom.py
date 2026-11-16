#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把每日早报推送到企业微信。

两种通道按环境变量自动选择（都配时优先群机器人）：
  A) 群机器人（最省事）：WECOM_WEBHOOK
     企业微信群 → 群机器人 → 添加 → 复制 Webhook 地址
  B) 应用消息：WECOM_CORPID + WECOM_CORPSECRET + WECOM_AGENTID
     可选 WECOM_TOUSER（默认 @all）

未配置任何凭据时静默跳过（退出 0，不阻断发布流程）。
同一批数据只推一次：push_state.json 记录已推送的 data.js 时间戳。
--dry-run 只打印不发送，--force 忽略去重。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
ROOT = BASE.parent
STATE = BASE / "push_state.json"
BJT = timezone(timedelta(hours=8))
API = "https://qyapi.weixin.qq.com/cgi-bin"


def log(m):
    print("[wecom] " + m, flush=True)


def data_stamp():
    """取本次数据的 generated_at 作为去重键（数据没变就不重复推）。"""
    for p in (BASE / "data" / "data.js", ROOT / "data.js"):
        if p.is_file():
            m = re.search(r'"generated_at"\s*:\s*"([^"]+)"', p.read_text(encoding="utf-8"))
            if m:
                return m.group(1)
    return datetime.now(timezone.utc).isoformat()


def post_json(url, payload, timeout=15):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def send_robot(hook, content):
    r = post_json(hook, {"msgtype": "markdown", "markdown": {"content": content}})
    return (r.get("errcode") == 0), r


def send_app(content, timeout=15):
    cid = os.environ.get("WECOM_CORPID", "").strip()
    secret = os.environ.get("WECOM_CORPSECRET", "").strip()
    agent = os.environ.get("WECOM_AGENTID", "").strip()
    touser = os.environ.get("WECOM_TOUSER", "@all").strip() or "@all"
    tok_url = f"{API}/gettoken?corpid={cid}&corpsecret={secret}"
    with urllib.request.urlopen(tok_url, timeout=timeout) as r:
        t = json.loads(r.read().decode("utf-8"))
    if t.get("errcode") != 0:
        return False, t
    url = f"{API}/message/send?access_token={t['access_token']}"
    base = {"touser": touser, "agentid": int(agent), "safe": 0}
    payload = dict(base, msgtype="markdown", markdown={"content": content})
    r = post_json(url, payload)
    # 部分老版本应用不支持 markdown，回退纯文本
    if r.get("errcode") != 0:
        r = post_json(url, dict(base, msgtype="text",
                                text={"content": content[:1800]}))
    return (r.get("errcode") == 0), r


def already_pushed(stamp, force):
    if force or not STATE.is_file():
        return False
    try:
        return json.loads(STATE.read_text(encoding="utf-8")).get("data_stamp") == stamp
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", default=str(BASE / "data" / "brief.md"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="忽略当日去重，强制再推一次")
    args = ap.parse_args()

    p = Path(args.message)
    if not p.is_file():
        log(f"早报文件不存在：{p}，跳过")
        return 0
    content = p.read_text(encoding="utf-8").strip()
    if not content:
        log("早报为空，跳过")
        return 0
    size = len(content.encode("utf-8"))
    log(f"早报 {size} 字节（上限 4096）")

    hook = os.environ.get("WECOM_WEBHOOK", "").strip()
    app_ready = all(os.environ.get(k, "").strip()
                    for k in ("WECOM_CORPID", "WECOM_CORPSECRET", "WECOM_AGENTID"))
    if not hook and not app_ready:
        log("未配置 WECOM_WEBHOOK / 应用凭据，跳过推送（发布流程不受影响）")
        return 0

    stamp = data_stamp()
    if already_pushed(stamp, args.force):
        log(f"该批数据已推送过（{stamp}），跳过；需要重推请加 --force")
        return 0

    channel = "群机器人" if hook else "应用消息"
    if args.dry_run:
        log(f"[dry-run] 通道={channel} 数据戳={stamp} 将发送以下内容：")
        print(content[:1200])
        return 0

    ok, resp = False, {}
    for attempt in range(1, 4):
        try:
            ok, resp = send_robot(hook, content) if hook else send_app(content)
            if ok:
                break
            log(f"第 {attempt} 次推送失败：{resp}")
        except Exception as e:
            log(f"第 {attempt} 次推送异常：{type(e).__name__}: {e}")
        if attempt < 3:
            time.sleep(2 * attempt)
    if not ok:
        log("推送最终失败（不影响站点发布）")
        return 0  # 推送是旁路能力，不阻断主流程

    STATE.write_text(json.dumps({
        "data_stamp": stamp,
        "pushed_at": datetime.now(BJT).isoformat(timespec="seconds"),
        "channel": channel,
        "bytes": size,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"已推送到企业微信（{channel}），数据戳 {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
