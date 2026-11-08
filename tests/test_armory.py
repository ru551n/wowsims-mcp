from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wowsims_mcp import armory, server
from wowsims_mcp.database import DatabaseError
from wowsims_mcp.presets import load_presets

PRESETS = load_presets()
SLOT_KEYS = {
    0: "head", 1: "neck", 2: "shoulder", 3: "back", 4: "chest", 5: "wrist",
    6: "hand", 7: "waist", 8: "leg", 9: "foot", 10: "leftFinger",
    11: "rightFinger", 12: "leftTrinket", 13: "rightTrinket", 14: "weapon",
    15: "offhand", 16: "ranged",
}  # fmt: skip
CLASS_NAMES = {"druid": "Druid", "hunter": "Hunter", "mage": "Mage"}
TREES = [
    (class_name, index)
    for class_name, trees in PRESETS["trees"].items()
    for index in range(len(trees))
]


def fake_character(
    class_name: str, spec_talents: list[list[tuple[int, int]]], preset_key: str
) -> dict[str, Any]:
    preset = PRESETS["specs"][preset_key]
    gear = {}
    for index, item in enumerate(preset["equipment"]["items"]):
        if not item.get("id"):
            continue
        gear[SLOT_KEYS[index]] = {
            "id": item["id"],
            "name": f"Item {item['id']}",
            **(
                {"enchantments": [{"enchantment_id": item["enchant"]}]}
                if item.get("enchant")
                else {}
            ),
            **(
                {"bonus_list": [item["randomSuffix"]]}
                if item.get("randomSuffix")
                else {}
            ),
        }
    return {
        "name": "Test",
        "surname": class_name.title(),
        "level": 70,
        "class": {"name": class_name.title()},
        "race": {"name": preset["races"][0].replace("_", " ").title()},
        "gear": gear,
        "specs": [
            {
                "active": True,
                "name": "Tree",
                "spentPoints": sum(rank for _, rank in talents),
                "talents": [{"id": i, "rank": rank} for i, rank in talents],
            }
            for talents in spec_talents
        ],
    }


def preset_talents(preset: dict[str, Any]) -> list[list[tuple[int, int]]]:
    trees = PRESETS["trees"][preset["class"]]
    strings = preset["talents"].split("-")
    strings += [""] * (len(trees) - len(strings))
    return [
        [
            (talent["ids"][0], int(digit))
            for talent, digit in zip(tree["talents"], digits, strict=False)
            if int(digit)
        ]
        for tree, digits in zip(trees, strings, strict=True)
    ]


@pytest.mark.parametrize("key", PRESETS["specs"])
def test_preset_talents_round_trip(key: str) -> None:
    preset = PRESETS["specs"][key]
    character = fake_character(preset["class"], preset_talents(preset), key)
    result = armory.to_sim(character, PRESETS)
    assert result[0] == preset["class"]
    assert result[1] == key
    # Digits past a tree's length are ignored by the sim (the balance preset has 5).
    trees = PRESETS["trees"][preset["class"]]
    expected = "-".join(
        digits[: len(tree["talents"])].rstrip("0")
        for digits, tree in zip(
            preset["talents"].split("-") + [""] * 3, trees, strict=False
        )
    ).rstrip("-")
    assert result[4] == expected
    assert not result[5]


def test_url_validation() -> None:
    good = "https://worldofwarcraft.blizzard.com/en-us/forever/eu/armory/character/rune-r%C3%B6vkl%C3%B6s"
    assert armory.parse_url(good) == good
    for bad in (
        good.replace("https", "http"),
        good.replace("worldofwarcraft.blizzard.com", "evil.example"),
        "https://worldofwarcraft.blizzard.com/en-us/forever/eu/armory",
        "https://worldofwarcraft.blizzard.com.evil.example/forever/eu/armory/character/x",
    ):
        with pytest.raises(DatabaseError):
            armory.parse_url(bad)


def test_extract_character_requires_profile_json() -> None:
    page = '<script>window.x = {"character": {"gear": {}, "name": "A"}}</script>'
    assert armory.extract_character(page)["name"] == "A"
    with pytest.raises(DatabaseError):
        armory.extract_character("<html></html>")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not Path("data/wowsimcli").exists(), reason="Pinned simulator is not built"
)
@pytest.mark.parametrize(("class_name", "tree_index"), TREES)
async def test_every_class_tree_simulates(
    class_name: str, tree_index: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    trees = PRESETS["trees"][class_name]
    maxed = [
        [
            (talent["ids"][0], talent["max"])
            for talent in tree["talents"]
            if index == tree_index
        ]
        for index, tree in enumerate(trees)
    ]
    key = next(k for k, p in PRESETS["specs"].items() if p["class"] == class_name)
    character = fake_character(class_name, maxed, key)

    async def fake_fetch(_url: str) -> dict[str, Any]:
        return character

    monkeypatch.setattr(server, "fetch_character", fake_fetch)
    url = "https://worldofwarcraft.blizzard.com/en-us/forever/eu/armory/character/x"
    result = await server.wowsims_simulate(armory_url=url, iterations=50, duration_s=30)
    assert result["ok"] is True, result
    assert result["dps"]["mean"] > 0
    expected = "-".join(
        "".join(
            str(talent["max"]) if k == tree_index else "" for talent in tree["talents"]
        )
        if k == tree_index
        else ""
        for k, tree in enumerate(trees)
    ).rstrip("-")
    assert result["talents"] == expected
