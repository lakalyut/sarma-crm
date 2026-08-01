import pytest

from app.models import Product
from app.product_parser import extract_weight, match_product_by_flavor, normalize_text


def make_product(brand, flavor, category="Табак для кальяна"):
    canonical_sku = f'{category} "{brand}" {flavor}'
    return Product(
        category=category,
        brand=brand,
        flavor=flavor,
        canonical_sku=canonical_sku,
        canonical_name=canonical_sku,
        default_weight_g=120,
        norm_brand=normalize_text(brand),
        norm_flavor=normalize_text(flavor),
        is_active=True,
        is_new=False,
    )


def test_normalize_text_lowercases_and_replaces_yo():
    assert normalize_text("Ёлка") == "елка"


def test_normalize_text_strips_parens_and_punctuation():
    assert normalize_text("Вирджин Пич (2.0)") == "вирджин пич"


def test_normalize_text_collapses_dashes_and_whitespace():
    assert normalize_text("Манго-Лайм   ") == "манго лайм"


def test_match_product_by_flavor_exact_match():
    products = [make_product("SL", "Ananas"), make_product("SL", "Малина")]

    product, score = match_product_by_flavor(
        'Табак для кальяна "SL" Малина 120г.', products
    )

    assert product is not None
    assert product.flavor == "Малина"
    assert score == 100


def test_match_product_by_flavor_fuzzy_typo_still_matches():
    products = [make_product("SL", "Клубничная содовая")]

    product, score = match_product_by_flavor(
        'Табак для кальяна "SL" Клубничн содовая 120г.', products
    )

    assert product is not None
    assert product.flavor == "Клубничная содовая"
    assert score >= 70


def test_match_product_by_flavor_below_threshold_returns_none():
    products = [make_product("SL", "Манго")]

    product, score = match_product_by_flavor(
        'Табак для кальяна "Совершенно другой бренд" Совсем другой вкус 120г.',
        products,
    )

    assert product is None
    assert score < 70


def test_match_product_by_flavor_empty_catalog():
    product, score = match_product_by_flavor("что угодно", [])
    assert product is None
    assert score == 0


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('Табак для кальяна "SL" Малина 120г.', 120),
        ('Табак для кальяна "SL" Малина 100 гр', 100),
        ('Tobacco "SL" Malina 50g', 50),
        ('Табак для кальяна "SL" Малина', None),
    ],
)
def test_extract_weight(raw, expected):
    assert extract_weight(raw) == expected
