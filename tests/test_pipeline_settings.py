import os

from classes.pipeline_settings import PipelineSettings
from read_type_methods import ConfigError


def test_le_os_padroes(monkeypatch):
    for chave in ("PANEL_FREQ", "TOP_CLASSES", "QTY_MAD_THRESHOLD",
                  "MIN_CLASS_ITEMS", "STATUS_FILTER", "READ_CHUNK_ROWS"):
        monkeypatch.delenv(chave, raising=False)
    cfg = PipelineSettings.from_env()
    assert cfg.panel_freq == "W"
    assert cfg.top_classes == 50
    assert cfg.qty_mad_threshold == 8.0
    assert cfg.min_class_items == 30
    assert cfg.status_filter == "Homologado"


def test_caminhos_derivam_da_raiz_de_dados(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/tmp/dados-teste")
    cfg = PipelineSettings.from_env()
    assert cfg.raw_csv.as_posix() == "/tmp/dados-teste/raw/contract_items.csv"
    assert cfg.interim_dir.as_posix() == "/tmp/dados-teste/interim"
    assert cfg.processed_dir.as_posix() == "/tmp/dados-teste/processed"


def test_env_e_ancorado_no_modulo():
    """O .env precisa ser achado mesmo sem arquivo chamador (python -c, pytest)."""
    from classes.pipeline_settings import CAMINHO_ENV
    assert CAMINHO_ENV.name == ".env"
    assert CAMINHO_ENV.parent.name == "src"


def test_recusa_top_classes_zero(monkeypatch):
    monkeypatch.setenv("TOP_CLASSES", "0")
    try:
        PipelineSettings.from_env()
        assert False, "deveria ter levantado ConfigError"
    except ConfigError as erro:
        assert "TOP_CLASSES" in str(erro)
