"""Search YouTube for formal talks by a person's name.

Uses yt-dlp's Python API with ``ytsearchN:`` pseudo-URLs. No API key needed.
Produces a deduped, duration-filtered, date-enriched candidate list that the
``interview-finder`` agent filters down into a curated shortlist.

Pipeline:
    1. Flat search across several query templates (keynote, interview, podcast, ...).
    2. Dedupe by video id, collect matching-query list per hit.
    3. Full-extract probe (parallel) for upload_date + description + final duration.
    4. Apply min-duration and live-status filters.
    5. Sort newest-first and return.

CLI:
    chorus-find "Dale Schuurmans" -o output/Dale_Schuurmans/_corpus/
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
from pathlib import Path

import yt_dlp

DEFAULT_QUERIES: tuple[str, ...] = (
    "{name} keynote",
    "{name} interview",
    "{name} podcast",
    "{name} talk",
    "{name} lecture",
    "{name} fireside",
)

DEFAULT_PER_QUERY = 15
DEFAULT_MIN_DURATION = 1200  # 20 min — anything shorter is almost never a formal talk

_log = logging.getLogger("chorus.search")


def _flat_search(query: str, limit: int) -> list[dict]:
    """Run ``ytsearchN:<query>`` via yt-dlp flat extractor. Fast, no per-video probes."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noprogress": True,
        "ignoreerrors": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception as e:
        _log.warning("flat-search failed for %r: %s", query, e)
        return []
    return (info or {}).get("entries") or []


def _full_probe(video_id: str) -> dict | None:
    """Full metadata probe for one video id. Gives upload_date + description + canonical duration.

    We never download, only probe metadata. ``format=None`` skips format selection
    so the JS-challenge warnings yt-dlp normally surfaces (about deno/npm) don't
    appear — they're irrelevant to metadata extraction.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noprogress": True,
        "extract_flat": False,
        "ignoreerrors": True,
        "format": None,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False,
            )
    except Exception as e:
        _log.warning("probe failed for %s: %s", video_id, e)
        return None


def search_name(
    name: str,
    *,
    queries: tuple[str, ...] = DEFAULT_QUERIES,
    per_query: int = DEFAULT_PER_QUERY,
    min_duration_sec: int = DEFAULT_MIN_DURATION,
    probe_workers: int = 6,
) -> list[dict]:
    """Search YouTube for candidate formal talks by ``name``.

    Returns a list of dicts with keys::

        id, url, title, channel, uploader, duration_sec, upload_date,
        description (truncated), view_count, matched_queries, live_status

    Sorted newest-first.
    """
    all_hits: dict[str, dict] = {}
    for template in queries:
        q = template.format(name=name)
        _log.info("search: %s", q)
        for entry in _flat_search(q, per_query):
            if not entry:
                continue
            vid = entry.get("id")
            if not vid:
                continue
            dur = entry.get("duration") or 0
            if dur and dur < min_duration_sec:
                continue
            hit = all_hits.setdefault(
                vid,
                {
                    "id": vid,
                    "title": entry.get("title"),
                    "duration_sec": entry.get("duration"),
                    "uploader": entry.get("uploader"),
                    "channel": entry.get("channel"),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "view_count": entry.get("view_count"),
                    "matched_queries": [],
                },
            )
            if q not in hit["matched_queries"]:
                hit["matched_queries"].append(q)

    if not all_hits:
        return []

    _log.info(
        "probing %d unique candidates for upload_date + description",
        len(all_hits),
    )

    # Parallel probes. yt-dlp is I/O-bound per video — threads are fine.
    with concurrent.futures.ThreadPoolExecutor(max_workers=probe_workers) as pool:
        probes = list(pool.map(_full_probe, list(all_hits.keys())))

    enriched: list[dict] = []
    for hit, full in zip(all_hits.values(), probes):
        if full is None:
            continue
        dur = full.get("duration") or hit.get("duration_sec") or 0
        if dur < min_duration_sec:
            continue
        live_status = full.get("live_status")
        if live_status in ("is_live", "is_upcoming"):
            continue
        hit.update(
            {
                "duration_sec": dur,
                "upload_date": full.get("upload_date"),
                "description": (full.get("description") or "")[:800],
                "channel": full.get("channel") or hit.get("channel"),
                "uploader": full.get("uploader") or hit.get("uploader"),
                "view_count": full.get("view_count") or hit.get("view_count"),
                "availability": full.get("availability"),
                "live_status": live_status,
            }
        )
        enriched.append(hit)

    enriched.sort(key=lambda c: c.get("upload_date") or "", reverse=True)
    return enriched


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Search YouTube for formal talks by a person's name.",
    )
    ap.add_argument("name", help="Subject name, e.g. 'Dale Schuurmans'")
    ap.add_argument(
        "-o",
        "--out-dir",
        default=None,
        help="Directory to write candidates.json (default: stdout)",
    )
    ap.add_argument(
        "--per-query",
        type=int,
        default=DEFAULT_PER_QUERY,
        help=f"Hits per query template (default: {DEFAULT_PER_QUERY})",
    )
    ap.add_argument(
        "--min-duration",
        type=int,
        default=DEFAULT_MIN_DURATION,
        help=f"Minimum video duration in seconds (default: {DEFAULT_MIN_DURATION})",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="[find] %(message)s",
        stream=sys.stderr,
    )

    results = search_name(
        args.name,
        per_query=args.per_query,
        min_duration_sec=args.min_duration,
    )
    payload = {"name": args.name, "count": len(results), "candidates": results}
    body = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "candidates.json"
        out_path.write_text(body, encoding="utf-8")
        print(out_path)
    else:
        sys.stdout.write(body + "\n")


if __name__ == "__main__":
    main()
