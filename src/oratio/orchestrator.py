"""Oratio orchestrator CLI.

Usage:
    uv run oratio <youtube_url> [--model claude-opus-4-6]
                                [--skip-fetch]
                                [--skip-synth]

Pipeline:
    0. fetch           (subprocess: oratio-fetch)
    1. investigate     (transcript-investigator agent)
    2. critic(inv)     (transcript-critic agent)         [loop max 2x]
    3. aggregate       (opinion-aggregator agent)
    4. write           (script-writer agent)
    5. critic(script)  (script-critic agent)             [loop max 2x]
    6. synthesize      (subprocess: Kokoro batch)

Each agent phase is a single `query()` call to the local `claude` binary via
claude-agent-sdk. No ANTHROPIC_API_KEY is used — auth is inherited from the
CLI login (Pro/Max subscription, etc.).
"""

from __future__ import annotations

import argparse
import asyncio
import json
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
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
OUTPUT_ROOT = REPO_ROOT / "output"
STAGING_DIR = OUTPUT_ROOT / "_staging"

DEFAULT_MODEL = "claude-opus-4-6"
MAX_CRITIC_ROUNDS = 2


# --------------------------------------------------------------------- helpers


def load_agent_prompt(role: str) -> str:
    """Load `.claude/agents/<role>.md`, strip YAML frontmatter, return body."""
    path = AGENTS_DIR / f"{role}.md"
    raw = path.read_text(encoding="utf-8")
    # Strip leading `---\n...\n---\n` frontmatter block if present.
    fm = re.match(r"^---\n.*?\n---\n", raw, re.DOTALL)
    return raw[fm.end():] if fm else raw


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


def final_work_dir(
    subject_name: str, metadata: dict, video_id: str
) -> Path:
    """Compute the finalized work-dir path: output/<Subject>/<date>__<id>__<title>/."""
    subject_folder = subject_dir_name(subject_name)
    upload = metadata.get("upload_date") or ""
    if len(upload) == 8 and upload.isdigit():
        date_str = f"{upload[:4]}-{upload[4:6]}-{upload[6:8]}"
    else:
        date_str = date.today().isoformat()
    title_slug = slugify(metadata.get("title") or "", max_len=50) or "untitled"
    leaf = f"{date_str}__{video_id}__{title_slug}"
    return OUTPUT_ROOT / subject_folder / leaf


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


# --------------------------------------------------------------------- driver


async def orchestrate(url: str, model: str, skip_fetch: bool, skip_synth: bool) -> None:
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

    if skip_synth:
        say("skipping synth per --skip-synth")
        return

    outputs = phase_synthesize(video_dir)
    say("done. mp3s:")
    for p in outputs:
        print(f"  {p}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Oratio orchestrator.")
    ap.add_argument("url", help="YouTube video URL")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--skip-fetch", action="store_true",
                    help="Reuse existing transcript if already fetched")
    ap.add_argument("--skip-synth", action="store_true",
                    help="Stop after script-critic; do not call Kokoro")
    args = ap.parse_args()
    try:
        asyncio.run(orchestrate(args.url, args.model, args.skip_fetch, args.skip_synth))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
