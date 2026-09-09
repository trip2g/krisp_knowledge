#!/usr/bin/env python3
"""Offline tests for the calls scripts.

    python3 tests/run.py

No network, no vault, no third-party packages. One line per case; the first
failure prints what broke and exits 1. What this does not cover is in README.md.
"""
import contextlib
import hashlib
import io
import os
import pathlib
import re
import sys
import traceback

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / 'packaging' / 'skills' / 'calls' / 'scripts'
FIXTURES = HERE / 'fixtures'
DEMO = ROOT / 'packaging' / 'demo' / 'call.txt'
SEEDED = ROOT / 'packaging' / 'vault' / 'transcripts'

sys.dont_write_bytecode = True  # a test run leaves no files behind
sys.path.insert(0, str(HERE))
import vault_stub  # noqa: E402

intake = vault_stub.load(SCRIPTS / 'intake.py', 'intake')
gate = vault_stub.load(SCRIPTS / 'gate.py', 'gate')

A = FIXTURES / 'shape_a_labels_timecodes.txt'   # Speaker N | MM:SS, words on the next line
B = FIXTURES / 'shape_b_labels_only.txt'        # Имя: реплика, no timecodes
C = FIXTURES / 'shape_c_plain.txt'              # neither
D = FIXTURES / 'shape_d_colon_trap.txt'         # a colon that is not a speaker


# ---------- harness ----------

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def refuses(fn, needle):
    """A REFUSED path: the script prints one line and exits 2."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            out = fn()
    except SystemExit as e:
        check(e.code == 2, f'exit {e.code}, expected 2')
        printed = buf.getvalue().strip()
        check(printed.startswith('REFUSED: ') and needle in printed,
              f'refusal {printed!r} does not mention {needle!r}')
        return
    check(False, f'expected a refusal containing {needle!r}, got {out!r}')


# ---------- helpers ----------

def fresh():
    return vault_stub.Vault().install(intake, gate)


def ingest(path, date, title=None):
    argv = ['intake.py', '--file', str(path), '--date', date]
    if title:
        argv += ['--title', title]
    out, code = vault_stub.run(intake, argv)
    return out, code


def ingest_ok(path, date, title=None):
    out, code = ingest(path, date, title)
    check(code == 0, f'{path.name}: exit {code}: {out}')
    m = re.search(r'(transcripts/\d{4}-\d{2}-\d{2}-([0-9a-f]{8})\.md)', out)
    check(m, f'{path.name}: no WRITTEN path in {out!r}')
    return m.group(1), m.group(2), out


def note(V, path):
    """(frontmatter, body) with the note's single trailing newline dropped."""
    fm, body = gate.split_frontmatter(V[path])
    return fm, body.rstrip('\n')


def answered(V, tpath, id8, speakers, verdict='go'):
    argv = ['gate.py', 'answer', '--call', id8, '--verdict', verdict]
    if verdict == 'go':
        argv += ['--speakers', speakers, '--agenda', 'проверка', '--continues', 'none']
    return vault_stub.run(gate, argv)


def segments(V, id8, tpath, bounds, title='Тест'):
    V[f'segments/{id8}.md'] = gate.render(
        ['type: segments', f'transcript: "{tpath}"', f'review: "review/go/{id8}.md"',
         f'title: "{title}"'],
        'Саммари для теста.\n\n## Границы\n\n' + '\n'.join(bounds) + '\n')


def ready(fixture, date, speakers, bounds, title='Тест'):
    """intake -> answer -> segments, the state cut_draft expects."""
    V = fresh()
    tpath, id8, _ = ingest_ok(fixture, date)
    answered(V, tpath, id8, speakers)
    segments(V, id8, tpath, bounds, title)
    return V, tpath, id8


def quote_lines(V, id8, tpath):
    """The `> ` lines of a draft, split into attributions and quoted words."""
    _, tbody = note(V, tpath)
    names = gate.speaker_map(V[f'review/go/{id8}.md'])
    attributions = {' | '.join(x for x in (names.get(lab, lab), tc) if x)
                    for _, lab, tc, _ in gate.utterances(tbody)}
    quoted = []
    for line in V[f'calls/draft/{id8}.md'].split('\n'):
        if line.startswith('> ') and line[2:] not in attributions:
            quoted.append(line[2:])
    return quoted


# ---------- intake: the three shapes ----------

