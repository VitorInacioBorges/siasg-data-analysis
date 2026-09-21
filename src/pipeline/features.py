"""
Makes implicit information explicit, because a model only sees its columns.

Every feature here looks backwards. A column that peeked forward would be the
leak that produces a flattering score and a useless model — the same failure as
splitting a time series at random.

One limitation is structural rather than accidental: with a 365 day collection
window the panel has 52 weekly steps, so valor_lag_52 comes out entirely null.
Forecasting a year ahead needs a lag of 52 or more, because the model cannot be
handed a value it will not know at prediction time. Short horizons (one to eight
weeks) are well served by the short lags; the one-year horizon rests on trend and
calendar alone until the collection window grows. Widening the window makes
lag_52 populate with no change to this module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from classes.pipeline_settings import PipelineSettings

# Consumed by transform.py to build the ColumnTransformer.
CATEGORICAL_FEATURES = ["materialOuServicoNome", "classe"]

COMBO_KEY = ["materialOuServicoNome", "classe"]

# Periods in one year, per panel frequency. This is what makes the seasonal
# cycle and the annual lag follow PANEL_FREQ instead of assuming weeks: with a
# hardcoded 52 a monthly panel would compute a twelve-times-too-long cycle and
# an annual lag that reaches four years back.
PERIODS_PER_YEAR = {"W": 52, "M": 12, "Q": 4, "D": 365}
PERIODS_PER_YEAR_DEFAULT = 52

# Short lags for the near horizon; the annual one is added from the frequency.
SHORT_LAGS = (1, 4)
ROLLING_WINDOW = 4


def numeric_features(cfg: PipelineSettings) -> list[str]:
    """The numeric feature names build_features() produces for this frequency."""
    periods = PERIODS_PER_YEAR.get(cfg.panel_freq.upper()[:1], PERIODS_PER_YEAR_DEFAULT)
    fixed = ["tendencia", "semana_do_ano", "mes", "sazonal_sen", "sazonal_cos",
             "qtd_total", "qtd_mediana", "preco_unitario_mediano",
             "n_fornecedores", "n_orgaos", "taxa_desconto",
             "valor_media_4", "itens_media_4"]
    lagged = [f"{target}_lag_{d}"
                 for d in SHORT_LAGS + (periods,)
                 for target in ("valor", "itens")]
    return fixed + lagged


def build_features(panel: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame:
    """Adds calendar, trend, lag, and rolling-mean columns to the panel."""
    out = panel.sort_values(COMBO_KEY + ["semana"]).copy()

    # Calendar. The week number carries seasonality a linear model can use only
    # as a cycle, so it also goes in as sine and cosine — week 52 and week 1 are
    # neighbours, which a raw integer cannot express.
    stamp = out["semana"].dt.to_timestamp()
    out["semana_do_ano"] = stamp.dt.isocalendar().week.astype(int)
    out["mes"] = stamp.dt.month

    # The cycle length comes from the configured frequency, so the sine and
    # cosine describe one real year whatever the panel's grain.
    frequency = cfg.panel_freq.upper()[:1]
    periods = PERIODS_PER_YEAR.get(frequency)
    if periods is None:
        print(f"Aviso: PANEL_FREQ={cfg.panel_freq!r} não está no mapa de períodos; "
              f"assumindo {PERIODS_PER_YEAR_DEFAULT} períodos por ano.")
        periods = PERIODS_PER_YEAR_DEFAULT

    angle = 2 * np.pi * out["semana_do_ano"] / periods
    out["sazonal_sen"] = np.sin(angle)
    out["sazonal_cos"] = np.cos(angle)

    # Trend, as periods since the start of the panel. Zero-based so the
    # intercept of a linear model reads as "the first week".
    ordinais = out["semana"].astype("int64")
    out["tendencia"] = (ordinais - ordinais.min()).astype(int)

    # Lags and rolling means are computed per combination. Grouping is what
    # stops the lag of one class from reaching into another's history — without
    # it, the first week of class B would inherit the last week of class A.
    groups = out.groupby(COMBO_KEY, observed=True)
    for lag in SHORT_LAGS + (periods,):
        out[f"valor_lag_{lag}"] = groups["valor_total"].shift(lag)
        out[f"itens_lag_{lag}"] = groups["n_itens"].shift(lag)

    # shift(1) before rolling: the mean must not include the week being
    # predicted. Including it would be the leak this whole module avoids.
    out["valor_media_4"] = (groups["valor_total"]
                              .transform(lambda s: s.shift(1)
                                         .rolling(ROLLING_WINDOW).mean()))
    out["itens_media_4"] = (groups["n_itens"]
                              .transform(lambda s: s.shift(1)
                                         .rolling(ROLLING_WINDOW).mean()))

    empty = [c for c in out.columns
              if c.endswith(f"_{periods}") and out[c].isna().all()]
    if empty:
        print(f"Aviso: {', '.join(empty)} está(ão) inteiramente vazia(s) — o painel "
              f"tem {out['semana'].nunique()} semanas, menos que a defasagem de {periods}. "
              f"Amplie WINDOW_DAYS no .env para habilitar o horizonte de um ano.")

    return out.sort_values(["semana"] + COMBO_KEY).reset_index(drop=True)
