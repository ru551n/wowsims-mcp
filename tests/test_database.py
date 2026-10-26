from __future__ import annotations

import pytest

from wowsims_mcp.database import DatabaseError, GameDatabase, make_filters


def test_exact_search(database: GameDatabase) -> None:
    result = database.search("the thunderfury blessed blade windseeker")
    assert result["status"] == "exact"
    assert result["candidates"][0]["id"] == 19019
    assert result["candidates"][0]["probability"] > 0.9


def test_misspelling_search(database: GameDatabase) -> None:
    result = database.search("lionhart helm")
    assert result["status"] == "confident"
    assert result["candidates"][0]["name"] == "Lionheart Helm"
    assert database.resolve("lionhart helm")["id"] == 3


def test_duplicate_names_require_a_choice(database: GameDatabase) -> None:
    result = database.search("Insignia of the Horde")
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2
    assert {candidate["same_name_count"] for candidate in result["candidates"]} == {2}
    with pytest.raises(DatabaseError):
        database.resolve("Insignia of the Horde")


def test_unknown_item_is_not_a_claim_about_the_game(database: GameDatabase) -> None:
    result = database.search("notarealitemxyz")
    assert result["status"] == "not_found"
    assert result["none_of_these"] == 1
    assert "may still exist" in result["summary"]


def test_empty_query_browses_with_filters(database: GameDatabase) -> None:
    result = database.search(
        filters=make_filters(slot="weapon", weapon_type="dagger", ilvl_min=60)
    )
    assert result["status"] == "browse"
    assert [item["name"] for item in result["items"]] == ["Felstriker"]
    assert result["total"] == 1
    assert result["has_more"] is False


def test_class_filter_includes_unrestricted_items(database: GameDatabase) -> None:
    result = database.search(filters=make_filters(character_class="rogue"), limit=25)
    assert result["total"] == len(database.items)


def test_invalid_filter_is_actionable(database: GameDatabase) -> None:
    with pytest.raises(DatabaseError, match="Valid values"):
        make_filters(slot="hat")


def test_item_card_has_stats_effects_and_sources(database: GameDatabase) -> None:
    card = database.item_card(database.by_id[4])
    assert card["weapon_type"] == "dagger"
    assert card["stats"] == {"agility": 5}
    assert card["sources"] == [
        {
            "type": "drop",
            "boss": "General Drakkisath",
            "zone": "Blackrock Spire",
            "npc_id": 10,
            "wowhead_url": "https://www.wowhead.com/forever/npc=10",
        }
    ]
    assert database.item_card(database.by_id[3])["sources"] == [
        {"type": "crafted", "profession": "blacksmithing"}
    ]
    assert database.item_card(database.by_id[19019])["sources"] == [{"type": "unknown"}]
    assert database.item_card(database.by_id[17182])["effects"][0]["proc"] == {"ppm": 2}


def test_resolve_by_id_and_missing_id(database: GameDatabase) -> None:
    assert database.resolve("19019")["name"].startswith("Thunderfury")
    with pytest.raises(DatabaseError, match="not in the sim database"):
        database.resolve(999)
