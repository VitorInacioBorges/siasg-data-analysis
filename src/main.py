"""
Collects procurement item data from the Compras.gov.br open data API.

Each record is one item of a public contract under Law 14.133/2021, already
classified by the API as Material or Service and carrying its value. That is
what makes it possible to answer: what has the government been spending on?

API docs: https://dadosabertos.compras.gov.br/swagger-ui/index.html
Endpoint: /modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133
No API key required.

Scale note: a one-year window is roughly 5 million items over ~10,000
requests. Chunks are therefore streamed straight to CSV rather than held in
memory, and every finished chunk is checkpointed so an interrupted run can
resume instead of starting over.

Every setting lives in the .env file — see .env.example.
Query parameter names stay in Portuguese because that is the API contract.

Shape of the program, outermost first:
    main()          reads config, prints the plan, handles the exit code
    collect()       walks the chunks, owns the checkpoint and the writer
    fetch_chunk()   pages through one date range
    fetch_page()    a single HTTP GET, with retries
    summarize()     reads the finished CSV back and prints the rankings
Each layer only knows about the one below it, which is why an error can be
raised deep in fetch_page() and still be reported cleanly in main().
"""

# Postpones evaluation of type annotations, so builtin generics like
# `dict[str, Any]` work on Python versions before 3.9/3.10.
from __future__ import annotations

import threading
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Iterator

from read_type_methods import ConfigError

from classes.settings import Settings
from classes.checkpoint import Checkpoint
from classes.csv_writer import CsvWriter

import pandas as pd 
import requests 

from dotenv import load_dotenv

load_dotenv() # .env file loading

# Fronteira de referência da grade de blocos: uma segunda-feira arbitrária,
# fixa para sempre. Todas as fronteiras válidas são EPOCH + k * chunk_days.
# Ancorar numa data absoluta (em vez de contar a partir da ponta da janela) é
# o que faz a chave de um bloco ser a mesma ontem, hoje e amanhã — sem isso,
# o checkpoint de uma execução não serve para a seguinte.
CHUNK_EPOCH = date(2000, 1, 3)

def align_to_grid(day: date, chunk_days: int) -> date:
    """Recua `day` até a fronteira anterior da grade global."""
    # O resto da divisão diz quantos dias `day` está depois da última
    # fronteira; subtraí-lo pousa exatamente nela.
    return day - timedelta(days=(day - CHUNK_EPOCH).days % chunk_days)

def iter_date_chunks(start: date, end: date, chunk_days: int) -> Iterator[tuple[date, date]]:
    """Splits the window into consecutive chunks so no single request is too wide."""
    # Começa na fronteira da grade, não na ponta da janela. Isso baixa alguns
    # dias a mais que WINDOW_DAYS pediu — um superconjunto, nunca um buraco.
    current = align_to_grid(start, chunk_days)
    while current < end:
        # Sem min(): a grade define o fim, mesmo que ele passe de `end`. Um
        # bloco truncado teria uma chave que mudaria na próxima execução, que
        # é justamente o que estamos consertando.
        chunk_end = current + timedelta(days=chunk_days)
        yield current, chunk_end
        current = chunk_end


def fetch_page(session: requests.Session, settings: Settings, params: dict[str, Any]) -> dict:
    """GETs one page, retrying on throttling, server errors and dropped connections."""
    # Remembers why the previous attempt failed, so the final error message can
    # say what actually went wrong rather than just "it failed".
    last_problem = ""

    # Attempts are numbered from 1 because the number is both displayed to the
    # user and used as the backoff multiplier below.
    for attempt in range(1, settings.max_retries + 1):
        try:
            response = session.get(
                settings.items_url, params=params, timeout=settings.request_timeout
            )
        except requests.RequestException as error:
            # The API drops connections when it is throttling, so this is a retry, not a failure.
            last_problem = f"{type(error).__name__}: {error}"
            # None marks "no response at all", which the block below skips over
            # to land directly on the retry path.
            response = None

        if response is not None:
            # Anything under 400 is a success; the body is the JSON payload.
            if response.status_code < 400:
                try:
                    return response.json()
                except ValueError as error:
                    # 200 with a body that is not JSON — a maintenance page or
                    # a proxy's HTML. Decoding it must happen inside the retry
                    # loop: left outside, the error would escape both this loop
                    # and main()'s handler, ending the run in a raw traceback
                    # with no hint that the download can be resumed. Treated
                    # like a dropped connection, because it is just as temporary.
                    last_problem = f"resposta não era JSON ({type(error).__name__}: {error})"

            # 4xx means the request itself is wrong (bad filter, bad date) and
            # would fail identically forever — so fail immediately instead of
            # burning the retry budget. The two exceptions are 408 (timeout)
            # and 429 (too many requests), which are temporary by definition.
            elif response.status_code not in (408, 429) and response.status_code < 500:
                raise RuntimeError(
                    f"A API recusou a requisição com status {response.status_code}: "
                    # Truncated: an HTML error page would otherwise flood the terminal.
                    f"{response.text[:300]}"
                )

            # Left over: 408, 429 and every 5xx — all worth retrying.
            else:
                last_problem = f"status {response.status_code}"

        # Budget exhausted. Raising RuntimeError (rather than exiting) lets
        # collect() run its finally block and main() print the resume hint.
        if attempt == settings.max_retries:
            raise RuntimeError(
                f"Falha após {settings.max_retries} tentativas ({last_problem}). "
                f"Tente aumentar RETRY_BACKOFF ou reduzir PAGE_SIZE no .env."
            )

        # Linear backoff: 15s, 30s, 45s… Each wait is longer than the last, so
        # a throttled API is given progressively more room to recover.
        wait = settings.retry_backoff * attempt
        print(f"    {last_problem}; aguardando {wait}s antes de tentar de novo "
              f"(tentativa {attempt}/{settings.max_retries})...")
        time.sleep(wait)

    # Unreachable: the loop either returns or raises. Present so the function
    # cannot fall through to an implicit None if the logic above ever changes.
    raise RuntimeError("Falha inesperada ao buscar a página.")


