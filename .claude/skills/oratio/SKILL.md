---
name: oratio
description: Turn a thought leader's interview(s) into a two-voice podcast. Given a YouTube URL (or in future, a person's name), produce a short (~5 min) distilled summary and a long (~30 min, split into ~10 min chapters) narrative podcast, both synthesized via Kokoro 82M TTS. Trigger with /oratio <URL> or /oratio <name>.
---

# Oratio: Interview → Two-Voice Podcast

Turns a thought leader's interview transcript into two podcast formats, synthesized with a two-voice Kokoro 82M setup. Designed to let a user listen to curated opinions during a run or commute instead of watching an hour of YouTube.

## Voice convention (non-negotiable)

- Two official Kokoro voices only: **`am_puck`** (male) and **`af_heart`** (female).
- The interviewee is heard in their own-gender voice. The host/narrator uses the opposite gender for auditory separation.
- `[MO]` (or any non-HOST tag) = interviewee voice, reserved for **verbatim direct quotes only**. Never paraphrase under this tag.
- `[HOST]` = narrator voice, carries all framing, transitions, and paraphrased context.

## Pipeline

1. **Fetch** (`tools/youtube_fetcher`) — yt-dlp pulls subtitles + metadata. Produces `output/<video_id>/transcript.txt` (with `[mm:ss]` cues) and `metadata.json`.
2. **Investigate** (`transcript-investigator`) — Reads one transcript, extracts `(theme, thesis, verbatim_quote, timestamp)` tuples. One agent call per transcript.
3. **Critique investigation** (`transcript-critic`) — Verifies every `verbatim_quote` is present in `transcript.txt`. Flags paraphrases, hallucinations, truncations. Loops back to investigator if issues found.
4. **Aggregate** (`opinion-aggregator`) — Clusters tuples into 3-5 coherent themes. For a single-video POC, produces a flat theme map. For multi-video runs (future), deduplicates repeated anecdotes and tracks stance evolution across interviews.
5. **Write** (`script-writer`) — Takes the theme map + raw quotes and produces two outputs:
    - `short/script.txt` — ~5 min distillation, ~750-900 words total, thesis + 3-5 anchored points
    - `long/ch01_script.txt` … — thematic chapters, each ~1500 words (~10 min), narrative flow within the chapter
   Script style rules (TTS-friendly):
    - Short sentences. Avoid nested clauses.
    - Punctuation carries all pauses (no SSML). Use `.`, `,`, `—`, `...` deliberately.
    - No markdown, no URLs, no bracketed citations, no list numbering like "1." or "2)".
    - Spell out acronyms on first use (e.g. "UBI, universal basic income"), then use the acronym.
    - Every `[MO]` line must be a verbatim extract from the transcript, wrapped in quotation marks.
6. **Critique script** (`script-critic`) — Verifies (a) every `[MO]` block is verbatim, (b) no style-rule violations, (c) short version hits 750-900 words, (d) long chapters hit 1400-1700 words. Loops back to writer if issues.
7. **Synthesize** (`tools/kokoro_tts`) — `uv run oratio-tts <script> -o <out.mp3> --subject-gender {male|female}`. Produces one mp3 per script.

## Output layout

```
output/<video_id>/
├── metadata.json
├── transcript.srt
├── transcript.txt
├── opinions.json              # from aggregator: themes + quotes + timestamps
├── short/
│   ├── script.txt
│   └── short.mp3
└── long/
    ├── ch01_<slug>_script.txt
    ├── ch01_<slug>.mp3
    ├── ch02_<slug>_script.txt
    ├── ch02_<slug>.mp3
    ├── ch03_<slug>_script.txt
    └── ch03_<slug>.mp3
```

## Delegation rules

- The orchestrator (this skill) does **not** call Kokoro or read the transcript itself. It reads progress files, spawns sub-agents, and runs the two CLI tools (`oratio-fetch`, `oratio-tts`).
- Sub-agents write their outputs to disk; orchestrator reads paths, not contents, to keep context small.
- Critic loops: max 2 rounds. If still failing after round 2, surface to user.

## Single-video POC mode

When invoked with one YouTube URL and no name-search step:
- Skip the `interview-finder` phase (not yet implemented).
- Run fetch → investigate → critique → aggregate → write → critique → synthesize for that single video.
- Produce short (1 mp3) + long (as many chapters as the content supports — typically 2-4, floating based on content density; optimize for quality not count).

## Multi-video mode (future)

When invoked with a name:
- `interview-finder` agent curates a shortlist via `yt-dlp` search + WebSearch.
- Fetch each, investigate each, then a cross-video deduplication step in `opinion-aggregator` before writing.

## Invocation

- `/oratio <youtube_url>` — single-video POC mode
- `/oratio <name>` — full mode (once `interview-finder` exists)
- `--subject-gender male|female` — required unless obvious from context; falls back to asking user
