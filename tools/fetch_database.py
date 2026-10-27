from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("commit")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    url = (
        "https://raw.githubusercontent.com/wowsims/forever/"
        f"{args.commit}/assets/database/db.json"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "wowsims-mcp-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise SystemExit("Downloaded database has an invalid schema")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, separators=(",", ":")))


if __name__ == "__main__":
    main()
