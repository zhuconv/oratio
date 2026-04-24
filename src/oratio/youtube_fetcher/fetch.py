"""Fetch YouTube video metadata + subtitles via yt-dlp.

Outputs per URL:
    <out>/<video_id>/metadata.json      - title, uploader, duration, URL, etc.
    <out>/<video_id>/transcript.srt     - original SRT (preserves timing)
    <out>/<video_id>/transcript.txt     - flat text with [mm:ss] prefixes per cue

Prefers human-written subtitles; falls back to auto-generated.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yt_dlp


SUBTITLE_LANG = "en"


def _srt_to_text(srt_path: Path) -> str:
    """Convert SRT cues to '[mm:ss] <text>\\n' lines. Dedupes consecutive duplicates
    (common in YouTube auto-captions that overlap)."""
    raw = srt_path.read_text(encoding="utf-8")
    # SRT cue block: index \n start --> end \n text...
    cue_re = re.compile(
        r"\d+\s*\n"
        r"(\d{2}):(\d{2}):(\d{2})[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}\s*\n"
        r"(.*?)(?=\n\n|\Z)",
        re.DOTALL,
    )
    lines: list[str] = []
    last_text = ""
    for m in cue_re.finditer(raw):
        hh, mm, ss, text = m.groups()
        text = re.sub(r"<[^>]+>", "", text).strip().replace("\n", " ")
        text = re.sub(r"\s+", " ", text)
        if not text or text == last_text:
            continue
        last_text = text
        total_min = int(hh) * 60 + int(mm)
        lines.append(f"[{total_min:02d}:{ss}] {text}")
    return "\n".join(lines) + "\n"


def fetch(url: str, out_root: Path) -> Path:
    """Fetch one video's transcript + metadata. Returns the per-video output dir."""
    out_root.mkdir(parents=True, exist_ok=True)
    # Probe id first so we know where to write.
    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    video_id = info["id"]
    video_dir = out_root / video_id
    video_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [SUBTITLE_LANG],
        "subtitlesformat": "srt/vtt/best",
        "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # yt-dlp names subs <id>.<lang>.srt or .vtt
    srt = next(video_dir.glob(f"{video_id}.{SUBTITLE_LANG}.srt"), None)
    vtt = next(video_dir.glob(f"{video_id}.{SUBTITLE_LANG}.vtt"), None)
    sub_path: Path | None
    if srt and srt.exists():
        sub_path = srt
    elif vtt and vtt.exists():
        # Convert vtt -> srt via ffmpeg is easiest, but parsing vtt is close enough:
        # yt-dlp usually gives srt when requested; we fall back here.
        sub_path = _vtt_to_srt(vtt, video_dir / f"{video_id}.{SUBTITLE_LANG}.srt")
    else:
        sub_path = None

    metadata = {
        "id": video_id,
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "channel": info.get("channel"),
        "duration_sec": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "url": info.get("webpage_url", url),
        "description": info.get("description"),
        "subtitles_source": _classify_sub_source(info, sub_path),
    }
    (video_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False)
    )

    if sub_path is None:
        print(f"[warn] no subtitles for {video_id}", file=sys.stderr)
        return video_dir

    canonical_srt = video_dir / "transcript.srt"
    if sub_path.resolve() != canonical_srt.resolve():
        canonical_srt.write_text(sub_path.read_text(encoding="utf-8"))
    (video_dir / "transcript.txt").write_text(_srt_to_text(canonical_srt))
    return video_dir


def _vtt_to_srt(vtt: Path, srt_out: Path) -> Path:
    """Minimal VTT -> SRT: strip WEBVTT header, change '.' to ',' in timestamps,
    renumber cues."""
    text = vtt.read_text(encoding="utf-8")
    text = re.sub(r"^WEBVTT.*?\n\n", "", text, count=1, flags=re.DOTALL)
    cues = [c.strip() for c in text.split("\n\n") if "-->" in c]
    out: list[str] = []
    for i, cue in enumerate(cues, 1):
        cue = cue.replace(".", ",", 2)  # only timestamps have '.' before text
        out.append(f"{i}\n{cue}")
    srt_out.write_text("\n\n".join(out) + "\n")
    return srt_out


def _classify_sub_source(info: dict, sub_path: Path | None) -> str:
    if sub_path is None:
        return "none"
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    if SUBTITLE_LANG in subs:
        return "manual"
    if SUBTITLE_LANG in auto:
        return "auto"
    return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch YouTube transcript via yt-dlp.")
    ap.add_argument("url", help="YouTube video URL")
    ap.add_argument(
        "-o", "--out", default="output", help="output root dir (default: ./output)"
    )
    args = ap.parse_args()
    video_dir = fetch(args.url, Path(args.out))
    print(video_dir)


if __name__ == "__main__":
    main()
