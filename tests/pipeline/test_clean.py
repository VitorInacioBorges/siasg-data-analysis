import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.clean import REASON_VALUE, clean


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path,
        value_ceiling=10_000_000_000.0)


def _frame(rows):
    return pd.DataFrame(rows, columns=[
        "idCompraItem", "codigoClasse", "materialOuServicoNome",
        "quantidade", "valorUnitarioEstimado", "valorTotalResultado"])


def test_quarantines_the_impossible_total(cfg):
    """O caso real: 1.713.940 unidades de serviço postal a R$ 132.000 cada."""
    entry = _frame([
        ("normal", "7010", "Material", 10.0, 100.0, 1_000.0),
        ("correios", None, "Serviço", 1_713_940.0, 132_000.0, 226_240_080_000.0),
    ])
    kept, quarantined = clean(entry, cfg)
    assert list(quarantined["idCompraItem"]) == ["correios"]
    assert quarantined["motivo"].iloc[0] == REASON_VALUE
    assert list(kept["idCompraItem"]) == ["normal"]


def test_spares_audited_legitimate_contracts(cfg):
    """Os contratos que auditamos à mão, e a escala pública que parece absurda.

    As três primeiras linhas são contratos reais grandes. As duas últimas são o
    que a regra anterior colocava em quarentena por engano: 28 milhões de doses
    de vacina e 8,8 milhões de munições não são erro de digitação.
    """
    entry = _frame([
        ("obras", None, "Serviço", 1.0, 616_720_624.99, 604_989_321.0),
        ("ambulancia", "7010", "Material", 3_000.0, 277_807.0, 824_931_000.0),
        ("ressonancia", "7010", "Material", 50.0, 8_254_384.14, 303_286_600.0),
        ("vacina", "6505", "Material", 28_000_000.0, 1.42, 39_760_000.0),
        ("municao", "1305", "Material", 8_800_000.0, 2.62, 23_040_000.0),
    ])
    kept, quarantined = clean(entry, cfg)
    assert quarantined.empty
    assert len(kept) == 5


def test_quantity_alone_never_quarantines(cfg):
    """Quantidade enorme com total modesto passa — é compra em massa.

    Esta é a regressão que importa: a regra anterior marcava estas linhas.
    """
    entry = _frame([
        ("merenda", None, "Serviço", 250_800_000.0, 24.0, 6_019_200_000.0),
        ("vale", None, "Serviço", 3_432_000_000.0, 3.0, 9_000_000_000.0),
    ])
    kept, quarantined = clean(entry, cfg)
    assert quarantined.empty
    assert len(kept) == 2


def test_the_ceiling_is_exclusive(cfg):
    """Exatamente no teto passa; um centavo acima, não."""
    entry = _frame([
        ("no_teto", "7010", "Material", 1.0, 1.0, 10_000_000_000.0),
        ("acima", "7010", "Material", 1.0, 1.0, 10_000_000_000.01),
    ])
    kept, quarantined = clean(entry, cfg)
    assert list(kept["idCompraItem"]) == ["no_teto"]
    assert list(quarantined["idCompraItem"]) == ["acima"]


def test_missing_value_is_kept(cfg):
    """valorTotalResultado nulo não pode ser tratado como acima do teto."""
    entry = _frame([("sem_valor", "7010", "Material", 5.0, 100.0, None)])
    kept, quarantined = clean(entry, cfg)
    assert quarantined.empty
    assert len(kept) == 1


def test_nothing_evaporates(cfg):
    """A invariante que pegaria uma linha perdida no caminho."""
    entry = _frame([
        ("a", "7010", "Material", 1.0, 1.0, 1.0),
        ("b", None, "Serviço", 1.0, 1.0, 226_240_080_000.0),
        ("c", "8905", "Material", 2.0, 2.0, 4.0),
    ])
    kept, quarantined = clean(entry, cfg)
    assert len(kept) + len(quarantined) == len(entry)


def test_reports_what_it_removed(cfg, capsys):
    """Nada sai em silêncio: a mensagem diz quantos itens e quanto valor."""
    entry = _frame([
        ("ok", "7010", "Material", 1.0, 1.0, 1.0),
        ("fora", None, "Serviço", 1.0, 1.0, 226_240_080_000.0),
    ])
    clean(entry, cfg)
    out = capsys.readouterr().out
    assert "quarentena" in out
    assert "1 item" in out
