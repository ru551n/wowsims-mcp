from __future__ import annotations

import pytest

from wowsims_mcp.database import DatabaseError, GameDatabase
from wowsims_mcp.presets import build_request, list_specs, load_presets


def test_list_specs_and_manifest_pin() -> None:
    specs = list_specs(load_presets())
    assert len(specs) == 12
    assert all(spec["has_default_preset"] for spec in specs)
    assert {spec["class"] for spec in specs} == {
        "druid",
        "hunter",
        "mage",
        "paladin",
        "priest",
        "rogue",
        "shaman",
        "warlock",
        "warrior",
    }


def test_build_request_with_gear(real_database: GameDatabase) -> None:
    request, metadata = build_request(
        load_presets(),
        real_database,
        "combat",
        "rogue",
        "troll",
        {"main hand": "Thunderfury"},
        iterations=10,
    )
    player = request["raid"]["parties"][0]["players"][0]
    assert player["race"] == "RaceTroll"
    assert player["rogue"]["options"] == {}
    assert "spec" not in player
    assert player["equipment"]["items"][14]["id"] == 19019
    assert metadata["gear_overrides"][0]["id"] == 19019


def test_spec_class_mismatch_lists_valid_specs(real_database: GameDatabase) -> None:
    with pytest.raises(DatabaseError, match="fury_warrior"):
        build_request(load_presets(), real_database, "combat", "warrior", "orc")


def test_invalid_race_lists_valid_races(real_database: GameDatabase) -> None:
    with pytest.raises(DatabaseError, match="Valid races"):
        build_request(load_presets(), real_database, "retribution", "paladin", "tauren")


def test_invalid_gear_slot_is_actionable(real_database: GameDatabase) -> None:
    with pytest.raises(DatabaseError, match="cannot be equipped in head"):
        build_request(
            load_presets(),
            real_database,
            "combat",
            "rogue",
            "troll",
            {"head": "Thunderfury"},
        )


def test_ambiguous_gear_returns_candidates(real_database: GameDatabase) -> None:
    with pytest.raises(DatabaseError) as error:
        build_request(
            load_presets(),
            real_database,
            "combat",
            "rogue",
            "troll",
            {"head": "notarealitemxyz"},
        )
    assert "No matching item in the sim database" in str(error.value)
