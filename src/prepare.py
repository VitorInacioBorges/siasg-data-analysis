"""
Turns the collector's raw CSV into a model-ready weekly panel.

Shape of the program, outermost first:
    main()          reads config, prints the plan, handles the exit code
    run_stages()    runs the stages in order and writes each artefact
Each stage is a function in src/pipeline/, testable on its own.

Stages, and what each one leaves on disk:
    load       -> (in memory) typed item grain, deduplicated
    clean      -> interim/itens_limpos.parquet, interim/quarentena.parquet
    aggregate  -> processed/painel.parquet
    features   -> processed/painel_features.parquet
    plots      -> reports/figures/*.png

Every setting lives in the .env file — see .env.example.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from classes.pipeline_settings import PipelineSettings
from pipeline.aggregate import to_panel
from pipeline.clean import clean
from pipeline.features import build_features
from pipeline.load import load_raw
from pipeline.plots import make_figures
from read_type_methods import ConfigError

STAGES = ["load", "clean", "aggregate", "features", "plots"]

EXIT_OK = 0
EXIT_ERROR = 1
# 130 is the conventional shell code for "terminated by SIGINT" (Ctrl+C).
EXIT_INTERRUPTED = 130


def _write(df: pd.DataFrame, path: Path) -> None:
    """Writes Parquet, falling back to CSV when pyarrow is absent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False)
    except ImportError:
        fallback = path.with_suffix(".csv")
        print(f"Aviso: pyarrow não está instalado; gravando {fallback.name} "
              f"em vez de Parquet (arquivo maior e sem tipos preservados).")
        df.to_csv(fallback, index=False, encoding="utf-8-sig")


def run_stages(cfg: PipelineSettings, ate: str) -> int:
    """Runs the stages up to and including `ate`. Returns rows in the panel."""
    limit = STAGES.index(ate)

    print("Lendo", cfg.raw_csv, flush=True)
    raw_items = load_raw(cfg.raw_csv, cfg)
    if limit == 0:
        return len(raw_items)

    kept_items, quarantined = clean(raw_items, cfg)
    # The invariant that would have caught the duplicate rows the day they
    # appeared: cleaning splits the frame, it never shrinks the total.
    assert len(kept_items) + len(quarantined) == len(raw_items), (
        f"limpeza perdeu linhas: {len(raw_items)} entraram, "
        f"{len(kept_items) + len(quarantined)} saíram"
    )
    _write(kept_items, cfg.interim_dir / "itens_limpos.parquet")
    _write(quarantined, cfg.interim_dir / "quarentena.parquet")
    if limit == 1:
        return len(kept_items)

    panel = to_panel(kept_items, cfg)
    n_weeks = panel["semana"].nunique()
    n_combos = panel[["materialOuServicoNome", "classe"]].drop_duplicates().shape[0]
    assert len(panel) == n_weeks * n_combos, (
        f"painel não é retângulo: {len(panel)} linhas para "
        f"{n_weeks} semanas x {n_combos} combinações"
    )
    expected = kept_items["valorTotalResultado"].sum()
    assert abs(panel["valor_total"].sum() - expected) < 1e-6 * max(1.0, abs(expected)), (
        "a agregação não preservou a soma dos valores"
    )
    _write(panel, cfg.processed_dir / "painel.parquet")
    print(f"Painel: {len(panel):,} linhas ({n_weeks} semanas x {n_combos} combinações)")
    if limit == 2:
        return len(panel)

    featured = build_features(panel, cfg)
    _write(featured, cfg.processed_dir / "painel_features.parquet")
    if limit == 3:
        return len(featured)

    figures = make_figures(raw_items, kept_items, panel, cfg.figures_dir,
                             quarantined=quarantined)
    print(f"{len(figures)} figura(s) em {cfg.figures_dir}")
    return len(featured)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code rather than exiting itself."""
    parser = argparse.ArgumentParser(
        description="Prepara o painel semanal a partir do CSV bruto do coletor.")
    parser.add_argument("--ate", choices=STAGES, default=STAGES[-1],
                        help="roda até este estágio, inclusive")
    args = parser.parse_args(argv)

    try:
        cfg = PipelineSettings.from_env()
    except ConfigError as error:
        # A configuration mistake is the user's to fix, so it is reported as a
        # plain message instead of a traceback.
        print(f"Erro de configuração no .env: {error}")
        return EXIT_ERROR

    print(f"Estágios: {' -> '.join(STAGES[:STAGES.index(args.ate) + 1])}")
    print(f"Saída:    {cfg.interim_dir} e {cfg.processed_dir}")

    try:
        rows = run_stages(cfg, args.ate)
    except FileNotFoundError as error:
        print(f"Erro: {error}")
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return EXIT_INTERRUPTED

    if rows == 0:
        print("\nNenhuma linha sobreviveu aos filtros. Revise STATUS_FILTER no .env.")
        return EXIT_OK

    print(f"\nPronto. {rows:,} linhas no artefato final.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
