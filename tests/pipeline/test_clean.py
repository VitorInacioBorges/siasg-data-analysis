import numpy as np
import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.clean import REASON_QUANTITY, clean


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path,
        qty_mad_threshold=8.0, min_class_items=30)


def _frame(rows):
    return pd.DataFrame(rows, columns=[
        "idCompraItem", "codigoClasse", "materialOuServicoNome",
        "quantidade", "valorUnitarioEstimado", "valorTotalResultado"])


@pytest.fixture
def base():
    """40 compras normais de informática, para a classe ter mediana e MAD."""
    rng = np.random.default_rng(7)
    normais = [(f"n{i}", "7010", "Material", float(q), 2000.0, q * 2000.0)
               for i, q in enumerate(rng.integers(1, 500, 40))]
    return _frame(normais)


def test_quarantines_impossible_quantity(cfg, base):
    # o caso real: 11.880.000 tablets a R$ 1.550
    suspect = _frame([("tablet", "7010", "Material",
                        11_880_000.0, 1550.0, 18_414_000_000.0)])
    kept, quarantined = clean(pd.concat([base, suspect], ignore_index=True), cfg)
    assert list(quarantined["idCompraItem"]) == ["tablet"]
    assert quarantined["motivo"].iloc[0] == REASON_QUANTITY
    assert "tablet" not in set(kept["idCompraItem"])


def test_legitimate_rows_survive(cfg, base):
    # 50 ressonâncias a R$ 8,25 mi e 3.000 ambulâncias a R$ 277 mil
    legitimate = _frame([
        ("ressonancia", "7010", "Material", 50.0, 8_254_384.14, 303_286_600.0),
        ("ambulancia", "7010", "Material", 3000.0, 277_807.0, 824_931_000.0),
    ])
    kept, quarantined = clean(pd.concat([base, legitimate], ignore_index=True), cfg)
    assert {"ressonancia", "ambulancia"} <= set(kept["idCompraItem"])
    assert quarantined.empty


def test_zero_mad_does_not_fire(cfg):
    """Classe de serviço onde toda quantidade é 1: MAD = 0, regra não se aplica."""
    services = _frame([(f"s{i}", "sem-classe", "Serviço", 1.0, 1000.0, 1000.0)
                       for i in range(40)])
    works = _frame([("obra", "sem-classe", "Serviço",
                    1.0, 616_720_624.99, 604_989_321.0)])
    kept, quarantined = clean(pd.concat([services, works], ignore_index=True), cfg)
    assert quarantined.empty
    assert "obra" in set(kept["idCompraItem"])


def test_rule_is_one_sided(cfg, base):
    """Quantidade muito BAIXA não é marcada: não infla total nenhum."""
    tiny = _frame([("fracao", "7010", "Material", 0.001, 2000.0, 2.0)])
    kept, quarantined = clean(pd.concat([base, tiny], ignore_index=True), cfg)
    assert quarantined.empty
    assert "fracao" in set(kept["idCompraItem"])


def test_nothing_evaporates(cfg, base):
    suspect = _frame([("tablet", "7010", "Material",
                        11_880_000.0, 1550.0, 18_414_000_000.0)])
    entry = pd.concat([base, suspect], ignore_index=True)
    kept, quarantined = clean(entry, cfg)
    assert len(kept) + len(quarantined) == len(entry)


def test_small_class_borrows_global_stats(cfg, base):
    """Uma classe com 2 itens não tem MAD confiável; cai para o global."""
    small = _frame([
        ("p1", "9999", "Material", 5.0, 100.0, 500.0),
        ("p2", "9999", "Material", 50_000_000.0, 100.0, 5_000_000_000.0),
    ])
    kept, quarantined = clean(pd.concat([base, small], ignore_index=True), cfg)
    assert "p2" in set(quarantined["idCompraItem"])
    assert "p1" in set(kept["idCompraItem"])
