# Oratio

**Turn a 60-minute YouTube lecture into a 5-minute podcast — written by agents, narrated in two voices, running entirely off your Claude subscription.**

Oratio is a single CLI that points at a YouTube URL, runs a five-stage Claude Opus 4.6 agent pipeline to extract verbatim opinions and draft a production-grade script, then renders it with Kokoro 82M TTS into MP3s you can actually listen to. Two voices — a narrator plus the subject, speaking their own words verbatim — and no `ANTHROPIC_API_KEY`: the Claude Agent SDK shells out to your local `claude` binary and inherits Pro/Max auth.

[![License MIT](https://img.shields.io/badge/license-MIT-blue.svg)](#license)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org)
[![Built with Claude](https://img.shields.io/badge/agents-Claude%20Opus%204.6-D97757.svg)](https://docs.claude.com/en/docs/claude-code)
[![TTS Kokoro 82M](https://img.shields.io/badge/TTS-Kokoro%2082M-7C3AED.svg)](https://github.com/hexgrad/kokoro)
[![yt-dlp](https://img.shields.io/badge/fetch-yt--dlp-FF0000.svg)](https://github.com/yt-dlp/yt-dlp)

## Listen to an example

A 4.9-minute short produced end-to-end by the pipeline from a 64-minute RLC 2025 keynote by **Dale Schuurmans**, *Language Models and Computation*. No human edits inside the run.

https://github.com/user-attachments/assets/9eefc4ec-4dfe-4c29-8719-c23311e3d9ad

🎧 **[Download the MP3](https://raw.githubusercontent.com/zhuconv/oratio/main/examples/dale_schuurmans_llms_as_universal_computers.mp3)** · 📄 **[Read the script](examples/dale_schuurmans_llms_as_universal_computers.txt)**

The `.txt` is the raw `[HOST]` / `[DALE]` tagged script the agents wrote. The MP3 is what Kokoro did with it.

## Quickstart

```bash
brew install espeak-ng ffmpeg
npm install -g @anthropic-ai/claude-code && claude    # log in once
git clone https://github.com/zhuconv/oratio && cd oratio
uv sync
uv run oratio "https://www.youtube.com/watch?v=<ID>"
open output/<Subject>/<date>__<id>__<slug>/short/short.mp3
```

That's it. One short MP3, plus one ~10-minute MP3 per thematic chapter.

## Why it exists

Long-form interviews and academic talks are the highest-signal AI content on the internet — and the hardest to consume. You rarely have 90 free minutes. You often do have 5.

Two things make Oratio more than "another summarizer":

1. **The agents call your local `claude` CLI.** No API key, no billing, no token juggling — the Agent SDK spawns the logged-in binary and agent turns bill against your Pro or Max subscription. The orchestrator is just five `query()` calls stitched together with a critic loop.
2. **Quotes are preserved verbatim, in the subject's voice.** Every line tagged `[DALE]` in the script is a byte-for-byte substring of the transcript. A dedicated critic agent greps every quote against `transcript.txt` and blocks the pipeline if even one word drifts. Then Kokoro renders those quotes in a different voice from the narrator, so "what the host says about Dale" and "what Dale actually said" are audibly distinct.

The result is something closer to a written essay read aloud than a robotic recap — and because the quotes are audited, you can trust it more than a summary.

## Pipeline

<p align="center">
  <img src="assets/pipeline.svg" alt="Oratio pipeline: YouTube URL → fetch → investigator → transcript-critic → aggregator → script-writer → script-critic → Kokoro TTS → MP3s. Critics can retry their upstream agent up to 2x." width="100%"/>
</p>

Every agent box is a single `claude_agent_sdk.query()` call with a role-specific system prompt loaded from `.claude/agents/<role>.md`. Critics can send work back to their upstream agent for one retry before the orchestrator gives up and proceeds.

## Case studies

| Source | Length | Kind | Result |
|---|---|---|---|
| **Dale Schuurmans** — RLC 2025 keynote, *Language Models and Computation* | 64 min | Academic lecture | 5 MP3s, ~42 min total. Zero human edits inside the pipeline. [Listen.](https://raw.githubusercontent.com/zhuconv/oratio/main/examples/dale_schuurmans_llms_as_universal_computers.mp3) |
| **Mo Gawdat** — interview on AI, UBI, and the job market | 40 min | Pop interview | 5 MP3s, ~29 min total. Validated end-to-end; assembled before the orchestrator landed. |

Two wildly different source genres, same pipeline, coherent output. That's the main thing this POC was proving.

## Setup in detail

<details>
<summary>Expand for prerequisites, Python, auth</summary>

**System (macOS tested):**

```bash
brew install espeak-ng ffmpeg
```

**Claude Code CLI — the Agent SDK spawns this and inherits its login.** No `ANTHROPIC_API_KEY` is used anywhere in the orchestrator.

```bash
npm install -g @anthropic-ai/claude-code
claude        # one-time login; Pro/Max covers all agent calls
```

**Python 3.11–3.12:**

```bash
uv sync       # installs yt-dlp, kokoro, claude-agent-sdk, torch, etc.
```

**First Kokoro run** downloads ~330 MB of model weights from Hugging Face. After that it runs fully offline on CPU or Apple Silicon MPS.

</details>

## Usage

### End-to-end

```bash
uv run oratio "https://www.youtube.com/watch?v=E0Q96IKXx6Q"
```

Output layout (subject-indexed, date-sortable, re-runnable):

```
output/
└── Dale_Schuurmans/
    └── 2025-08-25__yGLoWZP1MyA__dale_schuurmans_language_models/
        ├── metadata.json
        ├── transcript.srt / transcript.txt
        ├── opinions.raw.json              # investigator
        ├── transcript_critic_report.json
        ├── opinions.json                  # aggregator — themes, subject_gender
        ├── script_critic_report.json
        ├── short/
        │   ├── script.txt                 # ~800 words, ~5 min
        │   └── short.mp3
        └── long/
            ├── ch01_<slug>_script.txt     # ~1500 words / ~10 min per chapter
            ├── ch01_<slug>.mp3
            └── ...
```

A run lives in `output/_staging/<video_id>/` until the aggregator determines `subject_name`, then the orchestrator moves it to its final home. Re-running `--skip-fetch` locates the existing dir wherever it is.

### Flags

```bash
uv run oratio <URL> [--model claude-opus-4-6]   # any Opus-class model the CLI recognizes
                    [--skip-fetch]              # reuse existing transcript
                    [--skip-synth]              # stop before Kokoro (scripts only)
```

### Just one stage

Every stage is a standalone CLI:

```bash
uv run oratio-fetch <URL> -o output/                      # transcript only
uv run oratio-tts path/to/script.txt -o out.mp3 \         # TTS from any tagged script
                  --subject-gender male
```

## Script format

```
[HOST] Narration spoken by the host voice.
[DALE] "A verbatim direct quote in quotation marks."
[HOST] More narration.
```

- `[HOST]` — narrator voice, carries all framing and paraphrase.
- `[<FIRSTNAME>]` — subject voice, **only verbatim quotes**, wrapped in `"…"`. Mo Gawdat → `[MO]`. Naval Ravikant → `[NAVAL]`.
- Blank line = paragraph break (longer audio pause).

Two Kokoro voices, paired by subject gender so the narrator and subject are always audibly different:

| Subject gender | Host voice | Quote voice |
|---|---|---|
| Male   | `af_heart` | `am_puck`  |
| Female | `am_puck`  | `af_heart` |

Override with `--host-voice` / `--quote-voice` on `oratio-tts`.

## Customizing the agents

Agent behavior lives in markdown under [`.claude/agents/`](.claude/agents). The YAML frontmatter names the role and declares allowed tools; the body is the system prompt. Next run picks up your changes — no code edit required.

Useful tweaks:

- Loosen `script-critic` acronym-expansion for technical audiences (it currently nags "AI" and "LLM" on every occurrence).
- Change chapter-count target in `opinion-aggregator` (defaults to 3–5 based on content density).
- Tighten `transcript-investigator` density targets for longer sources.

## Known limitations

- **Runtime is long.** A 60-min source takes ~45–60 min of agent wall-clock time plus ~6 min of Kokoro synth on Apple Silicon. The investigator alone runs 8–15 min because it grep-verifies every quote it extracts.
- **Critic warnings are noisy.** Many `warn`-level issues (acronyms, homographs) don't actually degrade audio. Treat the verdict as advisory unless it's `block`.
- **Single-video runs only.** The name-based interview-finder phase isn't built yet.
- **English only.** Kokoro supports other languages but the voice conventions and script rules are tuned for English.
- **macOS-tested.** Dependencies (`espeak-ng`, `ffmpeg`, `torch`) exist on Linux and WSL, but I haven't verified the full pipeline there.

## Roadmap

- `interview-finder` agent — one subject name in, N videos out, aggregator dedupes across them.
- Relax `script-critic` acronym strictness for technical subjects, detect audience level automatically.
- `--subject-name-hint` to help the aggregator when metadata is thin.
- Optional `--style` preset for `script-writer` (editorial / narrative / lecture-notes).
- Parallel chapter synthesis in `oratio-tts` (currently sequential per script).

## Repo map

```
oratio/
├── pyproject.toml                 # deps + 3 CLI entry points
├── .claude/agents/                # 5 markdown agent specs (editable)
├── src/oratio/
│   ├── orchestrator.py            # oratio CLI — the pipeline driver
│   ├── youtube_fetcher/fetch.py   # oratio-fetch — yt-dlp wrapper
│   └── kokoro_tts/synthesize.py   # oratio-tts — two-voice Kokoro wrapper
├── examples/                      # Dale Schuurmans short (mp3 + txt)
└── output/                        # per-video artifacts (gitignored)
```

## License

MIT for the Oratio code. Kokoro model weights are Apache-2.0. You are responsible for complying with YouTube's Terms of Service for any transcripts you fetch.
