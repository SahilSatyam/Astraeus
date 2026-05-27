import pytest
from astraeus_workers import __doc__ as workers_doc
from astraeus_workers import main as main_mod


@pytest.mark.unit
def test_workers_module_loads() -> None:
    assert workers_doc is not None
    assert "Phase 0" in workers_doc


@pytest.mark.unit
def test_main_is_importable() -> None:
    assert callable(main_mod.main)
