"""Oratio orchestrator CLI.

Usage:
    uv run oratio <url_or_name> [--model claude-opus-4-6]
                                # URL-mode flags:
                                [--skip-fetch]
                                [--skip-synth]
                                # name-mode flags:
                                [--max-videos 5]
                                [--min-duration 1200]
                                [--skip-search]

Two modes, auto-detected by the first positional arg:

URL mode — one YouTube URL → one subject → short + long (themed) podcast.
    0. fetch           (subprocess: oratio-fetch)
    1. investigate     (transcript-investigator)
    2. critic(inv)     (transcript-critic)              [loop max 2x]
    3. aggregate       (opinion-aggregator)
    4. write           (script-writer)
    5. critic(script)  (script-critic)                  [loop max 2x]
    6. annotate        (deterministic post-process: .md + sources.json)
    7. synthesize      (subprocess: Kokoro batch)

Name mode — a person's name → corpus of talks → chronological podcast.
    0. search          (subprocess: oratio-find)
    1. filter          (interview-finder)
    2. per video (parallel):
         fetch → investigate → transcript-critic        [loop max 2x]
    3. era-aggregate   (era-aggregator)
    4. write           (corpus-script-writer)
    5. critic(script)  (corpus-script-critic)           [loop max 2x]
    6. annotate        (deterministic post-process: .md + sources.json)
    7. synthesize      (subprocess: Kokoro batch)

Each agent phase is a single ``query()`` call to the local ``claude`` binary via
claude-agent-sdk. No ANTHROPIC_API_KEY is used — auth is inherited from the
CLI login (Pro/Max subscription).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
# Agent specs live at the repo root so the plugin install layout and the
# dev-mode layout can share one source of truth. `.claude/agents` is a symlink
# to `agents/` for in-repo Claude Code sessions; orchestrator reads the real path.
AGENTS_DIR = REPO_ROOT / "agents"
OUTPUT_ROOT = REPO_ROOT / "output"
STAGING_DIR = OUTPUT_ROOT / "_staging"

DEFAULT_MODEL = "claude-opus-4-6"
MAX_CRITIC_ROUNDS = 2

# Clobber ANTHROPIC_API_KEY in the env we hand to the `claude` binary. The SDK
# merges this dict last, so it overrides anything inherited from the user's
# shell. Empty string tells `claude` the key is absent, which forces it to
# fall back to subscription auth (Pro/Max) stored in its OAuth keychain. This
# is the only code-level guarantee that a stray exported key doesn't silently
# switch us to API billing mid-run.
_SUBSCRIPTION_ONLY_ENV = {"ANTHROPIC_API_KEY": ""}


# --------------------------------------------------------------------- helpers


def load_agent_prompt(role: str) -> str:
    """Load `.claude/agents/<role>.md`, strip YAML frontmatter, return body."""
    path = AGENTS_DIR / f"{role}.md"
    raw = path.read_text(encoding="utf-8")
    # Strip leading `---\n...\n---\n` frontmatter block if present.
    fm = re.match(r"^---\n.*?\n---\n", raw, re.DOTALL)
    return raw[fm.end():] if fm else raw


_YT_URL_RE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)


def is_youtube_url(s: str) -> bool:
    """True if ``s`` looks like a YouTube URL; otherwise it's a name."""
    return bool(_YT_URL_RE.match(s.strip()))


def video_id_from_url(url: str) -> str:
    """Extract YouTube video id from URL."""
    qs = parse_qs(urlparse(url).query)
    if "v" in qs:
        return qs["v"][0]
    # Handle youtu.be/<id> form
    path = urlparse(url).path.lstrip("/")
    if path:
        return path.split("/")[0]
    raise ValueError(f"Could not extract video id from {url!r}")


_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def slugify(text: str, *, sep: str = "_", max_len: int = 60, lower: bool = True) -> str:
    """Filesystem-safe slug. Preserves ASCII alnum, collapses everything else to `sep`."""
    if not text:
        return ""
    s = _SLUG_RE.sub(sep, text).strip(sep)
    if lower:
        s = s.lower()
    return s[:max_len].rstrip(sep)


def subject_dir_name(subject_name: str) -> str:
    """Top-level folder for a subject: 'Mo Gawdat' -> 'Mo_Gawdat'."""
    return _SLUG_RE.sub("_", subject_name.strip()).strip("_")


