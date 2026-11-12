"""Capture physical PDF pages and retrieve exact page citations."""

from __future__ import annotations

import hashlib
import io
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
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "can", "did", "do", "does", "for",
    "from", "give", "has", "have", "how", "if", "in", "is", "it", "of", "on", "or", "reported",
    "state", "shown", "that", "the", "their", "then", "this", "to", "use", "using", "was", "were",
    "what", "when", "which", "who", "with", "within", "year", "fy", "answer", "calculate", "company",
})
_EXPANSIONS = {
    "ebitda": ("operating", "income", "depreciation", "amortization"),
    "capex": ("capital", "spending", "expenditures"),
    "geographies": ("geographic", "regions", "countries", "markets", "international"),
    "geography": ("geographic", "regions", "countries", "markets", "international"),
    "legal": ("proceedings", "litigation", "lawsuits"),
    "battles": ("proceedings", "litigation"),
    "restructuring": ("impairment", "charges", "costs"),
    "margin": ("revenue", "sales", "operating", "income"),
}


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

    document_id = value.document_id.strip()
    if not document_id or document_id != value.document_id:
        raise ValueError("document_id must be a non-blank trimmed string")
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
    terms = [term for term in raw if term not in _STOP_WORDS and (len(term) > 1 or term.isdigit())]
    for term in tuple(terms):
        terms.extend(_EXPANSIONS.get(term, ()))
    return tuple(dict.fromkeys(terms))


def _lexical_score(text: str, terms: tuple[str, ...], backend_score: float) -> tuple[float, float]:
    counts = Counter(_TOKEN.findall(text.lower()))
    matched = sum(1 for term in terms if counts[term])
    numeric = sum(1 for term in terms if term.isdigit() and counts[term])
    repeated = sum(min(counts[term], 3) for term in terms)
    return (matched * 5.0 + numeric * 4.0 + repeated + backend_score * 0.01, backend_score)


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Retrieve distinct page entries using public scoped-Memory search."""

    if limit < 1:
        raise ValueError("limit must be positive")
    terms = _query_terms(question)
    query = " ".join(terms) or question
    page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=max(100, limit * 8)))
    ranked = sorted(page.hits, key=lambda hit: _lexical_score(hit.text, terms, hit.score), reverse=True)
    seen: set[tuple[str, str, int]] = set()
    citations: list[MemoryCitation] = []
    for hit in ranked:
        key = (hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
        )
        if len(citations) == limit:
            break
    return tuple(citations)


__all__ = [
    "PDFDocumentInput",
    "PDFPageInput",
    "PDF_PAGE_SOURCE_DEFINITION",
    "parse_pdf_document",
    "search_pdf_pages",
]
