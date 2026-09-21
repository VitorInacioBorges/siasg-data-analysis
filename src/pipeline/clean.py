"""
The plausibility filter, and the only stage that removes rows on judgement.

The measured problem: eight rows out of 488.740 carry 78,7% of the value, and
they are data entry errors at the source — 11.880.000 tablets, 867.796.000 kilos
of goat meat, 1.713.940 units of postal service. Summing them annualises to
R$ 2,6 trillion in federal line items, which is impossible.

The errors live in the quantity, not in the total. Legitimate large contracts
appear with quantity 1 (the whole contract in the unit price) or with dozens of
units. That is why the rule reads quantity and not value: a ceiling on value
would remove real road works and MRI scanners along with the typos.

Nothing is deleted. Removed rows are returned as a second frame with the reason
attached, so the caller can write them to data/interim/quarentena.parquet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from classes.pipeline_settings import PipelineSettings
from pipeline.load import _pt_br

REASON_QUANTITY = "quantidade implausível na classe"

# Scale factor that makes the median absolute deviation a consistent estimator
# of the standard deviation for normally distributed data. Without it the
# threshold would not be comparable to a z-score.
MAD_SCALE = 1.4826


def _mad(series: pd.Series) -> float:
    """Median absolute deviation: a spread measure the outliers cannot inflate."""
    return float((series - series.median()).abs().median())


def clean(df: pd.DataFrame, cfg: PipelineSettings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits the frame into (kept, quarantined). Removes nothing silently."""
    work = df.copy()

    # log10 because quantities span nine orders of magnitude, from 1 unit to
    # 867 million. On the linear scale the median is meaningless.
    work["_log_qtd"] = np.log10(
        work["quantidade"].where(work["quantidade"] > 0)
    )

    # dropna=False keeps the missing-class rows as their own group: 19% of the
    # data has no codigoClasse, and it includes the civil works contracts.
    group = work.groupby("codigoClasse", dropna=False, observed=True)["_log_qtd"]
    median = group.transform("median")
    mad = group.transform(_mad)
    size = group.transform("size")

    global_median = work["_log_qtd"].median()
    global_mad = _mad(work["_log_qtd"].dropna())

    # A class whose quantities are all identical has MAD 0, and dividing by it
    # would flag every row that differs at all. Service classes are like this —
    # quantity is 1 on nearly every contract — and they are exactly where the
    # legitimate R$ 604 million works sit. The rule simply does not apply there.
    no_spread = mad.isna() | (mad == 0)

    # A class with a handful of items has a median and a MAD, but neither means
    # anything. Borrow the global distribution instead.
    small_class = (size < cfg.min_class_items) & ~no_spread

    effective_median = median.where(~small_class, global_median)
    effective_mad = mad.where(~small_class, global_mad)

    z = (work["_log_qtd"] - effective_median) / (MAD_SCALE * effective_mad)

    # One-sided on purpose. A quantity that is too small understates a total and
    # cannot produce the R$ 226 billion artefact; and quantity 1 is the norm for
    # works and continuing services. Only the high tail is suspect.
    # NaN comparisons are False, so rows without a usable quantity are kept.
    suspect = (z > cfg.qty_mad_threshold) & ~no_spread
    if global_mad == 0:
        # Degenerate input: every quantity in the frame is identical.
        suspect = pd.Series(False, index=work.index)

    quarantined = work[suspect].copy()
    quarantined["motivo"] = REASON_QUANTITY
    quarantined["z_quantidade"] = z[suspect]

    kept = work[~suspect].drop(columns="_log_qtd")
    quarantined = quarantined.drop(columns="_log_qtd")

    if len(quarantined):
        value = quarantined["valorTotalResultado"].sum()
        print(f"{_pt_br(len(quarantined))} item(ns) em quarentena por quantidade "
              f"implausível, somando R$ {_pt_br(value, 2)}.")

    return kept.reset_index(drop=True), quarantined.reset_index(drop=True)
