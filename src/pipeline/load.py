"""
Faithful read of the collector's output.

Does three things and only three: deduplicate, drop the dead columns, filter by
status. Anything that requires a judgement call about the data belongs in
clean.py — this module's job is to hand the next stage a typed, honest frame.

The raw CSV may be several hundred megabytes and may be mid-write while the
collector runs, so it is read in slices and tolerant of a truncated last line.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from classes.pipeline_settings import PipelineSettings

# Cardinality 1 in the real data, or almost entirely absent. itemCategoriaNome
# reads "Informática (TIC)" on every row of a dataset that contains goat meat
# and antipsychotics — the API field is broken, not narrow.
DEAD_COLUMNS = ["itemCategoriaNome", "temResultado", "codigoGrupo"]

# Identifiers, never arithmetic: read as text so a CNPJ keeps its leading zero.
TEXT_COLUMNS = ["idCompraItem", "orgaoEntidadeCnpj", "unidadeOrgaoCodigoUnidade",
                 "codigoClasse", "codItemCatalogo"]

NUMERIC_COLUMNS = ["quantidade", "valorUnitarioEstimado", "valorTotal",
                     "valorTotalResultado"]

# Few distinct values each, repeated millions of times: `category` stores the
# labels once and an integer per row, which is what keeps this in memory.
CATEGORY_COLUMNS = ["materialOuServicoNome", "materialOuServico", "unidadeMedida",
                     "situacaoCompraItemNome", "nomeFornecedor"]


def load_raw(path: Path, cfg: PipelineSettings) -> pd.DataFrame:
    """Reads the raw CSV, deduplicates it, and returns the item grain."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} não existe. Rode o coletor primeiro: python src/main.py"
        )

    slices = pd.read_csv(
        path,
        encoding="utf-8-sig",
        chunksize=cfg.read_chunk_rows,
        # The collector may be appending right now, leaving the last line half
        # written. Skipping it is right; doing so silently is not — the count
        # is reported below.
        on_bad_lines="skip",
        parse_dates=["dataInclusaoPncp"],
        dtype={c: "string" for c in TEXT_COLUMNS},
        low_memory=False,
    )
    df = pd.concat(list(slices), ignore_index=True)

    read_rows = len(df)
    # One extra pass over the file, a few seconds, to tell a skipped line from a
    # line that was never there.
    with path.open("rb") as fh:
        in_file = sum(1 for _ in fh) - 1
    if in_file > read_rows:
        print(f"Aviso: {in_file - read_rows:,} linha(s) do CSV foram puladas por "
              f"estarem malformadas (provavelmente a última, se o coletor está rodando).")

    df = df.drop(columns=[c for c in DEAD_COLUMNS if c in df.columns])

    # Rule 0: the collector re-downloads an interrupted chunk and appends its
    # rows a second time, so the raw layer legitimately holds duplicates.
    # idCompraItem is the API's unique key.
    before = len(df)
    df = df.drop_duplicates("idCompraItem", keep="first")
    if before > len(df):
        print(f"{before - len(df):,} linha(s) duplicada(s) removida(s) "
              f"({(before - len(df)) / before:.1%} do arquivo).")

    for column in NUMERIC_COLUMNS:
        # errors="coerce": an empty cell becomes NaN instead of raising. Items
        # that were never awarded have no valorTotalResultado at all.
        # astype("float64"): to_numeric alone returns int64 when every value in
        # the column happens to be a whole number, which breaks the promise
        # that these columns are always float64.
        df[column] = pd.to_numeric(df[column], errors="coerce").astype("float64")

    # The API writes class codes as floats ("7010.0"). They are identifiers.
    if "codigoClasse" in df.columns:
        df["codigoClasse"] = (df["codigoClasse"]
                              .str.replace(r"\.0$", "", regex=True)
                              .astype("string"))

    for column in CATEGORY_COLUMNS:
        if column in df.columns:
            df[column] = df[column].astype("category")

    before = len(df)
    df = df[df["situacaoCompraItemNome"] == cfg.status_filter]
    print(f"{before - len(df):,} linha(s) fora de '{cfg.status_filter}' removida(s); "
          f"{len(df):,} restantes.")

    return df.reset_index(drop=True)
