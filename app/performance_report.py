"""Summarize safe metric records piped from Docker logs; never print raw logs."""

import json
import math
import sys
from collections import defaultdict


def summarize(lines):
    groups = defaultdict(list)
    imports = defaultdict(list)
    for line in lines:
        start = line.find('{"event":')
        if start < 0:
            continue
        try:
            record = json.loads(line[start:])
            duration = float(record["duration_ms"])
            if not math.isfinite(duration) or duration < 0:
                continue
            if record["event"] == "http_request":
                if not isinstance(record["method"], str) or not isinstance(
                    record["route"], str
                ):
                    continue
                int(record["status"])
                sql_count = float(record["sql_count"])
                sql_ms = float(record["sql_duration_ms"])
                if not all(
                    math.isfinite(value) and value >= 0 for value in (sql_count, sql_ms)
                ):
                    continue
                key = (record["method"], record["route"])
                groups[key].append(record)
            elif record["event"] == "import_phase":
                if not isinstance(record["request_id"], str) or not isinstance(
                    record["phase"], str
                ):
                    continue
                if record["outcome"] not in ("ok", "error"):
                    continue
                imports[record["request_id"]].append(record)
        except (ValueError, KeyError, TypeError):
            continue
    requests = []
    for (method, route), rows in sorted(groups.items()):
        durations = sorted(float(row["duration_ms"]) for row in rows)
        requests.append(
            {
                "method": method,
                "route": route,
                "requests": len(rows),
                "avg_ms": round(sum(durations) / len(rows), 2),
                "p95_ms": durations[math.ceil(len(rows) * 0.95) - 1],
                "max_ms": durations[-1],
                "errors": sum(int(row["status"]) >= 500 for row in rows),
                "avg_sql_count": round(
                    sum(float(row["sql_count"]) for row in rows) / len(rows), 2
                ),
                "avg_sql_ms": round(
                    sum(float(row["sql_duration_ms"]) for row in rows) / len(rows), 2
                ),
            }
        )
    import_runs = []
    for request_id, phases in list(imports.items())[-20:]:
        totals = defaultdict(float)
        for phase in phases:
            totals[phase["phase"]] += float(phase["duration_ms"])
        import_runs.append(
            {
                "request_id": request_id,
                "phase_ms": {name: round(value, 2) for name, value in totals.items()},
                "phase_errors": sum(row["outcome"] == "error" for row in phases),
            }
        )
    return {"requests": requests, "recent_imports": import_runs}


if __name__ == "__main__":
    print(json.dumps(summarize(sys.stdin), ensure_ascii=False, indent=2))