@case('intake: Speaker N | MM:SS — header and words become one numbered line')
def _():
    V = fresh()
    tpath, id8, out = ingest_ok(A, '2026-03-11')
    fm, body = note(V, tpath)
    lines = body.split('\n')
    check(fm['lines'] == '8', f'lines={fm["lines"]}, expected 8')
    check(fm['timecodes'] == 'true', 'timecodes should be true')
    check(fm['labels'] == '["Speaker 1", "Speaker 2"]', f'labels={fm["labels"]}')
    check(lines[0] == '1 | Speaker 1 | 00:00 | Так, привет, слышно меня нормально?', lines[0])
    check(len(lines) == 8, f'{len(lines)} body lines')


@case('intake: Имя: реплика — labels, no timecodes')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(B, '2026-03-12')
    fm, body = note(V, tpath)
    check(fm['labels'] == '["Аня", "Борис"]', f'labels={fm["labels"]}')
    check(fm['timecodes'] == 'false', 'timecodes should be false')
    check(body.split('\n')[3] == '4 | Борис |  | Хорошо, верну. Кстати: сроки. Мы успеваем к пятнице?',
          'a second colon in the words must survive verbatim')


@case('intake: plain prose — no labels, no timecodes, still one line per utterance')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(C, '2026-03-13')
    fm, body = note(V, tpath)
    check(fm['labels'] == '[]', f'labels={fm["labels"]}')
    check(fm['timecodes'] == 'false', 'timecodes should be false')
    check(body.split('\n')[0].startswith('1 |  |  | Мы вчера обсуждали'), body.split('\n')[0])
    check(len(gate.utterances(body)) == 6, 'six utterances')


@case('intake: two-pass labels — a mid-sentence colon does not mint a speaker')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(D, '2026-03-14')
    fm, body = note(V, tpath)
    check(fm['labels'] == '["Аня", "Борис"]', f'labels={fm["labels"]}: «Вопрос» is not a speaker')
    rows = gate.utterances(body)
    check(rows[4][1] == '', f'line 5 must have no label, got {rows[4][1]!r}')
    check(rows[4][3] == 'Вопрос: кто это делает?', f'line 5 text={rows[4][3]!r}')
    check(rows[2][3] == 'Тогда так: сначала макеты, потом вёрстка.', f'line 3 text={rows[2][3]!r}')


# ---------- intake: the invariants ----------

@case('intake: line numbering is stable across runs')
def _():
    for f in (A, B, C, D, DEMO):
        raw = f.read_text(encoding='utf-8')
        one = intake.body_of(intake.normalise(raw))
        two = intake.body_of(intake.normalise(raw))
        check(one == two, f'{f.name}: normalising twice gave different bodies')


@case('intake: every utterance is a verbatim substring of the forwarded file')
def _():
    for f in (A, B, C, D, DEMO):
        raw = f.read_text(encoding='utf-8')
        for lab, tc, text in intake.normalise(raw):
            check(text in raw, f'{f.name}: {text!r} is not in the source')


@case('intake: the same file twice is refused, and no second note is written')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(A, '2026-03-11')
    out, code = ingest(A, '2026-03-11')
    check(code == 2, f'exit {code}, expected 2')
    check(out.startswith('REFUSED: exists ') and tpath in out, out)
    check(len([p for p in V if p.startswith('transcripts/')]) == 1, 'a second note was written')


@case('intake: the same file under another date is still the same call')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(A, '2026-03-11')
    out, code = ingest(A, '2026-07-01')
    check(code == 2 and tpath in out, out)
    check(len([p for p in V if p.startswith('transcripts/')]) == 1, 'a second note was written')


@case('intake: no --date is refused, never guessed from the clock')
def _():
    fresh()
    out, code = vault_stub.run(intake, ['intake.py', '--file', str(A)])
    check(code == 2 and out.startswith('REFUSED: unreadable') and '--date' in out, out)
    out, code = ingest(A, '11.03.2026')
    check(code == 2 and 'YYYY-MM-DD' in out, out)


@case('intake: the id is the first 8 hex of the sha256 of the body')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(A, '2026-03-11')
    fm, body = note(V, tpath)
    full = hashlib.sha256(body.encode('utf-8')).hexdigest()
    check(fm['sha256'] == full, 'frontmatter sha256 does not match the body it describes')
    check(id8 == full[:8] and tpath.endswith(f'-{full[:8]}.md'), 'the filename id is not sha256[:8]')
    check(fm['lines'] == str(len(body.split('\n'))), 'lines does not count the body')
    check(fm['chars'] == str(len(body)), 'chars does not measure the body')


