import re

from rapidfuzz import fuzz, process

from .models import Product


# --------------------------
# Нормализация текста
# --------------------------
def normalize_text(s: str) -> str:
    # приводим к нижнему регистру, убираем ё
    s = s.lower().replace("ё", "е")
    # убираем содержимое в скобках
    s = re.sub(r"\(.*?\)", " ", s)
    # дефис -> пробел, чтобы "манго-лайм" == "манго лайм"
    s = s.replace("-", " ")
    # оставляем только буквы/цифры/пробелы
    s = re.sub(r"[^a-zа-я0-9\s]+", " ", s)
    # схлопываем пробелы
    return " ".join(s.split())


# --------------------------
# Парсер строки из справочника
# --------------------------
def parse_product_line(line: str):
    """
    Формат:
        "Сарма" Банановое суфле
        "САРМА 360" Легкая Азиатская Дыня
    """
    line = line.strip()
    if '"' not in line:
        return None

    # корректная регулярка: "Бренд" остальное
    m = re.match(r'"([^"]+)"\s*(.*)', line)
    if not m:
        return None

    brand = m.group(1).strip()
    rest = m.group(2).strip()

    # определяем линейку
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


# --------------------------
# Построение SKU
# --------------------------
def build_canonical_sku(category: str, brand: str, line: str | None, flavor: str) -> str:
    if line:
        return f'{category} "{brand}" {line} {flavor}'
    return f'{category} "{brand}" {flavor}'


# --------------------------
# Построение канонического имени
# --------------------------
def build_canonical_name(canonical_sku: str, weight: int | None) -> str:
    if weight:
        return f"{canonical_sku} {weight}г."
    return canonical_sku


# --------------------------
# Извлечение веса из сырой строки
# --------------------------
def extract_weight(raw: str):
    m = re.search(r"(\d+)\s*(г|гр|g)", raw.lower())
    return int(m.group(1)) if m else None


def extract_flavor_from_raw(raw: str, products: list[Product]) -> str:
    """
    Из сырой номенклатуры стараемся вытащить только аромат.
    Пример:
    'Табак для кальяна - Сарма 360 - ПЕРСИК Молоко ... - легкая линейка - 120 г'
    -> 'персик молоко'
    """
    text = raw.lower()

    # убираем скобки с описаниями
    text = re.sub(r"\(.*?\)", " ", text)

    # убираем вес
    text = re.sub(r"\d+\s*(г|гр|g)\b", " ", text)

    # убираем ключевые фразы типа продукта
    for phrase in ["табак для кальяна -", "табак для кальяна"]:
        text = text.replace(phrase, " ")

    # убираем "легкая линейка" / "крепкая линейка"
    text = re.sub(r"\b(легкая линейка|крепкая линейка)\b", " ", text)
    # часто остаются просто "легкая" / "крепкая" — тоже уберём
    text = re.sub(r"\b(легкая|крепкая)\b", " ", text)

    # убираем бренд (Сарма / САРМА 360 и т.п.)
    brands = sorted({p.brand.lower() for p in products if p.brand}, key=len, reverse=True)
    for b in brands:
        idx = text.find(b)
        if idx != -1:
            # откусываем всё до конца бренда
            text = text[idx + len(b) :]
            break

    # чистим всё, что не буквы/цифры/пробел/дефис
    text = re.sub(r"[^a-zа-я0-9\s\-]+", " ", text)

    # дефис -> пробел
    text = text.replace("-", " ")

    # схлопываем пробелы
    return " ".join(text.split())


# --------------------------
# Поиск продукта по аромату
# --------------------------


def match_product_by_flavor(raw_name: str, products: list[Product]):
    """
    1) Выделяем из сырой строки аромат.
    2) Сначала пробуем точное сравнение norm_flavor.
    3) Потом fuzzy-мэтчинг по flavor.
    """

    if not products:
        return None, 0

    flavor_query = extract_flavor_from_raw(raw_name, products)
    if not flavor_query:
        flavor_query = raw_name

    norm_query = normalize_text(flavor_query)

    # 1) точное совпадение по norm_flavor
    for p in products:
        if p.norm_flavor == norm_query:
            return p, 100

    # 2) fuzzy matching по "человеческому" flavor
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
