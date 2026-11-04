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

# 3) 图标资源
for f in favicon.ico favicon.svg favicon.png favicon-16.png favicon-32.png apple-touch-icon.png; do
  [ -f "$ROOT/$f" ] && cp "$ROOT/$f" "$SITE/"
done

# 4) 用构建号替换 index.html 里的 @@BUILD@@，强制浏览器刷新缓存
BUILD_ID="${OTT_BUILD_ID:-$(date +%Y%m%d%H%M%S)}"
if command -v sed >/dev/null; then
  sed -i.bak "s/@@BUILD@@/$BUILD_ID/g" "$SITE/index.html" && rm -f "$SITE/index.html.bak"
fi

echo "site 已生成: $SITE"
ls -la "$SITE"