# ---------- the shipped demo ----------

@case('demo: packaging/demo/call.txt reproduces the seeded transcript byte for byte')
def _():
    check(DEMO.exists(), f'{DEMO} is missing')
    body = intake.body_of(intake.normalise(DEMO.read_text(encoding='utf-8')))
    id8 = hashlib.sha256(body.encode('utf-8')).hexdigest()[:8]
    seeds = sorted(SEEDED.glob(f'*-{id8}.md'))
    check(seeds, f'no seeded note transcripts/*-{id8}.md matches demo/call.txt')
    V = fresh()
    for seed in seeds:
        want = seed.read_text(encoding='utf-8')
        fm, _ = gate.split_frontmatter(want)
        out, code = ingest(DEMO, fm['date'], fm['title'])
        check(code == 0, f'{seed.name}: intake exit {code}: {out}')
        got = V[f'transcripts/{seed.name}']
        check(got == want, f'{seed.name} differs from what intake.py produces now')


# ---------- gate 1 ----------

@case('gate: the question names the date, the title, the labels and the first lines')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(A, '2026-03-11', 'Бюджет и подрядчик')
    q = gate.question(tpath)
    check('2026-03-11' in q and '«Бюджет и подрядчик»' in q and id8 in q, q)
    check('— Speaker 1 [4 реплик]' in q and '— Speaker 2 [4 реплик]' in q, q)
    check('Первые строки:' in q and '  1 | Так, привет' in q, q)


@case('gate: a call with no labels says so instead of naming none')
def _():
    fresh()
    tpath, id8, _ = ingest_ok(C, '2026-03-13')
    q = gate.question(tpath)
    check('реплик без меток' in q, q)


@case('gate: answer refuses a label the transcript does not have')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(A, '2026-03-11')
    out, code = vault_stub.run(gate, ['gate.py', 'answer', '--call', id8, '--speakers', 'Speaker 9=Кто-то'])
    check(code == 2 and 'labels not in transcript: Speaker 9' in out, out)
    check('Speaker 1, Speaker 2' in out, 'the refusal must list the real labels')
    check(f'review/go/{id8}.md' not in V, 'a note was written despite the refusal')


@case('gate: answer writes review/go, links the transcript and mints the people')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(A, '2026-03-11')
    out, code = answered(V, tpath, id8, 'Speaker 1=Иван Петров;Speaker 2=Анна Кац')
    check(code == 0 and out.split('\n')[0] == f'WRITTEN review/go/{id8}.md', out)
    check(out.count('NEW PERSON') == 2, out)
    body = V[f'review/go/{id8}.md']
    check(f'[[{tpath}|дословно]]' in body, 'the review note must link the transcript')
    check('[[people/unconfirmed/Иван Петров|Иван Петров]]' not in body, 'people are linked as they were known when asked')
    p = V['people/unconfirmed/Анна Кац.md']
    check(f'[[{tpath}|{id8}]]' in p and f'[[calls/{id8}|{id8}]]' in p, 'a person note links the call it came from')


@case('gate: answering a second time is refused, the first answer stands')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(B, '2026-03-12')
    answered(V, tpath, id8, 'Аня=Анна Кац;Борис=Борис Лунц')
    first = V[f'review/go/{id8}.md']
    out, code = answered(V, tpath, id8, 'Аня=Кто-то Другой')
    check(code == 2 and out == f'REFUSED: exists review/go/{id8}.md', out)
    check(V[f'review/go/{id8}.md'] == first, 'the review note was overwritten')


@case('gate: «семейный» and «не разбирать» close the call in review/done')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(A, '2026-03-11')
    out, code = answered(V, tpath, id8, '', verdict='family')
    check(code == 0 and out == f'WRITTEN review/done/{id8}.md', out)
    check('reason: family' in V[f'review/done/{id8}.md'], 'the reason must be recorded')
    check(f'review/go/{id8}.md' not in V, 'nothing goes to review/go')


# ---------- gate 2: the cutter ----------

