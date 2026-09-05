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
"""

from __future__ import annotations

import csv # .csv files usage
import json # .json files usage
import os # OS and global methods
import time # time management methods
from dataclasses import dataclass, field
from pathlib import Path # path construction methods
from typing import Any, Iterator

# files classes and functions import
import read_type_methods
import error_handlers
from classes.settings import Settings
from classes.checkpoint import Checkpoint
from classes.csv_writer import CsvWriter

import pandas as pd # data analysis lib
import requests # request handling methods
from dotenv import load_dotenv

load_dotenv() # .env file loading

PAGE_SIZE_MIN = 10 # min pagination requests
PAGE_SIZE_MAX = 500 # max pagination requests
SUMMARY_CHUNK_ROWS = 200_000 # CSV chunk rows reading limit

def iter_date_chunks(start: date, end: date, chunk_days: int) -> Iterator[tuple[date, date]]:
    """Splits the window into consecutive chunks so no single request is too wide."""
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=chunk_days), end)
        yield current, chunk_end
        current = chunk_end


def fetch_page(session: requests.Session, settings: Settings, params: dict[str, Any]) -> dict:
    """GETs one page, retrying on throttling, server errors and dropped connections."""
    last_problem = ""

    for attempt in range(1, settings.max_retries + 1):
        try:
            response = session.get(
                settings.items_url, params=params, timeout=settings.request_timeout
            )
        except requests.RequestException as error:
            # The API drops connections when it is throttling, so this is a retry, not a failure.
            last_problem = f"{type(error).__name__}: {error}"
            response = None

        if response is not None:
            if response.status_code < 400:
                return response.json()

            if response.status_code not in (408, 429) and response.status_code < 500:
                raise RuntimeError(
                    f"A API recusou a requisição com status {response.status_code}: "
                    f"{response.text[:300]}"
                )

            last_problem = f"status {response.status_code}"

        if attempt == settings.max_retries:
            raise RuntimeError(
                f"Falha após {settings.max_retries} tentativas ({last_problem}). "
                f"Tente aumentar RETRY_BACKOFF ou reduzir PAGE_SIZE no .env."
            )

        wait = settings.retry_backoff * attempt
        print(f"    {last_problem}; aguardando {wait}s antes de tentar de novo "
              f"(tentativa {attempt}/{settings.max_retries})...")
        time.sleep(wait)

    raise RuntimeError("Falha inesperada ao buscar a página.")


def fetch_chunk(
    session: requests.Session, settings: Settings, start: date, end: date
) -> Iterator[list[dict]]:
    """Yields one page of records at a time, so nothing accumulates in memory."""
    page = 1

    while True:
        params = {
            "dataInclusaoPncpInicial": start.isoformat(),
            "dataInclusaoPncpFinal": end.isoformat(),
            "pagina": page,
            "tamanhoPagina": settings.page_size,
            **settings.filters,
        }

        payload = fetch_page(session, settings, params)
        batch = payload.get("resultado") or []
        if not batch:
            return

        yield batch

        if payload.get("paginasRestantes", 0) <= 0:
            return

        page += 1
        time.sleep(settings.request_delay)


def collect(settings: Settings) -> int:
    checkpoint = Checkpoint(settings.checkpoint_file)

    if settings.resume:
        checkpoint.load()
    else:
        checkpoint.reset()
        settings.output_csv.unlink(missing_ok=True)

    writer = CsvWriter(settings.output_csv, settings.columns, append=settings.resume)
    chunks = list(iter_date_chunks(settings.start_date, settings.end_date, settings.chunk_days))

    try:
        with requests.Session() as session:
            for index, (start, end) in enumerate(chunks, start=1):
                key = f"{start.isoformat()}_{end.isoformat()}"
                label = f"[{index}/{len(chunks)}] {start.isoformat()} → {end.isoformat()}"

                if key in checkpoint.done:
                    print(f"{label}: já baixado, pulando.")
                    continue

                print(f"{label}: baixando...", flush=True)
                chunk_rows = 0
                for batch in fetch_chunk(session, settings, start, end):
                    writer.write(batch)
                    chunk_rows += len(batch)
                    print(f"    {chunk_rows:,} itens...", end="\r", flush=True)

                checkpoint.mark(key)
                print(f"    {chunk_rows:,} itens gravados.          ")
                time.sleep(settings.request_delay)
    finally:
        writer.close()

    return writer.rows_written


def summarize(settings: Settings) -> None:
    """Reads the CSV back in bounded slices and prints the headline numbers."""
    header = pd.read_csv(settings.output_csv, nrows=0, encoding="utf-8-sig")
    available = set(header.columns)

    # valorTotalResultado is the awarded value; valorTotal is only the estimate.
    value_column = "valorTotalResultado" if "valorTotalResultado" in available else "valorTotal"
    if value_column not in available:
        print("\nO CSV não contém colunas de valor; resumo não gerado.")
        return

    group_columns = [c for c in ("materialOuServicoNome", "itemCategoriaNome", "descricaoResumida")
                     if c in available]
    totals: dict[str, pd.Series] = {}
    counts: dict[str, pd.Series] = {}

    reader = pd.read_csv(
        settings.output_csv,
        usecols=group_columns + [value_column],
        chunksize=SUMMARY_CHUNK_ROWS,
        encoding="utf-8-sig",
    )
    for frame in reader:
        frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce").fillna(0)
        for column in group_columns:
            grouped = frame.groupby(column)[value_column]
            totals[column] = totals.get(column, pd.Series(dtype=float)).add(
                grouped.sum(), fill_value=0
            )
            counts[column] = counts.get(column, pd.Series(dtype=float)).add(
                grouped.count(), fill_value=0
            )

    if "materialOuServicoNome" in totals:
        print("\nGasto total por tipo (Material x Serviço):")
        ranking = totals["materialOuServicoNome"].sort_values(ascending=False)
        for name, total in ranking.items():
            quantity = int(counts["materialOuServicoNome"][name])
            print(f"  {str(name):<12} R$ {total:>18,.2f}   ({quantity:,} itens)")

    if "itemCategoriaNome" in totals:
        print(f"\nTop {settings.top_items} categorias por valor:")
        ranking = totals["itemCategoriaNome"].sort_values(ascending=False).head(settings.top_items)
        for name, total in ranking.items():
            print(f"  R$ {total:>18,.2f}  {name}")

    if "descricaoResumida" in totals:
        print(f"\nTop {settings.top_items} itens por valor:")
        ranking = totals["descricaoResumida"].sort_values(ascending=False).head(settings.top_items)
        for name, total in ranking.items():
            print(f"  R$ {total:>18,.2f}  {str(name)[:70]}")


def main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as error:
        print(f"Erro de configuração no .env: {error}")
        return 1

    total_chunks = len(list(iter_date_chunks(settings.start_date, settings.end_date, settings.chunk_days)))
    print(f"Período: {settings.start_date.isoformat()} até {settings.end_date.isoformat()} "
          f"({settings.window_days} dias, {total_chunks} blocos de {settings.chunk_days} dias)")
    if settings.filters:
        print(f"Filtros: {settings.filters}")
    print(f"Saída:   {settings.output_csv}")

    try:
        rows = collect(settings)
    except RuntimeError as error:
        print(f"\nErro: {error}")
        print("O progresso foi salvo. Rode de novo com RESUME=true para continuar de onde parou.")
        return 1
    except KeyboardInterrupt:
        print("\nInterrompido. Rode de novo com RESUME=true para continuar de onde parou.")
        return 130

    if not settings.output_csv.exists() or settings.output_csv.stat().st_size == 0:
        print("\nNenhum item retornado para o período e filtros informados.")
        return 0

    print(f"\n{rows:,} itens gravados nesta execução em {settings.output_csv}")
    summarize(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
