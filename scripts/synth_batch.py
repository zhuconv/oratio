"""Batch-synthesize all Mo Gawdat POC scripts in one Kokoro session."""

from pathlib import Path

from oratio.kokoro_tts.synthesize import synthesize, voices_for_subject


HOST, QUOTE = voices_for_subject("male")  # af_heart, am_puck

BASE = Path("output/E0Q96IKXx6Q")

JOBS = [
    (BASE / "short" / "script.txt", BASE / "short" / "short.mp3"),
    (BASE / "long" / "ch01_ten_years_of_turbulence_script.txt",
     BASE / "long" / "ch01_ten_years_of_turbulence.mp3"),
    (BASE / "long" / "ch02_chess_is_over_script.txt",
     BASE / "long" / "ch02_chess_is_over.mp3"),
    (BASE / "long" / "ch03_raising_superman_script.txt",
     BASE / "long" / "ch03_raising_superman.mp3"),
]

for script_path, out_path in JOBS:
    print(f"\n[synth] {script_path}  ->  {out_path}")
    synthesize(
        script_path=script_path,
        out_path=out_path,
        host_voice=HOST,
        quote_voice=QUOTE,
        host_tag="HOST",
        quote_tag="MO",
        speed=1.0,
        lang_code="a",
    )
    print(f"[done]  {out_path}")

print("\nAll done.")
