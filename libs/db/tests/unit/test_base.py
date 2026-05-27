import pytest
from astraeus_db.base import Base, SystemHealth


@pytest.mark.unit
def test_system_health_registered_in_metadata() -> None:
    assert "system_health" in Base.metadata.tables


@pytest.mark.unit
def test_system_health_columns() -> None:
    table = Base.metadata.tables["system_health"]
    cols = {c.name for c in table.columns}
    assert cols == {"id", "component", "checked_at"}


@pytest.mark.unit
def test_system_health_component_unique() -> None:
    table = Base.metadata.tables["system_health"]
    assert table.columns["component"].unique
    # SystemHealth class also exposes the same name.
    assert SystemHealth.__tablename__ == "system_health"
