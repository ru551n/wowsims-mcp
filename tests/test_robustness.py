from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from wowsims_mcp import server
from wowsims_mcp.simulation import SimulationRunner
from wowsims_mcp.storage import CharacterStore


def test_case_variant_save_updates_one_character() -> None:
    store = CharacterStore(":memory:")
    settings = {"raid": {"parties": [{"players": []}]}}
    store.save("owner", "Main Rogue", "rogue", "combat", "troll", settings)
    store.save("owner", "main rogue", "mage", "arcane", "human", settings)
    assert len(store.list("owner")) == 1
    assert store.get("owner", "MAIN ROGUE")["class"] == "mage"
    store.delete("owner", "MAIN ROGUE", confirm=True)
    assert store.list("owner") == []
    store.close()


@pytest.mark.asyncio
async def test_mcp_json_import_accepts_transport_preparsed_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(
        "/tmp/wowsims-forever/ui/specs/hunter/dps/builds/phase_1/bm/pre_raid.build.json"
    )
    if not path.exists():
        pytest.skip("Pinned UI export fixture is not available")
    store = CharacterStore(":memory:")
    monkeypatch.setattr(server, "_store", store)
    _, result = await server.mcp.call_tool(
        "wowsims_save_character",
        {
            "owner": "owner",
            "name": "My Hunter",
            "source": "sim_json",
            "data": path.read_text(),
        },
    )
    assert result["ok"] is True, result
    assert result["class"] == "hunter"
    store.close()


@pytest.mark.asyncio
async def test_simulation_limiter_admits_capacity(tmp_path: Path) -> None:
    binary = tmp_path / "wowsimcli"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "json.dump({'iterationsDone': 1, 'raidMetrics': {}}, "
        "open(sys.argv[sys.argv.index('--outfile') + 1], 'w'))\n"
    )
    binary.chmod(0o755)
    runner = SimulationRunner(binary, concurrency=2)
    results = await asyncio.gather(*(runner.run({}) for _ in range(4)))
    assert len(results) == 4
