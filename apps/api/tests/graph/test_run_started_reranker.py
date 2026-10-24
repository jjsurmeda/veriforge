"""KI-22: run.started carries the run's reranker id so a live run can show it."""

from decisions.thresholds import active_reranker_id
from runtime import RuntimeSettings, reset_runtime_settings, set_runtime_settings
from schemas.events import RunStarted


def test_run_started_serialises_the_reranker() -> None:
    token = set_runtime_settings(RuntimeSettings.from_data(1, {"retrieval": {"reranker": "llm"}}))
    try:
        event = RunStarted(reranker=active_reranker_id())
    finally:
        reset_runtime_settings(token)
    assert event.model_dump(mode="json")["reranker"] == "llm"
    assert RunStarted().reranker is None
