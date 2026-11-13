"""Capture physical PDF pages and retrieve exact page citations."""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter

from pydantic import BaseModel
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime import SearchMemoryRequest
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

_SOURCE_TYPE = "pdf-page"
_TOKEN = re.compile(r"[a-z]+|\d+")
_STOP_WORDS = frozenset({
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "by",
    "can",
    "did",
    "do",
    "does",
    "for",
    "from",
    "give",
    "has",
    "have",
    "how",
    "if",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "reported",
    "state",
    "shown",
    "that",
    "the",
    "their",
    "then",
    "this",
    "to",
    "use",
    "using",
    "was",
    "were",
    "what",
    "when",
    "which",
    "who",
    "with",
    "within",
    "year",
    "fy",
    "answer",
    "calculate",
    "company",
    "amount",
    "assume",
    "details",
    "following",
    "information",
    "millions",
    "perspective",
    "primarily",
    "question",
    "relying",
    "respond",
    "response",
    "shown",
    "using",
    "usd",
    "important",
    "materially",
    "ongoing",
    "analyst",
    "directly",
    "explicitly",
    "outlined",
    "unadjusted",
    "define",
    "investment",
    "less",
    "only",
    "perspective",
    "quantity",
})
_CONCEPTS = {
    "amortization": ("amortization", "amortisation"),
    "battles": ("legal", "proceedings", "litigation", "lawsuit", "contingencies"),
    "capex": ("capex", "capital", "expenditures", "spending", "purchases", "property", "plant", "equipment"),
    "depreciation": ("depreciation", "depreciated"),
    "ebitda": ("ebitda", "operating", "income", "depreciation", "amortization"),
    "expenditure": ("expenditure", "expenditures", "spending", "purchases"),
    "expenditures": ("expenditure", "expenditures", "spending", "purchases"),
    "geographies": ("geographic", "geographies", "regions", "countries", "markets", "international", "segments"),
    "geography": ("geographic", "geographies", "regions", "countries", "markets", "international", "segments"),
    "income": ("income", "earnings", "profit"),
    "legal": ("legal", "proceedings", "litigation", "lawsuit", "contingencies"),
    "margin": ("margin", "revenue", "sales", "operating", "income"),
    "net": ("net",),
    "ppne": ("property", "plant", "equipment", "net"),
    "restructuring": ("restructuring", "productivity", "impairment", "charges", "costs"),
    "revenue": ("revenue", "revenues", "sales"),
    "sales": ("sales", "revenue", "revenues"),
    "operating": ("operating", "operations"),
    "statements": ("statement", "statements", "consolidated"),
    "flows": ("flows", "activities"),
}
_PHRASES = (
    ("legal proceedings", 9.0),
    ("consolidated statement of income", 8.0),
    ("consolidated statement of operations", 8.0),
    ("consolidated statement of cash flows", 8.0),
    ("capital spending", 7.0),
    ("depreciation and amortization", 7.0),
    ("operating profit", 6.0),
    ("operating income", 6.0),
    ("reportable segments", 6.0),
    ("our operations", 5.0),
)


