"""Two-voice podcast synthesizer using Kokoro 82M.

Script format::

    [HOST] Narration spoken by the host voice.
    [MO] "A direct quote, spoken by the interviewee voice."
    [HOST] More narration.

Tag names are configurable via --host-tag / --quote-tag. Blank lines separate
paragraphs (become longer pauses). Only [MO]-style tags use the quote voice;
all paraphrase stays under [HOST].
"""

from __future__ import annotations

import argparse
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from pydub import AudioSegment

warnings.filterwarnings("ignore", category=UserWarning)

SAMPLE_RATE = 24_000
PAUSE_INTER_SENTENCE_MS = 120
PAUSE_INTER_SPEAKER_MS = 360
PAUSE_PARAGRAPH_MS = 560

# Canonical Chorus voice convention: one male + one female voice, always paired,
# with the host speaking in the opposite gender of the interviewee.
VOICE_MALE = "am_puck"
VOICE_FEMALE = "af_heart"


def voices_for_subject(subject_gender: str) -> tuple[str, str]:
    """Return (host_voice, quote_voice) given the interviewee's gender.

    Convention: interviewee is heard in their own-gender voice; host uses the
    opposite-gender voice for clear auditory separation.
    """
    g = subject_gender.lower()
    if g in {"m", "male"}:
        return VOICE_FEMALE, VOICE_MALE  # female host narrates a male subject
    if g in {"f", "female"}:
        return VOICE_MALE, VOICE_FEMALE  # male host narrates a female subject
    raise ValueError(f"subject_gender must be 'male' or 'female', got {subject_gender!r}")


@dataclass
class Line:
    speaker: str  # "host" or "quote"
    text: str
    ends_paragraph: bool = False


def parse_script(
    raw: str, host_tag: str, quote_tag: str
) -> list[Line]:
    """Parse a tagged script into ordered Lines. Blank lines mark paragraph
    boundaries that become longer pauses."""
    lines: list[Line] = []
    tag_re = re.compile(rf"^\[(?P<tag>{re.escape(host_tag)}|{re.escape(quote_tag)})\]\s*(?P<text>.*)$")
    pending_paragraph_break = False
    for raw_line in raw.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if lines:
                pending_paragraph_break = True
            continue
        m = tag_re.match(stripped)
        if not m:
            # Continuation of previous speaker
            if not lines:
                raise ValueError(f"Script must start with a speaker tag: {stripped[:60]!r}")
            lines[-1].text += " " + stripped
            continue
        speaker = "host" if m.group("tag") == host_tag else "quote"
        text = m.group("text").strip()
        if not text:
            continue
        if pending_paragraph_break and lines:
            lines[-1].ends_paragraph = True
            pending_paragraph_break = False
        lines.append(Line(speaker=speaker, text=text))
    return lines


def _silence(ms: int) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * ms / 1000), dtype=np.float32)


def _tensor_to_np(audio) -> np.ndarray:
    arr = audio.detach().cpu().numpy().astype(np.float32)
    if arr.ndim == 2:
        arr = arr.mean(axis=0)
    return arr


def synthesize(
    script_path: Path,
    out_path: Path,
    host_voice: str,
    quote_voice: str,
    host_tag: str = "HOST",
    quote_tag: str = "MO",
    speed: float = 1.0,
    lang_code: str = "a",
) -> Path:
    """Render script to audio file (mp3 or wav based on out_path suffix)."""
    from kokoro import KPipeline  # lazy import; heavy

    raw = script_path.read_text(encoding="utf-8")
    lines = parse_script(raw, host_tag=host_tag, quote_tag=quote_tag)
    if not lines:
        raise ValueError("Script parsed to zero lines")

    pipeline = KPipeline(lang_code=lang_code)

    audio_parts: list[np.ndarray] = []
    prev_speaker: str | None = None

    for i, line in enumerate(lines):
        voice = host_voice if line.speaker == "host" else quote_voice
        # Inter-speaker pause
        if prev_speaker is not None:
            if line.speaker != prev_speaker:
                audio_parts.append(_silence(PAUSE_INTER_SPEAKER_MS))
            else:
                audio_parts.append(_silence(PAUSE_INTER_SENTENCE_MS))
        # Paragraph break pause (on the PREVIOUS line boundary, stored on prev line)
        if i > 0 and lines[i - 1].ends_paragraph:
            audio_parts.append(_silence(PAUSE_PARAGRAPH_MS - PAUSE_INTER_SPEAKER_MS))

        for result in pipeline(line.text, voice=voice, speed=speed):
            if result.audio is None:
                continue
            audio_parts.append(_tensor_to_np(result.audio))
        prev_speaker = line.speaker

    if not audio_parts:
        raise RuntimeError("No audio generated")

    full = np.concatenate(audio_parts)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = out_path.suffix.lower()
    if suffix == ".wav":
        sf.write(str(out_path), full, SAMPLE_RATE)
    elif suffix == ".mp3":
        # Write to in-memory WAV via soundfile then transcode to mp3 via pydub/ffmpeg
        tmp_wav = out_path.with_suffix(".wav")
        sf.write(str(tmp_wav), full, SAMPLE_RATE)
        seg = AudioSegment.from_wav(str(tmp_wav))
        seg.export(str(out_path), format="mp3", bitrate="192k")
        tmp_wav.unlink(missing_ok=True)
    else:
        raise ValueError(f"Unsupported output format: {suffix}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Two-voice Kokoro TTS synthesizer.")
    ap.add_argument("script", type=Path, help="Path to tagged script file")
    ap.add_argument("-o", "--out", type=Path, required=True, help="Output .mp3 or .wav")
    ap.add_argument(
        "--subject-gender",
        choices=["male", "female"],
        help=(
            "Gender of the interviewee. Auto-picks voices per Chorus convention: "
            "male subject -> host=af_heart, quote=am_puck; female subject -> host=am_puck, quote=af_heart. "
            "Overridden by --host-voice / --quote-voice if both are given."
        ),
    )
    ap.add_argument("--host-voice", help="Override host voice (e.g. af_heart, am_puck)")
    ap.add_argument("--quote-voice", help="Override quote voice")
    ap.add_argument("--host-tag", default="HOST")
    ap.add_argument("--quote-tag", default="MO")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument(
        "--lang-code",
        default="a",
        help="Kokoro lang code: 'a'=American English, 'b'=British English",
    )
    args = ap.parse_args()

    if args.host_voice and args.quote_voice:
        host_voice, quote_voice = args.host_voice, args.quote_voice
    elif args.subject_gender:
        host_voice, quote_voice = voices_for_subject(args.subject_gender)
        if args.host_voice:
            host_voice = args.host_voice
        if args.quote_voice:
            quote_voice = args.quote_voice
    else:
        ap.error("Provide either --subject-gender or both --host-voice and --quote-voice")

    path = synthesize(
        script_path=args.script,
        out_path=args.out,
        host_voice=host_voice,
        quote_voice=quote_voice,
        host_tag=args.host_tag,
        quote_tag=args.quote_tag,
        speed=args.speed,
        lang_code=args.lang_code,
    )
    print(path, file=sys.stderr)


if __name__ == "__main__":
    main()
