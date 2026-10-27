from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "check_upstream", Path(__file__).parents[1] / "tools/check_upstream.py"
)
assert spec and spec.loader
check_upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_upstream)
category = check_upstream.category
main = check_upstream.main


def test_upstream_categories() -> None:
    assert category("ui/specs/rogue/dps/presets.ts") == "Specs, talents, and rotations"
    assert category("assets/database/db.json") == "Items and game database"
    assert category("proto/api.proto") == "Protobuf and API"
    assert category("go.mod") == "Build and dependencies"
    assert category("README.md") == "Other upstream changes"


def test_monitor_no_change(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = root / "src/wowsims_mcp"
    source.mkdir(parents=True)
    sha = "a" * 40
    (source / "constants.py").write_text(f'SIM_COMMIT = "{sha}"\n')
    with patch.object(
        check_upstream, "github_json", return_value={"commit": {"sha": sha}}
    ):
        assert main_args(root, tmp_path / "report.json") == 0
    result = json.loads((tmp_path / "report.json").read_text())
    assert result["changed"] is False
    assert "unchanged" in result["message"]


def main_args(root: Path, output: Path) -> int:
    import sys

    with patch.object(
        sys,
        "argv",
        ["check_upstream.py", "--repository-root", str(root), "--output", str(output)],
    ):
        return main()
