import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from classes.pipeline_settings import PipelineSettings
from pipeline.features import CATEGORICAL_FEATURES, numeric_features
from pipeline.transform import build_transformer


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path)


@pytest.fixture
def X(cfg):
    n = 20
    data = {c: np.arange(n, dtype=float) for c in numeric_features(cfg)}
    data["materialOuServicoNome"] = ["Material", "Serviço"] * (n // 2)
    data["classe"] = ["A", "B", "C", "D"] * (n // 4)
    return pd.DataFrame(data)


def test_categoricals_become_binary_columns(cfg, X):
    out = build_transformer(cfg).fit_transform(X)
    # 2 valores de material/serviço + 4 classes + as numéricas
    assert out.shape[1] == 2 + 4 + len(numeric_features(cfg))


def test_unseen_category_does_not_break(cfg, X):
    transformador = build_transformer(cfg).fit(X)
    novo = X.head(1).copy()
    novo.loc[:, "classe"] = "Z"          # classe nunca vista no treino
    assert transformador.transform(novo).shape[1] == transformador.transform(X).shape[1]


def test_scaler_is_fitted_on_train_only(cfg, X):
    """O teste de vazamento: a média do scaler é a do treino, não a do todo."""
    train, test = X.iloc[:10], X.iloc[10:]
    modelo = Pipeline([("prep", build_transformer(cfg)), ("reg", Ridge())])
    modelo.fit(train, np.arange(10, dtype=float))

    # named_transformers_["num"] é o Pipeline (imputa + escala); o scaler
    # está dentro dele.
    scaler = (modelo.named_steps["prep"]
              .named_transformers_["num"].named_steps["escala"])
    expected = train["tendencia"].mean()
    # O índice vem da mesma lista que o transformador recebeu, não de uma
    # constante paralela que poderia estar em outra ordem.
    indice = numeric_features(cfg).index("tendencia")
    assert scaler.mean_[indice] == pytest.approx(expected)
    assert scaler.mean_[indice] != pytest.approx(X["tendencia"].mean())


def test_nan_features_do_not_break(cfg, X):
    """Os lags nascem com NaN nas primeiras semanas; o transformador aguenta."""
    X = X.copy()
    X.loc[0:3, "valor_lag_52"] = np.nan
    out = build_transformer(cfg).fit_transform(X)
    assert not np.isnan(out).any()
