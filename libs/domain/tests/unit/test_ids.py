from astraeus_domain.ids import AccountId, OrderId, Symbol


def test_typed_ids_are_strings_at_runtime() -> None:
    sym = Symbol("AAPL")
    assert sym == "AAPL"
    assert isinstance(sym, str)


def test_typed_ids_are_distinct_to_type_checker() -> None:
    # At runtime NewType is identity; this test mainly documents intent.
    # mypy --strict catches mixing AccountId where OrderId is expected
    # (string-equality check is fine at runtime even though the types differ).
    acct: str = AccountId("acct_1")
    order: str = OrderId("ord_1")
    assert acct != order
