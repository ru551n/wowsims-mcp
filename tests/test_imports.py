from __future__ import annotations

import json
from pathlib import Path

import pytest

from wowsims_mcp.database import DatabaseError, GameDatabase
from wowsims_mcp.imports import import_sim_json
from wowsims_mcp.presets import load_presets


def test_real_ui_json_import(real_database: GameDatabase) -> None:
    path = Path(__file__).parent / "fixtures/hunter.build.json"
    request, metadata, warnings = import_sim_json(
        path.read_text(), load_presets(), real_database
    )
    player = request["raid"]["parties"][0]["players"][0]
    assert metadata == {
        "class": "hunter",
        "spec": "beast_mastery",
        "race": "orc",
        "preset": "imported gear, talents, options, and rotation",
    }
    assert player["hunter"]["options"]["classOptions"]["petType"] == "Ravager"
    assert player["rotation"]["type"] == "TypeSimple"
    assert len(player["bonusStats"]["pseudoStats"]) == 27
    assert warnings


def test_import_rejects_invalid_json(real_database: GameDatabase) -> None:
    with pytest.raises(DatabaseError, match="not valid JSON"):
        import_sim_json("not json", load_presets(), real_database)


def test_import_warns_and_clears_unknown_items(real_database: GameDatabase) -> None:
    player = {
        "race": "RaceTroll",
        "rogue": {"options": {}},
        "equipment": {"items": [{"id": 999999}] + [{} for _ in range(16)]},
    }
    _, metadata, warnings = import_sim_json(
        json.dumps({"player": player}), load_presets(), real_database
    )
    assert metadata["class"] == "rogue"
    assert "Unknown item ID 999999" in warnings[0]