def fetch_chunk(
    session: requests.Session, settings: Settings, start: date, end: date
) -> Iterator[list[dict]]:
    """Yields one page of records at a time, so nothing accumulates in memory."""
    # The API numbers pages from 1.
    page = 1

    # No page count is known up front; the loop runs until the API says there
    # is nothing left. The two `return`s below are its exit conditions.
    while True:
        params = {
            # Window bounds, in the ISO form the API expects.
            "dataInclusaoPncpInicial": start.isoformat(),
            "dataInclusaoPncpFinal": end.isoformat(),
            "pagina": page,
            "tamanhoPagina": settings.page_size,
            # Unpacked last, so the user's .env filters are merged in alongside
            # the pagination parameters.
            **settings.filters,
        }

        payload = fetch_page(session, settings, params)
        # `or []` covers both a missing key and an explicit null in the JSON.
        batch = payload.get("resultado") or []
        if not batch:
            # Empty page: the range is exhausted (or was empty to begin with).
            return

        # yield, not return: the caller writes this page to disk and comes back
        # for the next one, so only one page is ever held in memory.
        yield batch

        # The API reports how many pages remain; zero means this was the last.
        # The default of 0 makes a missing field stop the loop rather than spin.
        if payload.get("paginasRestantes", 0) <= 0:
            return

        page += 1
        # Politeness delay between pages — the main defence against throttling.
        time.sleep(settings.request_delay)


