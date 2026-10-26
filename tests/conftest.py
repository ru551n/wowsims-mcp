from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wowsims_mcp.database import GameDatabase


@pytest.fixture(scope="session")
def real_database() -> GameDatabase:
    path = Path(__file__).parents[1] / "data" / "db.json"
    if not path.exists():
        pytest.skip("Pinned real database is not downloaded")
    return GameDatabase.load(path)


@pytest.fixture
def database() -> GameDatabase:
    def item(
        item_id: int,
        name: str,
        **values: Any,
    ) -> dict[str, Any]:
        return {
            "id": item_id,
            "name": name,
            "type": 13,
            "quality": 4,
            "phase": 1,
            "scalingOptions": {"0": {"ilvl": 60, "stats": {"1": 5}}},
            **values,
        }

    return GameDatabase(
        {
            "items": [
                item(
                    19019,
                    "Thunderfury, Blessed Blade of the Windseeker",
                    weaponType=9,
                    handType=2,
                    weaponSpeed=1.9,
                    unique=True,
                ),
                item(
                    17182,
                    "Sulfuras, Hand of Ragnaros",
                    weaponType=4,
                    handType=4,
                    itemEffects=[
                        {
                            "buffId": 123,
                            "buffName": "Fireball",
                            "proc": {"ppm": 2},
                        }
                    ],
                ),
                item(
                    1,
                    "Insignia of the Horde",
                    type=12,
                    classAllowlist=[4],
                    scalingOptions={"0": {"ilvl": 60}},
                ),
                item(
                    2,
                    "Insignia of the Horde",
                    type=12,
                    classAllowlist=[4],
                    scalingOptions={"0": {"ilvl": 65}},
                ),
                item(
                    3,
                    "Lionheart Helm",
                    type=1,
                    armorType=4,
                    sources=[{"crafted": {"profession": 2, "spellId": 1}}],
                    scalingOptions={"0": {"ilvl": 65, "stats": {"0": 18}}},
                ),
                item(
                    4,
                    "Felstriker",
                    weaponType=2,
                    sources=[{"drop": {"npcId": 10, "zoneId": 20}}],
                ),
            ],
            "npcs": [{"id": 10, "name": "General Drakkisath", "zoneId": 20}],
            "zones": [{"id": 20, "name": "Blackrock Spire"}],
        }
    )
