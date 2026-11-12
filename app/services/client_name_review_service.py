"""Review names in sales and visits without loading individual records."""

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from itertools import chain, combinations, groupby

from sqlalchemy import func, or_, text, update

from ..models import ClientNameAlias, ClientNameDismissal, Sale, Visit
from ..utils.dates import month_sort_key
from .client_health_service import STATUS_LABELS, build_client_health

_QUOTES = str.maketrans("", "", "\"«»„“”'’‘`")
_NAME_LIMIT = 200
_ADDRESS_SUFFIX = re.compile(r"^(.+?)\s*\(([^()]+)\)$")
_ADDRESS_MARKER = re.compile(
    r"(?:^|[\s,(])(?:ул(?:\.|\s)|улица\b|пр\.|проспект\b|пр[-‑–](?:к?т)\b|пер\.|переулок\b|шоссе\b|наб\.|набережная\b|аллея\b)"
)
_RETAIL_SUFFIX = re.compile(r"\s*\(розничный клиент\)$")
_ADDRESS_VARIANT = "Название с адресом и без адреса"
_RETAIL_VARIANT = "Различаются пометкой «розничный клиент»"
_KARAOKE_VARIANT = "Разное написание названия и добавлен адрес"
_MANUAL_REASONS = {_ADDRESS_VARIANT, _RETAIL_VARIANT, _KARAOKE_VARIANT}
_PAYMENT_SUFFIX = re.compile(r"\s*[-–—]?\s*\((?:н|нал)\)$")
_CLIENT_NOTE_SUFFIX = re.compile(r"\s*\(к\*\)$")
_INLINE_ADDRESS = re.compile(
    r"(?P<name>.+?)[,;]\s*(?:ул\.?\s+|улица\s+)?"
    r"(?P<street>[^\W\d_][^\d,;()]*?)\s*[, ]\s*(?:д\.?\s*)?"
    r"(?P<house>\d+\s*[а-яёa-z]?)"
    r"(?:[ ,]+(?:корп(?:ус)?\.?|к\.?)\s*(?P<building>\d+[а-яёa-z]?))?"
)


def clean_spacing(name):
    return " ".join(name.split())


def comparison_name(name):
    return clean_spacing(
        unicodedata.normalize("NFC", name).translate(_QUOTES)
    ).casefold()


def _address_base(key, city):
    match = _ADDRESS_SUFFIX.fullmatch(key)
    if match:
        base, address = match.groups()
        if _ADDRESS_MARKER.search(address) or (
            address.startswith(city + ",") and re.search(r"\d", address)
        ):
            return base
    return None


def _karaoke_key(name):
    name = re.sub(r"['’`]s\b", "", name.casefold())
    return re.sub(r"\bкараоке\b", "karaoke", comparison_name(name))


def _inline_address_key(key):
    match = _INLINE_ADDRESS.fullmatch(key)
    if not match:
        return None
    name = re.sub(r"\s*([()])\s*", r"\1", match["name"]).strip()
    return (
        name,
        match["street"].strip(),
        match["house"].replace(" ", ""),
        match["building"],
    )


def _without_client_note(key):
    base = _CLIENT_NOTE_SUFFIX.sub("", key)
    if _ADDRESS_MARKER.search(base) and re.search(r"\d+[а-яёa-z]?\)?$", base):
        return base
    return key