def collect(settings: Settings) -> int:
    """Downloads the whole window chunk by chunk. Returns rows written this run.

    Owns the two pieces of durable state — the checkpoint and the CSV — and
    keeps them consistent: a chunk is marked done only after all of its rows
    have been flushed.
    """
    checkpoint = Checkpoint(settings.checkpoint_file)

    if settings.resume:
        # Continue a previous run: load which chunks are already on disk.
        checkpoint.load()
    else:
        # Fresh start. Checkpoint and CSV are cleared together — keeping one
        # without the other would mean either duplicated or missing rows.
        checkpoint.reset()
        settings.output_csv.unlink(missing_ok=True)

    # append mirrors resume: continue the existing file, or truncate it.
    writer = CsvWriter(settings.output_csv, settings.columns, append=settings.resume)
    # Materialised into a list (rather than left lazy) so len() can drive the
    # "[3/52]" progress counter.
    chunks = list(iter_date_chunks(settings.start_date, settings.end_date, settings.chunk_days))

    # Threads share memory, so every piece of state touched by more than one
    # of them needs a lock. There are exactly two: the CSV handle and the
    # checkpoint. Each is held for microseconds, against ~300ms of network
    # wait per request — the contention is negligible.
    lock_csv = threading.Lock()
    lock_checkpoint = threading.Lock()

    # requests.Session is not documented as thread-safe, so each thread gets
    # its own. threading.local() is an object whose attributes are private per
    # thread: `local.session` in thread A and in thread B are different
    # objects. Keep-alive still applies within each thread.
    local = threading.local()
    sessions: list[requests.Session] = []
    lock_sessions = threading.Lock()

    def session_for_thread() -> requests.Session:
        session = getattr(local, "session", None)
        if session is None:
            session = requests.Session()
            local.session = session
            # Kept in a list only so the finally block below can close them
            # all; the threads themselves never read this list.
            with lock_sessions:
                sessions.append(session)
        return session

    def download_chunk(index: int, start: date, end: date) -> int:
        """Downloads one whole chunk. Runs inside a worker thread.

        Written as a closure so it can reach the writer, the checkpoint and
        the locks without a nine-argument signature. Everything it touches is
        scoped to this one collect() call — there is no module-level state.
        """
        # The checkpoint identity of this chunk. Anchored to the calendar grid,
        # so the same chunk always produces the same key across runs.
        key = f"{start.isoformat()}_{end.isoformat()}"
        label = f"[{index}/{len(chunks)}] {start.isoformat()} → {end.isoformat()}"

        # Already downloaded by an earlier run — this is what resume buys.
        if key in checkpoint.done:
            print(f"{label}: já baixado, pulando.")
            return 0

        chunk_rows = 0
        for batch in fetch_chunk(session_for_thread(), settings, start, end):
            # Critical section 1: the file. csv.DictWriter.writerows is not
            # atomic — two threads writing at once interleave bytes in the
            # middle of a row. Deliberately short: the network wait happens
            # outside it, which is what lets the other threads run.
            with lock_csv:
                writer.write(batch)
            chunk_rows += len(batch)
            time.sleep(settings.request_delay)

        # A chunk whose end is still in the future keeps receiving items, so
        # marking it now would make the next run skip data that had not
        # arrived yet. Only closed chunks are recorded; the open one is
        # re-downloaded every run, which is exactly what keeps it current.
        if end <= date.today():
            # Critical section 2: the checkpoint. Reached only after every
            # page of this chunk is written — the order that keeps the mark
            # from ever claiming rows that are not on disk.
            with lock_checkpoint:
                checkpoint.mark(key)
            print(f"{label}: {chunk_rows:,} itens gravados.")
        else:
            print(f"{label}: {chunk_rows:,} itens gravados "
                  f"(bloco ainda aberto, será rebaixado na próxima execução).")
        return chunk_rows

    # Not a `with` block: on Ctrl+C or an API failure, `with` would wait for
    # every queued chunk to run before propagating. shutdown(cancel_futures)
    # drops the ones that have not started, so only the in-flight chunks
    # finish — seconds instead of the rest of the download.
    pool = ThreadPoolExecutor(max_workers=settings.max_workers)
    try:
        # submit() schedules the call and returns a Future — a promise of a
        # result that is not ready yet.
        futures = [
            pool.submit(download_chunk, index, start, end)
            for index, (start, end) in enumerate(chunks, start=1)
        ]
        # as_completed yields each Future as it finishes, in completion order
        # rather than submission order. .result() re-raises, in this thread,
        # whatever the worker raised — which is how fetch_page's RuntimeError
        # still reaches main() and prints the resume hint.
        for future in as_completed(futures):
            future.result()
    finally:
        # cancel_futures drops the chunks still queued; wait=True lets the
        # running ones finish writing, so the CSV is never cut mid-row.
        pool.shutdown(wait=True, cancel_futures=True)
        for session in sessions:
            session.close()
        # The CSV is closed last and always — on an API failure or a Ctrl+C
        # alike, the file must stay consistent with the checkpoint.
        writer.close()

    return writer.rows_written


