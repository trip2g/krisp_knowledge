#!/usr/bin/env bash
# Build calls.zip — the archive that turns an agent into a calls agent.
#
# Everything travels: the skill, its scripts, the one fleet role, the access
# rules, the guides and one demo transcript. Nothing is expected from the image
# except python3, which every agent base has.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
out="$(dirname "$here")/calls.zip"

# An update needs the machinery and nothing else: shipping the demo transcript
# to an agent that already has it changes nothing.
machinery_only=false
for arg in "$@"; do
  case "$arg" in
    --machinery) machinery_only=true ;;
    *) out="$arg" ;;
  esac
done

for f in "$here/install.sh" "$here/INSTALL.md" "$here/VERSION" \
         "$here/skills/calls/SKILL.md" "$here/skills/calls/scripts/gate.py" \
         "$here/skills/calls/scripts/intake.py" "$here/roles/segment.md" \
         "$here/cron/calls_ask.py"; do
  [ -f "$f" ] || { echo "pack: $f is missing" >&2; exit 1; }
done

# A skill the agent cannot parse is silently absent from its session, so the
# frontmatter is checked here rather than discovered on the client's box.
grep -qE '^name: calls$' "$here/skills/calls/SKILL.md" || {
  echo "pack: SKILL.md has no 'name: calls'" >&2; exit 1; }
grep -qE '^fleet_id: ' "$here/roles/segment.md" || {
  echo "pack: segment.md has no fleet_id" >&2; exit 1; }
python3 -m py_compile "$here/skills/calls/scripts/gate.py" \
                      "$here/skills/calls/scripts/intake.py"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/skills" "$work/roles" "$work/vault" "$work/cron" "$work/demo"
cp -r "$here/skills/." "$work/skills/"
cp "$here/roles/segment.md" "$work/roles/"
cp "$here/cron/calls_ask.py" "$work/cron/"
cp "$here/vault"/*.md "$work/vault/"
if [ "$machinery_only" = false ]; then
  cp -r "$here/vault/transcripts" "$work/vault/"
  cp "$here/demo/call.txt" "$work/demo/"
fi
cp "$here/install.sh" "$here/INSTALL.md" "$here/VERSION" "$work/"
find "$work" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

rm -f "$out"
(cd "$work" && zip -qr "$out" . -x '.*')
echo "$out — $(du -h "$out" | cut -f1), $(unzip -l "$out" | tail -1 | awk '{print $2}') files"