def _dated_leaf(metadata: dict, video_id: str) -> str:
    """Produce '<YYYY-MM-DD>__<id>__<title_slug>' from fetch metadata."""
    upload = metadata.get("upload_date") or ""
    if len(upload) == 8 and upload.isdigit():
        date_str = f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}"
    else:
        date_str = date.today().isoformat()
    title_slug = slugify(metadata.get("title") or "", max_len=50) or "untitled"
    return f"{date_str}__{video_id}__{title_slug}"


def final_work_dir(subject_name: str, metadata: dict, video_id: str) -> Path:
    """URL-mode finalized path: output/<Subject>/<date>__<id>__<title>/."""
    return OUTPUT_ROOT / subject_dir_name(subject_name) / _dated_leaf(metadata, video_id)


def corpus_dir_for(name: str) -> Path:
    """Name-mode corpus root: output/<Name>/_corpus/."""
    return OUTPUT_ROOT / subject_dir_name(name) / "_corpus"


def corpus_video_dir(corpus_dir: Path, metadata: dict, video_id: str) -> Path:
    """Name-mode per-video dir: <corpus_dir>/<date>__<id>__<title>/."""
    return corpus_dir / _dated_leaf(metadata, video_id)


def resolve_work_dir(video_id: str) -> Path | None:
    """Find an existing work dir for this video_id across all supported layouts:

    1. output/<Subject>/<date>__<video_id>__<title>/   (finalized)
    2. output/_staging/<video_id>/                     (in-progress)
    3. output/<video_id>/                              (legacy flat)
    """
    if not OUTPUT_ROOT.exists():
        return None
    for p in OUTPUT_ROOT.glob(f"*/*__{video_id}__*"):
        if p.is_dir():
            return p
    staged = STAGING_DIR / video_id
    if staged.exists():
        return staged
    flat = OUTPUT_ROOT / video_id
    if flat.exists() and flat.is_dir():
        return flat
    return None


