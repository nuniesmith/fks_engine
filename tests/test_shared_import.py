def test_shared_import():
    try:
        from fks_shared_python import get_risk_threshold  # type: ignore
    except Exception:  # pragma: no cover
        from shared_python import get_risk_threshold  # type: ignore
    assert callable(get_risk_threshold)
