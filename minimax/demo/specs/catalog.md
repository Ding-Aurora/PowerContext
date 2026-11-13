# Catalog contract

## CAT-001 — Existing category behavior
`list_products(products, category=None, status=None)` returns products in input
order, optionally restricted by exact category. An unknown category returns [].
Do not mutate the input. Return independent shallow copies of product dictionaries.

## CAT-002 — Status filtering (target change)
The optional status parameter accepts None, "active", or "archived".
None preserves all products (including legacy rows with no status).
An explicit status returns only rows with that status. Rows with no status do
not match an explicit status. Combine category and status with AND.
Reject every other status with ValueError, even when products is empty.

## CAT-003 — Verification
demo/tests/test_catalog.py::test_status_filter,
test_combined_filter, test_legacy_rows and test_invalid_status cover CAT-002.
The regression tests cover CAT-001: ordering, category, empty input and copies.
