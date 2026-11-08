from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from wowsims_mcp.simulation import SimulationRunner


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
