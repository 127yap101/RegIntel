"""Deterministic retrieval scores; floats never enter financial arithmetic."""

import math
from collections import Counter
from collections.abc import Sequence


def bm25(query: dict[str, int], documents: dict[str, dict[str, int]]) -> list[str]:
    if not documents or not query:
        return []
    lengths = {key: sum(terms.values()) for key, terms in documents.items()}
    average = sum(lengths.values()) / len(lengths)
    if average == 0:
        return []
    frequency = Counter(term for terms in documents.values() for term in terms)
    scored: list[tuple[float, str]] = []
    for key, terms in documents.items():
        score = 0.0
        for term in query:
            count = terms.get(term, 0)
            if count:
                inverse = math.log(
                    1 + (len(documents) - frequency[term] + 0.5) / (frequency[term] + 0.5)
                )
                score += (
                    inverse * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * lengths[key] / average))
                )
        if score > 0:
            scored.append((score, key))
    return [key for _, key in sorted(scored, key=lambda item: (-item[0], item[1]))]


def rrf(channels: Sequence[Sequence[str]]) -> list[str]:
    scores: dict[str, float] = {}
    for channel in channels:
        if len(set(channel)) != len(channel):
            raise ValueError("Ranking channels must contain distinct source IDs.")
        for rank, identity in enumerate(channel, 1):
            scores[identity] = scores.get(identity, 0.0) + 1.0 / (60 + rank)
    return sorted(scores, key=lambda identity: (-scores[identity], identity))
