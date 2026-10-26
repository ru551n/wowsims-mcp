from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

_WORD = re.compile(r"[^a-z0-9]+")
_STOP_WORDS = {"the", "of"}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.lower().replace("'", "").replace("\u2019", "")
    words = _WORD.sub(" ", value).split()
    return " ".join(word for word in words if word not in _STOP_WORDS)


def edit_distance_at_most(left: str, right: str, limit: int) -> int | None:
    if abs(len(left) - len(right)) > limit:
        return None
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    before_previous: list[int] | None = None
    for i, a in enumerate(left, 1):
        current = [i]
        row_min = i
        for j, b in enumerate(right, 1):
            value = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (a != b),
            )
            if (
                before_previous is not None
                and j > 1
                and a == right[j - 2]
                and left[i - 2] == b
            ):
                value = min(value, before_previous[j - 2] + 1)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return None
        before_previous = previous
        previous = current
    return previous[-1] if previous[-1] <= limit else None


def _edit_limit(word: str) -> int:
    if len(word) <= 4:
        return 1
    if len(word) <= 8:
        return 2
    return 3


def _trigrams(value: str) -> set[str]:
    compact = value.replace(" ", "")
    return {compact[i : i + 3] for i in range(max(0, len(compact) - 2))}


def _trigram_similarity(left: str, right: str) -> float:
    a, b = _trigrams(left), _trigrams(right)
    return len(a & b) / len(a | b) if a and b else 0.0


@dataclass(frozen=True, slots=True)
class Match:
    index: int
    score: float
    exact: bool


class NameMatcher:
    def __init__(self, names: Sequence[str]) -> None:
        self.names = names
        self.normalized = [normalize(name) for name in names]
        self.words = [name.split() for name in self.normalized]
        self.vocabulary = sorted({word for words in self.words for word in words})
        self.exact: dict[str, list[int]] = {}
        for index, name in enumerate(self.normalized):
            self.exact.setdefault(name, []).append(index)

    def _word_score(self, query: str, candidate: str) -> float:
        if query == candidate:
            return 1.0
        if len(query) >= 3 and candidate.startswith(query):
            return 0.94 + 0.04 * len(query) / len(candidate)
        distance = edit_distance_at_most(query, candidate, _edit_limit(query))
        if distance is None:
            return 0.0
        return 1.0 - distance / max(len(query), len(candidate), 5)

    def _score(self, query: str, index: int) -> float:
        name = self.normalized[index]
        query_words = query.split()
        name_words = self.words[index]
        if not query_words or not name_words:
            return 0.0
        word_scores = [
            max(self._word_score(query_word, word) for word in name_words)
            for query_word in query_words
        ]
        if len(query_words) == 1 and len(name_words) > 1:
            compact_query = query_words[0]
            for start in range(len(name_words)):
                combined = ""
                for word in name_words[start:]:
                    combined += word
                    word_scores.append(self._word_score(compact_query, combined))
        coverage = (
            max(word_scores)
            if len(query_words) == 1
            else sum(word_scores) / len(query_words)
        )
        extra_words = max(0, len(name_words) - len(query_words))
        trigram = _trigram_similarity(query, name)
        compact_query = query.replace(" ", "")
        compact_name = name.replace(" ", "")
        prefix = compact_name.startswith(compact_query)
        score = (
            60 * coverage
            + 25 * trigram
            - min(12, 3 * extra_words)
            + (12 if prefix else 0)
            + (8 if compact_query == compact_name else 0)
        )
        if len(query_words) == 1 and len(query_words[0]) >= 4:
            score += 4 * SequenceMatcher(None, query, name).ratio()
        return score

    def match(self, query: str, limit: int = 25) -> list[Match]:
        normalized = normalize(query)
        if not normalized:
            return []
        if normalized in self.exact:
            return [Match(index, 100.0, True) for index in self.exact[normalized]]
        matches = [
            Match(index, score, False)
            for index in range(len(self.names))
            if (score := self._score(normalized, index)) >= 35
        ]
        matches.sort(key=lambda match: match.score, reverse=True)
        return matches[:limit]


def probabilities(scores: Iterable[float]) -> tuple[list[float], float]:
    scores = list(scores)
    if not scores:
        return [], 1.0
    temperature = 8.0
    none_offset = 30.0
    weights = [math.exp((score - scores[0]) / temperature) for score in scores]
    none_weight = math.exp((none_offset - scores[0]) / temperature)
    total = sum(weights) + none_weight
    return [weight / total for weight in weights], none_weight / total
