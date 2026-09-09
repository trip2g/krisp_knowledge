#!/usr/bin/env python3
"""Gates of the calls pipeline: one call, one question, one note.

Subcommands (every outcome is one line on stdout; the skill says to relay it
verbatim and stop):

  ask                 cron, no model. Asks about the oldest call not yet asked
                      about; when every pending call has been asked, reminds
                      about the oldest one whose question is older than 24 h.
                      Prints nothing when there is nothing to ask.
  answer              the owner answered about a call. Writes review/go/<id8>.md
                      or review/done/<id8>.md (create-only, never overwrites),
                      creates people/unconfirmed/<name>.md for names the vault
                      does not know, prints the follow-up question if any.
  person              the owner told who a person is: people/unconfirmed/<name>
                      becomes people/<name>.
  retrigger           re-save a review note so the segment role runs again (a
                      role installed after the answer never saw the event).
  accept              gate 2: the owner read the draft. Writes calls/<id8>.md —
                      the draft plus his corrections and his «Вынести» list.
  status              queue lengths, writes nothing.
  init --since DATE   set the archive boundary in state/calls.md.

Calls arrive as forwarded .txt files through intake.py, so a call is addressed
by line number, never by timecode: a transcript body is one utterance per line,
`<n> | <label> | <MM:SS> | <текст>`, with label and timecode empty when the
file had none. docs: ../SKILL.md

Vault access: the agent's own trip2g over GraphQL, Bearer token from
TRIP2G_MCP_TOKEN_FILE (default /alloc/trip2g/mcp-token), URL derived from
TRIP2G_MCP_URL (default http://127.0.0.1:8080/_system/mcp).

State the script owns: state/calls.md — `since` (calls before it are the
archive and are never asked) and `asked` (id8 -> time of the last question).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

TOKEN_FILE = os.environ.get('TRIP2G_MCP_TOKEN_FILE', '/alloc/trip2g/mcp-token')
MCP_URL = os.environ.get('TRIP2G_MCP_URL', 'http://127.0.0.1:8080/_system/mcp')
GRAPHQL_URL = MCP_URL.replace('/_system/mcp', '/_system/graphql')
STATE_PATH = 'state/calls.md'
REMIND_HOURS = 24
# Everything forwarded is there because the owner forwarded it, so the default
# boundary asks about all of it; `init --since` still draws one if he wants.
SINCE_FLOOR = '1970-01-01'
# A boundary this far outside the transcript is not a slip, it is another call.
SNAP_MAX_LINES = 25
OWNER = os.environ.get('CALLS_OWNER', 'Владелец')


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
        'X-trip2g-client': 'calls-gate',
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


def hide_note(path):
    d = gql('''mutation($i: UpdateNotesInput!){ updateNotes(input: $i){ __typename
      ... on ErrorPayload { message } } }''', {'i': {'changes': [{'hide': {'path': path}}]}})
    return d['updateNotes']['__typename'] == 'UpdateNotesSuccessPayload'


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


def id8_of(path):
    m = re.search(r'([0-9a-f]{8})\.md$', path)
    return m.group(1) if m else None


def date_of(path):
    m = re.search(r'(\d{4}-\d{2}-\d{2})-[0-9a-f]{8}\.md$', path)
    return m.group(1) if m else None


def utterances(body):
    """[(line_no, label, timecode, text)] from the numbered transcript body.

    maxsplit=3 so an utterance may itself contain `|`; label and timecode are
    empty strings when the forwarded file carried none."""
    rows = []
    for line in body.split('\n'):
        parts = line.split(' | ', 3)
        if len(parts) == 4 and parts[0].strip().isdigit():
            rows.append((int(parts[0]), parts[1].strip(), parts[2].strip(), parts[3]))
    return rows


# ---------- state ----------

def load_state():
    content, h = read_note(STATE_PATH)
    if content is None:
        return {'since': SINCE_FLOOR, 'asked': {}, 'asked2': {}}, None
    fm, body = split_frontmatter(content)
    asked = {}
    m = re.search(r'```json\n(.*?)\n```', body, re.S)
    if m:
        try:
            asked = json.loads(m.group(1))
        except ValueError:
            asked = {}
    asked.setdefault('gate1', {})
    asked.setdefault('gate2', {})
    return {'since': fm.get('since') or SINCE_FLOOR,
            'asked': asked['gate1'], 'asked2': asked['gate2']}, h


def save_state(state, h):
    """Both gates in one note. The marks are what keeps a question from being
    asked again on the next tick, so a failure to write is loud: a silent one
    turns the cron into a repeater."""
    marks = {'gate1': state.get('asked', {}), 'gate2': state.get('asked2', {})}
    body = ('Состояние скилла calls. `since` — разговоры раньше этой даты считаются '
            'архивом и не спрашиваются. `gate1` — когда по разговору последний раз задан '
            'вопрос ворот 1, `gate2` — ворот 2.\n\n```json\n'
            + json.dumps(marks, ensure_ascii=False, indent=1) + '\n```\n')
    content = render(['type: state', 'since: ' + state['since']], body)
    r = write_note(STATE_PATH, content, h or '')
    if r != 'ok':
        die('REFUSED: vault state note changed under us')


# ---------- gate 2: the quote cutter ----------

# The boundary map is all the model produces. Quotes are cut here, by code,
# along its line numbers: a slice of the transcript cannot be shortened,
# doubled or invented, and the length of a call stops being a risk.

BOUND_RE = re.compile(r'^L?(\d+)\s*\|\s*(.+)$')


def speaker_map(review_body_and_meta):
    """The owner's map from the review note. Its frontmatter is nested, which
    split_frontmatter flattens away, so it is read from the raw text."""
    names, inside = {}, False
    for line in review_body_and_meta.split('\n'):
        if re.match(r'^speakers:\s*$', line):
            inside = True
            continue
        if inside:
            m = re.match(r'^\s+"?([^":]+)"?:\s*"?(.*?)"?\s*$', line)
            if m:
                names[m.group(1)] = m.group(2)
            else:
                inside = False
    return names


def snap(bounds, first, last):
    """A boundary outside the transcript is pulled to the nearest real line and
    the snap is printed in the note: an invented boundary must be visible."""
    fixed, snaps, seen = [], [], set()
    for n, head in sorted(bounds):
        k = min(max(n, first), last)
        if abs(k - n) > SNAP_MAX_LINES:
            die(f'REFUSED: unreadable boundary {n} is outside the transcript ({first}–{last})')
        if k != n:
            snaps.append(f'{n}->{k}')
        if k in seen:
            snaps.append(f'{n}=dup')
            continue
        seen.add(k)
        fixed.append((k, head))
    return fixed, snaps


def cut_draft(id8):
    """segments/<id8>.md + transcript + review -> calls/draft/<id8>.md."""
    seg_raw, _ = read_note(f'segments/{id8}.md')
    if seg_raw is None:
        die(f'REFUSED: unreadable segments/{id8}.md')
    seg, seg_body = split_frontmatter(seg_raw)
    tx_raw, _ = read_note(seg.get('transcript', ''))
    if tx_raw is None:
        die(f'REFUSED: unreadable {seg.get("transcript")!r} named by the segments note')
    tx, tx_body = split_frontmatter(tx_raw)
    rv_raw, _ = read_note(seg.get('review', ''))
    if rv_raw is None:
        die(f'REFUSED: unreadable {seg.get("review")!r} named by the segments note')
    names = speaker_map(rv_raw)

    utt = [(n, names.get(lab, lab), tc, text) for n, lab, tc, text in utterances(tx_body)]
    if not utt:
        die(f'REFUSED: unreadable transcript {seg.get("transcript")} has no numbered lines')

    bounds, summary_lines, mode = [], [], None
    for line in seg_body.split('\n'):
        if line.startswith('## Границы'):
            mode = 'b'
            continue
        if mode == 'b':
            m = BOUND_RE.match(line.strip())
            if m:
                bounds.append((int(m.group(1)), m.group(2).strip()))
        else:
            summary_lines.append(line)
    if not bounds:
        die(f'REFUSED: unreadable segments/{id8}.md has no "## Границы" lines')
    summary = '\n'.join(summary_lines).strip()
    bounds, snaps = snap(bounds, utt[0][0], utt[-1][0])

    tx_path = seg.get('transcript', '')
    meta = ['type: call_draft', 'title: ' + yaml_str(seg.get('title', '')),
            'date: ' + yaml_str(tx.get('date', '')),
            'transcript: ' + yaml_str(tx_path), 'review: ' + yaml_str(seg.get('review', '')),
            'segments: ' + yaml_str(f'segments/{id8}.md'), 'quotes: cut_by_code',
            'boundary_snaps: ' + yaml_str(' '.join(snaps))]
    out = [summary, '',
           '## Источники', '',
           f'- Сырой транскрипт: [[{tx_path}|дословно]]',
           f'- Ответ владельца на воротах: [[{seg.get("review", "")}|кто говорил и о чём]]',
           f'- Карта тем: [[segments/{id8}|границы]]',
           '', '## Темы', '']
    for i, (n, head) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else None
        chunk = [u for u in utt if u[0] >= n and (end is None or u[0] < end)]
        out += [f'**{n} | {head}**', '']
        for ln, name, tc, text in chunk:
            who = ' | '.join(x for x in (name, tc) if x)
            out += ([f'> {who}'] if who else []) + [f'> {text}', '>']
        if chunk:
            out[-1] = f'([[{tx_path}|транскрипт]] строки {chunk[0][0]}–{chunk[-1][0]})'
            out.append('')
    path = f'calls/draft/{id8}.md'
    if write_note(path, render(meta, '\n'.join(out)), '') != 'ok':
        die(f'REFUSED: exists {path}')
    return path, seg.get('title', ''), summary, [f'{n} | {head}' for n, head in bounds], snaps


# ---------- queue ----------

def pending(state):
    transcripts = list_paths('transcripts/%')
    done = {id8_of(p) for p in list(list_paths('review/go/%')) + list(list_paths('review/done/%'))}
    q = []
    for p in transcripts:
        d, i = date_of(p), id8_of(p)
        if not d or not i or d < state['since'] or i in done:
            continue
        q.append((d, i, p))
    q.sort()
    return q


def pending_gate2():
    """A segments note whose draft is not cut yet, and a draft the owner has
    not accepted yet. Both are set differences over id8, like gate 1."""
    segs = {id8_of(p) for p in list_paths('segments/%') if id8_of(p)}
    drafts = {id8_of(p) for p in list_paths('calls/draft/%') if id8_of(p)}
    done = {id8_of(p) for p in list_paths('calls/%') if '/draft/' not in p and id8_of(p)}
    return sorted(segs - drafts - done), sorted(drafts - done)


def gate2_question(id8, title, summary, heads, snaps):
    lines = [f'Готов разбор разговора {id8}: «{title}».', '', summary, '', 'Темы:']
    lines += [f'— {h}' for h in heads[:12]]
    if len(heads) > 12:
        lines.append(f'— … ещё {len(heads) - 12}')
    if snaps:
        lines.append('Границы, которые пришлось притянуть к ближайшей строке: ' + ', '.join(snaps))
    lines += ['', 'Прочитай и скажи: что неточно, чего не хватает, и что вынести в заметки '
                  '(имена людей, нити, планы созвонов). Не нужно выносить — так и скажи.']
    return '\n'.join(lines)


def question(path):
    content, _ = read_note(path)
    if content is None:
        die(f'REFUSED: unreadable {path}')
    fm, body = split_frontmatter(content)
    if not fm.get('sha256') or not fm.get('date'):
        die(f'REFUSED: unreadable {path}')
    rows = utterances(body)
    by = {}
    for n, lab, tc, text in rows:
        if lab:
            by.setdefault(lab, []).append((n, text))
    title = fm.get('title', '')
    out = [f'Новый разговор {fm["date"]}' + (f', «{title}»' if title else '')
           + f' (созвон {id8_of(path)}, {fm.get("lines", len(rows))} строк).']
    for lab, items in list(by.items())[:5]:
        picks = [items[0]] + ([items[len(items) // 2]] if len(items) > 3 else [])
        sample = ' … '.join(f'«{t[:110]}»' for _, t in picks if t)
        out.append(f'— {lab} [{len(items)} реплик]: {sample}')
    if not by:
        out.append('— реплик без меток: в файле нет имён говорящих.')
    out.append('Первые строки:')
    out += [f'  {n} | {text[:110]}' for n, _, _, text in rows[:3]]
    out.append('Ответь голосом или текстом: кто под какими метками, о чём разговор, продолжение какого прошлого '
               'разговора, разбирать ли вообще (или «семейный» / «не разбирать»).')
    return '\n'.join(out)


# ---------- commands ----------

def cmd_ask(args):
    state, h = load_state()
    if args.since:
        state['since'] = args.since
    now = dt.datetime.now(dt.timezone.utc)

    # Gate 2 goes first: a call already answered for is closer to being a note
    # than a call not yet looked at, and the owner asked for one at a time.
    to_cut, to_review = pending_gate2()
    if to_cut and not args.dry_run:
        id8 = to_cut[0]
        _, title, summary, heads, snaps = cut_draft(id8)
        state['asked2'][id8] = now.isoformat(timespec='minutes')
        save_state(state, h)
        print(gate2_question(id8, title, summary, heads, snaps))
        return
    for id8 in to_review:
        last = state['asked2'].get(id8)
        if last and not args.force:
            try:
                if now - dt.datetime.fromisoformat(last) < dt.timedelta(hours=REMIND_HOURS):
                    continue
            except ValueError:
                pass
        raw, _ = read_note(f'calls/draft/{id8}.md')
        if raw is None:
            continue
        meta, body = split_frontmatter(raw)
        summary = body.split('\n## Источники')[0].strip()
        heads = re.findall(r'^\*\*(\d+ \| .+?)\*\*$', body, re.M)
        if not args.dry_run:
            state['asked2'][id8] = now.isoformat(timespec='minutes')
            save_state(state, h)
        print(gate2_question(id8, meta.get('title', ''), summary, heads, []))
        return

    q = pending(state)
    if not q:
        return  # silence: nothing pending

    def due(when):
        """A question already asked comes back only after REMIND_HOURS."""
        try:
            return now - dt.datetime.fromisoformat(when) >= dt.timedelta(hours=REMIND_HOURS)
        except ValueError:
            return True

    # An unanswered call must not hold the queue: a fresh call is asked about
    # even while an older one waits for its answer. Never-asked first, oldest
    # of those; only when every pending call has been asked does the oldest
    # overdue one come back as a reminder.
    fresh = [x for x in q if x[1] not in state['asked']]
    if fresh:
        d, i, p = fresh[0]
    elif args.force:
        d, i, p = q[0]
    else:
        overdue = [x for x in q if due(state['asked'][x[1]])]
        if not overdue:
            return  # everything pending was asked recently: silence
        d, i, p = min(overdue, key=lambda x: state['asked'][x[1]])
    text = question(p)
    if args.dry_run:
        print(text)
        return
    state['asked'][i] = now.isoformat(timespec='minutes')
    save_state(state, h)
    print(text)


def find_transcript(id8):
    for p in list_paths(f'transcripts/%{id8}.md'):
        return p
    die(f'REFUSED: unreadable no transcript for {id8}')


def known_people():
    people = {os.path.basename(p)[:-3] for p in list_paths('people/%') if '/unconfirmed/' not in p and not os.path.basename(p).startswith('_')}
    unconfirmed = {os.path.basename(p)[:-3] for p in list_paths('people/unconfirmed/%') if not os.path.basename(p).startswith('_')}
    return people, unconfirmed


def cmd_answer(args):
    id8 = args.call.strip().lower()
    if not re.fullmatch(r'[0-9a-f]{8}', id8):
        die('REFUSED: unreadable call id must be 8 hex chars')
    tpath = find_transcript(id8)
    content, _ = read_note(tpath)
    fm, body = split_frontmatter(content or '')
    if not fm.get('date'):
        die(f'REFUSED: unreadable {tpath}')
    for existing in (f'review/go/{id8}.md', f'review/done/{id8}.md'):
        if list_paths(existing):
            die(f'REFUSED: exists {existing}')
    if args.verdict in ('family', 'skip'):
        note = render(['type: review', 'date: ' + fm['date'], 'transcript: ' + tpath, 'reason: ' + args.verdict], '')
        path = f'review/done/{id8}.md'
        r = write_note(path, note, '')
        print(f'WRITTEN {path}' if r == 'ok' else f'REFUSED: exists {path}')
        return
    labels = {lab for _, lab, _, _ in utterances(body) if lab}
    speakers = []
    for pair in (args.speakers or '').split(';'):
        if '=' not in pair:
            continue
        lab, name = (x.strip() for x in pair.split('=', 1))
        if lab and name:
            speakers.append((lab, name))
    if not speakers:
        die('REFUSED: unreadable no speakers given (label=name;label=name)')
    unknown_labels = [lab for lab, _ in speakers if labels and lab not in labels]
    if unknown_labels:
        die('REFUSED: unreadable labels not in transcript: ' + ', '.join(unknown_labels) + '. Метки в транскрипте: ' + ', '.join(sorted(labels)))
    meta = ['type: review', 'date: ' + fm['date'], 'transcript: ' + tpath, 'speakers:']
    meta += [f'  {yaml_str(lab)}: {yaml_str(name)}' for lab, name in speakers]
    cont = [c.strip() for c in (args.continues or '').split(',') if c.strip() and c.strip().lower() != 'none']
    meta.append('continues:' + ('' if cont else ' []'))
    meta += [f'  - calls/{c}' for c in cont]
    # Links, not plain strings: the graph is built from what the body points at,
    # so a note that only names its source is a leaf. docs: ../SKILL.md
    people, unconfirmed = known_people()
    who = []
    for lab, name in speakers:
        folder = 'people' if name in people else 'people/unconfirmed' if name in unconfirmed else ''
        who.append(f'[[{folder}/{name}|{name}]] ({lab})' if folder else f'{name} ({lab})')
    links = [f'Транскрипт: [[{tpath}|дословно]]', 'Кто говорил: ' + ', '.join(who)]
    if cont:
        links.append('Продолжение: ' + ', '.join(f'[[calls/{c}|разговор {c}]]' for c in cont))
    body_out = (args.agenda or '').strip() + '\n\n' + '\n'.join(links) + '\n'
    if args.plans:
        body_out += '\n## Планы созвонов\n' + '\n'.join('- ' + p.strip() for p in args.plans.split(';') if p.strip()) + '\n'
    path = f'review/go/{id8}.md'
    r = write_note(path, render(meta, body_out), '')
    if r != 'ok':
        die(f'REFUSED: exists {path}')
    print(f'WRITTEN {path}')
    followups = []
    for lab, name in speakers:
        if name == OWNER or name.startswith('Speaker') or name in people or name in unconfirmed:
            continue
        ppath = f'people/unconfirmed/{name}.md'
        pnote = render(['title: ' + yaml_str(name), 'type: person', 'confirmed: false',
                        'first: ' + fm['date'], 'aliases: [' + yaml_str(lab) + ']'],
                       f'Впервые встречен в разговоре [[{tpath}|{id8}]] ({fm["date"]}) под меткой {lab}.'
                       f'\n\n## По разговорам\n- {fm["date"]}: разговор [[calls/{id8}|{id8}]], транскрипт [[{tpath}|дословно]]\n')
        if write_note(ppath, pnote, '') == 'ok':
            followups.append(name)
    for name in followups:
        print(f'NEW PERSON {name}: спроси владельца, кто это (роль, как связаны, как ещё звучит имя), потом `gate.py person --name "{name}" --note "..." --role ...`')


def cmd_person(args):
    name = args.name.strip()
    src = f'people/unconfirmed/{name}.md'
    dst = f'people/{name}.md'
    content, h = read_note(src)
    if content is None:
        die(f'REFUSED: unreadable {src}')
    fm, body = split_frontmatter(content)
    meta = ['title: ' + yaml_str(name), 'type: person', 'confirmed: true',
            'role: ' + (args.role or 'unknown'), 'first: ' + fm.get('first', ''),
            'aliases: ' + (fm.get('aliases') or '[]')]
    today = dt.date.today().isoformat()
    body_out = body.rstrip('\n') + f'\n\n## Слово владельца ({today})\n{args.note.strip()}\n'
    r = write_note(dst, render(meta, body_out), '')
    if r != 'ok':
        die(f'REFUSED: exists {dst}')
    hidden = hide_note(src)
    print(f'WRITTEN {dst}' + ('' if hidden else f' (не удалось скрыть {src}, скрой руками)'))


def cmd_init(args):
    """Set the archive boundary: calls dated before --since are never asked."""
    state, h = load_state()
    state['since'] = args.since
    save_state(state, h)
    print(f'WRITTEN {STATE_PATH} since={args.since}')


def cmd_retrigger(args):
    """A change webhook fires on save, and a role installed later never sees the
    saves that came before it. Re-saving the review note is the replay."""
    id8 = args.call.strip().lower()
    path = f'review/go/{id8}.md'
    raw, h = read_note(path)
    if raw is None:
        die(f'REFUSED: unreadable {path}')
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    if 'requeued:' in raw:
        out = re.sub(r'^requeued: .*$', 'requeued: ' + stamp, raw, count=1, flags=re.M)
    else:
        end = raw.index('\n---', 3)
        out = raw[:end] + '\nrequeued: ' + stamp + raw[end:]
    if write_note(path, out, h) != 'ok':
        die(f'REFUSED: vault {path} changed under us')
    print(f'WRITTEN {path} requeued={stamp}')


def cmd_accept(args):
    """Gate 2: the owner read the draft. The draft is not rewritten — his
    corrections are a dated section under it, so a reader sees what came from
    the model and what from him."""
    id8 = args.call.strip().lower()
    if not re.fullmatch(r'[0-9a-f]{8}', id8):
        die('REFUSED: unreadable call id must be 8 hex chars')
    if list_paths(f'calls/{id8}.md'):
        die(f'REFUSED: exists calls/{id8}.md')
    raw, _ = read_note(f'calls/draft/{id8}.md')
    if raw is None:
        die(f'REFUSED: unreadable calls/draft/{id8}.md (нечего принимать)')
    meta_raw, body = split_frontmatter(raw)
    meta = ['type: call', 'title: ' + yaml_str(meta_raw.get('title', '')),
            'date: ' + yaml_str(meta_raw.get('date', '')),
            'transcript: ' + yaml_str(meta_raw.get('transcript', '')),
            'review: ' + yaml_str(meta_raw.get('review', '')),
            'draft: ' + yaml_str(f'calls/draft/{id8}.md'),
            'accepted_at: ' + dt.date.today().isoformat()]
    extract = [x.strip() for x in (args.extract or '').split(';') if x.strip() and x.strip().lower() != 'none']
    out = body.rstrip('\n')
    if args.fix:
        out += f'\n\n## Правки владельца ({dt.date.today().isoformat()})\n{args.fix.strip()}\n'
    out += '\n## Вынести\n' + ('\n'.join('- ' + x for x in extract) if extract else '- (ничего)') + '\n'
    path = f'calls/{id8}.md'
    if write_note(path, render(meta, out), '') != 'ok':
        die(f'REFUSED: exists {path}')
    print(f'WRITTEN {path}' + (f' — вынести: {len(extract)}' if extract else ' — выносить нечего'))


def cmd_status(args):
    state, _ = load_state()
    q = pending(state)
    # Both gates print what they last asked about, because the question itself
    # is delivered by cron outside the agent's conversation: a bare «всё ок»
    # has no anchor without these two lines.
    to_cut, to_review = pending_gate2()
    if state.get('asked2'):
        last2 = max(state['asked2'].items(), key=lambda kv: kv[1])
        if last2[0] in to_review:
            print(f'LAST REVIEWED {last2[0]} {last2[1]} (ждёт accept: правки и «Вынести»)')
    if state['asked']:
        last = max(state['asked'].items(), key=lambda kv: kv[1])
        print(f'LAST ASKED {last[0]} {last[1]}')
    print(f'gate1 pending: {len(q)} (since {state["since"]}); '
          f'gate2 pending: {len(to_cut)} к нарезке + {len(to_review)} к приёмке; '
          f'asked: {len(state["asked"])}')
    for d, i, p in q[:10]:
        print(f'  {d} {i} asked={state["asked"].get(i, "-")}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('ask'); a.add_argument('--since'); a.add_argument('--dry-run', action='store_true'); a.add_argument('--force', action='store_true')
    b = sub.add_parser('answer'); b.add_argument('--call', required=True); b.add_argument('--verdict', choices=['go', 'family', 'skip'], default='go')
    b.add_argument('--speakers', help='"Speaker 1=Иван Петров;Speaker 2=Анна Кац"'); b.add_argument('--agenda', default='')
    b.add_argument('--continues', help='id8[,id8] or none'); b.add_argument('--plans', help='"с кем и о чём; ещё"')
    r = sub.add_parser('retrigger'); r.add_argument('--call', required=True)
    f = sub.add_parser('accept'); f.add_argument('--call', required=True)
    f.add_argument('--fix', help='что неточно и чего не хватает — словами владельца')
    f.add_argument('--extract', help='"Анна Кац; пилот с Друзьями" — что вынести в заметки')
    c = sub.add_parser('person'); c.add_argument('--name', required=True); c.add_argument('--note', required=True); c.add_argument('--role')
    sub.add_parser('status')
    d = sub.add_parser('init'); d.add_argument('--since', required=True, help='YYYY-MM-DD: calls before it are the archive')
    args = ap.parse_args()
    {'ask': cmd_ask, 'answer': cmd_answer, 'person': cmd_person, 'status': cmd_status,
     'init': cmd_init, 'accept': cmd_accept, 'retrigger': cmd_retrigger}[args.cmd](args)


if __name__ == '__main__':
    main()
