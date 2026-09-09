#!/usr/bin/env python3
"""Intake of the calls pipeline: a forwarded .txt becomes one transcript note.

    python3 intake.py --file /path/to/forwarded.txt --date 2026-03-14 [--title "…"]

There is no recorder and no API here: the owner forwards a plain text file to
his agent, so the shape of that file is unknown — speaker labels, timecodes,
both or neither. The words are never rewritten. What intake adds is a line
number per utterance, and from there on the whole pipeline addresses a span of
a call by line number, the way the Krisp version addressed it by timecode.

The note is `transcripts/<date>-<id8>.md`, id8 = first 8 hex of the sha256 of
the normalised body. The same file sent twice is refused, not written twice.

Vault access: trip2g over GraphQL, Bearer token from TRIP2G_MCP_TOKEN_FILE
(default /alloc/trip2g/mcp-token), URL from TRIP2G_MCP_URL.

Body format, which gate.py and the segment role both read (docs: ../SKILL.md):

    <n> | <label> | <MM:SS> | <текст>

Label and timecode are empty when the file had none; the text may contain
`|`, so the line is split with maxsplit=3.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

TOKEN_FILE = os.environ.get('TRIP2G_MCP_TOKEN_FILE', '/alloc/trip2g/mcp-token')
MCP_URL = os.environ.get('TRIP2G_MCP_URL', 'http://127.0.0.1:8080/_system/mcp')
GRAPHQL_URL = MCP_URL.replace('/_system/mcp', '/_system/graphql')

# A header line of a recorder export pasted into a txt: «Speaker 1 | 04:12»,
# the words on the next line.
HEADER_RE = re.compile(r'^(.{1,60}?) \| (\d{1,3}:\d{2}(?::\d{2})?)$')
TC_RE = re.compile(r'^[\[(]?(\d{1,3}:\d{2}(?::\d{2})?)[\])]?\s*[-–—]?\s*(.*)$')
LABEL_RE = re.compile(r'^([^:]{1,40}):\s*(.*)$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


# ---------- vault ----------

def _token():
    try:
        return open(TOKEN_FILE).read().strip()
    except OSError as e:
        die(f'REFUSED: vault no token file {TOKEN_FILE}: {e}')


def gql(query, variables=None):
    body = json.dumps({'query': query, 'variables': variables or {}}).encode()
    req = urllib.request.Request(GRAPHQL_URL, data=body, headers={
        'Authorization': 'Bearer ' + _token(),
        'Content-Type': 'application/json',
        'X-trip2g-client': 'calls-intake',
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        die(f'REFUSED: vault http {e.code} {e.read()[:200]!r}')
    except urllib.error.URLError as e:
        die(f'REFUSED: vault unreachable {e.reason}')
    if out.get('errors'):
        die('REFUSED: vault ' + '; '.join(x.get('message', '?') for x in out['errors'])[:300])
    return out['data']


def list_paths(like):
    d = gql('query($f: NotePathsFilter){ notePaths(filter: $f){ path: value hash: latestContentHash } }',
            {'f': {'like': like}})
    return {x['path']: x['hash'] for x in d['notePaths']}


def read_note(path):
    d = gql('query($f: NotePathsFilter){ notePaths(filter: $f){ path: value content hash: latestContentHash } }',
            {'f': {'paths': [path]}})
    rows = d['notePaths']
    return (rows[0]['content'], rows[0]['hash']) if rows else (None, None)


def write_note(path, content, expected_hash=''):
    """expected_hash '' = create only; a hash = update only if unchanged."""
    d = gql('''mutation($i: UpdateNotesInput!){ updateNotes(input: $i){ __typename
      ... on UpdateNotesSuccessPayload { paths }
      ... on UpdateNotesHashMismatchPayload { path actualHash }
      ... on ErrorPayload { message } } }''',
            {'i': {'changes': [{'upsert': {'path': path, 'content': content, 'expectedHash': expected_hash}}]}})
    r = d['updateNotes']
    t = r['__typename']
    if t == 'UpdateNotesSuccessPayload':
        return 'ok'
    if t == 'UpdateNotesHashMismatchPayload':
        return 'exists'
    die('REFUSED: vault ' + str(r.get('message', r))[:300])


# ---------- notes ----------

def split_frontmatter(text):
    if not text.startswith('---'):
        return {}, text
    end = text.find('\n---', 3)
    if end < 0:
        return {}, text
    fm = {}
    for line in text[3:end].strip().split('\n'):
        m = re.match(r'^([A-Za-z_][\w-]*):\s*(.*)$', line)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
                v = v[1:-1]
            fm[m.group(1)] = v
    return fm, text[end + 4:].lstrip('\n')


def yaml_str(s):
    return json.dumps(str(s), ensure_ascii=False)


def render(meta_lines, body):
    return '---\n' + '\n'.join(meta_lines) + '\n---\n' + body.rstrip('\n') + '\n'


def die(line):
    print(line)
    sys.exit(2)


# ---------- the normaliser ----------

def label_shape(s):
    """A speaker label, not a sentence that happens to carry a colon."""
    s = s.strip()
    return bool(s) and len(s) <= 40 and len(s.split()) <= 4 and not re.search(r'[.!?,;]', s)


def clean_label(s):
    """Labels lose `|`: it is the field separator of the body, and the words of
    an utterance are protected by maxsplit, but a label is not."""
    return s.replace('|', '/').strip()


def split_line(line, known=None):
    """(label, timecode, text) of one raw line. known=None is the counting pass."""
    tc = ''
    m = TC_RE.match(line)
    if m:
        tc, line = m.group(1), m.group(2).strip()
    lab = ''
    m = LABEL_RE.match(line)
    if m and label_shape(m.group(1)) and (known is None or m.group(1).strip() in known):
        lab, line = m.group(1).strip(), m.group(2).strip()
    return lab, tc, line


def normalise(raw):
    """[(label, timecode, text)] — one tuple per utterance, words untouched.

    Two passes: a label is only believed when it opens two lines or more, so a
    mid-sentence colon («Смотри: я думаю…») does not mint a speaker."""
    lines = [x.strip() for x in raw.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n').split('\n')]
    counts = {}
    for x in lines:
        if not x or HEADER_RE.match(x):
            continue
        lab, _, _ = split_line(x)
        if lab:
            counts[lab] = counts.get(lab, 0) + 1
    known = {k for k, n in counts.items() if n >= 2}

    rows, i = [], 0
    while i < len(lines):
        line, i = lines[i], i + 1
        if not line:
            continue
        m = HEADER_RE.match(line)
        if m:
            lab, tc, text = m.group(1), m.group(2), ''
        else:
            lab, tc, text = split_line(line, known)
        if not text:
            # A header on a line of its own: the words are the next one.
            while i < len(lines) and not lines[i]:
                i += 1
            if i < len(lines) and not HEADER_RE.match(lines[i]):
                text, i = lines[i], i + 1
        if text:
            rows.append((clean_label(lab), tc, text))
    return rows


def body_of(rows):
    return '\n'.join(f'{n} | {lab} | {tc} | {text}' for n, (lab, tc, text) in enumerate(rows, 1))


# ---------- command ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--file', required=True, help='the forwarded .txt')
    ap.add_argument('--date', help='YYYY-MM-DD — when the call happened')
    ap.add_argument('--title', default='', help='как владелец назвал разговор')
    ap.add_argument('--dry-run', action='store_true', help='print the note, write nothing')
    args = ap.parse_args()

    # The date is asked for, never guessed: a forwarded file is usually old, and
    # today's date would file the call under the wrong day for good.
    if not args.date:
        die('REFUSED: unreadable нет даты разговора (--date YYYY-MM-DD); спроси владельца, когда он состоялся')
    if not DATE_RE.match(args.date):
        die(f'REFUSED: unreadable дата {args.date!r} не вида YYYY-MM-DD')
    try:
        raw = open(args.file, 'rb').read()
    except OSError as e:
        die(f'REFUSED: unreadable {args.file}: {e}')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('cp1251', errors='replace')

    rows = normalise(text)
    if not rows:
        die(f'REFUSED: unreadable {args.file} не содержит реплик')
    body = body_of(rows)
    full = hashlib.sha256(body.encode('utf-8')).hexdigest()
    id8 = full[:8]
    labels = sorted({lab for lab, _, _ in rows if lab})
    timecodes = any(tc for _, tc, _ in rows)
    path = f'transcripts/{args.date}-{id8}.md'

    meta = ['title: ' + yaml_str(args.title or f'Разговор {args.date}'), 'type: transcript',
            'source: telegram', 'date: ' + args.date, 'sha256: ' + full,
            'lines: %d' % len(rows), 'chars: %d' % len(body),
            'labels: [' + ', '.join(yaml_str(x) for x in labels) + ']',
            'timecodes: ' + ('true' if timecodes else 'false')]
    note = render(meta, body)

    if args.dry_run:
        print(note, end='')
        return
    # The id is the hash, so a duplicate can only hide behind the same id8;
    # the full sha256 in the note tells a duplicate from a collision.
    for p in sorted(list_paths(f'transcripts/%{id8}.md')):
        old, _ = read_note(p)
        fm, _ = split_frontmatter(old or '')
        if fm.get('sha256') == full:
            die(f'REFUSED: exists {p} — этот же файл уже загружен')
        if p == path:
            die(f'REFUSED: exists {p} — другой разговор с тем же id, переименуй файл')
    if write_note(path, note, '') != 'ok':
        die(f'REFUSED: exists {path}')
    print(f'WRITTEN {path} — {len(rows)} строк, метки: ' + (', '.join(labels) or 'нет')
          + (', таймкоды есть' if timecodes else ''))


if __name__ == '__main__':
    main()
