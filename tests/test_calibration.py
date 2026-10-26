from __future__ import annotations

import random
from collections import defaultdict

from test_matching import _typo

from wowsims_mcp.database import GameDatabase


def test_held_out_probability_reliability(real_database: GameDatabase) -> None:
    rng = random.Random(20261027)
    queries = []
    for item in rng.sample(real_database.items, 500):
        query = item["name"]
        for _ in range(rng.choice([1, 2])):
            query = _typo(query, rng)
        queries.append((query, item["id"]))
    unknown = [
        "Ashkandi Greatsword of the Brotherhood",
        "Notarealitemxyz",
        "Sulfuras Legendary Banana",
        "Frostmourne",
        "Thunderfury Blessed Blade of the Muffin",
        "Warglaive of Azzinoth",
        "Atiesh Greatstaff of the Guardian",
        "Not even an item",
        "qqqqqqqqqq",
        "Dragonwrath Tarecgosa Rest",
    ]
    queries.extend((query, None) for query in unknown)
    random.Random(42).shuffle(queries)
    held_out = queries[len(queries) // 2 :]
    bins: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    high_confidence = []
    for query, intended_id in held_out:
        result = real_database.search(query)
        if not result["candidates"]:
            continue
        candidate = result["candidates"][0]
        probability = candidate["probability"]
        correct = candidate["id"] == intended_id
        bins[min(9, int(probability * 10))].append((probability, correct))
        if probability >= 0.85:
            high_confidence.append(correct)
    assert sum(high_confidence) / len(high_confidence) >= 0.97
    for values in bins.values():
        if len(values) >= 5:
            predicted = sum(probability for probability, _ in values) / len(values)
            observed = sum(correct for _, correct in values) / len(values)
            assert abs(predicted - observed) <= 0.1
