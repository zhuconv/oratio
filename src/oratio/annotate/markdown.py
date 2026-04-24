"""Annotate Oratio scripts with source-linked Markdown.

Pure Python post-processor — no agent turns. For each ``[<SUBJECT>]`` verbatim
quote in a TTS-ready script, we emit a Markdown blockquote with a YouTube
deep-link to the exact second the quote appears. Each ``[HOST]`` paragraph
inherits the attribution of its nearest preceding quote so a reader can scrub
back to the source even for paraphrase passages.

Auto-detects mode:

- **Corpus mode** — looks for ``_corpus/evolution.json`` under the given
  subject directory and produces ``short/script.md`` plus
  ``long/<chapter_slug>.md`` per era.
- **URL mode** — looks for ``opinions.json`` + ``metadata.json`` at the run
  directory level and produces ``short/script.md`` plus ``long/<slug>.md``
  per chapter.

Each script also gets a sibling ``sources.json`` listing every block with its
source video id, timestamp (seconds), and a deep-link URL — useful for any
downstream tool that wants to sync audio playback to source video.

CLI:
    oratio-annotate <run_or_subject_dir>
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------- helpers

_TS_RE = re.compile(r"\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?")


def parse_timestamp(ts: str | int | None) -> int:
    """Parse '[mm:ss]', '[hh:mm:ss]', 'mm:ss', or int seconds → int seconds."""
    if ts is None:
        return 0
    if isinstance(ts, int):
        return ts
    m = _TS_RE.match(str(ts).strip())
    if not m:
        return 0
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def fmt_time(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def yt_url(video_id: str, seconds: int = 0) -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    return f"{base}&t={seconds}s" if seconds else base


# --------------------------------------------------------------- block parsing

@dataclass
class Block:
    tag: str
    text: str


_TAG_RE = re.compile(r"^\[([A-Z][A-Z0-9_]*)\]\s*(.*)$")


def parse_script(script_text: str) -> list[Block]:
    """Parse an Oratio TTS script into ordered ``[TAG]`` blocks. Blank lines
    end a block; continuation lines (no tag prefix) extend the current one."""
    blocks: list[Block] = []
    cur_tag: str | None = None
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_tag, cur_lines
        if cur_tag is not None and cur_lines:
            text = " ".join(s.strip() for s in cur_lines).strip()
            if text:
                blocks.append(Block(cur_tag, text))
        cur_tag = None
        cur_lines = []

    for line in script_text.splitlines():
        if not line.strip():
            flush()
            continue
        m = _TAG_RE.match(line)
        if m:
            flush()
            cur_tag = m.group(1)
            cur_lines = [m.group(2)]
        else:
            cur_lines.append(line)
    flush()
    return blocks


# ----------------------------------------------------------- quote matching

_NORMALIZE_QUOTES = re.compile(r"[‘’“”'\"`]")


def normalize(s: str) -> str:
    s = _NORMALIZE_QUOTES.sub("", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_quote(text: str, quote_pool: list[dict]) -> dict | None:
    """Return the best match for ``text`` in ``quote_pool`` (or None).

    Matching uses normalized substring containment in either direction. When
    multiple match, prefer the one with the smallest length difference (i.e.
    the closest fit)."""
    needle = normalize(text)
    if not needle:
        return None
    candidates: list[tuple[dict, int]] = []
    for q in quote_pool:
        hay = normalize(q.get("quote") or "")
        if not hay:
            continue
        if needle in hay or hay in needle:
            candidates.append((q, abs(len(hay) - len(needle))))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]


def collect_quotes_from_evolution(evolution: dict) -> list[dict]:
    """Flatten every quote in evolution.json into a single pool with source ids."""
    pool: list[dict] = []
    for era in evolution.get("eras", []):
        for q in era.get("anchored_quotes", []):
            pool.append({
                "quote": q.get("quote"),
                "timestamp_s": parse_timestamp(q.get("timestamp")),
                "video_id": q.get("source_video_id"),
                "context": era.get("title") or era.get("id"),
            })
    for tr in evolution.get("transitions", []):
        for key in ("before_quote", "after_quote"):
            q = tr.get(key)
            if not q:
                continue
            pool.append({
                "quote": q.get("quote"),
                "timestamp_s": parse_timestamp(q.get("timestamp")),
                "video_id": q.get("source_video_id"),
                "context": (
                    f"transition {tr.get('from_era')}→{tr.get('to_era')} "
                    f"({key.replace('_quote', '')})"
                ),
            })
    for theme in evolution.get("stable_themes", []):
        for q in theme.get("representative_quotes", []):
            pool.append({
                "quote": q.get("quote"),
                "timestamp_s": parse_timestamp(q.get("timestamp")),
                "video_id": q.get("source_video_id"),
                "context": f"stable theme: {theme.get('title')}",
            })
    return pool


def collect_quotes_from_opinions(opinions: dict, fallback_video_id: str | None) -> list[dict]:
    pool: list[dict] = []
    for theme in opinions.get("themes", []):
        for q in theme.get("anchored_quotes", []):
            pool.append({
                "quote": q.get("quote"),
                "timestamp_s": parse_timestamp(q.get("timestamp")),
                "video_id": q.get("source_video_id") or fallback_video_id,
                "context": theme.get("title") or theme.get("id"),
            })
    return pool


# ----------------------------------------------------------- video metadata

def build_video_index(
    metadata_paths: list[Path],
    videos_json: dict | None = None,
) -> dict[str, dict]:
    """Map ``video_id`` → ``{url, title, upload_date, channel}``."""
    idx: dict[str, dict] = {}
    if videos_json:
        for v in videos_json.get("videos", []):
            vid = v.get("id")
            if not vid:
                continue
            idx[vid] = {
                "url": v.get("url") or yt_url(vid),
                "title": v.get("title"),
                "upload_date": v.get("upload_date"),
                "channel": v.get("channel"),
            }
    for mp in metadata_paths:
        if not mp.exists():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        vid = m.get("id")
        if not vid:
            continue
        e = idx.setdefault(vid, {})
        e["url"] = e.get("url") or m.get("url") or yt_url(vid)
        e["title"] = e.get("title") or m.get("title")
        e["upload_date"] = e.get("upload_date") or m.get("upload_date")
        e["channel"] = e.get("channel") or m.get("channel")
    return idx


# ----------------------------------------------------------- markdown render


def _short_title(t: str | None, cap: int = 50) -> str:
    if not t:
        return ""
    return t if len(t) <= cap else t[: cap - 1] + "…"


def _format_upload_date(d: str | None) -> str:
    if not d or len(d) < 8 or not d[:8].isdigit():
        return ""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def render_md(
    *,
    title: str,
    subtitle: str | None,
    blocks: list[Block],
    quote_pool: list[dict],
    video_index: dict[str, dict],
    subject_tag: str,
) -> tuple[str, list[dict]]:
    """Render a script as Markdown and return ``(md_text, sources_index)``."""
    out: list[str] = [f"# {title}", ""]
    if subtitle:
        out.append(f"_{subtitle}_")
        out.append("")

    sources: list[dict] = []
    last_match: dict | None = None
    unmatched = 0

    for block in blocks:
        if block.tag == "HOST":
            out.append(block.text)
            out.append("")
            sources.append({
                "tag": "HOST",
                "text_excerpt": block.text[:160],
                "near_video_id": last_match["video_id"] if last_match else None,
                "near_timestamp_s": last_match["timestamp_s"] if last_match else None,
            })
        elif block.tag == subject_tag:
            text = block.text.strip().strip('"').strip("'").strip()
            match = find_quote(text, quote_pool)
            if match and match.get("video_id"):
                last_match = match
                v = video_index.get(match["video_id"], {})
                ts = match["timestamp_s"] or 0
                ts_url = yt_url(match["video_id"], ts)
                vtitle = _short_title(v.get("title")) or match["video_id"]
                date_part = _format_upload_date(v.get("upload_date"))
                meta_bits = [f"[**{fmt_time(ts)}**]({ts_url})"]
                if vtitle:
                    meta_bits.append(f"_{vtitle}_")
                if date_part:
                    meta_bits.append(date_part)
                out.append("> " + " · ".join(meta_bits))
                out.append(">")
                out.append(f"> {text}")
                out.append("")
                sources.append({
                    "tag": subject_tag,
                    "text": text,
                    "video_id": match["video_id"],
                    "timestamp_s": ts,
                    "url": ts_url,
                    "context": match.get("context"),
                })
            else:
                unmatched += 1
                out.append(f"> {text}")
                out.append("")
                sources.append({
                    "tag": subject_tag,
                    "text": text,
                    "matched": False,
                })
        else:
            out.append(f"**[{block.tag}]** {block.text}")
            out.append("")

    md = "\n".join(out).rstrip() + "\n"
    if unmatched:
        # Footnote: a small disclaimer at the bottom.
        md += (
            f"\n_{unmatched} quote{'s' if unmatched != 1 else ''} could not be "
            f"matched against the source data; check evolution.json or "
            f"opinions.json for any drift._\n"
        )
    return md, sources


# ----------------------------------------------------------- mode handlers


def annotate_corpus(subject_dir: Path) -> list[Path]:
    """Annotate name-mode output: ``output/<Subject>/{short,long}/``."""
    corpus_dir = subject_dir / "_corpus"
    evolution_path = corpus_dir / "evolution.json"
    if not evolution_path.exists():
        raise FileNotFoundError(f"missing {evolution_path}")
    evolution = json.loads(evolution_path.read_text(encoding="utf-8"))
    quote_pool = collect_quotes_from_evolution(evolution)

    videos_path = corpus_dir / "videos.json"
    videos_json = (
        json.loads(videos_path.read_text(encoding="utf-8"))
        if videos_path.exists()
        else None
    )
    metadata_paths = list(corpus_dir.glob("*__*__*/metadata.json"))
    video_index = build_video_index(metadata_paths, videos_json)

    subject_tag = evolution.get("subject_tag", "GUEST")
    subject_name = evolution.get("subject_name", "")

    written: list[Path] = []

    short_txt = subject_dir / "short" / "script.txt"
    if short_txt.exists():
        blocks = parse_script(short_txt.read_text(encoding="utf-8"))
        date_range = evolution.get("date_range") or {}
        years = ""
        if date_range.get("earliest") and date_range.get("latest"):
            y1, y2 = date_range["earliest"][:4], date_range["latest"][:4]
            years = f"{y1}–{y2}" if y1 != y2 else y1
        subtitle = (
            f"Chronological overview · {evolution.get('video_count', '?')} talks"
            + (f" · {years}" if years else "")
        )
        md, sources = render_md(
            title=f"{subject_name} — Chronological Overview",
            subtitle=subtitle,
            blocks=blocks,
            quote_pool=quote_pool,
            video_index=video_index,
            subject_tag=subject_tag,
        )
        md += "\n## Source talks\n\n"
        # Stable order: by upload_date descending if available
        for vid, v in sorted(
            video_index.items(),
            key=lambda kv: kv[1].get("upload_date") or "",
            reverse=True,
        ):
            t = v.get("title") or vid
            d = _format_upload_date(v.get("upload_date"))
            md += f"- [{t}]({v.get('url', yt_url(vid))})" + (f" — {d}" if d else "") + "\n"
        out_path = subject_dir / "short" / "script.md"
        out_path.write_text(md, encoding="utf-8")
        (subject_dir / "short" / "sources.json").write_text(
            json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written.append(out_path)

    for txt in sorted((subject_dir / "long").glob("era*_script.txt")):
        slug = txt.stem.replace("_script", "")
        era = next(
            (e for e in evolution.get("eras", []) if e.get("chapter_slug") == slug),
            None,
        )
        title = era.get("title") if era else slug
        subtitle = None
        if era and era.get("date_range"):
            dr = era["date_range"]
            y1, y2 = (dr.get("start") or "")[:4], (dr.get("end") or "")[:4]
            subtitle = f"{y1}–{y2}" if y1 and y2 and y1 != y2 else y1 or y2 or None
        blocks = parse_script(txt.read_text(encoding="utf-8"))
        md, sources = render_md(
            title=f"{subject_name} — {title}",
            subtitle=subtitle,
            blocks=blocks,
            quote_pool=quote_pool,
            video_index=video_index,
            subject_tag=subject_tag,
        )
        if era:
            md += "\n## Sources for this era\n\n"
            for vid in era.get("source_video_ids", []):
                v = video_index.get(vid, {})
                t = v.get("title") or vid
                d = _format_upload_date(v.get("upload_date"))
                md += f"- [{t}]({v.get('url', yt_url(vid))})" + (f" — {d}" if d else "") + "\n"
        out_path = txt.with_name(f"{slug}.md")
        out_path.write_text(md, encoding="utf-8")
        (txt.with_name(f"{slug}_sources.json")).write_text(
            json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written.append(out_path)

    return written


def annotate_url(run_dir: Path) -> list[Path]:
    """Annotate URL-mode output: ``output/<Subject>/<date>__<id>__<slug>/``."""
    opinions_path = run_dir / "opinions.json"
    metadata_path = run_dir / "metadata.json"
    if not opinions_path.exists():
        raise FileNotFoundError(f"missing {opinions_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"missing {metadata_path}")
    opinions = json.loads(opinions_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    fallback_vid = metadata.get("id")
    quote_pool = collect_quotes_from_opinions(opinions, fallback_vid)
    video_index = build_video_index([metadata_path])

    subject_tag = opinions.get("subject_tag", "GUEST")
    subject_name = opinions.get("subject_name", "")
    src_title = metadata.get("title") or fallback_vid or "untitled"
    src_url = metadata.get("url") or yt_url(fallback_vid or "")

    written: list[Path] = []

    short_txt = run_dir / "short" / "script.txt"
    if short_txt.exists():
        blocks = parse_script(short_txt.read_text(encoding="utf-8"))
        md, sources = render_md(
            title=f"{subject_name} — {src_title}",
            subtitle="Short overview · ~5 min",
            blocks=blocks,
            quote_pool=quote_pool,
            video_index=video_index,
            subject_tag=subject_tag,
        )
        md += f"\n## Source\n\n[{src_title}]({src_url})\n"
        out_path = run_dir / "short" / "script.md"
        out_path.write_text(md, encoding="utf-8")
        (run_dir / "short" / "sources.json").write_text(
            json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written.append(out_path)

    for txt in sorted((run_dir / "long").glob("ch*_script.txt")):
        slug = txt.stem.replace("_script", "")
        m = re.match(r"ch(\d+)_(.+)", slug)
        chapter_label = f"Chapter {int(m.group(1))}" if m else slug
        blocks = parse_script(txt.read_text(encoding="utf-8"))
        md, sources = render_md(
            title=f"{subject_name} — {chapter_label}",
            subtitle=src_title,
            blocks=blocks,
            quote_pool=quote_pool,
            video_index=video_index,
            subject_tag=subject_tag,
        )
        md += f"\n## Source\n\n[{src_title}]({src_url})\n"
        out_path = txt.with_name(f"{slug}.md")
        out_path.write_text(md, encoding="utf-8")
        (txt.with_name(f"{slug}_sources.json")).write_text(
            json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written.append(out_path)

    return written


def annotate(target: Path) -> list[Path]:
    """Auto-detect mode and emit Markdown + sources.json sidecars."""
    target = target.resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"not a directory: {target}")
    if (target / "_corpus" / "evolution.json").exists():
        return annotate_corpus(target)
    if (target / "opinions.json").exists():
        return annotate_url(target)
    raise FileNotFoundError(
        f"could not detect Oratio output mode in {target}. "
        f"Expected '_corpus/evolution.json' (name mode) or 'opinions.json' (URL mode)."
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Emit source-linked Markdown + sources.json next to each Oratio "
            "script.txt. Auto-detects URL vs name mode."
        ),
    )
    ap.add_argument(
        "dir",
        help="output/<Subject>/ for name mode, or output/<Subject>/<run>/ for URL mode",
    )
    args = ap.parse_args()
    paths = annotate(Path(args.dir))
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
