# Oratio

Turn a thought leader's interview — or any long-form YouTube video — into a two-voice podcast you can actually listen to on the run.

One command takes a URL, pulls the transcript, runs a Claude agent pipeline that extracts verbatim opinions and writes a tight narrative script, and synthesizes the result with Kokoro 82M TTS into an MP3 you can `open`.

```bash
uv run oratio "https://www.youtube.com/watch?v=<ID>"
```

Output: one ~5-minute distilled "short" version, plus a long version split into ~10-minute thematic chapters.

## Status

POC. Two videos validated end-to-end:

- **Mo Gawdat** (40-min interview) → 5 MP3s, ~29 min total, manually assembled (before the orchestrator existed).
- **Dale Schuurmans** (64-min academic talk on LLMs and computation) → 5 MP3s, ~42 min total, fully produced by the agent orchestrator with zero human editing inside the pipeline.

## How it works

```
  YouTube URL
      │
      ▼
 ┌──────────────┐
 │  oratio-fetch │     yt-dlp → transcript.srt + transcript.txt + metadata.json
 └──────────────┘
      │
      ▼
 ┌─────────────────────────┐
 │ transcript-investigator │  Claude Opus 4.6 agent — reads transcript, extracts
 └─────────────────────────┘   (theme, thesis, verbatim_quote, timestamp) tuples
      │                        → opinions.raw.json
      ▼
 ┌──────────────────────┐
 │  transcript-critic   │    Claude Opus 4.6 agent — greps every quote against
 └──────────────────────┘    the transcript, flags fabrications / overreach
      │                       → transcript_critic_report.json
      ▼                       (loops back to investigator if needs_revision, max 2x)
 ┌──────────────────────┐
 │ opinion-aggregator   │    Claude Opus 4.6 agent — clusters opinions into
 └──────────────────────┘    3-5 themes, picks narrative order, tags subject_gender
      │                       → opinions.json
      ▼
 ┌──────────────────────┐
 │   script-writer      │    Claude Opus 4.6 agent — writes the short script +
 └──────────────────────┘    one long chapter per theme, in [HOST]/[SUBJECT] form
      │                       → short/script.txt, long/chNN_<slug>_script.txt
      ▼
 ┌──────────────────────┐
 │   script-critic      │    Claude Opus 4.6 agent — verifies every [SUBJECT] line
 └──────────────────────┘    is a verbatim extract + TTS-style compliance
      │                       → script_critic_report.json
      ▼                       (loops back to writer if needs_revision, max 2x)
 ┌──────────────────────┐
 │      oratio-tts      │    Kokoro 82M (local, CPU/MPS) — two-voice render
 └──────────────────────┘     → short.mp3, chNN_<slug>.mp3
```

Each agent is a single `claude_agent_sdk.query()` call with a role-specific
system prompt loaded from `.claude/agents/<role>.md`. Critics can send work
back to their upstream agent for one retry before the orchestrator gives up
and proceeds.

## Setup

System deps (macOS):

```bash
brew install espeak-ng ffmpeg
```

Claude Code CLI must be installed and logged in — the Agent SDK spawns the
local `claude` binary and inherits its auth, so a Pro/Max subscription covers
all agent calls. **No `ANTHROPIC_API_KEY` needed.**

```bash
# If you don't have it:
npm install -g @anthropic-ai/claude-code
claude        # log in once
```

Python deps:

```bash
cd oratio
uv sync       # Python 3.11+, installs yt-dlp, kokoro, claude-agent-sdk, torch, etc.
```

## Usage

### End-to-end

```bash
uv run oratio "https://www.youtube.com/watch?v=E0Q96IKXx6Q"
```

Produces per-video artifacts under a subject-indexed folder:

```
output/
├── _staging/                                  # fetch dumps here; moved out post-aggregate
├── Mo_Gawdat/
│   └── 2026-03-31__E0Q96IKXx6Q__ex_google_exec.../
│       ├── metadata.json
│       ├── transcript.srt                     # original subtitles
│       ├── transcript.txt                     # [mm:ss] prefixed, deduped
│       ├── opinions.raw.json                  # investigator output
│       ├── transcript_critic_report.json
│       ├── opinions.json                      # aggregator output (subject_gender, themes)
│       ├── script_critic_report.json
│       ├── short/
│       │   ├── script.txt                     # ~800 words, ~5 min
│       │   └── short.mp3
│       └── long/
│           ├── ch01_<slug>_script.txt         # ~1500 words each, ~10 min each
│           ├── ch01_<slug>.mp3
│           ├── ch02_<slug>_script.txt
│           └── ch02_<slug>.mp3
└── Dale_Schuurmans/
    └── 2025-08-25__yGLoWZP1MyA__dale_schuurmans_language_models.../
        └── ...
```

