"""Standalone offline diffusion worker. Run in its own process:

    python -I diffusion_runner.py <job.json> <out_dir>

Loads a Diffusers pipeline strictly from a local directory
(``local_files_only=True``, Hugging Face offline flags set by the caller, and a
network namespace where the host supports one). It never downloads weights.
Device is chosen from what is present: CUDA, then Apple MPS, then CPU.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(job_path: str, out_dir: str) -> int:
    import diffusers  # noqa: PLC0415 - only importable where the capability probe passed
    import torch  # noqa: PLC0415

    job = json.loads(Path(job_path).read_text())
    device = "cuda" if torch.cuda.is_available() else ("mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
    dtype = torch.float16 if device == "cuda" else torch.float32
    pipe = diffusers.AutoPipelineForText2Image.from_pretrained(job["model_dir"], local_files_only=True, torch_dtype=dtype)
    pipe = pipe.to(device)
    generator = torch.Generator(device="cpu").manual_seed(int(job["seed"]))
    image = pipe(job["prompt"], num_inference_steps=int(job["steps"]), width=int(job["width"]), height=int(job["height"]),
                 generator=generator).images[0]
    out = Path(out_dir)
    image.save(out / "image.png")
    (out / "diffusion.json").write_text(json.dumps({"diffusers": diffusers.__version__, "torch": torch.__version__,
                                                    "device": device, "dtype": str(dtype), "model": job["model_dir"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
