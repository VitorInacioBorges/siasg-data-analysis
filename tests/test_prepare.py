import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

import prepare

HEADER = ("idCompraItem,dataInclusaoPncp,codigoClasse,materialOuServicoNome,"
             "situacaoCompraItemNome,itemCategoriaNome,temResultado,codigoGrupo,"
             "quantidade,valorUnitarioEstimado,valorTotal,valorTotalResultado,"
             "nomeFornecedor,orgaoEntidadeCnpj\n")


def _row(i, dia, qtd=10.0):
    return (f"id{i},2025-01-{dia:02d}T10:00:00,7010,Material,Homologado,"
            f"Informática (TIC),True,,{qtd},100.0,1000.0,900.0,forn{i},org1\n")


@pytest.fixture
def environment(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = "".join(_row(i, 2 + (i % 20)) for i in range(60))
    (raw / "contract_items.csv").write_text(HEADER + rows, encoding="utf-8-sig")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIGURES_DIR", str(tmp_path / "fig"))
    monkeypatch.setenv("TOP_CLASSES", "5")
    return tmp_path


def test_full_run_writes_the_artefacts(environment):
    assert prepare.main([]) == 0
    assert (environment / "interim" / "itens_limpos.parquet").exists()
    assert (environment / "interim" / "quarentena.parquet").exists()
    assert (environment / "processed" / "painel.parquet").exists()
    assert (environment / "processed" / "painel_features.parquet").exists()
    assert list((environment / "fig").glob("*.png"))


def test_stops_at_a_stage(environment):
    assert prepare.main(["--ate", "clean"]) == 0
    assert (environment / "interim" / "itens_limpos.parquet").exists()
    assert not (environment / "processed" / "painel.parquet").exists()


def test_missing_csv_returns_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert prepare.main([]) == 1
    assert "src/main.py" in capsys.readouterr().out


def test_panel_sum_matches_the_kept_items(environment):
    prepare.main([])
    kept = pd.read_parquet(environment / "interim" / "itens_limpos.parquet")
    panel = pd.read_parquet(environment / "processed" / "painel.parquet")
    assert panel["valor_total"].sum() == pytest.approx(
        kept["valorTotalResultado"].sum())
