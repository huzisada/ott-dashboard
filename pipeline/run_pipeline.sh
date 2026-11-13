#!/usr/bin/env bash
# OTT 看板 · 一键抓取管道
# 用法：./run_pipeline.sh
# 流程：抓取 → AI 处理 → 导出前端数据。任一步失败即中止并保留旧数据。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="${1:-/workspace/ott-dashboard}"
LOG="$DIR/data/pipeline.log"

mkdir -p "$DIR/data"
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 开始 =====" >> "$LOG"

cd "$DIR"

# 1) 抓取（失败自动重试 2 次）
ok=0
for attempt in 1 2 3; do
  if python3 crawl.py >> "$LOG" 2>&1; then ok=1; break; fi
  echo "抓取失败，第 $attempt 次重试…" >> "$LOG"
  sleep $((attempt * 10))
done
if [ "$ok" -ne 1 ]; then
  echo "!! 抓取连续失败，保留上一版数据" >> "$LOG"
  echo "ALERT: 抓取失败 $(date '+%F %T')" > "$DIR/data/alert.txt"
  exit 1
fi

# 1.5) 正文摘录：为「内容摘要」补真实原文片段
#      该步骤失败不阻断主管道，摘要会自动如实降级为标题要点
if ! python3 enrich.py >> "$LOG" 2>&1; then
  echo "!! 正文摘录失败，本次摘要降级为标题要点" >> "$LOG"
fi

# 2) AI 处理 + 3) 导出
python3 ai_process.py >> "$LOG" 2>&1
python3 export.py >> "$LOG" 2>&1

# 3.5) LLM 全站总结（DeepSeek；先清洗正文再调用，失败不阻断发布）
#      读取顺序：环境变量 LLM_API_KEY → pipeline/llm_key.txt（未填则整步跳过）
if [ -n "${LLM_API_KEY:-}" ] || [ -s "$DIR/llm_key.txt" ]; then
  if ! python3 -c "import trafilatura" 2>/dev/null; then
    echo "安装 trafilatura…" >> "$LOG"
    python3 -m pip install --quiet --disable-pip-version-check trafilatura >> "$LOG" 2>&1 || true
  fi
  if ! python3 summarize.py >> "$LOG" 2>&1; then
    echo "!! LLM 总结失败，前端将回退规则版总结" >> "$LOG"
  fi
else
  echo "未配置 LLM key，跳过全站总结（前端回退规则版）" >> "$LOG"
fi

# 4) 同步到部署目录（前端直接读 data.js）
if [ -d "$DEPLOY" ]; then
  cp "$DIR/data/data.js" "$DEPLOY/data.js"
  echo "已同步 data.js → $DEPLOY" >> "$LOG"
fi

# 5) 成功即清除告警
rm -f "$DIR/data/alert.txt"
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 完成 =====" >> "$LOG"
tail -3 "$LOG"
