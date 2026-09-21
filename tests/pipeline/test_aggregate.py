import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.aggregate import BUCKET_OTHER, BUCKET_NO_CLASS, to_panel


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path,
        panel_freq="W", top_classes=2)


def _items(rows):
    df = pd.DataFrame(rows, columns=[
        "dataInclusaoPncp", "codigoClasse", "materialOuServicoNome",
        "quantidade", "valorUnitarioEstimado", "valorTotal",
        "valorTotalResultado", "nomeFornecedor", "orgaoEntidadeCnpj"])
    df["dataInclusaoPncp"] = pd.to_datetime(df["dataInclusaoPncp"])
    return df


def test_sum_is_preserved(cfg):
    itens = _items([
        ("2025-01-02", "A", "Material", 2.0, 50.0, 100.0, 90.0, "f1", "o1"),
        ("2025-01-03", "A", "Material", 4.0, 50.0, 200.0, 180.0, "f2", "o1"),
    ])
    panel = to_panel(itens, cfg)
    assert panel["valor_total"].sum() == pytest.approx(270.0)
    assert panel["n_itens"].sum() == 2


def test_panel_is_a_full_rectangle(cfg):
    """Uma classe compra na semana 1, a outra na semana 3. O painel tem as duas
    em todas as três semanas, com zero onde não houve compra."""
    itens = _items([
        ("2025-01-02", "A", "Material", 1.0, 10.0, 10.0, 10.0, "f1", "o1"),
        ("2025-01-16", "B", "Serviço", 1.0, 20.0, 20.0, 20.0, "f2", "o2"),
    ])
    panel = to_panel(itens, cfg)
    n_weeks = panel["semana"].nunique()
    n_combos = panel[["materialOuServicoNome", "classe"]].drop_duplicates().shape[0]
    assert len(panel) == n_weeks * n_combos
    assert n_weeks == 3
    assert (panel["valor_total"] == 0).sum() == len(panel) - 2


def test_reduces_to_top_classes(cfg):
    """top_classes=2: as duas maiores por valor ficam, o resto vira "Outras"."""
    itens = _items([
        ("2025-01-02", "A", "Material", 1.0, 1.0, 1.0, 1000.0, "f", "o"),
        ("2025-01-02", "B", "Material", 1.0, 1.0, 1.0, 500.0, "f", "o"),
        ("2025-01-02", "C", "Material", 1.0, 1.0, 1.0, 10.0, "f", "o"),
        ("2025-01-02", "D", "Material", 1.0, 1.0, 1.0, 5.0, "f", "o"),
    ])
    panel = to_panel(itens, cfg)
    classes = set(panel["classe"])
    assert {"A", "B", BUCKET_OTHER} <= classes
    assert "C" not in classes and "D" not in classes


def test_missing_class_gets_its_own_bucket(cfg):
    itens = _items([
        ("2025-01-02", None, "Serviço", 1.0, 100.0, 100.0, 100.0, "f", "o"),
    ])
    panel = to_panel(itens, cfg)
    assert BUCKET_NO_CLASS in set(panel["classe"])


def test_material_and_service_stay_in_the_key(cfg):
    """Os baldes misturam M e S, então a divisão só é recuperável com a coluna
    na chave de agrupamento."""
    itens = _items([
        ("2025-01-02", None, "Material", 1.0, 1.0, 1.0, 10.0, "f", "o"),
        ("2025-01-02", None, "Serviço", 1.0, 1.0, 1.0, 20.0, "f", "o"),
    ])
    panel = to_panel(itens, cfg)
    no_class = panel[panel["classe"] == BUCKET_NO_CLASS]
    assert set(no_class["materialOuServicoNome"]) == {"Material", "Serviço"}


def test_discount_rate(cfg):
    itens = _items([
        ("2025-01-02", "A", "Material", 1.0, 100.0, 100.0, 80.0, "f", "o"),
    ])
    panel = to_panel(itens, cfg)
    linha = panel[panel["valor_total"] > 0].iloc[0]
    assert linha["taxa_desconto"] == pytest.approx(0.8)
