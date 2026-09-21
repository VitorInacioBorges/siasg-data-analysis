import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.load import load_raw

HEADER = ("idCompraItem,dataInclusaoPncp,codigoClasse,materialOuServicoNome,"
             "situacaoCompraItemNome,itemCategoriaNome,temResultado,codigoGrupo,"
             "quantidade,valorUnitarioEstimado,valorTotal,valorTotalResultado\n")


def _row(ident, classe="7010.0", status="Homologado", qtd="10"):
    return (f"{ident},2025-09-22T00:04:59,{classe},Material,{status},"
            f"Informática (TIC),True,,{qtd},100.0,1000.0,900.0\n")


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "raw" / "contract_items.csv"
    path.parent.mkdir(parents=True)
    path.write_text(
        HEADER
        + _row("a1")
        + _row("a1")                          # duplicata exata
        + _row("a2")
        + _row("a3", status="Fracassado")     # filtrada pelo status
        , encoding="utf-8-sig")
    return PipelineSettings(
        raw_csv=path, interim_dir=tmp_path / "interim",
        processed_dir=tmp_path / "processed", figures_dir=tmp_path / "fig",
        read_chunk_rows=2)


def test_drops_duplicate_ids(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    assert df["idCompraItem"].is_unique
    assert set(df["idCompraItem"]) == {"a1", "a2"}


def test_drops_the_three_dead_columns(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    for morta in ("itemCategoriaNome", "temResultado", "codigoGrupo"):
        assert morta not in df.columns


def test_filters_by_status(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    assert (df["situacaoCompraItemNome"] == "Homologado").all()


def test_types_and_normalisation(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    assert df["quantidade"].dtype == "float64"
    assert pd.api.types.is_datetime64_any_dtype(df["dataInclusaoPncp"])
    # o CSV traz "7010.0"; o código é identificador, não número
    assert df["codigoClasse"].iloc[0] == "7010"


def test_missing_file_gives_a_clear_message(cfg, tmp_path):
    with pytest.raises(FileNotFoundError, match="src/main.py"):
        load_raw(tmp_path / "nao-existe.csv", cfg)