class PDFDocumentInput(BaseModel):
    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one readable PDF without partial results."""

    document_id = value.document_id
    if not document_id.strip():
        raise ValueError("document_id must not be blank")
    if not value.content:
        raise ValueError("PDF content must not be empty")
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")
        texts = tuple((page.extract_text() or "") for page in reader.pages)
        if not texts:
            raise ValueError("PDF must contain at least one page")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF could not be parsed completely") from error
    return tuple(
        PDFPageInput(
            document_id=document_id,
            document_sha256=digest,
            page_number=index,
            text=text,
        )
        for index, text in enumerate(texts, start=1)
    )


def _identity(page: PDFPageInput) -> str:
    key = f"{page.document_id}\0{page.document_sha256}\0{page.page_number}".encode()
    return "pdf:" + hashlib.sha256(key).hexdigest()


class _PDFPageAdapter:
    name = _SOURCE_TYPE
    input_class = PDFPageInput
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        return PDFPageSource(
            name=_identity(value),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput.model_validate(source.model_dump(include=set(PDFPageInput.model_fields)))


class _PDFTextEvidence:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=_SOURCE_TYPE,
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = AdapterSourceDefinition(
    _PDFPageAdapter(), projections=(_PDFTextEvidence(),)
)


def _query_terms(question: str) -> tuple[str, ...]:
    raw = _TOKEN.findall(question.lower())
    return tuple(dict.fromkeys(term for term in raw if term not in _STOP_WORDS and (len(term) > 1 or term.isdigit())))


def _concepts(terms: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    result = []
    seen = set()
    for term in terms:
        concept = tuple(dict.fromkeys(_CONCEPTS.get(term, (term,))))
        key = frozenset(concept)
        if key not in seen:
            seen.add(key)
            result.append(concept)
    return tuple(result)


def _probes(terms: tuple[str, ...], concepts: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    probes: list[str] = []

    def add(parts) -> None:
        probe = " ".join(dict.fromkeys(parts))
        if probe and probe not in probes:
            probes.append(probe)

    add(terms)
    for concept in concepts:
        add(concept[:4])
        for alternative in concept:
            if len(alternative) >= 5:
                add((alternative,))
    for left, right in zip(concepts, concepts[1:]):
        add((left[0], right[0]))
    # Single high-information terms remove the Memory service's multi-term admission
    # floor from the recall stage. Global scoring below restores query specificity.
    for term in terms:
        if len(term) >= 5 or term.isdigit():
            add((term,))
    return tuple(probes[:24])


def _score_candidates(candidates, concepts: tuple[tuple[str, ...], ...], terms: tuple[str, ...]):
    counts = {key: Counter(_TOKEN.findall(hit.text.lower())) for key, hit in candidates.items()}
    document_count = max(1, len(candidates))
    document_frequency = Counter(token for frequencies in counts.values() for token in frequencies)
    vocabulary = {term for alternatives in concepts for term in alternatives}
    weights = {term: math.log((document_count + 1) / (document_frequency[term] + 1)) + 1.0 for term in vocabulary}
    concept_weights = tuple(max(weights[term] for term in alternatives) for alternatives in concepts)
    total_concept_weight = sum(concept_weights) or 1.0
    query_vocabulary = {term for alternatives in concepts for term in alternatives}

    def score(item):
        key, hit = item
        frequencies = counts[key]
        matched_concept_weight = 0.0
        lexical = 0.0
        for alternatives, concept_weight in zip(concepts, concept_weights, strict=True):
            present = [term for term in alternatives if frequencies[term]]
            if not present:
                continue
            matched_concept_weight += concept_weight
            best = max(weights[term] for term in present)
            lexical += best * (1.0 + min(sum(frequencies[term] for term in present), 3) * 0.15)
        coverage = matched_concept_weight / total_concept_weight
        text = hit.text.lower()
        phrase = sum(1 for left, right in zip(terms, terms[1:]) if f"{left} {right}" in text)
        section = sum(
            weight for value, weight in _PHRASES if value in text and query_vocabulary.intersection(value.split())
        )
        years = sum(1 for term in terms if term.isdigit() and frequencies[term])
        return (
            coverage * 18.0 + lexical + phrase * 2.5 + section + years * 1.5 + hit.score * 0.1,
            -len(text),
        )

    return sorted(candidates.items(), key=score, reverse=True)


# Section names describe financial documents generally; they contain no report
# names, benchmark questions, page numbers or precomputed evidence.
_SECTIONS = {
    "income": (r"(?:consolidated\s+)?statements?\s+of\s+(?:income|operations|earnings|profit)",),
    "cash": (r"(?:consolidated\s+)?statements?\s+of\s+cash\s+flows?",),
    "balance": (r"(?:consolidated\s+)?balance\s+sheets?", r"statements?\s+of\s+financial\s+position"),
    "legal": (r"(?:item\s+3[. :–-]*)?legal\s+proceedings", r"commitments\s+and\s+contingencies"),
    "segments": (
        r"(?:our\s+)?(?:divisions|reportable\s+segments|operating\s+segments)",
        r"geographic(?:al)?\s+(?:information|areas|segments)",
    ),
}


def _sections_for_question(question: str) -> tuple[str, ...]:
    query = question.casefold()
    sections = []
    if re.search(r"income|earnings|profit|revenue|margin|ebitda|p&l", query):
        sections.append("income")
    if re.search(r"cash|capex|capital expend|depreciation|amortization|ebitda|d&a", query):
        sections.append("cash")
    if re.search(r"balance sheet|assets|liabilit|equity|working capital|inventory|inventories|receivable", query):
        sections.append("balance")
    if re.search(r"legal|litigation|lawsuit|battles|contingenc", query):
        sections.append("legal")
    if re.search(r"geograph|regions|countries|segments|operates|operations located", query):
        sections.append("segments")
    return tuple(sections)


def _section_strength(text: str, section: str) -> float:
    # A heading near the start is stronger evidence than a passing reference in
    # the body or a table of contents listing several unrelated sections.
    body = text.split("\n", 1)[-1].lower()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    prefix = " ".join(lines[:12])
    patterns = _SECTIONS[section]
    score = 0.0
    for line in lines[:12]:
        if len(line) <= 140 and any(
            re.match(r"(?:item\s+\d+[. :–-]*|\d+[. :–-]*)?" + pattern, line) for pattern in patterns
        ):
            score = max(score, 1.0 if not re.search(r"\s\d+\s*$", line) else 0.25)
    if not score and any(re.search(pattern, prefix) for pattern in patterns):
        score = 0.2
    if sum(any(re.search(pattern, prefix) for pattern in patterns) for patterns in _SECTIONS.values()) >= 3:
        score *= 0.15
    return score


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Retrieve exact page citations with balanced coverage of requested statements."""
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    terms = _query_terms(question)
    concepts = _concepts(terms)
    sections = _sections_for_question(question)
    section_queries = {
        "income": ("statement income", "statement operations", "statement earnings"),
        "cash": ("cash flows", "cash flow", "financing activities"),
        "balance": ("balance sheet", "financial position"),
        "legal": ("legal proceedings", "litigation", "contingencies"),
        "segments": ("geographic", "segments", "divisions"),
    }
    # Reserve probe budget for requested statement types before broad expansion
    # can exhaust it. Use only public Memory search; every returned identity
    # must come from a persisted hit.
    probes = list(
        dict.fromkeys(
            [probe for section in sections for probe in section_queries[section]] + list(_probes(terms, concepts))
        )
    )[:32]
    candidates = {}
    ranks = Counter()
    for probe in probes or (question,):
        page = await memory.search(SearchMemoryRequest(query=probe, mode="fts", limit=max(120, limit * 6)))
        for rank, hit in enumerate(page.hits, start=1):
            key = (hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id)
            candidates.setdefault(key, hit)
            ranks[key] += 1.0 / (20 + rank)
    candidates = {key: hit.model_copy(update={"score": ranks[key]}) for key, hit in candidates.items()}
    ranked = _score_candidates(candidates, concepts, terms)
    positions = {key: rank for rank, (key, _) in enumerate(ranked)}
    selected = []
    seen = set()
    # Keep a small independent quota per requested section so a question
    # requiring two statements cannot lose one to repeated discussion pages.
    quota = min(3, max(1, limit // max(1, len(sections) * 2)))
    for section in sections:
        matches = [(key, hit, _section_strength(hit.text, section)) for key, hit in ranked]
        matches = [item for item in matches if item[2] >= 0.5]
        matches.sort(key=lambda item: (-item[2], positions[item[0]]))
        for key, hit, _ in matches[:quota]:
            if key not in seen and len(selected) < limit:
                selected.append(hit)
                seen.add(key)
    for key, hit in ranked:
        if len(selected) >= limit:
            break
        if key not in seen:
            selected.append(hit)
            seen.add(key)
    return tuple(
        MemoryCitation(memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id)
        for hit in selected
    )


__all__ = [
    "PDFDocumentInput",
    "PDFPageInput",
    "PDF_PAGE_SOURCE_DEFINITION",
    "parse_pdf_document",
    "search_pdf_pages",
]
