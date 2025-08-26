def test_shared_import():
    from shared_python import get_risk_threshold  # type: ignore
    assert callable(get_risk_threshold)
