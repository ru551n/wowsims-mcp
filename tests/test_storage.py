from __future__ import annotations

import pytest

from wowsims_mcp.storage import CharacterError, CharacterStore


@pytest.fixture
def store() -> CharacterStore:
    store = CharacterStore(":memory:")
    yield store
    store.close()


def settings(name: str) -> dict:
    return {"raid": {"parties": [{"players": [{"name": name}]}]}}


def test_multiple_characters_and_default(store: CharacterStore) -> None:
    store.save("discord-1", "Rogue-One", "rogue", "combat", "troll", settings("one"))
    store.save("discord-1", "Mage-One", "mage", "arcane", "human", settings("two"))
    assert len(store.list("discord-1")) == 2
    assert store.get("discord-1")["name"] == "Rogue-One"
    store.set_default("discord-1", "Mage-One")
    assert store.get("discord-1")["name"] == "Mage-One"
    assert store.get("discord-1", "rogue-one")["name"] == "Rogue-One"


def test_same_name_can_exist_for_different_users(store: CharacterStore) -> None:
    store.save("discord-1", "Main", "rogue", "combat", "troll", settings("one"))
    store.save(
        "discord-2",
        "Main",
        "mage",
        "arcane",
        "human",
        settings("two"),
    )
    assert store.get("discord-1", "Main")["class"] == "rogue"
    assert store.get("discord-2", "Main")["class"] == "mage"


@pytest.mark.parametrize("operation", ["save", "default", "delete"])
def test_cannot_modify_another_users_character(
    store: CharacterStore, operation: str
) -> None:
    store.save("discord-1", "Main", "rogue", "combat", "troll", settings("one"))
    store.save("discord-2", "Main", "mage", "arcane", "human", settings("two"))
    with pytest.raises(CharacterError) as error:
        if operation == "save":
            store.save(
                "discord-2",
                "main",
                "mage",
                "arcane",
                "human",
                settings("two"),
                expected_owner="discord-2",
            )
        elif operation == "default":
            store.set_default("discord-2", "Main")
        else:
            store.delete("discord-2", "Main", confirm=True)
    assert error.value.code == "CHARACTER_OWNERSHIP_MISMATCH"
    assert "another Discord user" in str(error.value)
    assert store.get("discord-1", "Main")["class"] == "rogue"


def test_delete_requires_confirmation(store: CharacterStore) -> None:
    store.save("discord-1", "Main", "rogue", "combat", "troll", settings("one"))
    with pytest.raises(CharacterError) as error:
        store.delete("discord-1", "Main", confirm=False)
    assert error.value.code == "CONFIRM_REQUIRED"
    assert store.delete("discord-1", "Main", confirm=True)["deleted"] == "Main"
