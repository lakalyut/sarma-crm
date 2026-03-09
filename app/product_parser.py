import re

from rapidfuzz import fuzz, process

from .models import Product


def normalize_text(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.replace("-", " ")
    s = re.sub(r"[^a-zа-я0-9\s]+", " ", s)
    return " ".join(s.split())

def parse_product_line(line: str):
    line = line.strip()
    if '"' not in line:
        return None

    m = re.match(r'"([^"]+)"\s*(.*)', line)
    if not m:
        return None

    brand = m.group(1).strip()
    rest = m.group(2).strip()

    line_name = None
    flavor = rest

    for marker in ["Легкая", "Крепкая"]:
        if rest.startswith(marker + " "):
            line_name = marker
            flavor = rest[len(marker) :].strip()
            break

    if not flavor:
        return None

    return {
        "brand": brand,
        "line": line_name,
        "flavor": flavor,
    }


def build_canonical_sku(
    category: str, brand: str, line: str | None, flavor: str
) -> str:
    if line:
        return f'{category} "{brand}" {line} {flavor}'
    return f'{category} "{brand}" {flavor}'


def build_canonical_name(canonical_sku: str, weight: int | None) -> str:
    if weight:
        return f"{canonical_sku} {weight}г."
    return canonical_sku


def extract_weight(raw: str):
    m = re.search(r"(\d+)\s*(г|гр|g)", raw.lower())
    return int(m.group(1)) if m else None


def extract_flavor_from_raw(raw: str, products: list[Product]) -> str:
    text = raw.lower()
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"\d+\s*(г|гр|g)\b", " ", text)

    for phrase in ["табак для кальяна -", "табак для кальяна"]:
        text = text.replace(phrase, " ")

    text = re.sub(r"\b(легкая линейка|крепкая линейка)\b", " ", text)
    text = re.sub(r"\b(легкая|крепкая)\b", " ", text)

    brands = sorted(
        {p.brand.lower() for p in products if p.brand}, key=len, reverse=True
    )
    for b in brands:
        idx = text.find(b)
        if idx != -1:
            text = text[idx + len(b) :]
            break

    text = re.sub(r"[^a-zа-я0-9\s\-]+", " ", text)
    text = text.replace("-", " ")

    return " ".join(text.split())


def match_product_by_flavor(raw_name: str, products: list[Product]):

    if not products:
        return None, 0

    flavor_query = extract_flavor_from_raw(raw_name, products)
    if not flavor_query:
        flavor_query = raw_name

    norm_query = normalize_text(flavor_query)

    for p in products:
        if p.norm_flavor == norm_query:
            return p, 100

    flavor_map = {p.flavor: p for p in products}

    match = process.extractOne(
        flavor_query,
        list(flavor_map.keys()),
        scorer=fuzz.WRatio,
    )

    if match is None:
        return None, 0

    best, score = match[0], match[1]

    if score < 70:
        return None, int(score)

    return flavor_map[best], int(score)
