# krisp_knowledge

Turn your [Krisp](https://krisp.ai) call recordings into a linked, navigable knowledge
base — not a pile of summaries and a chat bot.

The pipeline is three [trip2g](https://trip2g.com) **fleet role-notes** wired by
change-webhooks. Drop a raw transcript into the vault and the knowledge base builds
itself, in the same vault it lives in: a call note per recording, a growing glossary of
people/tools/projects/terms, daily notes with action checkboxes, and append-only topic
logs. Every claim quotes the exact transcript lines behind it.

A fully synthetic sample vault lives in [`example/vault/`](example/vault) — inputs and
the notes the cascade produced from them.

## What you get

| Note | Folder | What it holds |
|------|--------|---------------|
| **transcript** | `transcripts/` | the raw, verbatim transcript — the auditable source |
| **call** | `calls/` | inferred title, summary card, link to the transcript, and per topic a one-line takeaway above the verbatim quote below, cited by timerange |
| **concept** | `concepts/` | one note per person/org/project/tool/term, with aliases and mentions that quote the exact lines where it came up; grows across calls |
| **daily** | `daily/` | action checkboxes on top, dated log below, no summary; a "tomorrow" task lands on the next day |
| **topic log** | `log/` | recurring subjects, append-only, each mention under a `### [[YYYY-MM-DD]]` heading |

Two navigation axes: **by topic** (concept graph + wikilinks) and **by time** (daily
notes + the calls magazine). Time is authoritative: it is decoded from the call id (a
UUIDv7 with a millisecond timestamp), never from the local clock.

## The cascade

Three role-notes in [`roles/`](roles); the fleet turns each into a webhook:

```
Krisp API ──(cron)── roles/ingest.md    executor: code, no LLM — verbatim transcripts
                          │ writes transcripts/**
                          ▼ change-webhook
                     roles/segment.md   LLM — topic boundaries, inferred title, quoted evidence
                          │ writes calls/**
                          ▼ change-webhook
                     roles/extract.md   LLM — concepts, daily notes, topic logs
                            writes concepts/** daily/** log/**
```

Ingest is the only source-specific stage. Everything after is source-agnostic: swap
Krisp for books, YouTube, or support threads by replacing `roles/ingest.md` alone.
Because the raw transcript is preserved verbatim, you can re-run the LLM stages any
time the prompt or model improves — no re-fetch.

## Prerequisites

- [trip2g](https://github.com/trip2g/trip2g) — provides both tools used here:
  - **memcli** (`cli/memcli`) — boots a local trip2g instance + two-way sync for a vault folder
  - **fleet** (`cmd/fleet`) — the agent host that runs the role-notes
- A **Krisp** session token, `KRISP_TOKEN` (only for ingesting your own calls)
- An **OpenRouter** API key, `OPENROUTER_API_KEY` (https://openrouter.ai/keys), or any
  OpenAI-compatible endpoint

Neither memcli nor fleet is published standalone yet — build them from the trip2g repo:

```bash
git clone https://github.com/trip2g/trip2g
cd trip2g
go build -o ~/bin/fleet ./cmd/fleet          # the agent host (single static binary)
cd cli/memcli && npm install && npm run build # memcli -> dist/memcli.js
```

Get `KRISP_TOKEN` from your browser: open app.krisp.ai, DevTools → Network → any
`api.krisp.ai` request → copy the `Authorization: Bearer <token>` value.

## Try it in 2 minutes (no keys needed)

Serve the committed synthetic example as a browsable site:

```bash
git clone https://github.com/trip2g/krisp_knowledge
cd krisp_knowledge
node /path/to/trip2g/cli/memcli/dist/memcli.js up --folder example/vault
```

Open the printed URL: the calls magazine on the front page, `/daily`, `/concepts`,
`/log`. (Note URLs turn dashes into underscores: `calls/2024-03-12-018e321a.md` is
served at `/calls/2024_03_12_018e321a`.)

## Run the cascade on a transcript (`fleet --once`)

`fleet --once` runs a single role-note offline against a local folder — same engine as
the daemon, no trip2g connection. This is how you test the cascade (and how the
committed `example/vault` output was produced):

```bash
export OPENROUTER_API_KEY=sk-or-...
cd example/vault   # or your own vault

# step 1: transcript -> call note (topic boundaries + inferred title)
fleet --once ../../roles/segment.md --vault . \
      --target transcripts/2024-03-12-018e321a.md \
      --llm-base-url https://openrouter.ai/api/v1 --llm-api-key $OPENROUTER_API_KEY

# step 2: call note -> concepts, daily note, topic logs
fleet --once ../../roles/extract.md --vault . \
      --target calls/2024-03-12-018e321a.md \
      --llm-base-url https://openrouter.ai/api/v1 --llm-api-key $OPENROUTER_API_KEY
```

Each run prints a JSON result (`status`, `tokens_used`, the notes written) and writes
the notes into the folder. Cost is a few cents per call on `openai/gpt-5.4-mini` (the
default in the roles; override with the `model:` frontmatter field).

`--once` covers the LLM roles. The ingest role uses `executor: code` and runs on the
fleet daemon (below); for local testing, drop transcript files into `transcripts/`
yourself — any note with `Name | MM:SS` lines and a `created_at` in the frontmatter
works.

## Go live: the self-building vault

To have the cascade run by itself on every new transcript:

1. Serve your vault: `memcli up --folder <your-vault>` (two-way sync: notes the fleet
   writes appear back in your folder).
2. Copy `roles/` into the vault — the fleet discovers role-notes under `roles/`.
3. Run the fleet daemon against the instance (see
   [`docs/dev/fleet_run.md`](https://github.com/trip2g/trip2g/blob/main/docs/dev/fleet_run.md)
   in the trip2g repo for flags, keys, and networking):

```bash
KRISP_TOKEN=... KRISP_BASE_URL=https://api.krisp.ai fleet \
  --trip2g-url http://localhost:20181 \
  --callback-url http://127.0.0.1:9090 \
  --jwt-secret <JWT_SECRET from the vault's .trip2g-memory/env> \
  --fleet-secret $(openssl rand -hex 32) \
  --llm-base-url https://openrouter.ai/api/v1 \
  --llm-api-key $OPENROUTER_API_KEY \
  --allowed-programs python --sandbox-network true
```

The cron ingest role pulls new Krisp calls every 15 minutes; each written transcript
wakes segmentation; each call note wakes extraction.

**Caveat:** trip2g's webhook SSRF guard blocks deliveries to loopback/private
addresses unless the server runs with `DEV=true`. The stock memcli container does not
set it, so an all-on-localhost live cascade currently needs a dev-mode trip2g (e.g.
the trip2g repo's `docker-compose.test.yml` stack, where this exact wiring is
exercised end-to-end in `e2e/krisp-ingest.spec.js`). `fleet --once` has no such
constraint — it needs no server at all.

## Vault templates

[`vault-templates/`](vault-templates) holds the magazine index pages (`index.md`,
`daily/index.md`, `concepts/index.md`, `log/index.md`) and `_header.md`/`_footer.md`.
Copy them into a fresh vault once and it renders as a browsable site.

## Provenance

Every claim cites its source, and the citation is the source: notes quote the verbatim
transcript lines behind each statement, with a timerange link. The LLM's summary is
the value-add; the quote underneath is the proof. Since the emit step is an LLM, a
quote can still occasionally be mislabeled — call notes carry `needs_review: true` so
a human confirms inferred titles and spot-checks quotes.

## Files

```
roles/ingest.md       Krisp API -> transcripts/**   (executor: code, cron, no LLM)
roles/segment.md      transcripts/** -> calls/**    (LLM, change-webhook)
roles/extract.md      calls/** -> concepts, daily, log  (LLM, change-webhook)
vault-templates/      magazine index pages, _header/_footer
example/vault/        synthetic transcripts + the notes the cascade produced
.env.example          the two keys you need
```

Nothing private is committed: your `.env`, vaults, and caches are gitignored. Only the
synthetic `example/` ships in the repo.
