#!/bin/sh
# Regenerate the read-only snapshots in docs/ from the live runs. Usage: scripts/publish_site.sh [run ids...]
# With DEPLOY=cloudflare it also deploys docs/ to the Cloudflare Pages project "mendel-evolve".
cd "$(dirname "$0")/.." || exit 1
RUNS="${*:-p60 cp-haiku-1 cp-haiku-2 cp-haiku-3}"
for r in $RUNS; do
  [ -f "runs/$r/state.json" ] && uv run python -m mendel.dashboard.snapshot --run "$r" --runs runs --out "docs/$r.html" 2>&1 | grep -v VIRTUAL_ENV
done
if grep -l -E "/Users/|sk-ant-" docs/*.html >/dev/null 2>&1; then echo "refusing to publish: a snapshot contains a local path or a key"; exit 1; fi
if [ "$DEPLOY" = "cloudflare" ]; then npx --yes wrangler@latest pages deploy docs --project-name mendel-evolve --branch main --commit-dirty=true; fi
