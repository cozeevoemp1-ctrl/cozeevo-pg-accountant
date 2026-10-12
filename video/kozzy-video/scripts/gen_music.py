"""Generate an instrumental track with ACE-Step 1.5 (MIT, local) for a brand video.

Runs with ACE-Step's own venv (installed at D:/Work/Claude Projects/tools/ACE-Step-1.5):
  "D:/Work/Claude Projects/tools/ACE-Step-1.5/.venv/Scripts/python.exe" scripts/gen_music.py \
      --caption "upbeat modern tech product launch, instrumental, ..." --bpm 120 --duration 34 \
      --out public/music/app_demo.flac --seed 7

GTX 1070 (8 GB, Pascal): 2B turbo DiT, no LM, CPU offload — ACE-Step auto-selects the pt backend.
Generate 2-3 seeds and pick by ear; keep the BPM equal to the spec so cuts land on bars.
"""
import argparse
import os
import shutil
import sys

ACE_ROOT = r"D:\Work\Claude Projects\tools\ACE-Step-1.5"
sys.path.insert(0, ACE_ROOT)

from acestep.handler import AceStepHandler  # noqa: E402
from acestep.llm_inference import LLMHandler  # noqa: E402
from acestep.inference import GenerationParams, GenerationConfig, generate_music  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caption", required=True)
    ap.add_argument("--bpm", type=int, default=120)
    ap.add_argument("--duration", type=float, default=34)
    ap.add_argument("--key", default="C Major")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    dit, llm = AceStepHandler(), LLMHandler()
    msg, ok = dit.initialize_service(project_root=ACE_ROOT, config_path="acestep-v15-turbo", device="cuda",
                                     offload_to_cpu=True, offload_dit_to_cpu=True)
    if not ok:
        sys.exit(f"init failed: {msg}")

    params = GenerationParams(task_type="text2music", caption=a.caption, lyrics="[Instrumental]", instrumental=True,
                              duration=a.duration, bpm=a.bpm, keyscale=a.key, timesignature="4",
                              inference_steps=a.steps, shift=3.0, seed=a.seed, thinking=False,
                              enable_normalization=True, normalization_db=-1.0)
    config = GenerationConfig(batch_size=1, use_random_seed=False, audio_format="flac")
    tmp = os.path.join(os.path.dirname(os.path.abspath(a.out)), "_ace_tmp")
    res = generate_music(dit, llm, params, config, save_dir=tmp)
    if not res.success:
        sys.exit(f"generation failed: {res.error}")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    shutil.move(res.audios[0]["path"], a.out)
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
