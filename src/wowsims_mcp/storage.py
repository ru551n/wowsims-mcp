from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, overload


class CharacterError(ValueError):
    def __init__(self, code: str, message: str, next_step: str) -> None:
        super().__init__(message)
        self.code = code
        self.next_step = next_step


class CharacterStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(
            path or os.environ.get("WOWSIMS_STORAGE_PATH", "data/characters.db")
        )
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                owner TEXT NOT NULL,
                name TEXT NOT NULL,
                class TEXT NOT NULL,
                spec TEXT NOT NULL,
                race TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                raw_import TEXT,
                is_default INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (owner, name)
            )
            """
        )
        self.connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS one_default_character "
            "ON characters(owner) WHERE is_default = 1"
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def _assert_can_modify(self, owner: str, name: str) -> None:
        row = self.connection.execute(
            "SELECT owner FROM characters WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        if row is not None and row["owner"] != owner:
            raise CharacterError(
                "CHARACTER_OWNERSHIP_MISMATCH",
                f"Character {name!r} belongs to another Discord user.",
                "Choose a different character name; you cannot modify "
                "another user's character.",
            )

    def save(
        self,
        owner: str,
        name: str,
        character_class: str,
        spec: str,
        race: str,
        settings: dict[str, Any],
        raw_import: str | None = None,
        make_default: bool | None = None,
        expected_owner: str | None = None,
    ) -> dict[str, Any]:
        owner, name = owner.strip(), name.strip()
        if not owner or not name:
            raise CharacterError(
                "INVALID_INPUT",
                "Owner and character name are required.",
                "Provide both values.",
            )
        if len(name) > 100:
            raise CharacterError(
                "INVALID_INPUT",
                "Character name is limited to 100 characters.",
                "Shorten the name.",
            )
        if expected_owner is not None:
            row = self.connection.execute(
                "SELECT owner FROM characters WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            if row is not None and row["owner"] != expected_owner:
                raise CharacterError(
                    "CHARACTER_OWNERSHIP_MISMATCH",
                    f"Character {name!r} belongs to another Discord user.",
                    "You cannot modify another user's character.",
                )
        existing = self.get(owner, name, required=False)
        count = self.connection.execute(
            "SELECT COUNT(*) FROM characters WHERE owner = ?", (owner,)
        ).fetchone()[0]
        default = make_default if make_default is not None else count == 0
        if existing and make_default is None:
            default = bool(existing["is_default"])
        now = datetime.now(UTC).isoformat()
        with self.connection:
            if default:
                self.connection.execute(
                    "UPDATE characters SET is_default = 0 WHERE owner = ?", (owner,)
                )
            self.connection.execute(
                """
                INSERT INTO characters
                    (owner, name, class, spec, race, settings_json,
                     raw_import, is_default, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner, name) DO UPDATE SET
                    class = excluded.class, spec = excluded.spec, race = excluded.race,
                    settings_json = excluded.settings_json,
                    raw_import = excluded.raw_import,
                    is_default = excluded.is_default, updated_at = excluded.updated_at
                """,
                (
                    owner,
                    name,
                    character_class,
                    spec,
                    race,
                    json.dumps(settings, separators=(",", ":")),
                    raw_import,
                    int(default),
                    now,
                ),
            )
        return self.get(owner, name)

    @overload
    def get(
        self, owner: str, name: str | None = None, required: Literal[True] = True
    ) -> dict[str, Any]: ...

    @overload
    def get(
        self, owner: str, name: str | None, required: Literal[False]
    ) -> dict[str, Any] | None: ...

    def get(
        self, owner: str, name: str | None = None, required: bool = True
    ) -> dict[str, Any] | None:
        if name:
            row = self.connection.execute(
                "SELECT * FROM characters WHERE owner = ? AND name = ? COLLATE NOCASE",
                (owner, name),
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT * FROM characters WHERE owner = ? AND is_default = 1", (owner,)
            ).fetchone()
            if row is None:
                rows = self.list(owner)
                if len(rows) > 1:
                    raise CharacterError(
                        "AMBIGUOUS_CHARACTER",
                        "You have several characters and no default.",
                        "Specify a character name or set a default.",
                    )
                if rows:
                    row = self.connection.execute(
                        "SELECT * FROM characters WHERE owner = ? AND name = ?",
                        (owner, rows[0]["name"]),
                    ).fetchone()
        if row is None:
            if not required:
                return None
            if name:
                raise CharacterError(
                    "CHARACTER_NOT_FOUND",
                    f"Character {name!r} was not found for this user.",
                    "Call wowsims_list_characters or save the character first.",
                )
            raise CharacterError(
                "NO_CHARACTERS",
                "No characters are saved for this user.",
                "Save a character from a preset or wowsims UI JSON first.",
            )
        result = dict(row)
        result["settings"] = json.loads(result.pop("settings_json"))
        result["is_default"] = bool(result["is_default"])
        return result

    def list(self, owner: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT name, class, spec, race, is_default, updated_at "
            "FROM characters WHERE owner = ? ORDER BY name COLLATE NOCASE",
            (owner,),
        ).fetchall()
        return [{**dict(row), "is_default": bool(row["is_default"])} for row in rows]

    def set_default(self, owner: str, name: str) -> dict[str, Any]:
        self._assert_can_modify(owner, name)
        self.get(owner, name)
        with self.connection:
            self.connection.execute(
                "UPDATE characters SET is_default = 0 WHERE owner = ?", (owner,)
            )
            self.connection.execute(
                "UPDATE characters SET is_default = 1 WHERE owner = ? "
                "AND name = ? COLLATE NOCASE",
                (owner, name),
            )
        return self.get(owner, name)

    def delete(self, owner: str, name: str, confirm: bool) -> dict[str, Any]:
        if not confirm:
            raise CharacterError(
                "CONFIRM_REQUIRED",
                "Deleting a character requires confirm=true.",
                "Ask the user to confirm before deleting this saved character.",
            )
        self._assert_can_modify(owner, name)
        character = self.get(owner, name)
        with self.connection:
            self.connection.execute(
                "DELETE FROM characters WHERE owner = ? AND name = ? COLLATE NOCASE",
                (owner, name),
            )
            if character["is_default"]:
                self.connection.execute(
                    "UPDATE characters SET is_default = 1 WHERE owner = ? "
                    "AND name = (SELECT name FROM characters WHERE owner = ? LIMIT 1)",
                    (owner, owner),
                )
        return {"deleted": character["name"]}
