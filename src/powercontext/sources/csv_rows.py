"""Capture offline CSV records as individually addressable Source evidence."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class CSVDocumentInput(BaseModel):
    document_id: str
    primary_key: str
    content: bytes


def _validate_document_id(document_id: str) -> None:
    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty and have no surrounding whitespace")


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Encode the two identity components independently, preserving their exact text."""
    _validate_document_id(document_id)
    return _row_identity(f"csv:{quote(document_id, safe='')}:", primary_key_value)


def _row_identity(prefix: str, primary_key_value: str) -> str:
    if not primary_key_value.strip():
        raise ValueError("primary key value must not be blank")
    source_id = prefix + quote(primary_key_value, safe="")
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"CSV Source identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


def _key_index(columns: tuple[str, ...], primary_key: str) -> int:
    if not columns or any(not column.strip() for column in columns):
        raise ValueError("CSV header must contain non-blank columns")
    if len(set(columns)) != len(columns):
        raise ValueError("CSV header columns must be unique")
    if not primary_key or primary_key not in columns:
        raise ValueError("primary_key must exactly match a CSV header column")
    return columns.index(primary_key)


class CSVRowInput(BaseModel):
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self) -> CSVRowInput:
        index = _key_index(self.columns, self.primary_key)
        if len(self.values) != len(self.columns):
            raise ValueError("CSV record width must match its header")
        if self.values[index] != self.primary_key_value:
            raise ValueError("primary_key_value must match the corresponding CSV field")
        csv_row_source_id(self.document_id, self.primary_key_value)
        return self


class CSVRowSource(Source):
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Validate the entire document before exposing any of its rows."""
    _validate_document_id(value.document_id)
    prefix = f"csv:{quote(value.document_id, safe='')}:"
    rows: list[CSVRowInput] = []
    seen: set[str] = set()
    reader = csv.reader(io.StringIO(value.content.decode("utf-8-sig"), newline=""), strict=True)
    try:
        columns = tuple(next(reader, ()))
        key_index = _key_index(columns, value.primary_key)
        for fields in reader:
            if not fields:
                continue
            if len(fields) != len(columns):
                raise ValueError(f"CSV record ending at line {reader.line_num} has the wrong width")
            key = fields[key_index]
            if key in seen:
                raise ValueError(f"Duplicate CSV primary key at line {reader.line_num}")
            _row_identity(prefix, key)
            # Header, width, key and identity have all been checked above. Avoid
            # validating and copying the shared header again for every record.
            rows.append(
                CSVRowInput.model_construct(
                    document_id=value.document_id,
                    primary_key=value.primary_key,
                    primary_key_value=key,
                    columns=columns,
                    values=tuple(fields),
                )
            )
            seen.add(key)
    except csv.Error as exc:
        raise ValueError(f"Invalid CSV at line {reader.line_num}: {exc}") from exc
    return tuple(rows)


class _CSVRowAdapter:
    name = "csv-row"
    input_class = CSVRowInput
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class _CSVRowTextEvidence:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=_CSVRowAdapter.name,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = AdapterSourceDefinition(
    _CSVRowAdapter(),
    projections=(_CSVRowTextEvidence(),),
)
