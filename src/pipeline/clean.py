"""
The plausibility filter, and the only stage that removes rows on judgement.

The measured problem: six rows out of 1.440.492 carry 53,77% of the total
value, and they are data-entry errors at the source. The largest is 1.713.940
units of postal service at R$ 132.000 each — R$ 226 bilhões, 31% of the dataset
in one row. Left in, the year reads R$ 735 bi; taken out, R$ 340 bi.

The rule reads the awarded total, not the quantity, because the absurdity is in
the product. An earlier design measured implausible quantity within each class
and was dropped after being measured against a full year: it missed that largest
row entirely (z = 3,41 against a threshold of 8), and the 177 rows it caught on
its own were legitimate public purchases at scale — 28 million vaccine doses,
8,8 million rounds of ammunition, 8.797 textbooks. Quantity within a class does
not separate bulk from typo.

Known limitation, accepted: two real errors stay in — 867.796.000 kg of goat
meat (R$ 3,3 bi) and 850.000 notebooks (R$ 4,4 bi), together 1% of the total.
Reaching them would need a ceiling that also removes the school meal programme.

Nothing is deleted. Removed rows come back as a second frame with the reason
attached, so the caller can write them to data/interim/quarentena.parquet.
"""

from __future__ import annotations

import pandas as pd

from classes.pipeline_settings import PipelineSettings
# Reused rather than duplicated: the messages here are Portuguese too, and one
# number formatter for the package is one place to fix it.
from pipeline.load import _pt_br

REASON_VALUE = "valor total implausível para um item de linha"


def clean(df: pd.DataFrame, cfg: PipelineSettings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits the frame into (kept, quarantined). Removes nothing silently."""
    # NaN > x is False, so an item that was never awarded a value is kept
    # rather than treated as exceeding the ceiling.
    suspect = df["valorTotalResultado"] > cfg.value_ceiling

    quarantined = df[suspect].copy()
    quarantined["motivo"] = REASON_VALUE
    kept = df[~suspect]

    if len(quarantined):
        total = quarantined["valorTotalResultado"].sum()
        print(f"{_pt_br(len(quarantined))} item(ns) em quarentena — {REASON_VALUE} "
              f"— somando R$ {_pt_br(total, 2)}.")

    return kept.reset_index(drop=True), quarantined.reset_index(drop=True)
