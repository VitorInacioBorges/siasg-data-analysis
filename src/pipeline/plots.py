"""
The figures, and one rule they all obey: raw and clean are shown side by side.

Eight rows out of 488.740 carry 78,7% of the value in the real data, so a chart
of the cleaned series alone would hide the single most consequential decision in
this pipeline. Every figure that can show both, shows both.

Palette: two categorical slots, #2a78d6 and #eb6834, validated against the six
checks of the dataviz method on the light surface (lightness band, chroma floor,
CVD separation, normal-vision floor, contrast — all pass). Do not substitute
without re-running that validator.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Categorical slots 1 and 2. Identity, not magnitude, so two distinct hues.
SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"
# Text wears text tokens, never the series colour.
INK = "#0b0b0b"
INK_MUTED = "#52514e"
SURFACE = "#fcfcfb"
GRID = "#e3e2de"


def _new_figure(titulo: str, subtitulo: str = "") -> tuple[plt.Figure, plt.Axes]:
    """One figure, styled once: recessive axes, no top/right spines."""
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    # The title is pushed clear of the subtitle rather than sitting 16pt above
    # the axes: at that pad the 10pt subtitle drawn at y=1.02 ends exactly where
    # the title begins, and the two render on top of each other.
    ax.set_title(titulo, color=INK, fontsize=13, loc="left",
                 pad=30 if subtitulo else 8)
    if subtitulo:
        ax.text(0, 1.02, subtitulo, transform=ax.transAxes,
                color=INK_MUTED, fontsize=10, va="bottom")
    # Recessive grid and axes: the data carries the ink.
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(GRID)
    ax.tick_params(colors=INK_MUTED, labelsize=9)
    return fig, ax


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def _weekly_series(itens: pd.DataFrame) -> pd.Series:
    return (itens.set_index("dataInclusaoPncp")["valorTotalResultado"]
            .resample("W").sum())


def make_figures(raw_items: pd.DataFrame, kept_items: pd.DataFrame, panel: pd.DataFrame,
                   destination: Path, quarantined: pd.DataFrame | None = None) -> list[Path]:
    """Writes the four figures and returns their paths."""
    destination = Path(destination)
    paths: list[Path] = []

    # --- 1. the series, before and after cleaning -------------------------
    before, after = _weekly_series(raw_items), _weekly_series(kept_items)
    fig, ax = _new_figure("Gasto homologado por semana",
                      "Antes e depois do filtro de plausibilidade")
    # 2px lines, per the mark spec.
    ax.plot(before.index, before.to_numpy() / 1e9, color=SERIES_1, linewidth=2,
            label="Bruto")
    ax.plot(after.index, after.to_numpy() / 1e9, color=SERIES_2, linewidth=2,
            label="Limpo")
    # Two series: legend always, and direct labels because there are <= 4.
    # Opposite vertical offsets, because the two series end at the same value
    # whenever the cleaning removed nothing — and then a shared offset stacks
    # the two labels into one unreadable smear.
    for series, color, label, dy in ((before, SERIES_1, "Bruto", 8),
                                     (after, SERIES_2, "Limpo", -8)):
        if len(series):
            ax.annotate(label, (series.index[-1], series.iloc[-1] / 1e9),
                        xytext=(6, dy), textcoords="offset points",
                        color=color, fontsize=9, va="center")
    ax.set_ylabel("R$ bilhões", color=INK_MUTED, fontsize=10)
    ax.legend(frameon=False, labelcolor=INK_MUTED, fontsize=9)
    paths.append(_save(fig, destination / "01-serie-bruto-vs-limpo.png"))

    # --- 2. the distribution, on a log axis -------------------------------
    values = kept_items["valorTotalResultado"].dropna()
    values = values[values > 0]
    fig, ax = _new_figure("Distribuição do valor por item",
                      "Escala logarítmica: a mediana e a média diferem em 271x")
    if len(values):
        # One series: no legend box, the title names it.
        ax.hist(values, bins=np.logspace(np.log10(values.min()),
                                          np.log10(values.max()), 50),
                color=SERIES_1)
        ax.set_xscale("log")
        ax.axvline(values.median(), color=INK_MUTED, linewidth=1.5,
                   linestyle="--")
        ax.annotate(f"mediana R$ {values.median():,.0f}",
                    (values.median(), ax.get_ylim()[1] * 0.9),
                    xytext=(8, 0), textcoords="offset points",
                    color=INK_MUTED, fontsize=9)
    ax.set_xlabel("R$ por item (log)", color=INK_MUTED, fontsize=10)
    ax.set_ylabel("itens", color=INK_MUTED, fontsize=10)
    paths.append(_save(fig, destination / "02-distribuicao-log.png"))

    # --- 3. composition over time -----------------------------------------
    composition = (panel.groupby(["semana", "materialOuServicoNome"], observed=True)
            ["valor_total"].sum().unstack(fill_value=0))
    fig, ax = _new_figure("Composição do gasto por semana",
                      "Material e serviço, sobre os dados limpos")
    if not composition.empty:
        base = np.zeros(len(composition))
        for column, color in zip(composition.columns, (SERIES_1, SERIES_2)):
            height = composition[column].to_numpy() / 1e9
            # A 2px surface gap between stacked segments keeps the boundary
            # readable without a border colour.
            ax.bar(range(len(composition)), height, bottom=base, color=color,
                   label=str(column), width=0.82, linewidth=2,
                   edgecolor=SURFACE)
            base = base + height
        step = max(1, len(composition) // 12)
        ax.set_xticks(range(0, len(composition), step))
        # The week's first day, not str(Period), which renders the full range
        # "2025-09-15/2025-09-21" and costs a third of the canvas in tick text.
        ax.set_xticklabels([s.start_time.strftime("%Y-%m-%d")
                            for s in composition.index[::step]],
                           rotation=45, ha="right")
        ax.legend(frameon=False, labelcolor=INK_MUTED, fontsize=9)
    ax.set_ylabel("R$ bilhões", color=INK_MUTED, fontsize=10)
    paths.append(_save(fig, destination / "03-composicao-material-servico.png"))

    # --- 4. what the cleaning removed -------------------------------------
    fig, ax = _new_figure("O que a limpeza removeu",
                      "Valor em quarentena, por motivo")
    if quarantined is not None and len(quarantined):
        by_reason = (quarantined.groupby("motivo")["valorTotalResultado"]
                      .agg(["sum", "size"]).sort_values("sum"))
        positions = range(len(by_reason))
        ax.barh(positions, by_reason["sum"] / 1e9, color=SERIES_2, height=0.6)
        ax.set_yticks(positions)
        ax.set_yticklabels(by_reason.index, fontsize=9)
        # Direct labels on the bars: the magnitude is the message.
        for i, (value, n) in enumerate(zip(by_reason["sum"], by_reason["size"])):
            ax.annotate(f"R$ {value / 1e9:,.1f} bi · {n:,} itens",
                        (value / 1e9, i), xytext=(6, 0),
                        textcoords="offset points", color=INK_MUTED,
                        fontsize=9, va="center")
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
    else:
        ax.text(0.5, 0.5, "Nenhum item em quarentena", transform=ax.transAxes,
                ha="center", color=INK_MUTED, fontsize=11)
        ax.set_axis_off()
    ax.set_xlabel("R$ bilhões", color=INK_MUTED, fontsize=10)
    paths.append(_save(fig, destination / "04-quarentena.png"))

    return paths