@case('cutter: quotes are cut along the line numbers, verbatim, with a line anchor')
def _():
    V, tpath, id8 = ready(A, '2026-03-11', 'Speaker 1=Иван Петров;Speaker 2=Анна Кац',
                          ['1 | Бюджет урезан, найм заморожен', '6 | Эксклюзив вычёркивают'])
    path, title, summary, heads, snaps = gate.cut_draft(id8)
    check(path == f'calls/draft/{id8}.md' and snaps == [], f'{path} {snaps}')
    check(heads == ['1 | Бюджет урезан, найм заморожен', '6 | Эксклюзив вычёркивают'], heads)
    draft = V[path]
    check('**1 | Бюджет урезан, найм заморожен**' in draft, 'the heading carries its line number')
    check(f'([[{tpath}|транскрипт]] строки 1–5)' in draft, 'the anchor is a line range')
    check(f'([[{tpath}|транскрипт]] строки 6–8)' in draft, 'the last topic runs to the end')
    check('> Иван Петров | 00:00' in draft, 'the owner\'s names replace the labels')
    check('quotes: cut_by_code' in draft, 'the note must say who cut the quotes')


@case('cutter: every quote is a verbatim substring of the forwarded file')
def _():
    plans = [
        (A, '2026-03-11', 'Speaker 1=Иван Петров;Speaker 2=Анна Кац', ['1 | Первая', '6 | Вторая']),
        (B, '2026-03-12', 'Аня=Анна Кац;Борис=Борис Лунц', ['1 | Первая', 'L4 | Вторая']),
        (C, '2026-03-13', 'весь файл=Иван Петров', ['1 | Первая', '4 | Вторая']),
        (D, '2026-03-14', 'Аня=Анна Кац;Борис=Борис Лунц', ['1 | Первая', '3 | Вторая']),
        (DEMO, '2026-01-15', 'Speaker 1=Иван Петров;Speaker 2=Анна Кац', ['1 | Первая', '8 | Вторая']),
    ]
    for fixture, date, speakers, bounds in plans:
        V, tpath, id8 = ready(fixture, date, speakers, bounds)
        gate.cut_draft(id8)
        src = fixture.read_text(encoding='utf-8')
        quoted = quote_lines(V, id8, tpath)
        check(quoted, f'{fixture.name}: the draft quoted nothing')
        for q in quoted:
            check(q in src, f'{fixture.name}: quoted text is not in the source: {q!r}')


@case('cutter: a call with no labels quotes without an attribution line')
def _():
    V, tpath, id8 = ready(C, '2026-03-13', 'весь файл=Иван Петров', ['1 | Офис', '4 | Склад'])
    gate.cut_draft(id8)
    draft = V[f'calls/draft/{id8}.md']
    check('> Мы вчера обсуждали' in draft, 'the words are still quoted')
    check('> Иван Петров' not in draft, 'no attribution can be invented for an unlabelled file')


@case('cutter: an out-of-range boundary snaps to the nearest real line and is recorded')
def _():
    V, tpath, id8 = ready(A, '2026-03-11', 'Speaker 1=Иван Петров;Speaker 2=Анна Кац',
                          ['1 | Первая', '6 | Вторая', '12 | Выдуманная'])
    path, _, _, heads, snaps = gate.cut_draft(id8)
    check(snaps == ['12->8'], f'snaps={snaps}')
    check(heads[-1] == '8 | Выдуманная', heads)
    check('boundary_snaps: "12->8"' in V[path], 'the snap must be visible in the note')


@case('cutter: a duplicate boundary is dropped and recorded, not silently merged')
def _():
    V, tpath, id8 = ready(C, '2026-03-13', 'весь файл=Иван Петров',
                          ['1 | Первая', '4 | Вторая', '4 | Дубль'])
    path, _, _, heads, snaps = gate.cut_draft(id8)
    check(snaps == ['4=dup'], f'snaps={snaps}')
    check(len(heads) == 2 and heads[1] == '4 | Вторая', heads)
    check('boundary_snaps: "4=dup"' in V[path], 'the drop must be visible in the note')


@case('cutter: a boundary past the 25-line limit is refused, not snapped')
def _():
    V, tpath, id8 = ready(B, '2026-03-12', 'Аня=Анна Кац;Борис=Борис Лунц',
                          ['1 | Первая', '999 | Из другого разговора'])
    refuses(lambda: gate.cut_draft(id8), 'outside the transcript')
    check(f'calls/draft/{id8}.md' not in V, 'a draft was written despite the refusal')


@case('cutter: the L prefix is tolerated, plain numbers are the documented form')
def _():
    V, tpath, id8 = ready(B, '2026-03-12', 'Аня=Анна Кац;Борис=Борис Лунц',
                          ['L1 | Первая', 'L4 | Вторая'])
    _, _, _, heads, snaps = gate.cut_draft(id8)
    check(heads == ['1 | Первая', '4 | Вторая'] and snaps == [], f'{heads} {snaps}')


