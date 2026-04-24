---
name: oratio
description: Turn a YouTube URL (single-video mode) or a thought leader's name (corpus mode) into a two-voice podcast. Produces a ~5 min short overview plus per-theme (URL mode) or per-era (name mode) long chapters, all synthesized via Kokoro 82M TTS. Trigger with /oratio <URL> or /oratio <name>.
---

# Oratio: YouTube → Two-Voice Podcast

Turns a thought leader's public-speaking record into a two-voice podcast. Two modes:

- **URL mode** — one YouTube URL → short (~5 min) + themed long chapters (~10 min each).
- **Name mode** — a person's name → yt-dlp search → curated 3–5 talks → chronological audio biography with per-era chapters and transitions that track how their views evolved.

All stages run through local agent `query()` calls to your `claude` CLI (Pro/Max subscription inherited — no API key).

## Voice convention

- Two official Kokoro voices: **`am_puck`** (male), **`af_heart`** (female).
- The subject is heard in their own-gender voice; the host uses the opposite gender for auditory separation.
- `[HOST]` = narrator, carries all paraphrase and framing.
- `[<FIRSTNAME>]` = subject voice, **reserved for verbatim direct quotes only**, wrapped in `"..."`. Never paraphrase under this tag.

## Invocation

```
/oratio <youtube_url>                 # URL mode
/oratio <subject name>                # name mode
  [--max-videos 5]                    # name mode: cap on videos processed
  [--min-duration 1200]               # name mode: min seconds per video
  [--skip-search]                     # name mode: reuse candidates.json
  [--skip-fetch]                      # URL mode: reuse existing transcript
  [--skip-synth]                      # both: stop before Kokoro
  [--model claude-opus-4-6]
```

## URL-mode pipeline

1. **Fetch** (`oratio-fetch`) — yt-dlp pulls subtitles + metadata.
2. **Investigate** (`transcript-investigator`) — extracts `(theme, thesis, verbatim_quote, timestamp)` tuples.
3. **Critique investigation** (`transcript-critic`) — greps every quote against `transcript.txt`.
4. **Aggregate** (`opinion-aggregator`) — clusters into 3–5 themes, assigns `subject_gender` + `subject_tag`.
5. **Write** (`script-writer`) — `short/script.txt` (~800 words) + `long/ch<NN>_<slug>_script.txt` (~1500 words each).
6. **Critique script** (`script-critic`) — verbatim fidelity, TTS style, word counts.
7. **Synthesize** (`oratio-tts`) — one mp3 per script.

## Name-mode pipeline

1. **Search** (`oratio-find`) — yt-dlp Python API, multi-keyword search (keynote/interview/podcast/talk/lecture/fireside), duration filter, dedupe. Emits `candidates.json`.
2. **Filter** (`interview-finder`) — agent picks formal talks BY the subject (not about), sorted newest-first, with era hints. Emits `videos.json`.
3. **Per video (parallel)** — `oratio-fetch` → `transcript-investigator` → `transcript-critic` loop.
4. **Era-aggregate** (`era-aggregator`) — clusters opinions chronologically into 2–4 eras, identifies transitions with before/after quotes, flags stable themes. Critically: **never fabricates motivation** — if the subject never said why their view shifted, that's marked honestly.
5. **Corpus script-write** (`corpus-script-writer`) — `short/script.txt` (chronological overview, ~900 words) + `long/<chapter_slug>_script.txt` per era. Each era chapter opens with a transition passage from the previous era.
6. **Corpus script-critic** (`corpus-script-critic`) — verbatim fidelity across all source transcripts, plus `fabricated_motivation` check on every transition opening.
7. **Synthesize** (`oratio-tts`) — one mp3 per script.

## Output layout

### URL mode
```
output/<Subject>/<date>__<id>__<slug>/
├── metadata.json, transcript.srt, transcript.txt
├── opinions.raw.json, transcript_critic_report.json
├── opinions.json, script_critic_report.json
├── short/{script.txt, short.mp3}
└── long/{ch01_<slug>_script.txt, ch01_<slug>.mp3, ...}
```

### Name mode
```
output/<Subject>/
├── _corpus/
│   ├── candidates.json               # oratio-find
│   ├── videos.json                   # interview-finder
│   ├── opinions_index.json           # list of per-video opinions paths
│   ├── evolution.json                # era-aggregator
│   ├── script_critic_report.json
│   └── <date>__<id>__<slug>/         # per-video artifacts, one per included talk
├── short/{script.txt, overview.mp3}  # chronological overview
└── long/{era01_<slug>_script.txt, era01_<slug>.mp3, era02_..., ...}
```

## Delegation rules

- The orchestrator driver (`src/oratio/orchestrator.py`) is the only code that calls `query()`. Each agent phase is exactly one `query()` call.
- Sub-agents write their outputs to disk; the orchestrator reads paths, not contents, to keep its own context small.
- Critic loops: max 2 rounds. If still failing after round 2, surface to user.
- Name mode: per-video `transcript-investigator + transcript-critic` loops run in parallel via `asyncio.gather`.

## Style rules (Kokoro-friendly, both modes)

- Short sentences (< 25 words).
- Punctuation carries pauses (`.` `,` `—` `...`). No SSML.
- No markdown, no URLs, no bracketed citations, no stage directions.
- Spell out acronyms on first use (`UBI, universal basic income`, then `UBI`).
- `[HOST]` carries paraphrase; `[<SUBJECT_TAG>]` carries verbatim quotes only, wrapped in `"..."`.

## Subscription-auth guarantee

Every `query()` call is made with `ClaudeAgentOptions(env={"ANTHROPIC_API_KEY": ""})`. The Agent SDK merges this dict last, so any exported `ANTHROPIC_API_KEY` in the user's shell is clobbered inside the subprocess env. The `claude` CLI then falls back to its OAuth-stored subscription auth (Pro/Max). The orchestrator prints a `note:` at startup if a key was detected in the shell, so the user knows it was bypassed.
