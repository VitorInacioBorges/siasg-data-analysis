"""
The model-facing transformer, and the boundary where leakage is prevented.

Everything above this module runs once over the whole dataset, because
deduplicating and filtering by plausibility give the same answer regardless of
which fold is running. This one cannot: a StandardScaler's mean computed over
train and test together carries the future into the training set.

So this module returns the transformer UNFITTED. The caller embeds it in a
Pipeline, and sklearn refits it inside every fold. That is the whole reason the
file exists as a factory rather than as a fitted object.
"""

from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from classes.pipeline_settings import PipelineSettings
from pipeline.features import CATEGORICAL_FEATURES, numeric_features


def build_transformer(cfg: PipelineSettings) -> ColumnTransformer:
    """Builds the unfitted ColumnTransformer for the panel's feature columns."""
    # Lags are NaN for the first weeks of every combination, by construction.
    # Imputing the median keeps those rows usable; dropping them would throw
    # away the start of every series.
    numeric_pipe = Pipeline([
        ("imputa", SimpleImputer(strategy="median")),
        # Scaling matters for Ridge, which compares magnitudes, and is
        # harmless for the tree models. Keeping it makes swapping the
        # estimator a one-line change.
        ("escala", StandardScaler()),
    ])

    categorical_pipe = OneHotEncoder(
        # A class present only in the test fold must not raise: with a temporal
        # split, a class that appears late in the year is exactly that.
        handle_unknown="ignore",
        sparse_output=False,
    )

    return ColumnTransformer(
        [
            # Asked of features.py rather than hardcoded, so the annual lag's
            # name follows PANEL_FREQ and the two modules cannot drift apart.
            ("num", numeric_pipe, numeric_features(cfg)),
            ("cat", categorical_pipe, CATEGORICAL_FEATURES),
        ],
        # Anything not named is dropped: the targets and the key columns must
        # never reach the model as features.
        remainder="drop",
    )
