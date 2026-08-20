---
description: "Krisp meetings -> verbatim transcript notes (cron ingest, deterministic, no LLM)"
fleet_id: krisp-code
mode: cron
cron_schedule: "*/15 * * * *"
write_patterns: ["transcripts/**"]
max_depth: 1
timeout_seconds: 120
---
The only source-specific stage. Pulls recent calls from the Krisp API and writes each
one verbatim as `transcripts/YYYY-MM-DD-<id8>.md`. No LLM, no cost. Everything
downstream is source-agnostic: swapping Krisp for another recorder (or books, YouTube,
support threads) means replacing only this role.

The call instant is decoded from the Krisp meeting id (a UUIDv7 whose upper 48 bits are
a millisecond timestamp). That time, never the local clock, is the authority for
`created_at`, filenames, sorting, and daily bucketing. Writing a transcript note is what
wakes the segmentation role.

This body runs in codellm, not in the fleet — `fleet_id: krisp-code` routes it to the
fleet whose `--llm-base-url` points at a codellm service. `KRISP_TOKEN` and
`KRISP_BASE_URL` arrive as ordinary environment variables because codellm holds them
and lists them in its own `CODELLM_EXPOSE_ENV`; the role declares nothing about env and
the fleet never holds the values.

```python
import os
import json
import datetime
import requests

base_url = os.environ['KRISP_BASE_URL'].rstrip('/')
session = requests.Session()
session.headers['Authorization'] = 'Bearer ' + os.environ['KRISP_TOKEN']


def decode_uuid7_utc(meeting_id):
    # Krisp meeting id is a UUIDv7: upper 48 bits = milliseconds since epoch.
    ms = int(meeting_id.replace('-', '')[:12], 16)
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc)


resp = session.post(
    base_url + '/v2/meetings/list',
    json={'page': 1, 'limit': 100, 'isOwner': True},
    timeout=30,
).json()
meetings = resp.get('data', {}).get('rows', [])

changes = []
for meeting in meetings:
    mid = meeting['id']
    name = meeting.get('name', mid)
    speakers = meeting.get('speakers', [])
    created = decode_uuid7_utc(mid)

    tree = session.get(base_url + '/v2/block/' + mid + '/tree', timeout=30).json()

    lines = [
        '---',
        'title: "Krisp call ' + mid[:8] + '"',
        'type: transcript',
        'created_at: "' + created.isoformat() + '"',
        'source: krisp',
        'call_id: "' + mid + '"',
        '---',
        '# ' + name,
        '',
    ]
    for child in tree.get('children', []):
        if child.get('block_type') != 'utterance':
            continue
        idx = child.get('speakerIndex', 0)
        if 0 < idx <= len(speakers):
            sp = speakers[idx - 1]
            speaker = sp.get('first_name', '') + ' ' + sp.get('last_name', '')
        else:
            speaker = 'Speaker ' + str(idx)
        speech = child.get('speech', {})
        start = speech.get('start', 0.0)
        text = speech.get('text', '')
        mins = int(start) // 60
        secs = int(start) % 60
        lines.append(speaker.strip() + ' | {:02d}:{:02d}'.format(mins, secs))
        lines.append(text)
        lines.append('')

    path = 'transcripts/' + created.strftime('%Y-%m-%d') + '-' + mid[:8] + '.md'
    changes.append({'path': path, 'content': '\n'.join(lines)})

print(json.dumps({'changes': changes, 'answer': 'ingested ' + str(len(changes))}))
```
