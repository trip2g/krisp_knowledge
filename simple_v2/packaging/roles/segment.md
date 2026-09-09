---
description: "review/go -> boundary map: topics by line number, inferred title, summary (LLM, small output)"
fleet_id: codex
tools: [read_note, write_note]
read_patterns: ["transcripts/**", "review/**"]
write_patterns: ["segments/**"]
mode: change
trigger_on: [create, update]
trigger_include: ["review/go/**"]
for_each: changed_files
max_depth: 3
concurrency: skip
max_steps: 6
max_tokens: 80000
---
The owner approved this call for analysis and answered the first gate below.
Your job is ONLY the boundary map — small output, no retelling, no quotes.
The verbatim quotes are cut afterwards by code along the line numbers you emit,
so every number you write must be a real line of the transcript.

Gate note (owner's answers — who spoke under which label, what the call was
about, what to look for): `{{ change_file.Path }}`

{{ change_file.Content }}

Steps:

1. `read_note` the transcript at the path named by `transcript:` in the gate
   note's frontmatter. Every line starts with its own number: `12 | …`. That
   number is the address; a timecode, if the file had one, is just text.
2. Split the call into topic segments. Only major changes of subject; small
   talk at the start merges into the first topic. A topic heading states the
   takeaway in the language of the call, not a label: "смету к пятнице,
   поддержка отдельной строкой", not "обсуждение сметы".
3. Write ONE note with `write_note` at `segments/<id8>.md`, where `<id8>` is
   the eight hex characters before `.md` in the transcript path (for
   `transcripts/2026-01-15-4f01f193.md` that is `segments/4f01f193.md`).
   Everything in the language the call was held in. Strict format:

---
type: segments
transcript: "<the transcript path>"
review: "{{ change_file.Path }}"
date: "<copy date from the transcript frontmatter>"
title: "<inferred title in the call's language>"
---
<2-4 sentences: what was decided, what happens next. Use the names the owner
gave in the gate note, never the raw speaker labels.>

## Границы

12 | <takeaway heading of the segment that starts on line 12>
34 | <next>

Rules: the first boundary is line 1; numbers strictly increase; every number is
a line that exists; no quotes and no prose beyond the one heading per boundary.
A number you cannot point at in the transcript is worse than a missing segment,
because the cutter will snap it to the nearest real line and the note will
carry a boundary nobody chose.

Then call `finish`.
