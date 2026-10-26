from __future__ import annotations

from pathlib import Path

import pytest

from wowsims_mcp import server


@pytest.mark.asyncio
async def test_list_specs_tool() -> None:
    result = server.wowsims_list_specs()
    assert result["ok"] is True
    assert len(result["specs"]) == 12


@pytest.mark.asyncio
async def test_simulate_invalid_class_does_not_run() -> None:
    result = await server.wowsims_simulate(
        character_class="bard", spec="combat", race="human"
    )
    assert result["ok"] is False
    assert result["code"] == "INVALID_INPUT"
    assert "Valid classes" in result["message"]
    assert "next_step" in result


@pytest.mark.asyncio
@pytest.mark.skipif(
    not Path("data/wowsimcli").exists(), reason="Pinned simulator is not built"
)
async def test_real_simulation_with_custom_player() -> None:
    result = await server.wowsims_simulate(
        character_class="rogue",
        spec="combat",
        race="troll",
        gear={"main_hand": "Thunderfury"},
        iterations=10,
        duration_s=60,
    )
    assert result["ok"] is True
    assert result["race"] == "troll"
    assert result["gear_overrides"][0]["id"] == 19019
    assert result["dps"]["mean"] > 0
    assert result["iterations"] == 10
    assert "no raid buffs" in result["summary"]


@pytest.mark.asyncio
@pytest.mark.skipif(
    not Path("data/wowsimcli").exists(), reason="Pinned simulator is not built"
)
async def test_every_preset_runs() -> None:
    for spec in server.wowsims_list_specs()["specs"]:
        result = await server.wowsims_simulate(
            character_class=spec["class"],
            spec=spec["spec"],
            race=spec["races"][0],
            iterations=2,
            duration_s=30,
        )
        assert result["ok"] is True, (spec["id"], result)
        assert result["dps"]["mean"] > 0, spec["id"]
