import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.features import (CATEGORICAL_FEATURES, numeric_features,
                               build_features)


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path, panel_freq="W")


@pytest.fixture
def panel():
    weeks = pd.period_range("2025-01-06", periods=8, freq="W")
    rows = []
    for i, semana in enumerate(weeks):
        for combo in (("Material", "A"), ("Serviço", "B")):
            rows.append({
                "semana": semana, "materialOuServicoNome": combo[0],
                "classe": combo[1], "valor_total": float((i + 1) * 100),
                "n_itens": i + 1, "qtd_total": 10.0, "qtd_mediana": 2.0,
                "preco_unitario_mediano": 50.0,
                "valor_estimado_total": float((i + 1) * 120),
                "n_fornecedores": 2, "n_orgaos": 1, "taxa_desconto": 0.83})
    return pd.DataFrame(rows)


def test_lags_look_backwards(cfg, panel):
    out = build_features(panel, cfg)
    row_a = out[(out["classe"] == "A")].sort_values("semana")
    # a terceira semana tem valor 300 e o lag_1 dela é 200
    assert row_a["valor_total"].iloc[2] == 300.0
    assert row_a["valor_lag_1"].iloc[2] == 200.0
    # a primeira semana não tem passado
    assert pd.isna(row_a["valor_lag_1"].iloc[0])


def test_lag_does_not_cross_combinations(cfg, panel):
    """O lag da classe A nunca pega valor da classe B."""
    panel = panel.copy()
    panel.loc[panel["classe"] == "B", "valor_total"] = 9999.0
    out = build_features(panel, cfg)
    row_a = out[out["classe"] == "A"].sort_values("semana")
    assert (row_a["valor_lag_1"].dropna() != 9999.0).all()


def test_lag_52_is_empty_with_one_year(cfg, panel):
    """Documenta a limitação: 8 semanas de painel, lag_52 inteiramente nulo."""
    out = build_features(panel, cfg)
    assert out["valor_lag_52"].isna().all()


def test_calendar_features(cfg, panel):
    out = build_features(panel, cfg)
    assert out["tendencia"].min() == 0
    assert out["semana_do_ano"].between(1, 53).all()
    assert out["sazonal_sen"].between(-1, 1).all()


def test_declared_columns_exist_in_the_output(cfg, panel):
    """Tudo que numeric_features() promete precisa existir de fato."""
    out = build_features(panel, cfg)
    for column in CATEGORICAL_FEATURES + numeric_features(cfg):
        assert column in out.columns, column


def test_monthly_frequency_renames_the_annual_lag(cfg, panel):
    """A razão de a lista ser função e não constante."""
    import dataclasses
    mensal = dataclasses.replace(cfg, panel_freq="M")
    assert "valor_lag_12" in numeric_features(mensal)
    assert "valor_lag_52" not in numeric_features(mensal)
    assert "valor_lag_52" in numeric_features(cfg)
