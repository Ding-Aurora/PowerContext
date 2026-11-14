"""Captured PDF pages and offline retrieval through scoped Memory."""

from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from math import log1p
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import ScopedMemoryApplication


class PDFDocumentInput(BaseModel):
    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def nonblank_document(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must contain non-whitespace characters")
        return value


class PDFPageInput(BaseModel):
    document_id: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(gt=0, strict=True)
    text: str

    @field_validator("document_id")
    @classmethod
    def nonblank_document(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must contain non-whitespace characters")
        return value


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page, exposing results only after full success."""
    try:
        if not value.content:
            raise ValueError("empty PDF")
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")
        digest = hashlib.sha256(value.content).hexdigest()
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=number,
                text=page.extract_text() or "",
            )
            for number, page in enumerate(reader.pages, 1)
        )
        if not pages:
            raise ValueError("PDF contains no pages")
        return pages
    except Exception as error:
        raise ValueError("Unable to completely parse PDF") from error


class PDFPageSource(Source):
    document_id: str
    document_sha256: str
    page_number: int
    text: str


class _PDFPageAdapter:
    name = "pdf-page"
    input_class = PDFPageInput
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = f"{value.document_id}\0{value.document_sha256}\0{value.page_number}"
        name = "pdf:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return PDFPageSource(name=name, materialization=SourceMaterialization.CAPTURED, **value.model_dump())

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput.model_validate(source.model_dump(include=set(PDFPageInput.model_fields)))


class _PDFPageText:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        page = source
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{page.document_id}\n{page.text}",
            metadata={
                "document_id": page.document_id,
                "document_sha256": page.document_sha256,
                "page_number": page.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = AdapterSourceDefinition(
    _PDFPageAdapter(), projections=(_PDFPageText(),),
)

_WORDS = re.compile(r"[a-z]+|\d+")
_STOP = frozenset(
    "a an and any are as at be been by can could define details do does for from give has have how "
    "i if in into is it its of on only or perspective question relying reported respond response "
    "shown state than that the their these this to use using was were what when where which who "
    "why with would fy usd millions million calculate answer assuming analyst investment".split()
)
_SYNONYMS = (
    ("revenue", "revenues", "sales"),
    ("geographies", "geography", "geographic", "regions", "countries", "markets", "international", "domestic"),
    ("legal", "litigation", "proceedings", "lawsuits", "contingencies", "battles"),
    ("capex", "capital expenditures", "purchases property plant equipment", "additions property plant equipment"),
    ("ebitda", "operating income", "depreciation amortization"),
    ("income statement", "statements income", "statements operations", "earnings", "profit loss"),
    ("cash flow", "cash flows", "cashflows"),
    ("restructuring", "reorganization", "productivity"),
    ("debt", "borrowings", "indebtedness"),
    ("dividends", "distributions"),
    ("repurchases", "buybacks"),
)

_SECTIONS = (
    (r"income|earnings|profit|revenue|margin|ebitda|p&l",
     r"(?:consolidated\s+)?statements?\s+of\s+(?:income|operations|earnings|profit)"),
    (r"cash|capex|capital expend|depreciation|amortization|ebitda|d&a",
     r"(?:consolidated\s+)?statements?\s+of\s+cash\s+flows?"),
    (r"balance sheet|assets|liabilit|equity|working capital|inventory|inventories|receivable",
     r"(?:consolidated\s+)?(?:balance\s+sheets?|statements?\s+of\s+financial\s+position)"),
    (r"legal|litigation|lawsuit|battles|contingenc",
     r"(?:item\s+3[. :–-]*)?(?:legal\s+proceedings|commitments\s+and\s+contingencies)"),
    (r"geograph|regions|countries|segments|operates",
     r"(?:our\s+)?(?:divisions|reportable\s+segments|operating\s+segments|geographic(?:al)?\s+information)"),
)


def _has_heading(text: str, pattern: str) -> bool:
    lines = [line.strip().casefold() for line in text.partition("\n")[2].splitlines() if line.strip()]
    return any(
        len(line) < 140
        and re.fullmatch(pattern + r"[ :.–-]*", line) is not None
        for line in lines[:12]
    )


def _tokens(text: str) -> list[str]:
    return [
        word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "is", "us")) else word
        for word in _WORDS.findall(text.casefold())
        if word not in _STOP
    ]


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10,
) -> tuple[MemoryCitation, ...]:
    """Rank current, scoped PDF evidence with corpus-normalized lexical scores."""
    from powercontext.builtin.runtime.models import SearchMemoryRequest

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    if not question.strip():
        raise ValueError("question must not be blank")
    if limit == 0:
        return ()
    # Search and list both go through the scoped public API. Reading current
    # entries allows document-frequency scoring and inflection matching without
    # a database-specific FTS syntax or access to private storage.
    recalled = await memory.search(SearchMemoryRequest(query=question, mode="fts", limit=min(limit, 100)))
    records = (await memory.list()).entries
    pages = [
        record for record in records
        if any(source.source_type == "pdf-page" for source in record.entry.sources)
    ]
    if not pages:
        return ()
    # Document identifiers are part of the stored projection. Prefer the
    # explicitly named company before ranking financial terms across reports.
    question_terms = set(_tokens(question))
    company_matches = []
    for record in pages:
        document_id = record.entry.text.partition("\n")[0]
        company = document_id.split("_", 1)[0]
        terms = set(_tokens(company))
        company_matches.append(bool(terms) and terms <= question_terms)
    if any(company_matches):
        pages = [record for record, matches in zip(pages, company_matches, strict=True) if matches]
    documents = [Counter(_tokens(record.entry.text)) for record in pages]
    frequency: Counter[str] = Counter()
    for document in documents:
        frequency.update(document.keys())
    lengths = [sum(document.values()) for document in documents]
    average = max(1, sum(lengths) / len(lengths))
    query = question_terms
    weights = {term: 1.0 for term in query}
    for group in _SYNONYMS:
        if any(set(_tokens(phrase)) <= query for phrase in group):
            for phrase in group:
                for term in _tokens(phrase):
                    weights.setdefault(term, 0.4)
    recalled_ids = {hit.entry_id: rank for rank, hit in enumerate(recalled.hits)}
    scores = []
    for index, (record, document, length) in enumerate(zip(pages, documents, lengths, strict=True)):
        score = 0.0
        for term, weight in sorted(weights.items()):
            count = document.get(term, 0)
            if count:
                inverse = log1p((len(pages) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                score += weight * inverse * count * 2.2 / (count + 1.2 * (0.35 + 0.65 * length / average))
        rank = recalled_ids.get(record.entry.entry_id)
        if rank is not None:
            score += 0.2 / (rank + 1)
        scores.append((score, index))
    # Financial calculations can require several statements. Reserve a small
    # share of the result for each requested section before lexical filling.
    ranked = [index for _, index in sorted(scores, key=lambda item: (-item[0], item[1]))]
    sections = [heading for query, heading in _SECTIONS if re.search(query, question.casefold())]
    selected = []
    quota = min(3, max(1, limit // max(1, len(sections) * 2)))
    for heading in sections:
        matches = [index for index in ranked if _has_heading(pages[index].entry.text, heading)]
        selected.extend(matches[:quota])
    result = []
    seen = set()
    for index in selected + ranked:
        record = pages[index]
        identity = tuple(sorted(
            (source.source_type, source.source_id)
            for source in record.entry.sources if source.source_type == "pdf-page"
        ))
        if identity not in seen:
            seen.add(identity)
            result.append(record.citation)
        if len(result) == limit:
            break
    return tuple(result)
