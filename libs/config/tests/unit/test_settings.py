import pytest
from astraeus_config import (
    DatabaseSettings,
    Environment,
    ObservabilitySettings,
    RedisSettings,
    Settings,
)
from pydantic import SecretStr


@pytest.mark.unit
def test_database_dsn_uses_asyncpg() -> None:
    s = DatabaseSettings(host="db", port=5432, user="u", password=SecretStr("p"), name="astraeus")
    assert s.dsn.startswith("postgresql+asyncpg://u:p@db:5432/astraeus")


@pytest.mark.unit
def test_database_sync_dsn_uses_psycopg() -> None:
    s = DatabaseSettings(host="db", port=5432, user="u", password=SecretStr("p"), name="astraeus")
    assert s.sync_dsn.startswith("postgresql+psycopg://u:p@db:5432/astraeus")


@pytest.mark.unit
def test_redis_url_without_password() -> None:
    s = RedisSettings(host="r", port=6379, db=0)
    assert s.url == "redis://r:6379/0"


@pytest.mark.unit
def test_observability_sample_rate_bounds() -> None:
    with pytest.raises(ValueError, match="less than or equal"):
        ObservabilitySettings(sample_rate=2.0)


@pytest.mark.unit
def test_settings_default_env_local() -> None:
    s = Settings()
    assert s.env is Environment.LOCAL
    assert s.observability.log_format == "json"


@pytest.mark.unit
def test_environment_enum_values() -> None:
    assert {e.value for e in Environment} == {"local", "ci", "staging", "prod"}
