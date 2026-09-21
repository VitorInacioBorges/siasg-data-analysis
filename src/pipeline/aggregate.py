"""
Where the grain changes: one row per item becomes one row per period.

This is the step that makes forecasting possible at all. At the item grain there
is no "next week" — only items. The panel puts time on the row.

Two details decide whether the result is usable. Classes are reduced to the
largest N by value, because the real data has 434 of them and the top 50 already
cover 94,1% of the money — one-hot encoding all 434 would add more columns than
the panel has time steps. And the panel must come out a complete rectangle:
after a groupby, a week in which a class bought nothing simply does not exist,
and a lag would silently reach three weeks back instead of one.
"""

from __future__ import annotations

import pandas as pd

from classes.pipeline_settings import PipelineSettings

BUCKET_OTHER = "Outras"
BUCKET_NO_CLASS = "Sem classe"


def _reduce_classes(df: pd.DataFrame, cfg: PipelineSettings) -> pd.Series:
    """Keeps the top classes by awarded value; everything else gets a bucket."""
    classe = df["codigoClasse"].astype("object")
    missing = classe.isna()

    ranking = (df.loc[~missing]
               .groupby(classe[~missing], observed=True)["valorTotalResultado"]
               .sum()
               .sort_values(ascending=False))
    kept_classes = set(ranking.head(cfg.top_classes).index)

    reduced = classe.where(classe.isin(kept_classes), BUCKET_OTHER)
    # The missing-class bucket is kept separate from "Outras" because the two
    # mean different things: one is a small class, the other is no class at all.
    return reduced.mask(missing, BUCKET_NO_CLASS).astype("string")


def to_panel(df: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame:
    """Aggregates the item grain into semana × material/serviço × classe."""
    work = df.copy()
    work["semana"] = work["dataInclusaoPncp"].dt.to_period(cfg.panel_freq)
    work["classe"] = _reduce_classes(work, cfg)
    work["materialOuServicoNome"] = (work["materialOuServicoNome"]
                                         .astype("string"))

    key = ["semana", "materialOuServicoNome", "classe"]
    panel = work.groupby(key, observed=True).agg(
        valor_total=("valorTotalResultado", "sum"),
        n_itens=("valorTotalResultado", "size"),
        qtd_total=("quantidade", "sum"),
        qtd_mediana=("quantidade", "median"),
        preco_unitario_mediano=("valorUnitarioEstimado", "median"),
        valor_estimado_total=("valorTotal", "sum"),
        n_fornecedores=("nomeFornecedor", "nunique"),
        n_orgaos=("orgaoEntidadeCnpj", "nunique"),
    ).reset_index()

    # The rectangle. Every observed (material/serviço, classe) pair crossed with
    # every week in the range, so a lag always steps exactly one period back.
    combos = panel[["materialOuServicoNome", "classe"]].drop_duplicates()
    weeks = pd.period_range(panel["semana"].min(), panel["semana"].max(),
                              freq=cfg.panel_freq)
    full_grid = combos.merge(pd.DataFrame({"semana": weeks}), how="cross")
    panel = full_grid.merge(panel, on=key, how="left")

    # A week with no purchase is a zero, not a gap: the money and the count are
    # genuinely zero.
    for column in ("valor_total", "n_itens", "qtd_total", "valor_estimado_total",
                   "n_fornecedores", "n_orgaos"):
        panel[column] = panel[column].fillna(0)
    # Medians of an empty set stay NaN — there was no price to observe, which is
    # not the same as a price of zero.

    # How much of the estimate the government actually paid. Measured median in
    # the real data: 0,826.
    panel["taxa_desconto"] = (panel["valor_total"]
                               / panel["valor_estimado_total"].replace(0, pd.NA))

    return panel.sort_values(["semana"] + key[1:]).reset_index(drop=True)