def lock_client_names(db, city):
    """Keep imports and name changes for the same city in transaction order."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"pulse:client-names:{city}"},
        )


def get_client_aliases(db, city):
    return dict(
        db.query(ClientNameAlias.source_name, ClientNameAlias.canonical_name)
        .filter(ClientNameAlias.city == city)
        .all()
    )


def _missing_sale_type():
    normalized = Sale.type
    for whitespace in ("\t", "\r", "\n", "\u00a0", "\u202f", "\u200b", "\ufeff"):
        normalized = func.replace(normalized, whitespace, " ")
    return or_(Sale.type.is_(None), func.lower(func.trim(normalized)).in_(("", "nan")))


def _named_client():
    return func.lower(func.trim(Sale.client)).notin_(("", "nan"))


def get_review_cities(db):
    cities = {
        city
        for (city,) in db.query(Sale.city)
        .filter(_named_client(), _missing_sale_type())
        .distinct()
        if city and city.strip()
    }
    dismissed = defaultdict(set)
    for city, first, second in db.query(
        ClientNameDismissal.city,
        ClientNameDismissal.first_name,
        ClientNameDismissal.second_name,
    ):
        dismissed[city].add((first, second))
    names = (
        db.query(Sale.city, Sale.client)
        .filter(Sale.city.isnot(None), _named_client(), Sale.city.notin_(cities))
        .union(db.query(Visit.city, Visit.client).filter(Visit.city.notin_(cities)))
        .order_by(Sale.city)
        .yield_per(1000)
    )
    for city, rows in groupby(names, key=lambda row: row[0]):
        clients = {
            name
            for _, name in rows
            if name.strip() and name.strip().casefold() != "nan"
        }
        if city.strip() and next(
            iter_name_matches(
                clients,
                dismissed[city],
                city,
                lambda city=city: _review_statuses(db, city),
            ),
            None,
        ):
            cities.add(city)
    return sorted(cities)


def get_client_type_gaps(db, city):
    missing = (
        db.query(Sale.client, func.count(Sale.id))
        .filter(
            Sale.city == city,
            _named_client(),
            _missing_sale_type(),
        )
        .group_by(Sale.client)
        .order_by(Sale.client)
        .all()
    )
    if not missing:
        return []

    known_types = defaultdict(set)
    for client, point_type in (
        db.query(Sale.client, Sale.type)
        .filter(Sale.city == city, ~_missing_sale_type())
        .distinct()
    ):
        known_types[client].add(point_type)
    return [
        {
            "name": client,
            "count": count,
            "suggested_type": (
                next(iter(known_types[client]))
                if len(known_types[client]) == 1
                else None
            ),
        }
        for client, count in missing
    ]


def get_review_point_types(db, city):
    return [
        point_type
        for (point_type,) in db.query(Sale.type)
        .filter(Sale.city == city, ~_missing_sale_type())
        .distinct()
        .order_by(Sale.type)
    ]


def assign_missing_client_type(db, city, client, point_type):
    lock_client_names(db, city)
    if not city or point_type not in get_review_point_types(db, city):
        raise ValueError("Выберите тип точки из списка этого города.")
    if not client.strip() or client.strip().casefold() == "nan":
        raise ValueError("Выберите клиента с указанным названием.")
    result = db.execute(
        update(Sale)
        .where(Sale.city == city, Sale.client == client, _missing_sale_type())
        .values(type=point_type)
    )
    db.commit()
    return result.rowcount


def resolve_client_name(db, city, name):
    alias = db.get(ClientNameAlias, (city, name))
    return alias.canonical_name if alias else name


def _pair(first, second):
    return tuple(sorted((first, second)))


def _dismissed_pairs(db, city):
    return set(
        db.query(ClientNameDismissal.first_name, ClientNameDismissal.second_name)
        .filter(ClientNameDismissal.city == city)
        .all()
    )


def _names_in_city(db, city):
    names = {}
    for model, count_key, type_column in (
        (Sale, "sales", Sale.type),
        (Visit, "visits", Visit.sale_type),
    ):
        columns = [model.client, type_column, func.count(model.id)]
        grouping = [model.client, type_column]
        if model is Sale:
            columns += [Sale.month, func.sum(Sale.weight)]
            grouping.append(Sale.month)
        for name, point_type, count, *sale in (
            db.query(*columns)
            .filter(model.city == city, model.client.isnot(None))
            .group_by(*grouping)
        ):
            if not name.strip() or name.strip().casefold() == "nan":
                continue
            item = names.setdefault(
                name,
                dict(name=name, sales=0, visits=0, types=set(), months=set(), volume=0),
            )
            item[count_key] += count
            if point_type:
                item["types"].add(point_type)
            if sale:
                month, volume = sale
                if month:
                    item["months"].add(month)
                item["volume"] += volume or 0
    return names


def get_manual_review_clients(db, city):
    return sorted(
        _names_in_city(db, city).values(), key=lambda row: row["name"].casefold()
    )


def _nearby_keys(keys):
    """Generate candidates for one edit, adjacent swap or a missing space."""
    index = defaultdict(list)
    for key in sorted(keys):
        if not 6 <= len(key) <= _NAME_LIMIT:
            continue
        digits = tuple(re.findall(r"\d+", key))
        compact = key.replace(" ", "")
        signatures = {("edit", key), ("space", compact)}
        signatures.update(("edit", key[:i] + key[i + 1 :]) for i in range(len(key)))
        matches = set()
        for signature in signatures:
            bucket = index[digits, signature]
            matches.update(bucket)
            bucket.append(key)
        for other in sorted(matches):
            if compact == other.replace(" ", "") or _one_edit(key, other):
                yield key, other


def _high_similarity_keys(keys):
    """Index shared fragments before comparing the full normalized names."""
    index = defaultdict(list)
    for key in sorted(keys, key=lambda value: (len(value), value)):
        size = len(key)
        if not 12 <= size <= _NAME_LIMIT:
            continue
        digits = tuple(re.findall(r"\d+", key))
        fragments = {key[i : i + 4] for i in range(size - 3)}
        candidates = set()
        for fragment in fragments:
            for length in range((size * 9 + 10) // 11, size + 1):
                candidates.update(index.get((digits, length, fragment), ()))
            index[digits, size, fragment].append(key)
        for other in sorted(candidates):
            matcher = SequenceMatcher(None, key, other, autojunk=False)
            if matcher.quick_ratio() >= 0.90 and (score := matcher.ratio()) >= 0.90:
                yield key, other, score


def _review_statuses(db, city):
    months = [
        month
        for (month,) in db.query(Sale.month).filter(Sale.city == city).distinct()
        if month
    ]
    recent = sorted(months, key=month_sort_key)[-3:]
    if len(recent) < 3:
        return {}
    statuses = defaultdict(set)
    for row in build_client_health(db, city, recent)["rows"]:
        statuses[row["client"]].add(row["status"])
    return statuses


def _one_edit(first, second):
    if abs(len(first) - len(second)) > 1:
        return False
    if len(first) == len(second):
        differences = [
            i for i, (a, b) in enumerate(zip(first, second, strict=True)) if a != b
        ]
        if len(differences) == 1:
            return True
        if len(differences) != 2:
            return False
        i, j = differences
        return j == i + 1 and first[i] == second[j] and first[j] == second[i]
    shorter, longer = sorted((first, second), key=len)
    i = next(
        (i for i, (a, b) in enumerate(zip(shorter, longer, strict=False)) if a != b),
        len(shorter),
    )
    return shorter[i:] == longer[i + 1 :]


def iter_name_matches(names, dismissed, city, load_statuses):
    by_key = defaultdict(list)
    for name in sorted(names):
        by_key[comparison_name(name)].append(name)
    for variants in by_key.values():
        covered = set()
        for i, first in enumerate(variants[:-1]):
            group = [first]
            for other in variants[i + 1 :]:
                if all(_pair(other, name) not in dismissed for name in group):
                    group.append(other)
            pairs = set(combinations(group, 2))
            if pairs - covered:
                if len({clean_spacing(name).casefold() for name in group}) > 1:
                    reason = "Различаются кавычками или оформлением"
                elif len({name.casefold() for name in group}) > 1:
                    reason = "Различаются пробелами"
                    if len({clean_spacing(name) for name in group}) > 1:
                        reason = "Различаются регистром и пробелами"
                else:
                    reason = "Различаются регистром"
                yield group, reason
                covered.update(pairs)
    address_pairs = set()
    city_key = comparison_name(city)
    karaoke_by_base = defaultdict(list)
    for name in sorted(names):
        key = _karaoke_key(name)
        if re.search(r"\bkaraoke\b", key) and not _address_base(key, city_key):
            karaoke_by_base[key].append(name)
    for key, variants in by_key.items():
        base = _address_base(key, city_key)
        for short_name in by_key.get(base, ()):
            for full_name in variants:
                pair = _pair(short_name, full_name)
                if pair not in dismissed:
                    yield pair, _ADDRESS_VARIANT
                    address_pairs.add(pair)
        retail_base = _RETAIL_SUFFIX.sub("", key)
        for short_name in by_key.get(retail_base, ()) if retail_base != key else ():
            for full_name in variants:
                pair = _pair(short_name, full_name)
                if pair not in dismissed:
                    yield pair, _RETAIL_VARIANT
                    address_pairs.add(pair)
        if base:
            for full_name in variants:
                karaoke_base = _address_base(_karaoke_key(full_name), city_key)
                for short_name in karaoke_by_base.get(karaoke_base, ()):
                    pair = _pair(short_name, full_name)
                    if pair not in dismissed and pair not in address_pairs:
                        yield pair, _KARAOKE_VARIANT
                        address_pairs.add(pair)

    names_by_payment_base = defaultdict(list)
    for key, variants in by_key.items():
        base = _PAYMENT_SUFFIX.sub("", key).strip()
        if _ADDRESS_MARKER.search(base) and re.search(r"\d", base):
            names_by_payment_base[base].extend(variants)
    for variants in names_by_payment_base.values():
        for first, second in combinations(variants, 2):
            pair = _pair(first, second)
            if (
                comparison_name(first) != comparison_name(second)
                and pair not in dismissed
                and pair not in address_pairs
            ):
                yield pair, "Различаются пометками (Н) / (НАЛ)"
                address_pairs.add(pair)

    notes_by_base = defaultdict(list)
    for key, variants in by_key.items():
        notes_by_base[_without_client_note(key)].extend(variants)
    for variants in notes_by_base.values():
        for first, second in combinations(variants, 2):
            pair = _pair(first, second)
            if (
                comparison_name(first) != comparison_name(second)
                and pair not in dismissed
                and pair not in address_pairs
            ):
                yield pair, "Различаются пометкой (К*)"
                address_pairs.add(pair)

    inline_addresses = {}
    keys_by_address = defaultdict(list)
    for key in by_key:
        if address := _inline_address_key(key):
            inline_addresses[key] = address
            keys_by_address[address].append(key)
    for keys in keys_by_address.values():
        for first, second in combinations(keys, 2):
            for left in by_key[first]:
                for right in by_key[second]:
                    pair = _pair(left, right)
                    if pair not in dismissed and pair not in address_pairs:
                        yield pair, "Один адрес записан по-разному"
                        address_pairs.add(pair)

    nearby = ((first, second, None) for first, second in _nearby_keys(by_key))
    compared = set()
    statuses = None
    for first, second, score in chain(_high_similarity_keys(by_key), nearby):
        key_pair = _pair(first, second)
        if key_pair in compared and score is None:
            continue
        if score is not None and score >= 0.95:
            compared.add(key_pair)
        first_address = inline_addresses.get(first)
        second_address = inline_addresses.get(second)
        if (
            first_address
            and second_address
            and first_address[0] == second_address[0]
            and first_address != second_address
        ):
            continue
        for left in by_key[first]:
            for right in by_key[second]:
                pair = _pair(left, right)
                if pair not in dismissed and pair not in address_pairs:
                    similarity = (
                        f"{score:.1%}".replace(".", ",") if score is not None else ""
                    )
                    if score is not None and score < 0.95:
                        if statuses is None:
                            statuses = load_statuses()
                        left_status = statuses.get(left, ())
                        right_status = statuses.get(right, ())
                        previous = next(
                            (
                                status
                                for status in ("lost", "unstable")
                                if ("new" in left_status and status in right_status)
                                or ("new" in right_status and status in left_status)
                            ),
                            None,
                        )
                        if previous is None:
                            continue
                        reason = (
                            f"Сходство {similarity} · Новый и {STATUS_LABELS[previous]}"
                        )
                        address_pairs.add(pair)
                    else:
                        reason = (
                            f"Сходство названий {similarity}"
                            if similarity
                            else "Похожие названия"
                        )
                    yield [left, right], reason


def get_review_groups(db, city):
    names = _names_in_city(db, city)
    groups = []
    for variants, reason in iter_name_matches(
        names, _dismissed_pairs(db, city), city, lambda: _review_statuses(db, city)
    ):
        rows = sorted(
            (names[name] for name in variants),
            key=lambda row: (-row["sales"], -row["visits"], row["name"]),
        )
        groups.append(
            {
                "reason": reason,
                "rows": rows,
                "canonical": clean_spacing(rows[0]["name"]),
            }
        )
    for item in names.values():
        item["types"] = sorted(item["types"])
        item["months"] = sorted(item["months"], key=month_sort_key)
    return groups


def _count_names(db, model, city, names):
    return (
        db.query(model.client, func.count(model.id))
        .filter(model.city == city, model.client.in_(names))
        .group_by(model.client)
        .all()
    )


def preview_merge(db, city, variants, canonical):
    canonical = clean_spacing(canonical)
    variants = sorted(set(variants))
    if (
        not city
        or len(variants) < 2
        or not canonical
        or len(canonical) > _NAME_LIMIT
        or any(ord(char) < 32 for char in canonical)
    ):
        raise ValueError("Выберите минимум два варианта и укажите итоговое название.")
    sales = dict(_count_names(db, Sale, city, [*variants, canonical]))
    visits = dict(_count_names(db, Visit, city, [*variants, canonical]))
    present = sales.keys() | visits.keys()
    if not set(variants) <= present:
        raise ValueError("Названия уже изменились. Обновите список и повторите выбор.")
    if canonical not in variants and canonical in present:
        raise ValueError(
            "Итоговое название уже используется. Включите его в объединение."
        )
    aliases = get_client_aliases(db, city)
    if canonical in aliases:
        raise ValueError(
            "Это название уже связано с другим клиентом. Укажите актуальное название."
        )
    if any(aliases[name] not in present for name in variants if name in aliases):
        raise ValueError("Один из вариантов уже связан с другим клиентом.")
    if _dismissed_pairs(db, city).intersection(combinations(variants, 2)):
        raise ValueError("Некоторые варианты уже отмечены как разные клиенты.")
    sources = [name for name in variants if name != canonical]
    return {
        "canonical": canonical,
        "variants": variants,
        "sources": sources,
        "sales": sum(sales.get(name, 0) for name in sources),
        "visits": sum(visits.get(name, 0) for name in sources),
    }


def merge_names(db, city, variants, canonical, *, expected_counts):
    lock_client_names(db, city)
    plan = preview_merge(db, city, variants, canonical)
    if (plan["sales"], plan["visits"]) != expected_counts:
        raise ValueError("Число строк изменилось. Проверьте обновлённый список.")
    _apply_merge(db, city, plan["sources"], plan["canonical"])
    db.commit()
    return plan


def _apply_merge(db, city, sources, canonical):
    aliases = (
        db.query(ClientNameAlias)
        .filter(
            ClientNameAlias.city == city,
            ClientNameAlias.source_name.in_(sources)
            | ClientNameAlias.canonical_name.in_(sources),
        )
        .all()
    )
    existing = {alias.source_name for alias in aliases}
    for alias in aliases:
        alias.canonical_name = canonical
    db.add_all(
        ClientNameAlias(city=city, source_name=name, canonical_name=canonical)
        for name in sources
        if name not in existing
    )
    _carry_dismissals(db, city, sources, canonical)
    for model in (Sale, Visit):
        db.execute(
            update(model)
            .where(model.city == city, model.client.in_(sources))
            .values(client=canonical)
        )


def preview_bulk_merge(db, city):
    groups = []
    for group in get_review_groups(db, city) if city else []:
        rows = group["rows"]
        preferred = min(
            rows,
            key=lambda row: (
                _without_client_note(comparison_name(row["name"]))
                != comparison_name(row["name"]),
                -row["sales"],
                -row["visits"],
                row["name"] != clean_spacing(row["name"]),
                row["name"],
            ),
        )
        canonical = clean_spacing(preferred["name"])
        sources = [row for row in rows if row["name"] != canonical]
        groups.append(
            {
                "reason": group["reason"],
                "manual_selection": group["reason"] in _MANUAL_REASONS
                or " · Новый и " in group["reason"],
                "canonical": canonical,
                "variants": sorted(row["name"] for row in rows),
                "sources": [row["name"] for row in sources],
                "sales": sum(row["sales"] for row in sources),
                "visits": sum(row["visits"] for row in sources),
            }
        )
    snapshot = json.dumps([city, groups], ensure_ascii=False, sort_keys=True)
    return groups, hashlib.sha256(snapshot.encode()).hexdigest()


def merge_selected_names(db, city, expected_snapshot, selected_indices):
    lock_client_names(db, city)
    groups, snapshot = preview_bulk_merge(db, city)
    if snapshot != expected_snapshot:
        raise ValueError(
            "Список совпадений изменился. Проверьте обновлённый предпросмотр."
        )
    if not selected_indices:
        raise ValueError("Отметьте хотя бы одну группу.")
    indices = set(selected_indices)
    if min(indices) < 0 or max(indices) >= len(groups):
        raise ValueError("Выберите группы из текущего предпросмотра.")

    selected = []
    used_names = set()
    excluded = [
        set(group["variants"]) for i, group in enumerate(groups) if i not in indices
    ]
    for i in sorted(indices):
        group = groups[i]
        variants = set(group["variants"]) | {group["canonical"]}
        if used_names.intersection(variants):
            raise ValueError(
                f"«{group['canonical']}» пересекается с другой выбранной группой. "
                "Оставьте одну из пересекающихся групп и повторите сохранение."
            )
        if any(names <= variants for names in excluded):
            raise ValueError(
                f"«{group['canonical']}» включает названия из исключённой группы. "
                "Снимите отметку и с этой группы."
            )
        used_names.update(variants)
        selected.append(preview_merge(db, city, group["variants"], group["canonical"]))

    for group in selected:
        _apply_merge(db, city, group["sources"], group["canonical"])
        db.flush()
    db.commit()
    return selected


def _carry_dismissals(db, city, sources, canonical):
    existing = _dismissed_pairs(db, city)
    source_names = set(sources)
    updated = {
        _pair(
            canonical if first in source_names else first,
            canonical if second in source_names else second,
        )
        for first, second in existing
        if first in source_names or second in source_names
    }
    db.add_all(
        ClientNameDismissal(city=city, first_name=first, second_name=second)
        for first, second in updated - existing
        if first != second
    )


def dismiss_names(db, city, variants):
    lock_client_names(db, city)
    variants = sorted(set(variants))
    if not city or len(variants) < 2:
        raise ValueError("Выберите минимум два разных названия.")
    present = (
        dict(_count_names(db, Sale, city, variants)).keys()
        | dict(_count_names(db, Visit, city, variants)).keys()
    )
    if not set(variants) <= present:
        raise ValueError("Названия уже изменились. Обновите список и повторите выбор.")
    dismissed = _dismissed_pairs(db, city)
    db.add_all(
        ClientNameDismissal(city=city, first_name=first, second_name=second)
        for first, second in combinations(variants, 2)
        if (first, second) not in dismissed
    )
    db.commit()