def promote_to_final(work_dir: Path, opinions: dict) -> Path:
    """If `work_dir` is in staging, move it to its finalized location.

    Returns the (possibly new) path. Idempotent — a work_dir already in
    finalized form is returned unchanged.
    """
    if STAGING_DIR not in work_dir.parents:
        return work_dir
    metadata_path = work_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    video_id = metadata["id"]
    subject = opinions.get("subject_name") or "Unknown"
    target = final_work_dir(subject, metadata, video_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    # If target already exists (re-run with same subject/date/id), append suffix.
    if target.exists():
        for i in range(2, 20):
            candidate = target.with_name(f"{target.name}__rerun{i}")
            if not candidate.exists():
                target = candidate
                break
    shutil.move(str(work_dir), str(target))
    say(f"promoted: {work_dir.name} -> {target.relative_to(OUTPUT_ROOT)}")
    return target


def say(msg: str) -> None:
    print(f"\n\033[1;36m[oratio]\033[0m {msg}", flush=True)


def run_subprocess(cmd: list[str], cwd: Path) -> None:
    """Run a subprocess, stream output, raise on failure."""
    say(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Subprocess failed ({result.returncode}): {' '.join(cmd)}")


async def run_agent(
    role: str,
    user_prompt: str,
    allowed_tools: list[str],
    model: str,
    cwd: Path,
) -> str:
    """Invoke one Claude agent phase. Returns the final assistant text."""
    system_prompt = load_agent_prompt(role)
    opts = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
        cwd=str(cwd),
        env=_SUBSCRIPTION_ONLY_ENV,
    )
    final_text_parts: list[str] = []
    say(f"→ agent: {role}")
    async for msg in query(prompt=user_prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    # Stream a compact tag so user sees progress without flood.
                    preview = block.text[:80].replace("\n", " ")
                    print(f"    {role}> {preview}…", flush=True)
                    final_text_parts.append(block.text)
        elif isinstance(msg, ResultMessage):
            if msg.is_error:
                raise RuntimeError(f"{role}: agent errored ({msg.subtype})")
            say(
                f"  {role} done in {msg.duration_ms}ms "
                f"({msg.num_turns} turns)"
            )
    return "\n".join(final_text_parts)


# --------------------------------------------------------------------- phases


async def phase_investigate(video_dir: Path, model: str) -> Path:
    out = video_dir / "opinions.raw.json"
    user_prompt = (
        f"transcript_path: {video_dir / 'transcript.txt'}\n"
        f"metadata_path:   {video_dir / 'metadata.json'}\n"
        f"output_path:     {out}\n\n"
        "Follow the system prompt exactly. Write opinions.raw.json to output_path, "
        "then respond with only the absolute output path."
    )
    await run_agent(
        role="transcript-investigator",
        user_prompt=user_prompt,
        allowed_tools=["Read", "Grep", "Write"],
        model=model,
        cwd=video_dir.parent.parent,
    )
    if not out.exists():
        raise RuntimeError(f"investigator did not produce {out}")
    return out


async def phase_transcript_critic(video_dir: Path, model: str) -> dict:
    out = video_dir / "transcript_critic_report.json"
    user_prompt = (
        f"opinions_path:  {video_dir / 'opinions.raw.json'}\n"
        f"transcript_path:{video_dir / 'transcript.txt'}\n"
        f"report_path:    {out}\n\n"
        "Follow the system prompt. Write the report, then respond with only "
        "the absolute report path."
    )
    await run_agent(
        role="transcript-critic",
        user_prompt=user_prompt,
        allowed_tools=["Read", "Grep", "Write"],
        model=model,
        cwd=video_dir.parent.parent,
    )
    if not out.exists():
        raise RuntimeError(f"critic did not produce {out}")
    return json.loads(out.read_text(encoding="utf-8"))


async def phase_aggregate(video_dir: Path, model: str) -> Path:
    out = video_dir / "opinions.json"
    user_prompt = (
        f"raw_opinions_path: {video_dir / 'opinions.raw.json'}\n"
        f"output_path:       {out}\n\n"
        "One raw-opinions file (single-video POC). Follow the system prompt. "
        "Write opinions.json, then respond with only the absolute output path."
    )
    await run_agent(
        role="opinion-aggregator",
        user_prompt=user_prompt,
        allowed_tools=["Read", "Write"],
        model=model,
        cwd=video_dir.parent.parent,
    )
    if not out.exists():
        raise RuntimeError(f"aggregator did not produce {out}")
    return out


async def phase_write(video_dir: Path, model: str) -> Path:
    scripts_dir = video_dir
    short_dir = scripts_dir / "short"
    long_dir = scripts_dir / "long"
    short_dir.mkdir(parents=True, exist_ok=True)
    long_dir.mkdir(parents=True, exist_ok=True)
    user_prompt = (
        f"opinions_path: {video_dir / 'opinions.json'}\n"
        f"output_dir:    {scripts_dir}\n\n"
        "Write short/script.txt and long/ch<NN>_<slug>_script.txt files per the "
        "system prompt. After writing all files, respond with one path per line "
        "(absolute paths, nothing else)."
    )
    await run_agent(
        role="script-writer",
        user_prompt=user_prompt,
        allowed_tools=["Read", "Write"],
        model=model,
        cwd=video_dir.parent.parent,
    )
    short_script = short_dir / "script.txt"
    if not short_script.exists():
        raise RuntimeError(f"writer did not produce {short_script}")
    return scripts_dir


async def phase_script_critic(video_dir: Path, model: str) -> dict:
    out = video_dir / "script_critic_report.json"
    user_prompt = (
        f"scripts_dir:    {video_dir}\n"
        f"opinions_path:  {video_dir / 'opinions.json'}\n"
        f"report_path:    {out}\n\n"
        "Follow the system prompt. Write the report, respond with only the path."
    )
    await run_agent(
        role="script-critic",
        user_prompt=user_prompt,
        allowed_tools=["Read", "Grep", "Write"],
        model=model,
        cwd=video_dir.parent.parent,
    )
    if not out.exists():
        raise RuntimeError(f"script-critic did not produce {out}")
    return json.loads(out.read_text(encoding="utf-8"))


def phase_fetch(url: str) -> Path:
    """Fetch into staging. Orchestrator promotes to final location post-aggregate."""
    say(f"fetching: {url}")
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    run_subprocess(
        ["uv", "run", "oratio-fetch", url, "-o", str(STAGING_DIR)],
        cwd=REPO_ROOT,
    )
    vid = video_id_from_url(url)
    video_dir = STAGING_DIR / vid
    if not (video_dir / "transcript.txt").exists():
        raise RuntimeError(f"fetch did not produce transcript for {vid}")
    return video_dir


def fetch_one_into_corpus(url: str, corpus_dir: Path) -> Path:
    """Name-mode fetch: place a single video's artifacts under ``corpus_dir``
    with the canonical dated layout. Idempotent — if already fetched, reuses."""
    vid = video_id_from_url(url)
    existing = next(corpus_dir.glob(f"*__{vid}__*"), None)
    if existing and (existing / "transcript.txt").exists():
        say(f"  already fetched: {existing.name}")
        return existing

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staged = STAGING_DIR / vid
    if not (staged / "transcript.txt").exists():
        run_subprocess(
            ["uv", "run", "oratio-fetch", url, "-o", str(STAGING_DIR)],
            cwd=REPO_ROOT,
        )
    if not (staged / "transcript.txt").exists():
        raise RuntimeError(f"fetch did not produce transcript for {vid}")

    metadata = json.loads((staged / "metadata.json").read_text(encoding="utf-8"))
    target = corpus_video_dir(corpus_dir, metadata, vid)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged), str(target))
    say(f"  staged -> {target.relative_to(OUTPUT_ROOT)}")
    return target