Folder name pattern: `<Subject_Name>/<YYYY-MM-DD>__<video_id>__<title_slug>/`. Date sorts
chronologically, video_id stays unique, title_slug keeps the dir self-describing
when browsing.

During a run the work-dir lives at `output/_staging/<video_id>/`. Once the
aggregator determines `subject_name`, the orchestrator moves the dir to its
final subject-indexed location. Re-running `--skip-fetch` on the same URL
finds the existing dir wherever it lives.

### Options

```bash
uv run oratio <URL> [--model claude-opus-4-6]   # swap model if desired
                    [--skip-fetch]              # reuse existing transcript
                    [--skip-synth]              # stop before Kokoro (scripts only)
```

### Running just one piece

Each stage is also usable standalone:

```bash
# Transcript only
uv run oratio-fetch <URL> -o output/

# TTS only, from a hand-written script
uv run oratio-tts path/to/script.txt -o out.mp3 --subject-gender male
```

## Voice convention

Two Kokoro voices, paired by subject gender:

- **Male voice**: `am_puck`
- **Female voice**: `af_heart`
- **Rule**: the subject speaks in their own-gender voice; the narrator takes the opposite gender for clear auditory separation.

| Subject | Host voice | Quote voice |
|---------|------------|-------------|
| Male    | `af_heart` | `am_puck`   |
| Female  | `am_puck`  | `af_heart`  |

Override with `--host-voice` / `--quote-voice` on `oratio-tts`.

## Script format

```
[HOST] Narration spoken by the host voice.
[DALE] "A verbatim direct quote in quotation marks."
[HOST] More narration.
```

- `[HOST]` = narrator voice, carries all framing and paraphrase.
- `[<FIRSTNAME>]` = subject voice, **only verbatim quotes**, wrapped in `"…"`.
- The agent writer picks the tag from the subject's first name: Mo Gawdat → `[MO]`, Dale Schuurmans → `[DALE]`, Naval Ravikant → `[NAVAL]`.
- Blank line = paragraph break (longer audio pause).

## Repo layout

```
oratio/
├── pyproject.toml                 # deps + three CLI entry points
├── README.md                      # this file
├── .claude/
│   ├── skills/oratio/SKILL.md     # Claude Code skill spec (for in-session use)
│   └── agents/
│       ├── transcript-investigator.md
│       ├── transcript-critic.md
│       ├── opinion-aggregator.md
│       ├── script-writer.md
│       └── script-critic.md
├── src/oratio/
│   ├── orchestrator.py            # oratio CLI — the pipeline driver
│   ├── youtube_fetcher/fetch.py   # oratio-fetch CLI — yt-dlp wrapper
│   └── kokoro_tts/synthesize.py   # oratio-tts CLI — Kokoro TTS wrapper
├── scripts/
│   ├── smoke_sdk.py               # verify SDK + CLI auth
│   ├── synth_batch.py             # batch synth one-off (Mo Gawdat)
│   └── synth_dale.py              # batch synth one-off (Dale Schuurmans)
└── output/                        # per-video artifacts (gitignored)
```

## Customizing the pipeline

Agent behavior lives in markdown. To change what an agent does, edit its
spec in `.claude/agents/<role>.md` — the frontmatter describes the tools and
purpose, the body is the system prompt. Next run picks up changes.

**Common tweaks:**

- Loosen the `script-critic` acronym-expansion rule for technical subjects (it currently flags "AI" and "LLM" on every occurrence, which is overkill for audiences who already know those terms).
- Change the chapter-count target in `opinion-aggregator` (default floats 3-5 based on content density).
- Add a `--subject-name-hint` arg in `orchestrator.py` for subjects whose name isn't obvious from video metadata.

## Known limitations

- **Runtime is long.** A 60-min source takes ~45-60 min of agent wall-clock time + ~6 min of Kokoro synth on Apple Silicon. Investigator alone often runs 8-15 min because it grep-verifies every quote it extracts.
- **Critic is strict on warnings.** Many warn-level issues are cosmetic (acronyms, homographs) and don't actually degrade audio; treat the verdict as advisory unless it's `block`.
- **Single-video only.** The `interview-finder` phase mentioned in `SKILL.md` is not implemented yet — name-based multi-video runs need one more agent to search YouTube.
- **English only.** Kokoro supports other languages but the pipeline voices + script conventions are tuned for English.

## License

MIT — but Kokoro model weights are Apache-2.0, and you must comply with YouTube's
TOS for any transcripts you fetch.
