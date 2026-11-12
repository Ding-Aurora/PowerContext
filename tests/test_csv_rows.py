"""CSV boundary regressions independent of competition fixtures."""

import csv
import io
from urllib.parse import quote

import pytest

from powercontext.sources.csv_rows import CSVDocumentInput, CSVRowInput, csv_row_source_id, parse_csv_document


def test_parser_preserves_wide_unicode_records_and_empty_fields():
    columns = (" id ", *(f"字段{i}" for i in range(100)))
    values = (" 键:/% ", "0001", "false", "", 'quoted "value"\r\nnext', *("值" for _ in range(96)))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerow(values)
    rows = parse_csv_document(
        CSVDocumentInput(document_id="文档:%", primary_key=" id ", content=output.getvalue().encode("utf-8-sig"))
    )
    assert rows[0].columns == columns
    assert rows[0].values == values
    assert CSVRowInput.model_validate(rows[0].model_dump()) == rows[0]
    assert csv_row_source_id("文档:%", values[0]) == f"csv:{quote('文档:%', safe='')}:{quote(values[0], safe='')}"


@pytest.mark.parametrize("tail", [b'2,"unterminated', b"1,duplicate", b"  ,blank", b"2,wide,extra", b"\xff,invalid"])
def test_invalid_last_record_rejects_the_whole_document(tail):
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id="doc", primary_key="id", content=b"id,value\n1,ok\n" + tail))


def test_blank_physical_record_differs_from_quoted_empty_field():
    value = CSVDocumentInput(document_id="doc", primary_key="id", content=b'id\n\n""\n')
    with pytest.raises(ValueError):
        parse_csv_document(value)
    assert parse_csv_document(value.model_copy(update={"content": b"id\n\r\n"})) == ()


def test_percent_encoded_identity_boundary():
    assert len(csv_row_source_id("d", "x" * 250)) == 256
    with pytest.raises(ValueError):
        csv_row_source_id("d", "x" * 251)
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id="d", primary_key="id", content=b"id\n" + b"x" * 251))


@pytest.mark.parametrize("changes", [{"values": ("other",)}, {"primary_key": "missing"}, {"primary_key_value": " "}])
def test_direct_row_construction_still_validates(changes):
    fields = dict(document_id="doc", primary_key="id", primary_key_value="1", columns=("id",), values=("1",))
    with pytest.raises(ValueError):
        CSVRowInput(**(fields | changes))
