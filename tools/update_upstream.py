from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text()
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not update {path}")
    path.write_text(updated)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("commit", help="Full upstream commit SHA")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise SystemExit("Expected a full 40-character upstream commit SHA")
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.source, text=True
    ).strip()
    if actual != args.commit:
        raise SystemExit(f"Source checkout is {actual}, expected {args.commit}")
    replace_once(
        args.root / "src/wowsims_mcp/constants.py",
        r"SIM_COMMIT\s*=\s*[\"'][0-9a-f]{40}[\"']",
        f'SIM_COMMIT = "{args.commit}"',
    )
    replace_once(
        args.root / "Dockerfile",
        r"ARG WOWSIMS_COMMIT=[0-9a-f]{40}",
        f"ARG WOWSIMS_COMMIT={args.commit}",
    )
    replace_once(
        args.root / "Dockerfile",
        r"https://raw.githubusercontent.com/wowsims/forever/[0-9a-f]{40}/assets/database/db.json",
        f"https://raw.githubusercontent.com/wowsims/forever/{args.commit}/assets/database/db.json",
    )
    calibration_path = args.root / "src/wowsims_mcp/calibration.json"
    calibration = json.loads(calibration_path.read_text())
    calibration["sim_commit"] = args.commit
    calibration_path.write_text(json.dumps(calibration, indent=2) + "\n")
    subprocess.run(
        [
            "python3",
            "tools/build_presets.py",
            str(args.source),
            "src/wowsims_mcp/presets.json",
        ],
        cwd=args.root,
        check=True,
    )
    subprocess.run(
        [
            "python3",
            "tools/fetch_database.py",
            args.commit,
            "data/db.json",
        ],
        cwd=args.root,
        check=True,
    )


if __name__ == "__main__":
    main()
