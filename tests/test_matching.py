from __future__ import annotations

import random
from collections import Counter

from wowsims_mcp.database import GameDatabase
from wowsims_mcp.matching import edit_distance_at_most, normalize


def test_normalization() -> None:
    assert normalize("  The Lïonheart's, Helm! ") == "lionhearts helm"
    assert normalize("Band ofthe") == "band ofthe"


def test_damerau_levenshtein_transposition() -> None:
    assert edit_distance_at_most("helm", "hlem", 1) == 1
    assert edit_distance_at_most("ab", "ba", 1) == 1
    assert edit_distance_at_most("abc", "xyz", 1) is None


def _typo(name: str, rng: random.Random) -> str:
    words = name.split()
    index = rng.randrange(len(words))
    word = words[index]
    if len(word) < 3:
        return name
    position = rng.randrange(1, len(word))
    operation = rng.choice(
        ["delete", "insert", "substitute", "transpose", "drop_space"]
    )
    if operation == "delete":
        word = word[:position] + word[position + 1 :]
    elif operation == "insert":
        word = (
            word[:position] + rng.choice("abcdefghijklmnopqrstuvwxyz") + word[position:]
        )
    elif operation == "substitute":
        word = (
            word[: position - 1]
            + rng.choice("abcdefghijklmnopqrstuvwxyz")
            + word[position:]
        )
    elif operation == "transpose":
        word = (
            word[: position - 1]
            + word[position]
            + word[position - 1]
            + word[position + 1 :]
        )
    words[index] = word
    result = " ".join(words)
    if operation == "drop_space" and " " in result:
        position = rng.randrange(len(result))
        while result[position] != " ":
            position = rng.randrange(len(result))
        result = result[:position] + result[position + 1 :]
    return result


def test_real_database_typo_benchmark(real_database: GameDatabase) -> None:
    rng = random.Random(20261026)
    items = rng.sample(real_database.items, 200)
    counts: Counter[str] = Counter()
    for item in items:
        query = item["name"]
        for _ in range(2):
            query = _typo(query, rng)
        result = real_database.search(query)
        names = [candidate["name"] for candidate in result["candidates"]]
        counts["top1"] += bool(names and names[0] == item["name"])
        counts["top5"] += item["name"] in names
        counts["wrong_confident"] += (
            result["status"] == "confident" and names[0] != item["name"]
        )
    assert counts["top1"] / len(items) >= 0.9
    assert counts["top5"] / len(items) >= 0.97
    assert counts["wrong_confident"] == 0