def phase_synthesize(video_dir: Path) -> list[Path]:
    opinions_path = video_dir / "opinions.json"
    opinions = json.loads(opinions_path.read_text(encoding="utf-8"))
    gender = opinions.get("subject_gender")
    if gender not in ("male", "female"):
        raise RuntimeError(
            f"opinions.json missing subject_gender; got {gender!r}"
        )

    scripts: list[tuple[Path, Path]] = []
    short_script = video_dir / "short" / "script.txt"
    if short_script.exists():
        scripts.append((short_script, video_dir / "short" / "short.mp3"))
    for ch in sorted((video_dir / "long").glob("ch*_script.txt")):
        mp3 = ch.with_name(ch.stem.replace("_script", "") + ".mp3")
        scripts.append((ch, mp3))

    from oratio.kokoro_tts.synthesize import synthesize, voices_for_subject
    host_voice, quote_voice = voices_for_subject(gender)

    outputs: list[Path] = []
    for script_path, mp3_path in scripts:
        say(f"synth: {script_path.name} -> {mp3_path.name}")
        synthesize(
            script_path=script_path,
            out_path=mp3_path,
            host_voice=host_voice,
            quote_voice=quote_voice,
            host_tag="HOST",
            quote_tag=opinions.get("subject_tag", "GUEST"),
            speed=1.0,
            lang_code="a",
        )
        outputs.append(mp3_path)
    return outputs


# ----------------------------------------------------------- name-mode phases


def phase_search(name: str, corpus_dir: Path, min_duration: int) -> Path:
    """Call oratio-find subprocess. Produces corpus_dir/candidates.json."""
    say(f"searching YouTube for '{name}'")
    corpus_dir.mkdir(parents=True, exist_ok=True)
    run_subprocess(
        [
            "uv", "run", "oratio-find", name,
            "-o", str(corpus_dir),
            "--min-duration", str(min_duration),
            "-v",
        ],
        cwd=REPO_ROOT,
    )
    out = corpus_dir / "candidates.json"
    if not out.exists():
        raise RuntimeError(f"oratio-find did not produce {out}")
    return out


async def phase_interview_finder(
    *,
    name: str,
    candidates_path: Path,
    output_path: Path,
    max_videos: int,
    model: str,
) -> Path:
    user_prompt = (
        f"candidates_path: {candidates_path}\n"
        f"subject_name:    {name}\n"
        f"max_videos:      {max_videos}\n"
        f"min_videos:      1\n"
        f"output_path:     {output_path}\n\n"
        "Follow the system prompt exactly. Write videos.json to output_path, "
        "then respond with only the absolute output path."
    )
    await run_agent(
        role="interview-finder",
        user_prompt=user_prompt,
        allowed_tools=["Read", "Write"],
        model=model,
        cwd=candidates_path.parent,
    )
    if not output_path.exists():
        raise RuntimeError(f"interview-finder did not produce {output_path}")
    return output_path


