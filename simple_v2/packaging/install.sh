#!/usr/bin/env sh
# Install or update the calls pipeline on an agent.
#
# The two halves are not updated the same way. The machinery — the skill, the
# scripts, the role, the access rules and the guides — is overwritten every
# time, because there is one right version of it. The library — transcripts and
# the notes grown from them — is seeded only when missing, because past the
# first install it is the owner's own work.
set -eu

here="$(cd "$(dirname "$0")" && pwd)"
vault="${TRIP2G_VAULT_DIR:-/opt/data/secondbrain}"
skills="${CALLS_SKILLS_DIR:-/opt/data/skills}"
cron="${CALLS_CRON_DIR:-/opt/data/scripts}"
version="$(cat "$here/VERSION" 2>/dev/null || echo unknown)"

echo "calls $version -> $vault"

# machinery: always
mkdir -p "$skills/calls" "$vault/roles"
cp -r "$here/skills/calls/." "$skills/calls/"
printf '%s\n' "$version" > "$skills/calls/VERSION"
cp "$here/roles/segment.md" "$vault/roles/segment.md"
for note in _access_calls.md _access_internal.md call_transcripts.md calls_graph.md; do
  cp "$here/vault/$note" "$vault/$note"
done
mkdir -p "$cron"
cp "$here/cron/calls_ask.py" "$cron/calls_ask.py"
echo "  skill calls, role segment, 2 access rules, 2 guides, cron script"

# library: only what is not there yet
seeded=0
kept=0
for group in transcripts; do
  [ -d "$here/vault/$group" ] || continue
  mkdir -p "$vault/$group"
  for item in "$here/vault/$group"/*; do
    [ -e "$item" ] || continue
    target="$vault/$group/$(basename "$item")"
    if [ -e "$target" ]; then
      kept=$((kept + 1))
    else
      cp -r "$item" "$target"
      seeded=$((seeded + 1))
    fi
  done
done
echo "  library: $seeded seeded, $kept left alone"

# The notes are files until they are pushed; nothing above exists for the agent
# until this runs. See INSTALL.md.
if command -v secondbrain-sync >/dev/null 2>&1; then
  secondbrain-sync >/dev/null && echo "  vault synced"
else
  echo "  vault NOT synced: run the sync yourself, see INSTALL.md"
fi

# The owner's own name is how the pipeline knows not to file him as a new
# person. Wrong here means a card on the owner himself. See INSTALL.md.
if [ -z "${CALLS_OWNER:-}" ]; then
  echo "  CALLS_OWNER is not set — the owner will be filed as «Владелец»"
fi

# Writing the state note is also the first proof that the vault answers. A
# REFUSED here means the machinery is in place and the base is not reachable.
python3 "$skills/calls/scripts/gate.py" init --since "${CALLS_SINCE:-1970-01-01}"
python3 "$skills/calls/scripts/gate.py" status
echo "calls $version installed"
