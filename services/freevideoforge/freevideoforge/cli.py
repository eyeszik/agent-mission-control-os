"""Command-line interface.

    freevideoforge generate --topic "..." --duration 30 --aspect 9:16 --preset auto
    freevideoforge doctor
    freevideoforge providers
    freevideoforge runs
    freevideoforge status <run_id>
    freevideoforge resume <run_id>
    freevideoforge serve
    freevideoforge bootstrap

Exit codes: 0 success, 1 failure, 2 usage error, 3 environment blocked.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from . import api, doctor
from .errors import ForgeError
from .models import GenerateRequest, to_jsonable
from .version import __version__

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_BLOCKED = 3


class _Reporter:
    """Single-line progress for a TTY, plain lines otherwise."""

    def __init__(self, quiet: bool, json_mode: bool) -> None:
        self.quiet = quiet or json_mode
        self.tty = sys.stderr.isatty() and not json_mode
        self.started = time.time()

    def __call__(self, stage: str, fraction: float, message: str) -> None:
        if self.quiet:
            return
        elapsed = time.time() - self.started
        if self.tty:
            width = 28
            filled = int(width * max(0.0, min(1.0, fraction)))
            bar = "#" * filled + "." * (width - filled)
            sys.stderr.write(
                f"\r[{bar}] {fraction * 100:5.1f}% {elapsed:5.1f}s  {stage:<10} "
                f"{message[:52]:<52}"
            )
            sys.stderr.flush()
        else:
            print(f"[{fraction * 100:5.1f}%] {stage:<10} {message}", file=sys.stderr)

    def done(self) -> None:
        if self.tty and not self.quiet:
            sys.stderr.write("\n")
            sys.stderr.flush()


def _emit_json(payload: Any) -> None:
    print(json.dumps(to_jsonable(payload), indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_generate(args: argparse.Namespace) -> int:
    request = GenerateRequest(
        topic=args.topic,
        brief=args.brief or "",
        duration=args.duration,
        aspect=args.aspect,
        preset=args.preset,
        style=args.style,
        scenes=args.scenes,
        fps=args.fps,
        height=args.height,
        voice=args.voice,
        music=args.music,
        seed=args.seed,
        language=args.language,
        burn_captions=not args.no_burn_captions,
        output_dir=args.output,
        allow_paid=args.allow_paid,
        script_provider=args.script_provider,
        speech_provider=args.speech_provider,
        quality_preset=args.quality,
    )
    try:
        request.validate()
    except ForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    health = doctor.collect(args.workspace, allow_paid=args.allow_paid)
    if not health["can_render"]:
        print("FreeVideoForge cannot render on this host yet:", file=sys.stderr)
        for blocker in health["blockers"]:
            print(f"  ! {blocker}", file=sys.stderr)
        print("\nRun `freevideoforge doctor` for the full picture.", file=sys.stderr)
        return EXIT_BLOCKED

    reporter = _Reporter(args.quiet, args.json)
    result = api.generate(request, workspace=args.workspace, progress=reporter)
    reporter.done()

    if args.json:
        _emit_json(result)
        return EXIT_OK if result.ok else EXIT_FAILURE

    if not result.ok:
        print(f"\nFAILED ({result.state.value}): {result.error}", file=sys.stderr)
        print(f"Run id: {result.run_id}", file=sys.stderr)
        print(f"Resume with: freevideoforge resume {result.run_id}", file=sys.stderr)
        return EXIT_FAILURE

    print(f"\nDone in {time.time() - reporter.started:.1f}s")
    print(f"  run id     {result.run_id}")
    print(f"  duration   {result.duration:.2f}s")
    print(f"  video      {result.final_video}")
    print(f"  thumbnail  {result.thumbnail}")
    print(f"  captions   {result.captions}")
    print(f"  manifest   {result.manifest}")
    print(f"  qc report  {result.quality_report}")
    print(f"  providers  {', '.join(f'{k}={v}' for k, v in result.providers.items())}")
    for warning in result.warnings:
        print(f"  warning    {warning}")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    report = doctor.collect(args.workspace, allow_paid=args.allow_paid)
    if args.json:
        _emit_json(report)
    else:
        print(doctor.render_text(report))
    return EXIT_OK if report["can_render"] else EXIT_BLOCKED


def cmd_providers(args: argparse.Namespace) -> int:
    summary = api.describe_providers(args.workspace, allow_paid=args.allow_paid)
    if args.json:
        _emit_json(summary)
        return EXIT_OK
    print(f"Visual tier: {summary['visual_tier']}")
    print("\nActive:")
    for cap in summary["active"]:
        print(f"  + {cap['kind']:10} {cap['name']:14} {cap['detail']}")
    print("\nUnavailable:")
    for cap in summary["unavailable"]:
        print(f"  - {cap['kind']:10} {cap['name']:14} {cap['detail']}")
    return EXIT_OK


def cmd_runs(args: argparse.Namespace) -> int:
    runs = api.list_runs(args.workspace, limit=args.limit)
    if args.json:
        _emit_json(runs)
        return EXIT_OK
    if not runs:
        print("No runs yet.")
        return EXIT_OK
    print(f"{'RUN ID':<30} {'STATE':<18} TOPIC")
    for record in runs:
        print(f"{record['run_id']:<30} {record['state']:<18} {record['topic'][:44]}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    try:
        status = api.run_status(args.run_id, args.workspace)
    except ForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        _emit_json(status)
        return EXIT_OK
    print(f"run       {status['run_id']}")
    print(f"state     {status['state']}")
    print(f"topic     {status['topic']}")
    print(f"output    {status['output_dir']}")
    if status["error"]:
        print(f"error     {status['error']}")
    if status["scenes"]:
        print("scenes")
        for scene_id, data in status["scenes"].items():
            print(f"  {scene_id}  {data['state']:<8} attempts={data['attempts']}"
                  + (f"  error={data['error'][:60]}" if data["error"] else ""))
    return EXIT_OK


def cmd_resume(args: argparse.Namespace) -> int:
    reporter = _Reporter(args.quiet, args.json)
    try:
        result = api.resume(args.run_id, workspace=args.workspace, progress=reporter)
    except ForgeError as exc:
        reporter.done()
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    reporter.done()
    if args.json:
        _emit_json(result)
    elif result.ok:
        print(f"\nResumed and completed: {result.final_video}")
    else:
        print(f"\nStill failing: {result.error}", file=sys.stderr)
    return EXIT_OK if result.ok else EXIT_FAILURE


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    return serve(host=args.host, port=args.port, workspace=args.workspace,
                 open_browser=not args.no_browser)


def cmd_bootstrap(args: argparse.Namespace) -> int:
    from .bootstrap import bootstrap

    return bootstrap(workspace=args.workspace, json_mode=args.json)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freevideoforge",
        description="Local-first, zero-cost brief-to-video production. "
                    "No paid API, no credentials, no network at render time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            '  freevideoforge generate --topic "Why the moon changes shape" '
            "--duration 30 --aspect 9:16 --preset auto\n"
            "  freevideoforge doctor\n"
            "  freevideoforge serve --port 8765\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"freevideoforge {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspace", default=None,
                        help="Workspace root (default: cwd, or $FVF_WORKSPACE)")
    common.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    common.add_argument("--allow-paid", action="store_true",
                        help="Permit providers that would require paid credentials "
                             "(off by default; nothing bundled needs it)")

    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", parents=[common], help="Produce a video from a brief")
    gen.add_argument("--topic", required=True, help="What the video is about")
    gen.add_argument("--brief", default="",
                     help="Source material. Supplied sentences become the body "
                          "beats instead of a generated scaffold.")
    gen.add_argument("--duration", type=float, default=30.0, help="Target seconds")
    gen.add_argument("--aspect", default="9:16", choices=["9:16", "1:1", "16:9", "4:5"])
    gen.add_argument("--preset", default="auto",
                     choices=["auto", "local_video", "image_motion", "ffmpeg_motion"],
                     help="Visual tier. auto walks down to ffmpeg_motion.")
    gen.add_argument("--style", default="auto",
                     choices=["auto", "editorial", "neon", "clean", "warm", "slate"])
    gen.add_argument("--quality", default="balanced", choices=["draft", "balanced", "high"])
    gen.add_argument("--scenes", type=int, default=None, help="Override scene count")
    gen.add_argument("--fps", type=int, default=30)
    gen.add_argument("--height", type=int, default=None, help="Override output height")
    gen.add_argument("--voice", default="auto", help="TTS voice id, or auto")
    gen.add_argument("--music", default="ambient", choices=["none", "ambient"])
    gen.add_argument("--seed", type=int, default=None, help="Reproducibility seed")
    gen.add_argument("--language", default="en")
    gen.add_argument("--no-burn-captions", action="store_true",
                     help="Keep captions.srt as a sidecar only")
    gen.add_argument("--output", default=None, help="Output directory for this run")
    gen.add_argument("--script-provider", default="auto")
    gen.add_argument("--speech-provider", default="auto")
    gen.add_argument("--quiet", action="store_true")
    gen.set_defaults(func=cmd_generate)

    doc = sub.add_parser("doctor", parents=[common], help="Diagnose this host")
    doc.set_defaults(func=cmd_doctor)

    prov = sub.add_parser("providers", parents=[common], help="List provider capabilities")
    prov.set_defaults(func=cmd_providers)

    runs = sub.add_parser("runs", parents=[common], help="List recent runs")
    runs.add_argument("--limit", type=int, default=25)
    runs.set_defaults(func=cmd_runs)

    status = sub.add_parser("status", parents=[common], help="Inspect one run")
    status.add_argument("run_id")
    status.set_defaults(func=cmd_status)

    resume = sub.add_parser("resume", parents=[common],
                            help="Resume an interrupted or failed run")
    resume.add_argument("run_id")
    resume.add_argument("--quiet", action="store_true")
    resume.set_defaults(func=cmd_resume)

    serve = sub.add_parser("serve", parents=[common], help="Start the local web UI")
    serve.add_argument("--host", default="127.0.0.1",
                       help="Bind address. Defaults to loopback on purpose.")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true")
    serve.set_defaults(func=cmd_serve)

    boot = sub.add_parser("bootstrap", parents=[common],
                          help="Check and prepare the local environment")
    boot.set_defaults(func=cmd_bootstrap)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ninterrupted - the run is resumable: freevideoforge runs", file=sys.stderr)
        return EXIT_FAILURE
    except ForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILURE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
