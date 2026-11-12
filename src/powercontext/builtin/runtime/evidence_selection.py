"""Rank literal sentence spans against a query without model calls."""

import re
from collections import Counter
from collections.abc import Iterator, Sequence
from math import log1p

_WORD = re.compile(r"[\u3400-\u9fff]|[^\W\d_]+|\d+", re.UNICODE)
_BOUNDARY = re.compile(r"[.!?](?=\s|$)|[。！？]|\n\s*\n")
_ABBREVIATION = re.compile(r"\b(?:al|fig|e\.g|i\.e|vs|dr|et)\.$", re.I)
_STOP = frozenset(
    "a an and are as at be been being but by can could did do does for from had has have how "
    "in into is it its may of on or should so than that the their them there these they this "
    "those to was were what when where which who will with would".split()
)


def _term(word: str) -> str:
    word = word.casefold()
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _terms(text: str) -> list[str]:
    return [_term(word) for word in _WORD.findall(text) if word.casefold() not in _STOP]


def _sentences(text: str) -> Iterator[tuple[int, int]]:
    start = 0
    for boundary in _BOUNDARY.finditer(text):
        end = boundary.end()
        if _ABBREVIATION.search(text[max(start, end - 8):end]):
            continue
        segment = text[start:end]
        trimmed = segment.strip()
        if trimmed:
            left = start + len(segment) - len(segment.lstrip())
            yield left, left + len(trimmed)
        start = end
    segment = text[start:]
    tail = segment.strip()
    if tail:
        left = start + len(segment) - len(segment.lstrip())
        yield left, left + len(tail)


def rank_evidence(query: str, bodies: Sequence[str]) -> Iterator[tuple[int, int, int]]:
    query_terms = _terms(query)
    wanted = set(query_terms)
    phrases = set(zip(query_terms, query_terms[1:]))
    sentences = [
        (doc, start, end, _terms(body[start:end]))
        for doc, body in enumerate(bodies)
        for start, end in _sentences(body)
    ]
    frequency: Counter[str] = Counter()
    for _, _, _, terms in sentences:
        frequency.update(wanted.intersection(terms))
    weight = {term: log1p((len(sentences) + 1) / (frequency[term] + 1)) for term in wanted}

    scored: list[tuple[float, int, int, int]] = []
    strongest: dict[int, float] = {}
    for doc, start, end, terms in sentences:
        counts = Counter(terms)
        score = sum(
            weight[term] * (1 + 0.18 * log1p(counts[term] - 1))
            for term in sorted(wanted & counts.keys())
        )
        score += 0.4 * sum(
            weight[first] + weight[second]
            for first, second in sorted(phrases.intersection(zip(terms, terms[1:])))
        )
        score /= (0.75 + 0.25 * max(1, len(terms)) / 24) ** 0.5
        strongest[doc] = max(strongest.get(doc, 0), score)
        scored.append((score, doc, start, end))

    ranked = sorted(
        scored,
        key=lambda item: (-(item[0] + 0.24 * strongest[item[1]]), item[1], item[2]),
    )
    for score, doc, start, end in ranked:
        if score == 0 and frequency:
            continue
        yield doc, start, end
        if end - start > 240:
            tokens = list(_WORD.finditer(bodies[doc], start, end))
            matches = [index for index, token in enumerate(tokens) if _term(token.group()) in wanted]
            if matches:
                anchor = max(matches, key=lambda index: weight[_term(tokens[index].group())])
                for radius in (24, 12, 5):
                    left = tokens[max(0, anchor - radius)].start()
                    right = tokens[min(len(tokens) - 1, anchor + radius)].end()
                    yield doc, left, right
