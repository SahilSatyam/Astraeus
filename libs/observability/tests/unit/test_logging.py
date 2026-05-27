import pytest
import structlog
from astraeus_config import ObservabilitySettings
from astraeus_observability import configure_logging
from astraeus_observability.context import bind_request_context, clear_request_context


@pytest.mark.unit
def test_configure_logging_idempotent() -> None:
    settings = ObservabilitySettings(log_format="json", log_level="INFO")
    configure_logging(settings, service="api")
    configure_logging(settings, service="api")  # second call is fine
    log = structlog.get_logger("astraeus.test")
    assert log is not None


@pytest.mark.unit
def test_bind_and_clear_request_context() -> None:
    bind_request_context(request_id="r1", trace_id="t1", span_id="s1")
    ctx = structlog.contextvars.get_contextvars()
    assert ctx["request_id"] == "r1"
    assert ctx["trace_id"] == "t1"
    clear_request_context()
    assert structlog.contextvars.get_contextvars() == {}
