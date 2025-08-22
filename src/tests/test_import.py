def test_import_engine():
    import importlib
    mod = importlib.import_module("fks_engine.main")
    assert hasattr(mod, "main")
