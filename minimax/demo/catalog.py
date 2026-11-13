"""Small product catalog: the starting implementation lacks status filtering."""


def list_products(products, category=None, status=None):
    return [dict(item) for item in products if category is None or item["category"] == category]
