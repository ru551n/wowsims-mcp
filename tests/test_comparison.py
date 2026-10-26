from __future__ import annotations

from pathlib import Path

import pytest

from wowsims_mcp import server
from wowsims_mcp.database import GameDatabase
from wowsims_mcp.presets import build_request, load_presets


def test_variant_preserves_baseline(real_database: GameDatabase) -> None:
    from wowsims_mcp.comparison import build_variant_request

    baseline, _ = build_request(
        load_presets(), real_database, "combat", "rogue", "human", iterations=100
    )
    variant = build_variant_request(baseline, real_database, "Troll", race="troll")
    assert variant["request"]["simOptions"]["randomSeed"] == 1
    assert variant["request"]["simOptions"]["useLabeledRands"] is True
    assert variant["applied_overrides"] == [{"type": "race", "value": "troll"}]
    assert baseline["raid"]["parties"][0]["players"][0]["race"] == "RaceHuman"


@pytest.mark.asyncio
async def test_compare_rejects_empty_variant() -> None:
    result = await server.wowsims_compare(
        character_class="rogue",
        spec="combat",
        race="human",
        variants=[{"label": "No change"}],
    )
    assert result["ok"] is False
    assert result["code"] == "INVALID_OVERRIDE"
    assert "no overrides" in result["message"]


@pytest.mark.asyncio
@pytest.mark.skipif(
    not Path("data/wowsimcli").exists(), reason="Pinned simulator is not built"
)
async def test_real_comparison_has_noise_flags() -> None:
    result = await server.wowsims_compare(
        character_class="rogue",
        spec="combat",
        race="human",
        variants=[
            {"label": "Troll", "race": "troll"},
            {"label": "Thunderfury", "gear": {"main_hand": "Thunderfury"}},
        ],
        iterations=100,
        duration_s=60,
    )
    assert result["ok"] is True, result
    assert result["iterations"] == 100
    assert len(result["results"]) == 2
    thunderfury = next(
        variant for variant in result["results"] if variant["label"] == "Thunderfury"
    )
    assert thunderfury["delta"] < 0
    assert thunderfury["within_noise"] is False
