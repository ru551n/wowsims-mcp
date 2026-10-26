from __future__ import annotations

import pytest

from wowsims_mcp.database import DatabaseError, GameDatabase


def test_random_suffix_search_and_card(database: GameDatabase) -> None:
    result = database.search("Cogspinner Goggles of the Eagle")
    assert result["candidates"][0]["suffix"] == {"id": -6, "name": "of the Eagle"}
    card = database.item_card(database.by_id[5], "of the Eagle")
    assert card["name"] == "Cogspinner Goggles of the Eagle"
    assert card["stats"]["stamina"] == 59
    assert card["stats"]["intellect"] == pytest.approx(39.3294)
    assert "coefficients" not in card["suffix"]
    with pytest.raises(DatabaseError, match="not valid"):
        database.item_card(database.by_id[5], "of the Bear")


def test_loot_by_boss_and_zone(database: GameDatabase) -> None:
    for target in ("General Drakkisath", "Blackrock Spire"):
        result = database.get_loot(target)
        assert result["total"] == 1
        assert result["items"][0]["name"] == "Felstriker"
    assert database.get_loot("General Drakkisath")["resolved"]["type"] == "boss"
    assert database.get_loot("Blackrock Spire")["resolved"]["type"] == "zone"


def test_set_lookup(database: GameDatabase) -> None:
    result = database.get_set("Imperial Plate")
    assert result["id"] == 321
    assert [piece["name"] for piece in result["pieces"]] == [
        "Imperial Plate Chest",
        "Imperial Plate Boots",
    ]
    assert result["wowhead_url"].endswith("item-set=321")


def test_compare_items(database: GameDatabase) -> None:
    result = database.compare_items([3, 5])
    assert result["warning"] is None
    assert result["stat_table"]["strength"] == [18, 0]
    assert result["differences"][0]["deltas_vs_first"][0] == 0
    result = database.compare_items([3, 4])
    assert result["warning"] == "SLOT_MISMATCH"


def test_enchant_and_consumable_search(database: GameDatabase) -> None:
    enchants = database.search_enchants("greater agility", slot="back")
    assert enchants["enchants"][0]["id"] == 368
    assert enchants["enchants"][0]["stats"] == {"agility": 12}
    assert database.search_enchants(slot="head")["total"] == 0
    consumables = database.search_consumables("thistle tea")
    assert consumables["consumables"][0]["type"] == "food"
    assert database.search_consumables(consumable_type="potion")["total"] == 0


def test_wowhead_links(database: GameDatabase) -> None:
    assert database.get_wowhead_link("item", "Lionheart Helm") == {
        "ok": True,
        "url": "https://www.wowhead.com/forever/item=3",
        "kind": "item",
        "id": 3,
        "name": "Lionheart Helm",
        "verified": False,
    }
    assert database.get_wowhead_link("spell", 123)["url"].endswith("spell=123")
    with pytest.raises(DatabaseError, match="kind"):
        database.get_wowhead_link("guild", 1)
