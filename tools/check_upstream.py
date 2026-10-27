from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = "wowsims/forever"
PIN_PATTERN = re.compile(r"SIM_COMMIT\s*=\s*[\"']([0-9a-f]{40})[\"']")
CATEGORIES = {
    "Specs, talents, and rotations": ("ui/specs/", "sim/"),
    "Items and game database": (
        "assets/database/",
        "assets/db_inputs/",
        "tools/database/",
    ),
    "Protobuf and API": ("proto/", "schemas/"),
    "Build and dependencies": (
        "go.mod",
        "go.sum",
        "package.json",
        "package-lock.json",
        "Dockerfile",
        "makefile",
        "buf.yaml",
        ".nvmrc",
    ),
}


def github_json(path: str) -> dict:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "wowsims-mcp-upstream-monitor",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def category(path: str) -> str:
    for name, prefixes in CATEGORIES.items():
        if any(path == prefix or path.startswith(prefix) for prefix in prefixes):
            return name
    return "Other upstream changes"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    constants = (args.repository_root / "src/wowsims_mcp/constants.py").read_text()
    match = PIN_PATTERN.search(constants)
    if not match:
        raise SystemExit("Could not find SIM_COMMIT in constants.py")
    pinned = match.group(1)
    branch = github_json(f"/repos/{REPO}/branches/master")
    latest = branch["commit"]["sha"]
    result = {"pinned": pinned, "latest": latest, "changed": latest != pinned}
    if latest == pinned:
        result["message"] = f"Upstream is unchanged at {pinned[:12]}."
    else:
        comparison = github_json(f"/repos/{REPO}/compare/{pinned}...{latest}")
        if comparison.get("status") != "ahead":
            raise SystemExit(
                "Pinned commit is not an ancestor of upstream master: "
                f"{comparison.get('status')}"
            )
        grouped: dict[str, list[str]] = defaultdict(list)
        for file in comparison.get("files", []):
            grouped[category(file["filename"])].append(
                f"{file['status']}: {file['filename']}"
            )
        result.update(
            {
                "ahead_by": comparison["ahead_by"],
                "commits": [
                    {
                        "sha": commit["sha"],
                        "message": commit["commit"]["message"].splitlines()[0],
                        "url": commit["html_url"],
                    }
                    for commit in comparison.get("commits", [])
                ],
                "categories": dict(grouped),
                "compare_url": comparison["html_url"],
            }
        )
        lines = [
            f"Upstream advanced from `{pinned}` to `{latest}` "
            f"({comparison['ahead_by']} commits).",
            "",
            "Review and regenerate the pinned database and preset manifest, "
            "then run all spec smoke tests before upgrading.",
            "",
            f"[Compare changes]({comparison['html_url']})",
            "",
        ]
        for name, files in grouped.items():
            lines.extend([f"### {name}", ""])
            lines.append(f"{len(files)} changed files.")
            lines.append("")
            lines.extend(f"- `{file}`" for file in files[:30])
            if len(files) > 30:
                lines.append(f"- … {len(files) - 30} more files")
            lines.append("")
        result["message"] = "\n".join(lines)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
    print(result["message"])
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"changed={str(result['changed']).lower()}\n")
            output.write(f"latest={latest}\n")
            output.write(f"pinned={pinned}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, KeyError, ValueError) as exc:
        print(f"Upstream check failed: {exc}", file=sys.stderr)
        sys.exit(1)
