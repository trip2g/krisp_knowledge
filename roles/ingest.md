---
description: "Krisp meetings -> verbatim transcript notes (cron ingest, deterministic, no LLM)"
mode: cron
cron_schedule: "*/15 * * * *"
executor: code
write_patterns: ["transcripts/**"]
env_passthrough: ["KRISP_TOKEN", "KRISP_BASE_URL"]
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

```python
import os
import json
import datetime
import urllib.request

base_url = os.environ['KRISP_BASE_URL'].rstrip('/')
token = os.environ['KRISP_TOKEN']


def api_post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        base_url + path,
        data=data,
        headers={
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json',
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_get(path):
    req = urllib.request.Request(
        base_url + path,
        headers={'Authorization': 'Bearer ' + token},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def decode_uuid7_utc(meeting_id):
    # Krisp meeting id is a UUIDv7: upper 48 bits = milliseconds since epoch.
    ms = int(meeting_id.replace('-', '')[:12], 16)
    return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc)


resp = api_post('/v2/meetings/list', {'page': 1, 'limit': 100, 'isOwner': True})
meetings = resp.get('data', {}).get('rows', [])

changes = []
for meeting in meetings:
    mid = meeting['id']
    name = meeting.get('name', mid)
    speakers = meeting.get('speakers', [])
    created = decode_uuid7_utc(mid)

    tree = api_get('/v2/block/' + mid + '/tree')

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
