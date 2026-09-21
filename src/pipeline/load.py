"""
Faithful read of the collector's output.

Does three things and only three: deduplicate, drop the dead columns, filter by
status. Anything that requires a judgement call about the data belongs in
clean.py — this module's job is to hand the next stage a typed, honest frame.

The raw CSV is several hundred megabytes — 859 MB and 3,5 million rows as
measured — and may be mid-write while the collector runs, so the read tolerates
a truncated last line.

What "tolerant" means precisely, because the obvious reading is wrong: pandas
skips a row with extra fields, NaN-pads a row with missing fields, and raises
outright if a truncation lands inside a quoted field. Only the first of those
is `on_bad_lines`. So the module checks for a partial last row itself, drops it,
and turns the parser error into a message that names the cause.

A note on `chunksize`, so nobody reads more into it than is there: the frame is
concatenated immediately, because deduplicating needs a whole-file view and
duplicates cross chunk boundaries. So the slices do not bound peak memory here
— they only change how the parser is invoked. The honest floor for this
function is one full frame in memory.
"""

from __future__ import annotations

import warnings
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


def _pt_br(number: float, decimals: int = 0) -> str:
    """Formats a number the way the messages around it are written.

    Python's own thousands separator is the comma and its decimal mark the
    period — the opposite of Brazilian convention. Every message in this
    module is Portuguese, so "3.517.673" and "23,4%" are what the reader
    expects, not "3,517,673" and "23.4%".
    """
    texto = f"{number:,.{decimals}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _snapshot(path: Path) -> tuple[int, int]:
    """Size and mtime — the pair that says whether the file moved.

    Its own function so a test can replace it deterministically, instead of
    patching Path.stat and catching every incidental call.
    """
    info = path.stat()
    return info.st_size, info.st_mtime_ns


def _ends_mid_row(path: Path) -> bool:
    """True when the file does not end in a newline — its last row is partial.

    This is the only reliable signal that the collector was cut off mid-write,
    and it matters because pandas cannot tell. Measured against pandas 3.0.5:
    `on_bad_lines="skip"` discards a row with EXTRA fields, but a row with
    MISSING fields — which is what a truncated line is — gets NaN-padded and
    kept. The newline count cannot see it either, since an unterminated line
    contributes no newline byte, so the skipped-line comparison stays silent
    and the half row reaches the panel.

    CsvWriter writes through the csv module, which always emits a line
    terminator, so for this pipeline's own raw file a missing final newline
    means truncation and nothing else.
    """
    with path.open("rb") as handle:
        if handle.seek(0, 2) == 0:
            return False          # empty file: nothing to be partial
        handle.seek(-1, 2)
        return handle.read(1) != b"\n"


