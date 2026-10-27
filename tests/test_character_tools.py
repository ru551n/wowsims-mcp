from __future__ import annotations

import pytest

from wowsims_mcp import server
from wowsims_mcp.storage import CharacterStore


@pytest.fixture(autouse=True)
def memory_store(monkeypatch: pytest.MonkeyPatch) -> CharacterStore:
    store = CharacterStore(":memory:")
    monkeypatch.setattr(server, "_store", store)
    yield store
    store.close()


def save(owner: str, name: str, character_class: str = "rogue") -> dict:
    return server.wowsims_save_character(
        owner=owner,
        name=name,
        character_class=character_class,
        spec="combat" if character_class == "rogue" else "arcane",
        race="troll" if character_class == "rogue" else "human",
    )


def test_two_part_names_and_multiple_characters() -> None:
    assert save("discord-1", "Main Rogue")["ok"] is True
    assert save("discord-1", "Alt Mage", "mage")["ok"] is True
    characters = server.wowsims_list_characters("discord-1")["characters"]
    assert {character["name"] for character in characters} == {"Main Rogue", "Alt Mage"}
    assert server.wowsims_get_character("discord-1", "main rogue")["ok"] is True
    assert (
        server.wowsims_set_default_character("discord-1", "Alt Mage")[
            "default_character"
        ]
        == "Alt Mage"
    )


def test_cross_user_modification_returns_ownership_error() -> None:
    save("discord-1", "Main Rogue")
    save("discord-2", "Other Mage", "mage")
    server._store.connection.execute(
        "UPDATE characters SET name = 'Main Rogue' WHERE owner = 'discord-2'"
    )
    result = save("discord-2", "main rogue", "mage")
    assert result["ok"] is False
    assert result["code"] == "CHARACTER_OWNERSHIP_MISMATCH"
    assert "another Discord user" in result["message"]
    assert (
        server.wowsims_delete_character("discord-2", "Main Rogue", True)["code"]
        == "CHARACTER_OWNERSHIP_MISMATCH"
    )


def test_armory_update_is_an_unavailable_stub() -> None:
    save("discord-1", "Main Rogue")
    before = server.wowsims_get_character("discord-1", "Main Rogue")
    result = server.wowsims_update_character("discord-1", "Main Rogue")
    assert result["ok"] is False
    assert result["code"] == "SOURCE_UNAVAILABLE"
    assert "not open yet" in result["message"]
    assert server.wowsims_get_character("discord-1", "Main Rogue") == before


@pytest.mark.asyncio
async def test_simulate_saved_character() -> None:
    save("discord-1", "Main Rogue")
    result = await server.wowsims_simulate(
        owner="discord-1", character="Main Rogue", iterations=2, duration_s=30
    )
    assert result["ok"] is True, result
    assert result["resolved_character"] == "Main Rogue"
    assert result["dps"]["mean"] > 0
