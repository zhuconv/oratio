# Oratio

**A two-voice podcast studio in your terminal. Every quote audited byte-for-byte. Every quote linked back to the second on YouTube.**

Drop in a YouTube URL and Oratio gives you a 5-minute short plus themed long chapters. Drop in a *name* — `"Dale Schuurmans"`, `"Mo Gawdat"` — and Oratio searches YouTube, picks 3–5 talks, then writes a chronological audio biography that tracks how the person's views evolved era by era.

Claude Opus 4.6 agents do the writing. Kokoro 82M renders it locally in two voices. The whole pipeline bills against your Claude Pro/Max subscription — **no `ANTHROPIC_API_KEY` needed**.

[![License MIT](https://img.shields.io/badge/license-MIT-blue.svg)](#license)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org)
[![Built with Claude](https://img.shields.io/badge/agents-Claude%20Opus%204.6-D97757.svg)](https://docs.claude.com/en/docs/claude-code)
[![TTS Kokoro 82M](https://img.shields.io/badge/TTS-Kokoro%2082M-7C3AED.svg)](https://github.com/hexgrad/kokoro)
[![yt-dlp](https://img.shields.io/badge/fetch-yt--dlp-FF0000.svg)](https://github.com/yt-dlp/yt-dlp)

## Listen first

A 4.9-minute short the pipeline produced from a 64-minute RLC 2025 keynote by **Dale Schuurmans**, *Language Models and Computation*. No human edits inside the run.

<p align="center">
  <video src="https://github.com/user-attachments/assets/9eefc4ec-4dfe-4c29-8719-c23311e3d9ad" controls width="480"></video>
</p>

🎧 **[Download the MP3](https://raw.githubusercontent.com/zhuconv/oratio/main/examples/dale_schuurmans_llms_as_universal_computers.mp3)** · 📄 **[Read the script](examples/dale_schuurmans_llms_as_universal_computers.txt)**

The `.txt` is the raw `[HOST]` / `[DALE]` tagged script the agents wrote. The MP3 is what Kokoro did with it.

## Why this is not another summarizer

**1. A critic agent audits every quote.** Every line tagged `[DALE]` (or whatever the subject's first name is) must be a byte-for-byte substring of the raw transcript. The [`transcript-critic`](agents/transcript-critic.md) agent runs `grep -F` against `transcript.txt` and **blocks the pipeline if even one word drifts**. Same idea cross-source for name mode via [`corpus-script-critic`](agents/corpus-script-critic.md).

**2. The host and the subject sound different.** Kokoro renders narration in one voice and quotes in another, paired by subject gender. "What the host says about Dale" and "what Dale actually said" are *audibly* distinct.

**3. Source-linked Markdown sidecars.** Every script has a `script.md` next to it. Each quote is a blockquote with a deep-linked YouTube timestamp. Click → land on the exact second.

```markdown
> [**12:37**](https://www.youtube.com/watch?v=YnMqbpdHcaY&t=757s) · _ICAPS 2024 Keynote_ · 2024-07-02
>
> there was this sense in which this started to look to me at least like an actual computer where you you were you know providing a problem...
```

**4. No fabricated motivation.** When a thinker's view shifts but they never said *why*, the [`era-aggregator`](agents/era-aggregator.md) marks it honestly and the [`corpus-script-critic`](agents/corpus-script-critic.md) blocks any chapter that invents a reason.

**5. Runs off your Claude subscription.** No API key, no billing dashboard. The Agent SDK shells out to your local `claude` binary — see [Subscription auth](#subscription-auth) below for the one-line trick that guarantees this.

## Two modes

### URL mode — one video → short + chapters

```bash
uvx oratio "https://www.youtube.com/watch?v=yGLoWZP1MyA"
```

A `transcript-investigator` extracts `(theme, thesis, verbatim_quote, timestamp)` tuples. The `transcript-critic` greps each quote. The `opinion-aggregator` clusters into 3–5 themes. The `script-writer` drafts a ~5-minute short plus one ~10-minute chapter per theme. The `script-critic` verifies. Kokoro renders.

### Name mode — one name → chronological audio biography

```bash
uvx oratio "Dale Schuurmans" --max-videos 5
```

This is the more ambitious mode. Oratio:

1. **Searches YouTube** (`oratio-find`) across 6 keyword templates — `keynote`, `interview`, `podcast`, `talk`, `lecture`, `fireside` — applies a 20-min duration filter, dedupes, enriches with upload dates → `candidates.json`.
2. **Filters to formal talks BY the subject** ([`interview-finder`](agents/interview-finder.md)) — drops commentary, clips, wrong-person matches → `videos.json`.
3. **Investigates every video in parallel** — `transcript-investigator + transcript-critic` loops fan out via `asyncio.gather`.
4. **Builds a chronological era structure** ([`era-aggregator`](agents/era-aggregator.md)) — clusters opinions into 2–4 eras, identifies transitions with before/after quotes, surfaces stable themes that span every era. **Only agent that sees more than one talk at once.** Refuses to invent why a view shifted.
5. **Writes a chronological script** ([`corpus-script-writer`](agents/corpus-script-writer.md)) — 5-minute overview plus one ~10-minute chapter per era. Each era chapter opens with a transition passage from the previous era.
6. **Cross-source critic** ([`corpus-script-critic`](agents/corpus-script-critic.md)) — verbatim-grep against every per-video transcript, and a hard `fabricated_motivation` check on every transition opening.
7. **Annotates** — `script.md` + `sources.json` for every script (deterministic Python via `oratio-annotate`).
8. **Renders** — Kokoro emits one MP3 per script.

You get an overview MP3 plus one MP3 per era. Re-run any time — `--skip-search` reuses the curated `videos.json`; finished stages resume from disk.

## Quickstart

Pick whichever install style matches how you work:

### One-shot: uvx

```bash
brew install espeak-ng ffmpeg
npm install -g @anthropic-ai/claude-code && claude    # one-time login
uvx oratio "https://www.youtube.com/watch?v=<ID>"     # URL mode
uvx oratio "Dale Schuurmans"                          # name mode
uvx oratio-doctor                                     # self-check deps
```

### Inside Claude Code: install as a plugin

```
/plugin install zhuconv/oratio
/oratio https://www.youtube.com/watch?v=<ID>
/oratio "Dale Schuurmans" --max-videos 5
```

Ships all 9 agents plus the `/oratio` skill. Requires the `oratio` Python package (`uv tool install oratio` or `pip install oratio`).

### Traditional clone-and-uv

```bash
brew install espeak-ng ffmpeg
npm install -g @anthropic-ai/claude-code && claude
git clone https://github.com/zhuconv/oratio && cd oratio
uv sync
uv run oratio "https://www.youtube.com/watch?v=<ID>"
open output/<Subject>/<date>__<id>__<slug>/short/short.mp3
```

## Pipeline

<p align="center">
  <img src="assets/pipeline.svg" alt="Oratio pipeline: YouTube URL → fetch → investigator → transcript-critic → aggregator → script-writer → script-critic → Kokoro TTS → MP3s. Critics can retry their upstream agent up to 2x." width="100%"/>
</p>

Every box is one `claude_agent_sdk.query()` call. System prompts live in [`agents/<role>.md`](agents) — no code edits required to tweak behavior. Critics can send work back upstream for one retry; after that the orchestrator surfaces the failure.

The 9 agents:

| Agent | Mode | Job |
|---|---|---|
| [`transcript-investigator`](agents/transcript-investigator.md) | both | Extract `(theme, thesis, verbatim_quote, timestamp)` tuples. |
| [`transcript-critic`](agents/transcript-critic.md) | both | `grep -F` every quote against the transcript. Blocks on drift. |
| [`opinion-aggregator`](agents/opinion-aggregator.md) | URL | Cluster into 3–5 themes; assign `subject_gender`. |
| [`script-writer`](agents/script-writer.md) | URL | Draft short + per-theme chapter scripts. |
| [`script-critic`](agents/script-critic.md) | URL | Verbatim fidelity, TTS style, word counts. |
| [`interview-finder`](agents/interview-finder.md) | name | Filter raw search to formal talks BY the subject. |
| [`era-aggregator`](agents/era-aggregator.md) | name | Build 2–4 chronological eras + transitions. Never fabricates motivation. |
| [`corpus-script-writer`](agents/corpus-script-writer.md) | name | Chronological overview + per-era chapters with transition openings. |
| [`corpus-script-critic`](agents/corpus-script-critic.md) | name | Cross-source verbatim grep + `fabricated_motivation` block. |

## Case studies

### Name mode — Dale Schuurmans, six years of changing his mind

A single command pulled in 3 talks spanning 2019–2025 and produced 4 MP3s totaling ~35 minutes:

| File | Era | Source talk |
|---|---|---|
| [`short/overview.mp3`](https://raw.githubusercontent.com/zhuconv/oratio/main/examples/dale_schuurmans_name_mode_overview.mp3) | All three | Chronological overview |
| `long/era01_subbasement.mp3` | 2019 — Optimization in RL | DLRLSS 2019 |
| `long/era02_llms_as_computers.mp3` | 2024 — LLMs as a new kind of computer | ICAPS 2024 Keynote |
| `long/era03_hard_limits.mp3` | 2025 — Computational impossibility results | RLC 2025 keynote |

🎧 **[Listen to the chronological overview](https://raw.githubusercontent.com/zhuconv/oratio/main/examples/dale_schuurmans_name_mode_overview.mp3)** · 📄 **[Read the annotated script](examples/dale_schuurmans_name_mode_overview.md)** (every quote has a clickable YouTube timestamp)

The `era-aggregator` identified one stable theme running through all three eras — *"Think computationally, not statistically"* — supported by verbatim quotes from each talk. That theme becomes the through-line of the overview script.

### URL mode — same pipeline, two genres

| Source | Length | Kind | Result |
|---|---|---|---|
| **Dale Schuurmans** — RLC 2025 keynote, *Language Models and Computation* | 64 min | Academic lecture | 5 MP3s, ~42 min total. Zero human edits inside the pipeline. [Listen.](https://raw.githubusercontent.com/zhuconv/oratio/main/examples/dale_schuurmans_llms_as_universal_computers.mp3) |
| **Mo Gawdat** — interview on AI, UBI, and the job market | 40 min | Pop interview | 5 MP3s, ~29 min total. Validated end-to-end. |

Two genres, same pipeline, coherent output.

## Output layout

### URL mode

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
        ├── short/{script.txt, script.md, sources.json, short.mp3}
        └── long/
            ├── ch01_<slug>_script.txt     # ~1500 words / ~10 min per chapter
            ├── ch01_<slug>.md             # source-linked sidecar
            ├── ch01_<slug>.mp3
            └── ...
```

### Name mode

```
output/
└── Dale_Schuurmans/
    ├── _corpus/
    │   ├── candidates.json              # oratio-find raw search
    │   ├── videos.json                  # interview-finder verdict
    │   ├── opinions_index.json
    │   ├── evolution.json               # era-aggregator — eras, transitions, stable themes
    │   ├── script_critic_report.json
    │   └── <date>__<video_id>__<slug>/  # per-video artifacts
    ├── short/{script.txt, script.md, sources.json, overview.mp3}
    └── long/
        ├── era01_<slug>_script.txt      # one chapter per era
        ├── era01_<slug>.md
        ├── era01_<slug>.mp3
        └── ...
```

## Source-linked Markdown sidecars

Every run produces a `script.md` next to `script.txt` plus `sources.json`. Each verbatim quote is a blockquote with a deep-linked YouTube timestamp:

```markdown
> [**1:03:19**](https://www.youtube.com/watch?v=yGLoWZP1MyA&t=3799s) · _Dale Schuurmans, Language Models and Computation_ · 2025-08-25
>
> machine learning is awesome. Reinforcement learning even more so, but computer science matters. Especially when you're trying to train LLMs to to serve a whole range of problem instances. You are now confronted with the laws of computation.
```

Click the timestamp → YouTube jumps to that exact second. Each `[HOST]` paragraph carries the nearest preceding quote's video as a "near" attribution in `sources.json`, so downstream tools can highlight which talk a paraphrase passage draws from.

Run `oratio-annotate` on any existing run to regenerate sidecars without touching the agent pipeline.

## Subscription auth

The Agent SDK shells out to your local `claude` binary, which inherits Pro/Max OAuth from `claude login`. To make sure that path is taken even if you have an `ANTHROPIC_API_KEY` exported in your shell, every `query()` call uses:

```python
ClaudeAgentOptions(env={"ANTHROPIC_API_KEY": ""})
```

The SDK merges this dict last when building the subprocess env. The clobbered key is empty, so the `claude` CLI falls back to its OAuth-stored subscription auth. The orchestrator prints a `note:` at startup if a key was detected — so you know it was bypassed, not used.

## Script format

```
[HOST] Narration spoken by the host voice.
[DALE] "A verbatim direct quote in quotation marks."
[HOST] More narration.
```

- `[HOST]` — narrator voice. All framing and paraphrase.
- `[<FIRSTNAME>]` — subject voice. **Verbatim quotes only**, wrapped in `"…"`. Mo Gawdat → `[MO]`. Naval Ravikant → `[NAVAL]`.
- Blank line = paragraph break (longer audio pause).

Two Kokoro voices, paired by subject gender so the narrator and subject are always audibly different:

| Subject gender | Host voice | Quote voice |
|---|---|---|
| Male   | `af_heart` | `am_puck`  |
| Female | `am_puck`  | `af_heart` |

Override with `--host-voice` / `--quote-voice` on `oratio-tts`.

## Single-stage CLIs

Every stage is a standalone command:

```bash
uv run oratio-fetch <URL> -o output/                          # transcript only
uv run oratio-find "<name>" -o output/<Subject>/_corpus/      # YouTube search only
uv run oratio-tts path/to/script.txt -o out.mp3 \             # TTS from any tagged script
                  --subject-gender male
uv run oratio-annotate output/<Subject>/                      # regenerate .md sidecars
uv run oratio-doctor                                          # dependency self-check
```

## Flags

```bash
uv run oratio <URL_or_name> [--model claude-opus-4-6]
                            # URL mode:
                            [--skip-fetch]         # reuse existing transcript
                            # name mode:
                            [--max-videos 5]       # cap on videos selected
                            [--min-duration 1200]  # min seconds per candidate
                            [--skip-search]        # reuse candidates.json + videos.json
                            # both:
                            [--skip-synth]         # stop before Kokoro
```

## Setup in detail

<details>
<summary>Expand for prerequisites, Python, auth</summary>

**System (macOS tested):**

```bash
brew install espeak-ng ffmpeg
```

**Claude Code CLI — the Agent SDK spawns this and inherits its login.** No `ANTHROPIC_API_KEY` is used anywhere in the orchestrator. Even if you have one exported, the orchestrator clobbers it inside the subprocess env via `ClaudeAgentOptions(env={"ANTHROPIC_API_KEY": ""})`, so every agent turn bills against your Pro/Max subscription. A `note:` is printed at run start if a key is detected.

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

## Customizing the agents

Agent behavior lives in markdown under [`agents/`](agents) at the repo root (with a `.claude/agents` symlink so in-repo Claude Code sessions also see them). The YAML frontmatter names the role and declares allowed tools; the body is the system prompt. Next run picks up your changes — no code edit required.

Useful tweaks:

- Loosen `script-critic` / `corpus-script-critic` acronym-expansion for technical audiences (they currently nag "AI" and "LLM" on every occurrence).
- Change chapter-count target in `opinion-aggregator` (defaults to 3–5 based on content density).
- Tighten `transcript-investigator` density targets for longer sources.
- Change the search keyword menu in `src/oratio/youtube_search/find.py::DEFAULT_QUERIES` or raise `DEFAULT_PER_QUERY` if the finder needs a bigger pool.
- Tune the era boundaries in `era-aggregator.md` — 2–4 eras is the default envelope; widen if you're processing someone with a 30-year corpus.

## Known limitations

- **Name-mode runtime is long.** A 5-video corpus takes ~20 min of yt-dlp work plus ~20–30 min of parallel agent wall-clock per video. Expect 1–2 hours end-to-end.
- **URL-mode runtime is also long.** A 60-min source takes ~45–60 min of agent wall-clock plus ~6 min of Kokoro synth on Apple Silicon. The investigator alone runs 8–15 min because it grep-verifies every quote.
- **Critic warnings are noisy.** Many `warn`-level issues (acronyms, homographs) don't actually degrade audio. Treat the verdict as advisory unless it's `block`.
- **YouTube search quality is coarse.** For less-indexed academics or people with common names, the `interview-finder` agent excludes aggressively — you'll get 3 videos when you asked for 5. Pass a more specific name (`"Dale Schuurmans University of Alberta"`) to tighten matches.
- **No motivation fabrication.** The `era-aggregator` and `corpus-script-critic` jointly refuse to invent *why* a view changed when the subject never said. Honest, but the script will sometimes say "he has not said publicly why this shifted."
- **English only.** Kokoro supports other languages but the voice conventions and script rules are tuned for English.
- **macOS-tested.** Dependencies (`espeak-ng`, `ffmpeg`, `torch`) exist on Linux and WSL, but I haven't verified the full pipeline there.

## Roadmap

- `--subject-name-hint` / `--institution` flags to disambiguate same-name people at the finder stage.
- Relax `script-critic` / `corpus-script-critic` acronym strictness automatically for technical audiences.
- Optional `--style` preset for the script writers (editorial / narrative / lecture-notes).
- Parallel chapter synthesis in `oratio-tts` (currently sequential per script).
- Cached `candidates.json` warmup — fall back to a stale cache with a warning when `--skip-search` is set but no cache exists.
- Publish to PyPI so `uvx oratio` works without cloning.

## Repo map

```
oratio/
├── pyproject.toml                 # deps + 6 CLI entry points
├── .claude-plugin/plugin.json     # Claude Code plugin manifest
├── agents/                        # 9 markdown agent specs (editable)
│   ├── transcript-investigator.md
│   ├── transcript-critic.md
│   ├── opinion-aggregator.md
│   ├── script-writer.md
│   ├── script-critic.md
│   ├── interview-finder.md        # name mode: filter search to formal talks
│   ├── era-aggregator.md          # name mode: chronological clustering + transitions
│   ├── corpus-script-writer.md    # name mode: per-era chapters with transition openings
│   └── corpus-script-critic.md    # name mode: cross-source verbatim + fabrication checks
├── skills/oratio/SKILL.md         # /oratio slash-command spec
├── .claude/                       # symlinks to agents/ and skills/ for in-repo dev
├── src/oratio/
│   ├── orchestrator.py            # `oratio` CLI — URL + name mode driver
│   ├── youtube_fetcher/fetch.py   # `oratio-fetch` — yt-dlp transcript fetcher
│   ├── youtube_search/find.py     # `oratio-find` — yt-dlp name-based search
│   ├── kokoro_tts/synthesize.py   # `oratio-tts` — two-voice Kokoro wrapper
│   ├── annotate/markdown.py       # `oratio-annotate` — .md sidecar generator
│   └── doctor.py                  # `oratio-doctor` — dependency self-check
├── examples/                      # Dale Schuurmans short (mp3 + txt)
└── output/                        # per-video + per-subject artifacts (gitignored)
```

## License

MIT for the Oratio code. Kokoro model weights are Apache-2.0. You are responsible for complying with YouTube's Terms of Service for any transcripts you fetch.
