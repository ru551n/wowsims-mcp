from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .constants import SIM_COMMIT


class SimulationError(RuntimeError):
    code = "SIM_FAILED"


class SimulationTimeout(SimulationError):
    code = "SIM_TIMEOUT"


class SimulationUnavailable(SimulationError):
    code = "SIM_UNAVAILABLE"


class SimulationRunner:
    def __init__(
        self,
        binary: str | Path | None = None,
        timeout_s: float = 60,
        concurrency: int = 2,
    ) -> None:
        default_binary = (
            "data/wowsimcli" if Path("data/wowsimcli").is_file() else "wowsimcli"
        )
        self.binary = str(binary or os.environ.get("WOWSIMS_CLI_PATH", default_binary))
        self.timeout_s = timeout_s
        self._semaphore = asyncio.Semaphore(concurrency)

    async def run(self, request: dict[str, Any]) -> dict[str, Any]:
        async with self._semaphore:
            with tempfile.TemporaryDirectory(prefix="wowsims-mcp-") as directory:
                input_path = Path(directory) / "input.json"
                output_path = Path(directory) / "output.json"
                input_path.write_text(json.dumps(request), encoding="utf-8")
                try:
                    process = await asyncio.create_subprocess_exec(
                        self.binary,
                        "sim",
                        "--infile",
                        str(input_path),
                        "--outfile",
                        str(output_path),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                except OSError as exc:
                    raise SimulationUnavailable(
                        "The simulator binary is unavailable. Build wowsimcli "
                        "or set WOWSIMS_CLI_PATH to its location."
                    ) from exc
                try:
                    _, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=self.timeout_s
                    )
                except TimeoutError as exc:
                    process.kill()
                    await process.wait()
                    raise SimulationTimeout(
                        f"Simulation exceeded {self.timeout_s:g} seconds."
                    ) from exc
                if process.returncode != 0:
                    message = stderr.decode(errors="replace").strip()[-2000:]
                    raise SimulationError(
                        f"wowsimcli exited with {process.returncode}: {message}"
                    )
                try:
                    result = json.loads(output_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise SimulationError(
                        "wowsimcli did not produce a valid result."
                    ) from exc
                if not isinstance(result, dict):
                    raise SimulationError("wowsimcli returned a non-object result.")
                if result.get("error"):
                    error = result["error"]
                    message = error.get(
                        "message", "The simulator rejected the request."
                    )
                    first_line = message.splitlines()[0]
                    if first_line.startswith("runtime error:"):
                        first_line = (
                            "The simulator could not run this player configuration. "
                            "Check the gear, talents, and rotation compatibility."
                        )
                    raise SimulationError(first_line)
                return result


def simulation_summary(result: dict[str, Any]) -> dict[str, Any]:
    raid = result.get("raidMetrics") or {}
    players = [
        player
        for party in raid.get("parties") or []
        for player in party.get("players") or []
    ]
    if not players:
        raise SimulationError("The simulation result has no player metrics.")
    player = players[0]
    dps = player.get("dps") or raid.get("dps") or {}

    def action_damage(action: dict[str, Any]) -> float:
        return float(
            sum(target.get("damage", 0) for target in action.get("targets") or [])
        )

    actions = sorted(
        (action for action in player.get("actions") or [] if action_damage(action) > 0),
        key=action_damage,
        reverse=True,
    )
    total_damage = sum(action_damage(action) for action in actions)
    return {
        "dps": {"mean": dps.get("avg", 0), "stdev": dps.get("stdev", 0)},
        "iterations": result.get("iterationsDone", 0),
        "top_abilities": [
            {
                "name": action.get("id", {}).get("name")
                or f"Spell {action.get('id', {}).get('spellId', 'unknown')}",
                "pct": round(100 * action_damage(action) / total_damage, 1)
                if total_damage
                else 0,
            }
            for action in actions[:5]
        ],
        "sim_version": SIM_COMMIT,
    }
