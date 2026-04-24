"""Batch-synthesize Dale Schuurmans POC scripts."""

import json
from pathlib import Path

from oratio.kokoro_tts.synthesize import synthesize, voices_for_subject

BASE = Path("output/yGLoWZP1MyA")
opinions = json.loads((BASE / "opinions.json").read_text())
HOST, QUOTE = voices_for_subject(opinions["subject_gender"])
TAG = opinions["subject_tag"]

JOBS = [(BASE / "short" / "script.txt", BASE / "short" / "short.mp3")]
for ch in sorted((BASE / "long").glob("ch*_script.txt")):
    JOBS.append((ch, ch.with_name(ch.stem.replace("_script", "") + ".mp3")))

for script_path, out_path in JOBS:
    print(f"\n[synth] {script_path.name} -> {out_path.name}")
    synthesize(
        script_path=script_path,
        out_path=out_path,
        host_voice=HOST,
        quote_voice=QUOTE,
        host_tag="HOST",
        quote_tag=TAG,
        speed=1.0,
        lang_code="a",
    )
    print(f"[done]  {out_path.name}")

print("\nAll done.")
