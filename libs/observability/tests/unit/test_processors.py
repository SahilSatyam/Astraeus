import pytest
from astraeus_observability.processors import Redactor


@pytest.mark.unit
def test_redactor_scrubs_password() -> None:
    r = Redactor()
    out = r(None, "msg", {"password": "hunter2", "user": "sahil"})
    assert out["password"] == "***REDACTED***"
    assert out["user"] == "sahil"


@pytest.mark.unit
def test_redactor_case_insensitive() -> None:
    r = Redactor()
    out = r(None, "msg", {"API_KEY": "abc", "Token": "xyz"})
    assert out["API_KEY"] == "***REDACTED***"
    assert out["Token"] == "***REDACTED***"


@pytest.mark.unit
def test_redactor_recurses_into_nested_dicts() -> None:
    r = Redactor()
    out = r(
        None,
        "msg",
        {"db": {"password": "p", "host": "h"}, "list": [{"secret": "s"}, "ok"]},
    )
    assert out["db"]["password"] == "***REDACTED***"
    assert out["db"]["host"] == "h"
    assert out["list"][0]["secret"] == "***REDACTED***"
    assert out["list"][1] == "ok"


@pytest.mark.unit
def test_redactor_leaves_innocuous_keys_alone() -> None:
    r = Redactor()
    out = r(None, "msg", {"event": "user_logged_in", "user_id": 42})
    assert out == {"event": "user_logged_in", "user_id": 42}


@pytest.mark.unit
def test_redactor_custom_key_set() -> None:
    r = Redactor(keys=frozenset({"ssn"}))
    out = r(None, "msg", {"ssn": "111", "password": "kept"})
    assert out["ssn"] == "***REDACTED***"
    # password is no longer in the configured set
    assert out["password"] == "kept"
