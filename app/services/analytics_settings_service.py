from ..models import AnalyticsSettings

STATUS_DEFAULTS = {
    "new_client_months": 2,
    "lost_months": 2,
    "unstable_gap_months": 1,
}

SKU_STATUS_DEFAULTS = {f"sku_{key}": value for key, value in STATUS_DEFAULTS.items()}

DEFAULTS = {
    **STATUS_DEFAULTS,
    **SKU_STATUS_DEFAULTS,
    "status_window_months": 3,
    "client_segments_months": 6,
    "client_abc_a": 80,
    "client_abc_b": 95,
    "weight_abc_a": 80,
    "weight_abc_b": 95,
    "xyz_cv_x": 25,
    "xyz_cv_y": 50,
    "xyz_presence_y": 50,
    "xyz_presence_x": 80,
}


def get_analytics_settings(db):
    row = db.get(AnalyticsSettings, 1)
    saved = row.values if row else {}
    inherited = {f"sku_{key}": saved[key] for key in STATUS_DEFAULTS if key in saved}
    return DEFAULTS | inherited | saved


def get_sku_status_settings(db):
    settings = get_analytics_settings(db)
    return {key: settings[f"sku_{key}"] for key in STATUS_DEFAULTS}


def status_history_length(settings):
    return max(
        settings["status_window_months"],
        settings["lost_months"],
        settings["unstable_gap_months"] + 2,
    )


MATCHING_DEFAULTS = {
    "product_similarity": 70,
    "client_similarity_with_status": 90,
    "client_similarity": 95,
}


def get_matching_settings(db):
    row = db.get(AnalyticsSettings, 2)
    return MATCHING_DEFAULTS | (row.values if row else {})
