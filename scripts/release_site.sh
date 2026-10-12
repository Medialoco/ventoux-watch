#!/usr/bin/env bash
# Release locale du site : bump site/VERSION, tag site-vX.Y.Z, pousse, ouvre la release.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUMP="${1:-patch}"
case "$BUMP" in patch|minor|major) ;; *)
  echo "Usage: $0 [patch|minor|major]" >&2
  exit 1
esac
VERSION="$(python3 - "$BUMP" <<'PY'
import re, sys
kind = sys.argv[1]
raw = open("site/VERSION", encoding="utf-8").read().strip()
m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", raw)
if not m:
    raise SystemExit(f"Bad site/VERSION: {raw!r}")
a, b, c = (int(m.group(i)) for i in range(1, 4))
if kind == "major":
    a, b, c = a + 1, 0, 0
elif kind == "minor":
    b, c = b + 1, 0
else:
    c += 1
new = f"{a}.{b}.{c}"
open("site/VERSION", "w", encoding="utf-8").write(new + "\n")
print(new)
PY
)"
git add site/VERSION
git commit -m "Release site v${VERSION}"
git tag "site-v${VERSION}"
git push origin HEAD main
git push origin "site-v${VERSION}"
gh release create "site-v${VERSION}" \
  --title "Site v${VERSION}" \
  --notes "Release du site GitHub Pages."
gh workflow run pages.yml
echo "Site v${VERSION} — release créée, Pages en cours."