def summarize(settings: Settings) -> None:
    """Reads the CSV back in bounded slices and prints the headline numbers."""
    # nrows=0 reads the header alone, so the available columns can be inspected
    # without loading a multi-gigabyte file.
    header = pd.read_csv(settings.output_csv, nrows=0, encoding="utf-8-sig")
    available = set(header.columns)

    # valorTotalResultado is the awarded value; valorTotal is only the estimate.
    value_column = "valorTotalResultado" if "valorTotalResultado" in available else "valorTotal"
    # Reachable when COLUMNS excluded both: there is nothing to sum.
    if value_column not in available:
        print("\nO CSV não contém colunas de valor; resumo não gerado.")
        return

    # Group by whichever of the three dimensions the CSV actually contains, so
    # a narrowed COLUMNS list degrades the summary instead of crashing it.
    group_columns = [c for c in ("materialOuServicoNome", "itemCategoriaNome", "descricaoResumida")
                     if c in available]
    # Running totals per dimension, accumulated across chunks:
    # {column name -> Series indexed by group value}.
    totals: dict[str, pd.Series] = {}
    counts: dict[str, pd.Series] = {}

    # chunksize turns read_csv into an iterator of frames, so peak memory stays
    # proportional to one chunk rather than to the whole file. usecols narrows
    # each frame to the columns the summary actually needs.
    reader = pd.read_csv(
        settings.output_csv,
        usecols=group_columns + [value_column],
        # SUMMARY_CHUNK_ROWS in the .env: reads the file in fixed-size slices,
        # so peak memory follows one slice rather than the whole CSV.
        chunksize=settings.summary_chunk_rows,
        encoding="utf-8-sig",
    )
    for frame in reader:
        # errors="coerce" turns unparseable values into NaN instead of raising;
        # fillna(0) then keeps them from poisoning the sums.
        frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce").fillna(0)
        for column in group_columns:
            grouped = frame.groupby(column)[value_column]
            # .add(..., fill_value=0) merges this chunk's groups into the
            # running total. fill_value matters because a group present in one
            # chunk and absent in another would otherwise become NaN.
            totals[column] = totals.get(column, pd.Series(dtype=float)).add(
                grouped.sum(), fill_value=0
            )
            counts[column] = counts.get(column, pd.Series(dtype=float)).add(
                grouped.count(), fill_value=0
            )

    # Report 1: Material vs Service. Only two groups, so the full ranking prints.
    if "materialOuServicoNome" in totals:
        print("\nGasto total por tipo (Material x Serviço):")
        ranking = totals["materialOuServicoNome"].sort_values(ascending=False)
        for name, total in ranking.items():
            # counts holds floats after the .add() arithmetic; int() for display.
            quantity = int(counts["materialOuServicoNome"][name])
            # <12 left-pads the label, >18,.2f right-aligns the money column.
            print(f"  {str(name):<12} R$ {total:>18,.2f}   ({quantity:,} itens)")

    # Report 2: the biggest spending categories, capped by TOP_ITEMS.
    if "itemCategoriaNome" in totals:
        print(f"\nTop {settings.top_items} categorias por valor:")
        ranking = totals["itemCategoriaNome"].sort_values(ascending=False).head(settings.top_items)
        for name, total in ranking.items():
            print(f"  R$ {total:>18,.2f}  {name}")

    # Report 3: the biggest individual items, by their short description.
    if "descricaoResumida" in totals:
        print(f"\nTop {settings.top_items} itens por valor:")
        ranking = totals["descricaoResumida"].sort_values(ascending=False).head(settings.top_items)
        for name, total in ranking.items():
            # Descriptions run long; [:70] keeps each ranking line on one row.
            print(f"  R$ {total:>18,.2f}  {str(name)[:70]}")


def main() -> int:
    """Entry point. Returns the process exit code rather than exiting itself."""
    try:
        settings = Settings.from_env() # validates everythings before the first requisition
    except ConfigError as error:
        # A configuration mistake is the user's to fix, so it is reported as a
        # plain message instead of a traceback.
        print(f"Erro de configuração no .env: {error}")
        return 1

    # Recomputed here only to show the plan before the download starts; the
    # generator is consumed a second time inside collect().
    total_chunks = len(list(iter_date_chunks(settings.start_date, settings.end_date, settings.chunk_days)))
    print(f"Período: {settings.start_date.isoformat()} até {settings.end_date.isoformat()} "
          f"({settings.window_days} dias, {total_chunks} blocos de {settings.chunk_days} dias)")
    # Printed only when filters exist, so an unfiltered run stays quiet.
    if settings.filters:
        print(f"Filtros: {settings.filters}")
    print(f"Saída:   {settings.output_csv}")

    try:
        rows = collect(settings)
    except RuntimeError as error:
        # Raised by fetch_page() once the retries are spent. The rows already
        # downloaded are safe on disk, hence the resume hint.
        print(f"\nErro: {error}")
        print("O progresso foi salvo. Rode de novo com RESUME=true para continuar de onde parou.")
        return 1
    except KeyboardInterrupt:
        # Ctrl+C. collect()'s finally block has already closed the CSV, so the
        # partial download is intact and resumable.
        print("\nInterrompido. Rode de novo com RESUME=true para continuar de onde parou.")
        # 130 is the conventional shell code for "terminated by SIGINT".
        return 130

    # An empty or absent file means the window and filters matched nothing.
    # That is a valid outcome, not an error, so the exit code stays 0 — and
    # summarize() is skipped, since it would have no columns to read.
    if not settings.output_csv.exists() or settings.output_csv.stat().st_size == 0:
        print("\nNenhum item retornado para o período e filtros informados.")
        return 0

    # rows counts this run only; on a resumed run the file holds more.
    print(f"\n{rows:,} itens gravados nesta execução em {settings.output_csv}")
    summarize(settings)
    return 0


if __name__ == "__main__":
    # Runs only on direct execution, never on import. SystemExit propagates
    # main()'s return value to the shell as the process exit code.
    raise SystemExit(main())
