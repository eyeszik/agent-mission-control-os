#!/usr/bin/env python3
"""Export a project's output folder to Google Drive and record it in Notion.

    python scripts/export_to_drive.py --project-path runtime/foundry/demo            # dry run (default)
    RUNNER_MODE=local python scripts/export_to_drive.py --project-path ... --check   # read-only credential check
    RUNNER_MODE=local python scripts/export_to_drive.py --project-path ...           # upload

Exit codes: 0 done (uploaded, already uploaded, no changes, or dry run),
1 an API call or the upload verification failed, 2 configuration error.
See docs/drive-export.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.langgraph.integrations.drive_export._http import ApiError  # noqa: E402
from services.langgraph.integrations.drive_export.google_drive import DriveConfigError  # noqa: E402
from services.langgraph.integrations.drive_export.runner import (  # noqa: E402
    ExportConfig,
    ExportConfigError,
    ExportVerificationError,
    check_access,
    run_export,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-path", help="folder to export (default: AMC_PROJECT_PATH)")
    parser.add_argument("--project-id", help="Drive subfolder and record id (default: the folder name)")
    parser.add_argument("--brand-id", help="brand id recorded in Notion")
    parser.add_argument("--out-dir", help="local output directory (default: ./.amc-export)")
    parser.add_argument("--full", action="store_true", help="include every file, not only changed ones")
    parser.add_argument("--check", action="store_true", help="only verify Drive and Notion access (read-only)")
    args = parser.parse_args(argv)
    try:
        config = ExportConfig.from_env(project_path=args.project_path, project_id=args.project_id,
                                       brand_id=args.brand_id, out_dir=args.out_dir, full=args.full)
        output = check_access(config) if args.check else run_export(config).to_dict()
    except (ExportConfigError, DriveConfigError) as exc:
        print(json.dumps({"status": "CONFIG_ERROR", "error": str(exc)}), file=sys.stderr)
        return 2
    except (ApiError, ExportVerificationError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
