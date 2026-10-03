#!/bin/sh
# Keep the published site current: every INTERVAL seconds regenerate the snapshots in docs/ and, if they
# changed, commit only docs/ and push. Stops at END (epoch seconds; default: the submission deadline).
# Usage: nohup scripts/site_loop.sh > runs/logs/site_loop.log 2>&1 &
cd "$(dirname "$0")/.." || exit 1
INTERVAL="${INTERVAL:-1800}"
END="${END:-$(date -j -f '%Y-%m-%d %H:%M' '2026-10-04 14:45' +%s)}"
while [ "$(date +%s)" -lt "$END" ]; do
  if scripts/publish_site.sh >/dev/null 2>&1; then
    if ! git diff --quiet -- docs; then
      git commit -q -m "Site: refresh run snapshots

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- docs && git push -q origin main && echo "$(date '+%H:%M') pushed"
    else
      echo "$(date '+%H:%M') no change"
    fi
  else
    echo "$(date '+%H:%M') publish_site.sh failed; nothing pushed"
  fi
  sleep "$INTERVAL"
done