def load_raw(path: Path, cfg: PipelineSettings) -> pd.DataFrame:
    """Reads the raw CSV, deduplicates it, and returns the item grain."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} não existe. Rode o coletor primeiro: python src/main.py"
        )

    # Snapshot taken before both passes and compared after them. The skipped
    # line count subtracts two numbers produced by two separate reads, so it is
    # only meaningful if the file did not change in between — and the collector
    # appending mid-read is exactly the case this module claims to tolerate.
    # Without this guard, rows appended between the passes would be reported as
    # malformed: a false alarm in the one scenario the warning exists for.
    before = _snapshot(path)
    partial_tail = _ends_mid_row(path)

    slices = pd.read_csv(
        path,
        encoding="utf-8-sig",
        chunksize=cfg.read_chunk_rows,
        # "warn" rather than "skip": both discard a row with EXTRA fields,
        # but "warn" makes pandas say so, in its own words, instead of leaving
        # us to infer it. Rows with MISSING fields are NaN-padded either way,
        # which is why _ends_mid_row exists.
        on_bad_lines="warn",
        parse_dates=["dataInclusaoPncp"],
        dtype={c: "string" for c in TEXT_COLUMNS},
        low_memory=False,
    )
    try:
        with warnings.catch_warnings(record=True) as parser_warnings:
            warnings.simplefilter("always", pd.errors.ParserWarning)
            frames = list(slices)
    except pd.errors.ParserError as error:
        # Truncation landing inside a quoted field raises instead of skipping,
        # and on_bad_lines does not catch it. A clear message beats a traceback
        # the reader has to decode.
        raise RuntimeError(
            f"O CSV bruto ficou ilegível a partir de algum ponto ({error}). "
            f"Isso acontece quando o coletor é interrompido no meio de um campo "
            f"entre aspas. Espere o coletor terminar, ou rode-o de novo com "
            f"RESUME=true para completar o arquivo."
        ) from None
    df = pd.concat(frames, ignore_index=True)

    # Whether the file moved is decided BEFORE anything acts on the earlier
    # measurements, because all of them came from separate reads. Acting first
    # and disclaiming afterwards is what the previous version did, and it
    # discarded a legitimate row whenever the collector finished its write
    # during the parse: the drop had already happened by the time the warning
    # printed.
    changed = _snapshot(path) != before

    if changed:
        # No check before or after the parse is exact on a file being appended
        # to — a post-parse check only moves the window, it does not close it.
        # Two orderings, two opposite wrong answers, and nothing distinguishes
        # them from here. So the honest move is to act on none of it.
        #
        # This does not disclaim the CSV-reader warnings printed below: those
        # come from pandas itself, live during the parse, and hold regardless
        # of what the file does afterwards — only the partial-row heuristic
        # depends on a stale pre-parse snapshot.
        print("Aviso: o arquivo mudou durante a leitura — o coletor está rodando? "
              "A detecção de linha parcial não vale para esta execução, e "
              "nenhuma linha foi descartada por isso. Rode de novo quando a "
              "coleta terminar.")
    else:
        # Nothing moved, so the pre-read check describes the bytes pandas
        # parsed. The partial row goes first: NaN-padded and with its id
        # intact, it would survive dedup, add zero to every sum, and quietly
        # understate the panel.
        if partial_tail and len(df):
            df = df.iloc[:-1]
            print("Aviso: a última linha do CSV estava pela metade e foi "
                  "descartada (o coletor foi interrompido?).")

    # Reported whether or not the file moved: these are pandas' own words about
    # rows it discarded, and they are true regardless.
    #
    # This replaces an earlier count of our own, which subtracted the rows
    # pandas returned from the newlines in the file. That arithmetic was wrong
    # on this data: `descricaoResumida` contains newlines inside quoted fields —
    # 218.100 of them, measured — so the byte count exceeded the row count by
    # exactly that much and every run announced "218.100 linhas puladas" when
    # nothing had been skipped at all. Counting correctly means tracking quote
    # parity across 859 MB, which measured 7,85s against 0,39s for the naive
    # version. Asking pandas is exact and free.
    for warning in parser_warnings:
        print(f"Aviso do leitor de CSV: {str(warning.message)[:300]}")

    df = df.drop(columns=[c for c in DEAD_COLUMNS if c in df.columns])

    # Rule 0: the collector re-downloads an interrupted chunk and appends its
    # rows a second time, so the raw layer legitimately holds duplicates.
    # idCompraItem is the API's unique key.
    before = len(df)
    df = df.drop_duplicates("idCompraItem", keep="first")
    # `before > 0` guards a header-only file, where the percentage would divide
    # by zero.
    if before > 0 and before > len(df):
        removed = before - len(df)
        print(f"{_pt_br(removed)} linha(s) duplicada(s) removida(s) "
              f"({_pt_br(removed / before * 100, 1)}% do arquivo).")

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

    before = len(df)
    df = df[df["situacaoCompraItemNome"] == cfg.status_filter]
    print(f"{_pt_br(before - len(df))} linha(s) fora de '{cfg.status_filter}' "
          f"removida(s); {_pt_br(len(df))} restantes.")

    # Category conversion comes after the filter on purpose: converting first
    # would leave "Fracassado" and the other discarded statuses as dead
    # categories in the dtype's metadata.
    for column in CATEGORY_COLUMNS:
        if column in df.columns:
            df[column] = df[column].astype("category")

    return df.reset_index(drop=True)
