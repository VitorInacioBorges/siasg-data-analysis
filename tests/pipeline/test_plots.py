import matplotlib
matplotlib.use("Agg")           # sem display, antes de qualquer import de pyplot

import pandas as pd
import pytest

from pipeline.plots import make_figures


@pytest.fixture
def data():
    weeks = pd.period_range("2025-01-06", periods=6, freq="W")
    itens = pd.DataFrame({
        "dataInclusaoPncp": pd.to_datetime(
            ["2025-01-08", "2025-01-15", "2025-01-22"] * 2),
        "valorTotalResultado": [100.0, 200.0, 300.0, 1e10, 150.0, 250.0],
        "materialOuServicoNome": ["Material", "Serviço"] * 3,
    })
    kept_items = itens.drop(index=3)
    panel = pd.DataFrame([
        {"semana": s, "materialOuServicoNome": m, "classe": "A",
         "valor_total": 100.0 * (i + 1), "n_itens": i + 1}
        for i, s in enumerate(weeks) for m in ("Material", "Serviço")])
    return itens, kept_items, panel


def test_writes_the_four_pngs(data, tmp_path):
    itens, kept_items, panel = data
    quarantined = itens.loc[[3]].assign(motivo="quantidade implausível na classe")
    paths = make_figures(itens, kept_items, panel, tmp_path,
                              quarantined=quarantined)
    assert len(paths) == 4
    for path in paths:
        assert path.exists() and path.stat().st_size > 0
        assert path.suffix == ".png"


def test_empty_quarantine_does_not_break(data, tmp_path):
    itens, kept_items, panel = data
    vazia = itens.head(0).assign(motivo=pd.Series(dtype="object"))
    paths = make_figures(itens, kept_items, panel, tmp_path, quarantined=vazia)
    assert len(paths) == 4
