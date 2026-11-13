import pytest

from catalog import list_products


@pytest.fixture
def products():
    return [
        {"id": 1, "category": "book", "status": "active"},
        {"id": 2, "category": "book", "status": "archived"},
        {"id": 3, "category": "game", "status": "active"},
        {"id": 4, "category": "book"},
    ]


@pytest.mark.parametrize("status,ids", [("active", [1, 3]), ("archived", [2])])
def test_status_filter(products, status, ids):
    assert [p["id"] for p in list_products(products, status=status)] == ids


def test_combined_filter(products):
    assert [p["id"] for p in list_products(products, category="book", status="active")] == [1]


def test_legacy_rows():
    rows = [{"id": 1, "category": "book"}]
    assert list_products(rows, status="active") == []
    assert list_products(rows) == rows


@pytest.mark.parametrize("status", ["", "deleted", 0, [], {}])
@pytest.mark.parametrize("rows", [[], [{"id": 1, "category": "book"}]])
def test_invalid_status(rows, status):
    with pytest.raises(ValueError):
        list_products(rows, status=status)


def test_regression_category_and_order(products):
    assert [p["id"] for p in list_products(products, category="book")] == [1, 2, 4]
    assert list_products(products, category="unknown") == []
    assert list_products(products) == products


def test_regression_empty():
    assert list_products([]) == []


def test_regression_copies(products):
    result = list_products(products)
    result[0]["id"] = 99
    assert products[0]["id"] == 1