async def _investigate_one_video(
    video_entry: dict, video_dir: Path, model: str
) -> dict:
    """Run transcript-investigator + transcript-critic (with retry) on one video."""
    for round_num in range(1, MAX_CRITIC_ROUNDS + 1):
        await phase_investigate(video_dir, model)
        report = await phase_transcript_critic(video_dir, model)
        if report.get("verdict") == "pass":
            break
        say(
            f"  [{video_entry['id']}] transcript-critic verdict="
            f"{report.get('verdict')} (round {round_num}/{MAX_CRITIC_ROUNDS}); "
            "retrying investigator"
        )
    else:
        say(f"  [{video_entry['id']}] critic still failing; proceeding")
    opinions_raw = video_dir / "opinions.raw.json"
    if not opinions_raw.exists():
        raise RuntimeError(f"investigator did not leave {opinions_raw}")
    return {
        "video_id": video_entry["id"],
        "upload_date": video_entry.get("upload_date"),
        "path": str(opinions_raw),
    }


async def phase_era_aggregate(
    *,
    videos_path: Path,
    opinions_index_path: Path,
    output_path: Path,
    model: str,
    cwd: Path,
) -> Path:
    user_prompt = (
        f"videos_path:    {videos_path}\n"
        f"opinions_paths: {opinions_index_path}\n"
        f"output_path:    {output_path}\n\n"
        "Follow the system prompt exactly. Write evolution.json, then respond "
        "with only the absolute output path."
    )
    await run_agent(
        role="era-aggregator",
        user_prompt=user_prompt,
        allowed_tools=["Read", "Write"],
        model=model,
        cwd=cwd,
    )
    if not output_path.exists():
        raise RuntimeError(f"era-aggregator did not produce {output_path}")
    return output_path


async def phase_corpus_write(
    evolution_path: Path, output_dir: Path, model: str
) -> Path:
    (output_dir / "short").mkdir(parents=True, exist_ok=True)
    (output_dir / "long").mkdir(parents=True, exist_ok=True)
    user_prompt = (
        f"evolution_path: {evolution_path}\n"
        f"output_dir:     {output_dir}\n\n"
        "Follow the system prompt. Write short/script.txt and "
        "long/<chapter_slug>_script.txt files. After writing all files, respond "
        "with one path per line (absolute, nothing else)."
    )
    await run_agent(
        role="corpus-script-writer",
        user_prompt=user_prompt,
        allowed_tools=["Read", "Write"],
        model=model,
        cwd=output_dir,
    )
    short_script = output_dir / "short" / "script.txt"
    if not short_script.exists():
        raise RuntimeError(f"corpus-script-writer did not produce {short_script}")
    return output_dir


