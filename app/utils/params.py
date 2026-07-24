from fastapi import Request


def get_int_param(request: Request, name: str, default: int, min_value: int = 1) -> int:
    raw_value = request.query_params.get(name)

    if raw_value is None or raw_value == "":
        return default

    try:
        value = int(raw_value)
    except ValueError:
        return default

    return max(value, min_value)
