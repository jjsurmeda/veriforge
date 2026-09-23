from decisions.thresholds import threshold
from runtime import (
    RuntimeSettings,
    reset_runtime_settings,
    runtime_value,
    set_runtime_settings,
)


def test_runtime_settings_merge_defaults_and_nested_overrides() -> None:
    settings = RuntimeSettings.from_data(1, {"retrieval": {"top_k": 3}})

    assert settings.get("retrieval.top_k") == 3
    assert settings.get("retrieval.rrf_k") == 60
    assert settings.get("quota_estimates.deep") == 30_000


def test_runtime_settings_context_is_scoped() -> None:
    token = set_runtime_settings(RuntimeSettings.from_data(7, {"trace_sample_rate": 0.25}))
    try:
        assert runtime_value("trace_sample_rate", 1.0) == 0.25
    finally:
        reset_runtime_settings(token)

    assert runtime_value("trace_sample_rate", 1.0) == 1.0


def test_runtime_settings_override_reaches_decision_thresholds() -> None:
    token = set_runtime_settings(
        RuntimeSettings.from_data(8, {"thresholds": {"sufficient_retry": {"jev": 0.42}}})
    )
    try:
        assert threshold("sufficient_retry", "jev") == 0.42
    finally:
        reset_runtime_settings(token)
