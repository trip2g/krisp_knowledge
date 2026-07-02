---
description: "Call note -> concept glossary, daily note, topic logs (step 2 of 2)"
model: openai/gpt-5.4-mini
tools: [search, read_note, write_note, patch_note]
read_patterns: ["calls/**", "transcripts/**", "concepts/**", "daily/**", "log/**"]
write_patterns: ["concepts/**", "daily/**", "log/**"]
mode: change
trigger_on: [create, update]
trigger_include: ["calls/**"]
for_each: changed_files
max_depth: 3
concurrency: queue_one
max_steps: 20
max_tokens: 60000
---
A call note (summary + topic segments with verbatim quotes) was just written:
`{{ change_file.Path }}`. Distribute its knowledge into the vault: concept notes, the
daily note, and topic logs. The call's date and time come from `created_at` in its
frontmatter - never from the current clock.

## 1. Concepts (glossary)

For every named entity mentioned in the call - person, org, project, tool, term -
maintain one note at `concepts/<slug>.md` (`slug` = short latin kebab-case of the
canonical name). Named entities only: "the new employee" is not an entity. Tools and
services mentioned in passing (a design tool, a database) count as entities too.
Whenever you link a concept, use its slug: `[[<slug>|Name]]`.

- First `search` for the entity name (and plausible spellings) to find an existing
  note. ASR mishears names ("Cloud Code" for "Claude Code"): if an existing concept is
  clearly the same thing, MERGE into it and add the new spelling to `aliases` - do not
  create a duplicate.
- Read the existing note with `read_note` before rewriting it; keep every existing
  mention. Append the new mention, never rewrite old ones.
- Each mention quotes the exact call-note segment where the entity came up (evidence
  that cannot hallucinate), with a timerange link back to the call.

Format of `concepts/<slug>.md`:

---
title: "<canonical name>"
type: concept
kind: <person|org|project|tool|term>
aliases: [<raw spellings seen>]
mentions: <total count>
---
<one-line definition, from context>

## Mentions

### [[<call note path without .md>|<call title>]] (<YYYY-MM-DD>)
<one line: how it came up>
> <verbatim quote from the call note>

## 2. Daily note

Maintain `daily/YYYY-MM-DD.md` for the call's date (from `created_at`). Read it first
if it exists; merge, do not drop existing lines. Format - action checkboxes on top,
dated log below, no summary:

---
title: "<YYYY-MM-DD>"
type: daily
---
- [ ] <owner>: <action item from a call this day> ([[<call note path without .md>|<call title>]])

## Log

- HH:MM [[<call note path without .md>|<call title>]] - one-line gist with [[<slug>|concept]] links

An action promised "tomorrow" lands on the NEXT day's daily note, not this one.

## 3. Topic logs

A recurring subject (a project or theme that spans calls, e.g. a project's onboarding
work) gets an append-only note `log/<slug>.md`. Read it first if it exists. Append a
new dated section at the end; NEVER rewrite old entries:

---
title: "<topic>"
type: log
entries: <count>
---

### [[<YYYY-MM-DD>]]
- <what happened on this subject in this call, one or two lines, with [[<slug>|concept]] links>

## Rules

- Every claim cites its source and the citation IS the source: quote the verbatim
  lines behind each claim. Your summary is the value-add; the quote underneath is the
  proof.
- A quote is a CONTIGUOUS block of lines copied character-for-character from the call
  note, speaker labels included. Never stitch non-adjacent lines together and never
  alter a speaker label or timecode. When only part of a topic is relevant, quote the
  2-4 adjacent lines around it.
- Decisions, open questions, and actions carry an owner when the call names one.
- Write only under `concepts/`, `daily/`, `log/`. Do not touch the call note.

The call note:
{{ change_file.Content }}
