---
description: "Transcript -> call note: topic boundaries, inferred title, quoted evidence (step 1 of 2)"
model: openai/gpt-5.4-mini
tools: [write_note]
read_patterns: ["transcripts/**"]
write_patterns: ["calls/**"]
mode: change
trigger_on: [create, update]
trigger_include: ["transcripts/**"]
for_each: changed_files
max_depth: 3
concurrency: skip
max_steps: 5
max_tokens: 16000
---
You are given a verbatim call transcript. Lines follow the format `Name | MM:SS` or
`Speaker N | MM:SS`, then the utterance text. Raw ASR may be choppy.

Source file: `{{ change_file.Path }}`

Task: split the call into topic segments and write a **call note** with a summary card
on top and, per topic, a one-line takeaway above the verbatim quote below.

Rules:
- Split whenever the discussion moves to a different question, decision, or work item.
  Even a 2-3 minute call typically has 2-4 segments (e.g. problem framing, task
  assignments, a separate side decision). Never emit a single segment spanning the
  whole call unless the call genuinely never changes subject.
- Merge connection checks and opening small talk into the first topic; they are never
  their own segment.
- Take every timecode verbatim from the transcript, never invent or round one.
- A topic heading states the takeaway (Minto), not a label. Bad: "Budget discussion".
  Good: "Budget is cut - focus on one channel".
- The recorder's calendar title is unreliable. Infer a meaningful title from the call's
  main topics, and infer participant names from the content when the transcript only
  has `Speaker N` labels.
- Quote the transcript lines of each topic verbatim in a blockquote. The quote is the
  evidence; it must match the source exactly.

When done, write the result with the `write_note` tool. Path = `calls/` + the basename
of the source file (for `{{ change_file.Path }}` that is `calls/<name-without-folder>`).
Copy `created_at`, `source`, and `call_id` verbatim from the source frontmatter. Strict
format:

---
title: "<inferred title>"
title_source: inferred
type: call
created_at: "<copy from transcript frontmatter>"
source: krisp
call_id: "<copy from transcript frontmatter>"
transcript: "{{ change_file.Path }}"
speakers:
  - "<participant>"
needs_review: true
---
<2-3 sentence summary of the whole call: what was decided, what is next.>

Raw transcript: [[{{ change_file.Path }}|full transcript]]

## Topics

**<start timecode> <takeaway headline of the segment>**

> <verbatim transcript lines of this segment>

([[{{ change_file.Path }}|transcript]] <first timecode of segment>-<last timecode of segment>)

**<start timecode> <next segment>**
...

Fill every timecode placeholder with a real `MM:SS` value taken from the transcript;
never leave a placeholder in the output.

Transcript:
{{ change_file.Content }}
