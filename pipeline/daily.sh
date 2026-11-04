#!/usr/bin/env bash
# OTT 看板 · 自动抓取 + 发布（幂等：每天只成功抓取一次）
# 由 cron 每 6 小时触发；沙箱唤醒当年内任一时刻都会补抓当天数据
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="${1:-/workspace/ott-dashboard}"
LOG="$DIR/data/daily-cron.log"
LAST="$DIR/data/last_ok.txt"
PUBLISH="/root/.codebuddy/skills/sites/scripts/publish.js"

# 关键：cron/非交互环境不会自动加载 pyenv，必须显式把 pyenv 的 python 放最前，
# 否则 python3 会解析到 /usr/bin/python3（该解释器未装 bs4/playwright，导致抓取失败）
export PATH="/root/.pyenv/shims:/root/.pyenv/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:$PATH"

# 环境自检：确保 python3 能 import bs4 + playwright，否则明确报错而不是静默失败
if ! python3 -c "import bs4, playwright" 2>/dev/null; then
  echo "!! 环境异常：python3 缺少 bs4/playwright，PATH=$(echo "$PATH" | tr ':' '\n' | head -3 | tr '\n' ' ')" >> "$LOG"
  exit 1
fi

mkdir -p "$DIR/data"
TODAY="$(date '+%F')"

# 幂等：今天已成功抓取过则跳过
if [ -f "$LAST" ] && [ "$(cat "$LAST" 2>/dev/null)" = "$TODAY" ]; then
  echo "[$(date '+%F %T')] 今天($TODAY)已成功抓取，跳过" >> "$LOG"
  exit 0
fi

echo "===== $(date '+%F %T') 自动抓取开始（python3=$(command -v python3)）=====" >> "$LOG"
cd "$DIR" || { echo "!! 无法进入 $DIR" >> "$LOG"; exit 1; }

# 1) 抓取 → AI 处理 → 导出（失败保留上一版数据并写 alert.txt）
if bash run_pipeline.sh "$DEPLOY" >> "$LOG" 2>&1; then
  echo "$TODAY" > "$LAST"          # 记录今日已成功
  echo "抓取成功，开始发布…" >> "$LOG"
  # 2) 发布到线上（复用当前会话，输出稳定 shareLink）
  if node "$PUBLISH" --dir "$DEPLOY" >> "$LOG" 2>&1; then
    echo "发布成功 $(date '+%F %T')" >> "$LOG"
  else
    echo "!! 发布失败（数据已更新，仅线上未刷新）$(date '+%F %T')" >> "$LOG"
  fi
else
  echo "!! 抓取失败，保留旧数据 $(date '+%F %T')" >> "$LOG"
fi
