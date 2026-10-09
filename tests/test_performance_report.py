import json

from app.performance_report import summarize


def test_report_groups_requests_and_sums_import_batches():
    rows = [
        {
            "event": "http_request",
            "method": "POST",
            "route": "/import-xlsx",
            "status": status,
            "duration_ms": duration,
            "sql_count": 3,
            "sql_duration_ms": 2,
        }
        for status, duration in [(200, 10), (500, 100)]
    ] + [
        {
            "event": "import_phase",
            "request_id": "test-id",
            "phase": "save_sales",
            "outcome": outcome,
            "duration_ms": duration,
        }
        for outcome, duration in [("ok", 2), ("error", 3)]
    ]
    report = summarize(
        ["raw secret that must not appear", "INFO: {broken json}"]
        + ["web | INFO: " + json.dumps(row) for row in rows]
    )
    request = report["requests"][0]
    assert request["requests"] == 2
    assert request["avg_ms"] == 55
    assert request["p95_ms"] == 100
    assert request["errors"] == 1
    assert report["recent_imports"] == [
        {"request_id": "test-id", "phase_ms": {"save_sales": 5}, "phase_errors": 1}
    ]
    assert "secret" not in json.dumps(report)
    assert summarize([]) == {"requests": [], "recent_imports": []}


def test_report_ignores_incomplete_or_invalid_metric_records():
    rows = [
        {"event": "http_request", "duration_ms": 1, "method": "GET", "route": "/"},
        {
            "event": "import_phase",
            "duration_ms": 1,
            "request_id": "x",
            "phase": "parse_excel",
        },
        {"event": "http_request", "duration_ms": float("nan")},
        {"event": "import_phase", "duration_ms": -1},
    ]
    assert summarize(map(json.dumps, rows)) == {"requests": [], "recent_imports": []}