async def phase_corpus_critic(
    *,
    scripts_dir: Path,
    evolution_path: Path,
    corpus_dir: Path,
    model: str,
) -> dict:
    report_path = corpus_dir / "script_critic_report.json"
    user_prompt = (
        f"scripts_dir:    {scripts_dir}\n"
        f"evolution_path: {evolution_path}\n"
        f"corpus_dir:     {corpus_dir}\n"
        f"report_path:    {report_path}\n\n"
        "Follow the system prompt. Write the report, respond with only the path."
    )
    await run_agent(
        role="corpus-script-critic",
        user_prompt=user_prompt,
        allowed_tools=["Read", "Grep", "Write"],
        model=model,
        cwd=corpus_dir.parent,
    )
    if not report_path.exists():
        raise RuntimeError(f"corpus-script-critic did not produce {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def phase_synthesize_corpus(scripts_dir: Path, evolution_path: Path) -> list[Path]:
    evolution = json.loads(evolution_path.read_text(encoding="utf-8"))
    gender = evolution.get("subject_gender")
    if gender not in ("male", "female"):
        raise RuntimeError(
            f"evolution.json missing subject_gender; got {gender!r}"
        )

    from oratio.kokoro_tts.synthesize import synthesize, voices_for_subject
    host_voice, quote_voice = voices_for_subject(gender)
    subject_tag = evolution.get("subject_tag", "GUEST")

    jobs: list[tuple[Path, Path]] = []
    short_script = scripts_dir / "short" / "script.txt"
    if short_script.exists():
        jobs.append((short_script, scripts_dir / "short" / "overview.mp3"))
    for era_script in sorted((scripts_dir / "long").glob("era*_script.txt")):
        mp3 = era_script.with_name(era_script.stem.replace("_script", "") + ".mp3")
        jobs.append((era_script, mp3))

    outputs: list[Path] = []
    for script_path, mp3_path in jobs:
        say(f"synth: {script_path.name} -> {mp3_path.name}")
        synthesize(
            script_path=script_path,
            out_path=mp3_path,
            host_voice=host_voice,
            quote_voice=quote_voice,
            host_tag="HOST",
            quote_tag=subject_tag,
            speed=1.0,
            lang_code="a",
        )
        outputs.append(mp3_path)
    return outputs


# --------------------------------------------------------------------- driver


def _warn_if_api_key_in_env() -> None:
    """Surface any ANTHROPIC_API_KEY in the shell env. We clobber it before
    spawning the CLI, but warning here makes it explicit to the user that
    their key isn't being used and billing goes through their subscription."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        say(
            "note: ANTHROPIC_API_KEY is set in your shell. Oratio strips it "
            "before handing control to the local `claude` CLI, so all agent "
            "turns bill against your Pro/Max subscription, not the API. "
            "Unset it if the warning bothers you."
        )


async def orchestrate(url: str, model: str, skip_fetch: bool, skip_synth: bool) -> None:
    _warn_if_api_key_in_env()
    vid = video_id_from_url(url)
    if skip_fetch:
        video_dir = resolve_work_dir(vid)
        if video_dir is None or not (video_dir / "transcript.txt").exists():
            raise RuntimeError(
                f"--skip-fetch set but no existing work dir found for video_id {vid}. "
                f"Searched finalized, staging, and legacy layouts under {OUTPUT_ROOT}."
            )
        say(f"skipping fetch; reusing {video_dir.relative_to(OUTPUT_ROOT)}")
    else:
        video_dir = phase_fetch(url)

    # investigate + critic (up to MAX_CRITIC_ROUNDS attempts)
    for round_num in range(1, MAX_CRITIC_ROUNDS + 1):
        await phase_investigate(video_dir, model)
        report = await phase_transcript_critic(video_dir, model)
        if report.get("verdict") == "pass":
            break
        say(
            f"  transcript-critic verdict={report.get('verdict')} "
            f"(round {round_num}/{MAX_CRITIC_ROUNDS}); retrying investigator"
        )
    else:
        say("  transcript-critic still failing; proceeding anyway")

    await phase_aggregate(video_dir, model)

    # First moment we know subject_name -> promote out of staging.
    opinions = json.loads((video_dir / "opinions.json").read_text(encoding="utf-8"))
    video_dir = promote_to_final(video_dir, opinions)

    # write + script-critic (up to MAX_CRITIC_ROUNDS attempts)
    for round_num in range(1, MAX_CRITIC_ROUNDS + 1):
        await phase_write(video_dir, model)
        report = await phase_script_critic(video_dir, model)
        if report.get("verdict") == "pass":
            break
        say(
            f"  script-critic verdict={report.get('verdict')} "
            f"(round {round_num}/{MAX_CRITIC_ROUNDS}); retrying writer"
        )
    else:
        say("  script-critic still failing; proceeding anyway")

    # Annotate: deterministic .md sidecars with source-linked timestamps. Runs
    # before synth so the markdown is available even with --skip-synth.
    try:
        from oratio.annotate.markdown import annotate_url
        for p in annotate_url(video_dir):
            say(f"  annotated: {p.relative_to(OUTPUT_ROOT)}")
    except Exception as e:
        say(f"  annotate skipped: {e}")

    if skip_synth:
        say("skipping synth per --skip-synth")
        return

    outputs = phase_synthesize(video_dir)
    say("done. mp3s:")
    for p in outputs:
        print(f"  {p}")


async def orchestrate_name(
    name: str,
    model: str,
    max_videos: int,
    min_duration: int,
    skip_search: bool,
    skip_synth: bool,
) -> None:
    _warn_if_api_key_in_env()
    corpus_dir = corpus_dir_for(name)
    corpus_dir.mkdir(parents=True, exist_ok=True)

    # 0. search
    candidates_path = corpus_dir / "candidates.json"
    if skip_search and candidates_path.exists():
        say(f"skipping search; reusing {candidates_path.name}")
    else:
        phase_search(name, corpus_dir, min_duration)

    # 1. interview-finder
    videos_path = corpus_dir / "videos.json"
    if not videos_path.exists():
        await phase_interview_finder(
            name=name,
            candidates_path=candidates_path,
            output_path=videos_path,
            max_videos=max_videos,
            model=model,
        )
    else:
        say(f"reusing existing {videos_path.name}")
    videos_payload = json.loads(videos_path.read_text(encoding="utf-8"))
    videos = videos_payload.get("videos") or []
    if not videos:
        raise RuntimeError(
            f"interview-finder included 0 videos for '{name}'. "
            f"Inspect {videos_path} for exclusion reasons."
        )
    say(
        f"finder kept {len(videos)}/{videos_payload.get('total_candidates', '?')} "
        f"candidates"
    )

    # 2. per-video fetch (sequential — fast I/O, easier to debug)
    video_dirs: list[tuple[dict, Path]] = []
    for idx, v in enumerate(videos, 1):
        say(f"[{idx}/{len(videos)}] fetch: {v['title']}")
        vdir = fetch_one_into_corpus(v["url"], corpus_dir)
        video_dirs.append((v, vdir))

    # 3. per-video investigate + critic (parallel — agent turns dominate wall time)
    say(f"running investigator + critic on {len(video_dirs)} videos in parallel")
    opinions_index = await asyncio.gather(
        *[
            _investigate_one_video(v, vd, model)
            for v, vd in video_dirs
        ]
    )
    opinions_index_path = corpus_dir / "opinions_index.json"
    opinions_index_path.write_text(
        json.dumps(opinions_index, indent=2), encoding="utf-8"
    )

    # 4. era-aggregate
    evolution_path = corpus_dir / "evolution.json"
    await phase_era_aggregate(
        videos_path=videos_path,
        opinions_index_path=opinions_index_path,
        output_path=evolution_path,
        model=model,
        cwd=corpus_dir.parent,
    )

    # 5. write + critic loop — scripts live at output/<Subject>/{short,long}/
    scripts_dir = corpus_dir.parent
    for round_num in range(1, MAX_CRITIC_ROUNDS + 1):
        await phase_corpus_write(evolution_path, scripts_dir, model)
        report = await phase_corpus_critic(
            scripts_dir=scripts_dir,
            evolution_path=evolution_path,
            corpus_dir=corpus_dir,
            model=model,
        )
        if report.get("verdict") == "pass":
            break
        say(
            f"  corpus-script-critic verdict={report.get('verdict')} "
            f"(round {round_num}/{MAX_CRITIC_ROUNDS}); retrying writer"
        )
    else:
        say("  corpus-script-critic still failing; proceeding anyway")

    # Annotate the corpus output with source-linked Markdown sidecars.
    try:
        from oratio.annotate.markdown import annotate_corpus
        for p in annotate_corpus(scripts_dir):
            say(f"  annotated: {p.relative_to(OUTPUT_ROOT)}")
    except Exception as e:
        say(f"  annotate skipped: {e}")

    if skip_synth:
        say("skipping synth per --skip-synth")
        return

    outputs = phase_synthesize_corpus(scripts_dir, evolution_path)
    say("done. mp3s:")
    for p in outputs:
        print(f"  {p}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Oratio — YouTube → two-voice podcast. "
        "Accepts a YouTube URL (single-video mode) or a subject name (corpus mode).",
    )
    ap.add_argument(
        "target",
        help="YouTube video URL, or a subject name like 'Dale Schuurmans'.",
    )
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument(
        "--skip-synth",
        action="store_true",
        help="Stop after script-critic; do not call Kokoro.",
    )
    # URL mode only
    ap.add_argument(
        "--skip-fetch",
        action="store_true",
        help="(URL mode) Reuse existing transcript if already fetched.",
    )
    # name mode only
    ap.add_argument(
        "--max-videos",
        type=int,
        default=5,
        help="(name mode) Hard cap on videos selected by interview-finder.",
    )
    ap.add_argument(
        "--min-duration",
        type=int,
        default=1200,
        help="(name mode) Minimum video duration in seconds (default: 1200 = 20 min).",
    )
    ap.add_argument(
        "--skip-search",
        action="store_true",
        help="(name mode) Reuse candidates.json + videos.json if already present.",
    )
    args = ap.parse_args()

    try:
        if is_youtube_url(args.target):
            asyncio.run(
                orchestrate(
                    args.target,
                    args.model,
                    args.skip_fetch,
                    args.skip_synth,
                )
            )
        else:
            asyncio.run(
                orchestrate_name(
                    name=args.target,
                    model=args.model,
                    max_videos=args.max_videos,
                    min_duration=args.min_duration,
                    skip_search=args.skip_search,
                    skip_synth=args.skip_synth,
                )
            )
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
