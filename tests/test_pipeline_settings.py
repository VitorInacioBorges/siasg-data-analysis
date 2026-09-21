from classes.pipeline_settings import PipelineSettings
from read_type_methods import ConfigError


def test_reads_the_defaults(monkeypatch):
    for key in ("PANEL_FREQ", "TOP_CLASSES", "STATUS_FILTER",
                  "READ_CHUNK_ROWS", "VALUE_CEILING"):
        monkeypatch.delenv(key, raising=False)
    cfg = PipelineSettings.from_env()
    assert cfg.panel_freq == "W"
    assert cfg.top_classes == 50
    assert cfg.status_filter == "Homologado"
    assert cfg.value_ceiling == 10_000_000_000.0


def test_paths_derive_from_the_data_root(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/tmp/dados-teste")
    cfg = PipelineSettings.from_env()
    assert cfg.raw_csv.as_posix() == "/tmp/dados-teste/raw/contract_items.csv"
    assert cfg.interim_dir.as_posix() == "/tmp/dados-teste/interim"
    assert cfg.processed_dir.as_posix() == "/tmp/dados-teste/processed"


def test_env_path_is_passed_to_load_dotenv(monkeypatch):
    """Guards the behaviour, not the constant.

    Asserting only that ENV_PATH points at src/.env would still pass if someone
    kept the constant and reverted the call to a bare load_dotenv() — which is
    the very defect this task closes. So the test checks that load_dotenv is
    called WITH the anchored path.
    """
    import importlib

    import dotenv

    calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: calls.append((a, k)))

    import classes.pipeline_settings as module
    # reload re-executes `from dotenv import load_dotenv`, so the module binds
    # the patched function instead of the one captured at first import.
    importlib.reload(module)

    assert calls, "load_dotenv não foi chamado"
    assert calls[0][0], "load_dotenv foi chamado sem argumento — o .env seria ignorado"
    assert calls[0][0][0] == module.ENV_PATH
    assert module.ENV_PATH.name == ".env"
    assert module.ENV_PATH.parent.name == "src"


def test_rejects_top_classes_zero(monkeypatch):
    monkeypatch.setenv("TOP_CLASSES", "0")
    try:
        PipelineSettings.from_env()
        assert False, "deveria ter levantado ConfigError"
    except ConfigError as error:
        assert "TOP_CLASSES" in str(error)
