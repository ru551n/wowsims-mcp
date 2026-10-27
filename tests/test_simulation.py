from __future__ import annotations

from pathlib import Path

import pytest

from wowsims_mcp.database import GameDatabase
from wowsims_mcp.presets import build_request, load_presets
from wowsims_mcp.simulation import (
    SimulationError,
    SimulationRunner,
    SimulationTimeout,
    simulation_summary,
)


@pytest.mark.asyncio
async def test_runner_returns_result(tmp_path: Path) -> None:
    binary = tmp_path / "wowsimcli"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "request = json.load(open(sys.argv[sys.argv.index('--infile') + 1]))\n"
        "json.dump({'iterationsDone': request['simOptions']['iterations'], "
        "'raidMetrics': {}}, open(sys.argv[sys.argv.index('--outfile') + 1], 'w'))\n"
    )
    binary.chmod(0o755)
    runner = SimulationRunner(binary)
    result = await runner.run({"simOptions": {"iterations": 10}})
    assert result["iterationsDone"] == 10


@pytest.mark.asyncio
async def test_runner_rejects_sim_error(tmp_path: Path) -> None:
    binary = tmp_path / "wowsimcli"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "json.dump({'error': {'message': 'bad item'}}, "
        "open(sys.argv[sys.argv.index('--outfile') + 1], 'w'))\n"
    )
    binary.chmod(0o755)
    with pytest.raises(SimulationError, match="bad item"):
        await SimulationRunner(binary).run({})


@pytest.mark.asyncio
async def test_runner_kills_timed_out_process(tmp_path: Path) -> None:
    binary = tmp_path / "wowsimcli"
    binary.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
    binary.chmod(0o755)
    with pytest.raises(SimulationTimeout):
        await SimulationRunner(binary, timeout_s=0.01).run({})


def test_simulation_summary() -> None:
    result = {
        "iterationsDone": 100,
        "raidMetrics": {
            "parties": [
                {
                    "players": [
                        {
                            "dps": {"avg": 980.25, "stdev": 51.86},
                            "actions": [
                                {
                                    "id": {"name": "Sinister Strike"},
                                    "targets": [{"damage": 500}],
                                }
                            ],
                        }
                    ]
                }
            ]
        },
    }
    summary = simulation_summary(result)
    assert summary["dps"] == {"mean": 980.25, "stdev": 51.86}
    assert summary["top_abilities"][0]["name"] == "Sinister Strike"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not Path("data/wowsimcli").exists() or not Path("data/db.json").exists(),
    reason="Pinned simulator and database are not available",
)
async def test_real_simulator_smoke() -> None:
    request, _ = build_request(
        load_presets(),
        GameDatabase.load(Path("data/db.json")),
        "combat",
        "rogue",
        "human",
        iterations=10,
    )
    result = await SimulationRunner(Path("data/wowsimcli").resolve()).run(request)
    summary = simulation_summary(result)
    assert summary["iterations"] == 10
    assert summary["dps"]["mean"] > 0