@case('cutter: a segments note with no «## Границы» is refused')
def _():
    V, tpath, id8 = ready(A, '2026-03-11', 'Speaker 1=Иван Петров;Speaker 2=Анна Кац', [])
    refuses(lambda: gate.cut_draft(id8), 'has no "## Границы"')


# ---------- gate 2: accept ----------

@case('gate: accept appends the corrections under the draft instead of rewriting it')
def _():
    V, tpath, id8 = ready(A, '2026-03-11', 'Speaker 1=Иван Петров;Speaker 2=Анна Кац',
                          ['1 | Первая', '6 | Вторая'])
    gate.cut_draft(id8)
    draft = V[f'calls/draft/{id8}.md']
    out, code = vault_stub.run(gate, ['gate.py', 'accept', '--call', id8,
                                      '--fix', 'урезали на 20, а не на 30',
                                      '--extract', 'Анна Кац; договор с подрядчиком'])
    check(code == 0 and out == f'WRITTEN calls/{id8}.md — вынести: 2', out)
    final = V[f'calls/{id8}.md']
    check('## Правки владельца (' in final and 'урезали на 20' in final, 'the owner\'s words are missing')
    check('## Вынести\n- Анна Кац\n- договор с подрядчиком' in final, 'the extract list is missing')
    check(V[f'calls/draft/{id8}.md'] == draft, 'the draft was rewritten')
    _, dbody = gate.split_frontmatter(draft)
    check(dbody.split('\n## Правки')[0].strip() in final, 'the draft body must survive intact')


@case('gate: accept with nothing to extract says so, and refuses a second time')
def _():
    V, tpath, id8 = ready(B, '2026-03-12', 'Аня=Анна Кац;Борис=Борис Лунц', ['1 | Первая'])
    gate.cut_draft(id8)
    out, code = vault_stub.run(gate, ['gate.py', 'accept', '--call', id8, '--extract', 'none'])
    check(code == 0 and out.endswith('выносить нечего'), out)
    check('## Вынести\n- (ничего)' in V[f'calls/{id8}.md'], 'the empty list must still be written')
    out, code = vault_stub.run(gate, ['gate.py', 'accept', '--call', id8])
    check(code == 2 and out == f'REFUSED: exists calls/{id8}.md', out)


# ---------- the cron and the rest ----------

@case('gate: ask cuts the pending draft first and marks it in the state note')
def _():
    V, tpath, id8 = ready(A, '2026-03-11', 'Speaker 1=Иван Петров;Speaker 2=Анна Кац',
                          ['1 | Бюджет урезан', '6 | Эксклюзив вычёркивают'])
    out, code = vault_stub.run(gate, ['gate.py', 'ask'])
    check(code == 0 and out.startswith(f'Готов разбор разговора {id8}'), out)
    check('— 1 | Бюджет урезан' in out and '— 6 | Эксклюзив вычёркивают' in out, out)
    check('## Источники' not in out, 'the reminder must carry the summary, not the links block')
    check(f'"{id8}"' in V[gate.STATE_PATH], 'the state note must record the question')
    out2, _ = vault_stub.run(gate, ['gate.py', 'ask'])
    check(out2 == '', 'a call asked about a minute ago must not be asked again')


@case('gate: ask asks about a fresh call and stays silent when nothing is pending')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(A, '2026-03-11')
    out, code = vault_stub.run(gate, ['gate.py', 'ask'])
    check(code == 0 and f'(созвон {id8}' in out, out)
    out2, _ = vault_stub.run(gate, ['gate.py', 'ask'])
    check(out2 == '', 'the same call must not be asked twice within the reminder window')
    answered(V, tpath, id8, 'Speaker 1=Иван Петров;Speaker 2=Анна Кац')
    out3, _ = vault_stub.run(gate, ['gate.py', 'ask'])
    check(out3 == '', 'an answered call must leave the queue')


@case('gate: an old forwarded call is asked about — the default boundary is not today')
def _():
    fresh()
    tpath, id8, _ = ingest_ok(A, '2019-05-04')
    out, code = vault_stub.run(gate, ['gate.py', 'ask'])
    check(code == 0 and id8 in out, f'a 2019 call must still be asked about: {out!r}')


