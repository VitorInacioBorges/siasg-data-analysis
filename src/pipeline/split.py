"""
The temporal split, and the reason it cannot be sklearn's TimeSeriesSplit alone.

The panel holds around fifty rows per week, one per combination. TimeSeriesSplit
cuts by row position, so it lands in the middle of a week and puts half of that
week's classes in train and the other half in test. The model then sees part of
the very period it is being scored on — the leak that makes a random split
produce an R2 of 0,987 on data where the honest answer is 0,339.

So the split is taken over the distinct weeks and only then expanded to rows.
"""

from __future__ import annotations

from typing import Iterator

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit


def split_by_week(panel: pd.DataFrame, n_splits: int) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yields (train, test) positional row indices, cutting only between weeks."""
    weeks = np.sort(panel["semana"].unique())
    if len(weeks) < n_splits + 1:
        raise ValueError(
            f"{n_splits} dobras exigem pelo menos {n_splits + 1} semanas "
            f"distintas; o painel tem {len(weeks)}."
        )

    # Position of each row's week within the sorted week list, so a week-level
    # decision becomes a row-level mask without a join.
    position = pd.Series(panel["semana"]).map(
        {semana: i for i, semana in enumerate(weeks)}
    ).to_numpy()

    for train_weeks, test_weeks in TimeSeriesSplit(n_splits=n_splits).split(weeks):
        train = np.flatnonzero(np.isin(position, train_weeks))
        test = np.flatnonzero(np.isin(position, test_weeks))
        yield train, test
