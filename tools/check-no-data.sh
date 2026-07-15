#!/usr/bin/env bash
# Guard: fail if generated data or large blobs are tracked in git.
#
# This is the safety net that stops the ~20 GB history bloat from ever
# recurring. Run in CI (see .github/workflows/deploy.yml) and, optionally, as a
# local pre-commit hook:  git config core.hooksPath tools/hooks
set -euo pipefail

fail=0

tracked_data=$(git ls-files -- 'public/data/*' 'data/*' 2>/dev/null || true)
if [ -n "$tracked_data" ]; then
  echo "ERROR: generated data must not be committed — these files are tracked:"
  echo "$tracked_data" | sed 's/^/  /'
  fail=1
fi

# Any tracked file over 1 MB is almost certainly a stray artifact.
limit=$((1024 * 1024))
while IFS= read -r f; do
  [ -f "$f" ] || continue
  size=$(wc -c < "$f")
  if [ "$size" -gt "$limit" ]; then
    echo "ERROR: tracked file exceeds 1 MB: $f ($((size / 1024)) KB)"
    fail=1
  fi
done < <(git ls-files)

if [ "$fail" -ne 0 ]; then
  echo
  echo "Generated data belongs in public/data/ (git-ignored) and is published"
  echo "straight to Pages by CI. Do not commit it."
  exit 1
fi

echo "OK: no generated data or large blobs are tracked."