@case('gate: person promotes people/unconfirmed and keeps the call link')
def _():
    V, tpath, id8 = ready(B, '2026-03-12', 'Аня=Анна Кац;Борис=Борис Лунц', ['1 | Первая'])
    out, code = vault_stub.run(gate, ['gate.py', 'person', '--name', 'Борис Лунц',
                                      '--role', 'коллега', '--note', 'делает фронт'])
    check(code == 0 and out.startswith('WRITTEN people/Борис Лунц.md'), out)
    p = V['people/Борис Лунц.md']
    check('confirmed: true' in p and 'role: коллега' in p, p)
    check('aliases: ["Борис"]' in p, 'the label must survive as an alias')
    check(f'[[calls/{id8}|{id8}]]' in p, 'the call link must survive the promotion')
    check('## Слово владельца (' in p and 'делает фронт' in p, 'the owner\'s words are missing')
    check('people/unconfirmed/Борис Лунц.md' not in V, 'the unconfirmed card was not hidden')


@case('gate: retrigger stamps requeued without touching the body')
def _():
    V, tpath, id8 = ready(C, '2026-03-13', 'весь файл=Иван Петров', ['1 | Первая'])
    _, before = gate.split_frontmatter(V[f'review/go/{id8}.md'])
    out, code = vault_stub.run(gate, ['gate.py', 'retrigger', '--call', id8])
    check(code == 0 and 'requeued=' in out, out)
    fm, after = gate.split_frontmatter(V[f'review/go/{id8}.md'])
    check('requeued' in fm and after == before, 'retrigger must only stamp the frontmatter')


@case('gate: status prints the anchors the skill needs and writes nothing')
def _():
    V, tpath, id8 = ready(A, '2026-03-11', 'Speaker 1=Иван Петров;Speaker 2=Анна Кац', ['1 | Первая'])
    vault_stub.run(gate, ['gate.py', 'ask'])       # cuts the draft, marks gate 2
    before = dict(V)
    out, code = vault_stub.run(gate, ['gate.py', 'status'])
    check(code == 0 and f'LAST REVIEWED {id8}' in out, out)
    check('gate1 pending:' in out and 'gate2 pending:' in out, out)
    check(dict(V) == before, 'status wrote to the vault')


@case('gate: init draws the archive boundary')
def _():
    V = fresh()
    out, code = vault_stub.run(gate, ['gate.py', 'init', '--since', '2026-01-01'])
    check(code == 0 and out == f'WRITTEN {gate.STATE_PATH} since=2026-01-01', out)
    tpath, id8, _ = ingest_ok(A, '2025-12-31')
    out, _ = vault_stub.run(gate, ['gate.py', 'ask'])
    check(out == '', 'a call before the boundary must never be asked about')


# ---------- the contract the rest of the package depends on ----------

@case('contract: the sha256 recipe is reproducible from the note on disk')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(DEMO, '2026-01-15')
    fm, body = gate.split_frontmatter(V[tpath])
    again = hashlib.sha256(body.rstrip('\n').encode('utf-8')).hexdigest()
    check(again == fm['sha256'], 'body-after-frontmatter, rstripped, UTF-8 must rehash to sha256')
    check(V[tpath].endswith('пятницы.\n'), 'the note on disk ends with exactly one newline')


@case('contract: nothing branches on the source field')
def _():
    V = fresh()
    tpath, id8, _ = ingest_ok(DEMO, '2026-01-15')
    V[tpath] = V[tpath].replace('source: telegram', 'source: demo')
    q = gate.question(tpath)
    check(id8 in q, 'a note with source: demo must still produce a question')
    out, code = answered(V, tpath, id8, 'Speaker 1=Иван Петров;Speaker 2=Анна Кац')
    check(code == 0, f'source: demo broke answer: {out}')


@case('contract: circles are gone from the command surface')
def _():
    text = (SCRIPTS / 'gate.py').read_text(encoding='utf-8') + (SCRIPTS / 'intake.py').read_text(encoding='utf-8')
    for word in ('circle', 'subgraph', 'call_id'):
        check(word not in text.lower(), f'{word!r} is still in the scripts')
    with open(os.devnull, 'w') as null, contextlib.redirect_stderr(null):
        out, code = vault_stub.run(gate, ['gate.py', 'circles'])
    check(code == 2, 'the circles subcommand must not exist')


def main():
    for name, fn in CASES:
        try:
            fn()
        except Exception:
            print(f'FAIL  {name}')
            print()
            traceback.print_exc()
            return 1
        print(f'ok    {name}')
    print(f'\n{len(CASES)} cases, all green.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
