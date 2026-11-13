#!/usr/bin/env bash
# 组装可部署的静态站点到 ./site
# 由 GitHub Actions 调用；本地也可直接运行预览：python3 -m http.server -d site 8099
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="$ROOT/site"
rm -rf "$SITE"; mkdir -p "$SITE"

# 1) 前端主文件
cp "$ROOT/index.html" "$SITE/"

# 2) 最新数据（run_pipeline.sh 已复制到仓库根目录；兜底取 pipeline 产物）
if [ -f "$ROOT/data.js" ]; then
  cp "$ROOT/data.js" "$SITE/"
else
  cp "$ROOT/pipeline/data/data.js" "$SITE/"
fi

# 2.5) LLM 全站总结（pipeline/summarize.py 产出 pipeline/summary.json）
#      无该文件时写 null 占位，前端自动回退规则版总结，避免 404
python3 - "$ROOT" "$SITE" <<'PYI'
import json, sys
from pathlib import Path
root, site = Path(sys.argv[1]), Path(sys.argv[2])
src = root / "pipeline" / "summary.json"
data = None
if src.is_file():
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"!! summary.json 解析失败，按无总结处理：{e}")
js = ("/* 由 build_site.sh 从 pipeline/summary.json 生成，请勿手改 */\n"
      "window.__OTT_SUMMARY__ = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n")
(site / "summary.js").write_text(js, encoding="utf-8")
(root / "summary.js").write_text(js, encoding="utf-8")
print("summary.js 已生成：" + ("LLM 总结（%s）" % data.get("model") if data else "null（回退规则版）"))
PYI

# 3) 图标资源
for f in favicon.ico favicon.svg favicon.png favicon-16.png favicon-32.png apple-touch-icon.png; do
  [ -f "$ROOT/$f" ] && cp "$ROOT/$f" "$SITE/"
done

# 3.5) 订阅源完整配置 → sources.js（前端订阅源管理的权威配置）
#     同时写一份到仓库根，方便本地 file:// 预览；线上以 site/ 内的为准
python3 - "$ROOT" "$SITE" <<'PY'
import json, os, sys
from pathlib import Path
root, site = Path(sys.argv[1]), Path(sys.argv[2])
cfg = json.loads((root / "pipeline" / "sources.json").read_text(encoding="utf-8"))
# CI 里 GITHUB_REPOSITORY 由 Actions 自动注入，确保前端写回的仓库名绝对准确
full = os.environ.get("GITHUB_REPOSITORY", "huzisada/ott-dashboard")
owner, _, name = full.partition("/")
meta = {"owner": owner or "huzisada", "repo": name or "ott-dashboard"}
js = ("/* 由 build_site.sh 从 pipeline/sources.json 生成，请勿手改 */\n"
      "window.__OTT_REPO__ = " + json.dumps(meta, ensure_ascii=False) + ";\n"
      "window.__OTT_SRC_CONFIG__ = " + json.dumps(cfg, ensure_ascii=False, indent=1) + ";\n")
(site / "sources.js").write_text(js, encoding="utf-8")
(root / "sources.js").write_text(js, encoding="utf-8")
print("sources.js 已生成：%d 个源，写回目标 %s/%s" % (len(cfg.get("sources", [])), meta["owner"], meta["repo"]))
PY

# 4) 用构建号替换 index.html 里的 @@BUILD@@，强制浏览器刷新缓存
BUILD_ID="${OTT_BUILD_ID:-$(date +%Y%m%d%H%M%S)}"
if command -v sed >/dev/null; then
  sed -i.bak "s/@@BUILD@@/$BUILD_ID/g" "$SITE/index.html" && rm -f "$SITE/index.html.bak"
fi

echo "site 已生成: $SITE"
ls -la "$SITE"
