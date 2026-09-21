import numpy as np
import pandas as pd
import pytest

from pipeline.split import split_by_week


@pytest.fixture
def panel():
    weeks = pd.period_range("2025-01-06", periods=10, freq="W")
    rows = [{"semana": s, "classe": c, "valor_total": 1.0}
              for s in weeks for c in ("A", "B", "C")]
    return pd.DataFrame(rows)


def test_no_week_on_both_sides(panel):
    for train, test in split_by_week(panel, n_splits=3):
        semanas_treino = set(panel.iloc[train]["semana"])
        semanas_teste = set(panel.iloc[test]["semana"])
        assert not (semanas_treino & semanas_teste)


def test_train_is_always_the_past(panel):
    for train, test in split_by_week(panel, n_splits=3):
        assert panel.iloc[train]["semana"].max() < panel.iloc[test]["semana"].min()


def test_whole_weeks_only(panel):
    """Cada semana traz as três classes juntas: 3 linhas por semana."""
    for train, test in split_by_week(panel, n_splits=3):
        assert len(test) % 3 == 0


def test_number_of_folds(panel):
    assert len(list(split_by_week(panel, n_splits=3))) == 3


def test_rejects_too_many_folds(panel):
    with pytest.raises(ValueError, match="semanas"):
        list(split_by_week(panel, n_splits=20))
