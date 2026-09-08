"""
Streaming CSV sink for the downloaded items.

The dataset is far too large to hold in memory, so rows go to disk as soon as
they arrive. This class wraps that with the two rules the rest of the program
depends on: the header appears exactly once no matter how many batches are
written, and each batch is flushed immediately so an interrupted run leaves a
CSV that matches the checkpoint.

A third rule follows from resume: when appending to a file that already has a
header, that header decides the columns. The file must describe one schema
from first row to last, so what is already on disk wins over COLUMNS.
"""

# Postpones evaluation of type annotations, matching the rest of the package.
from __future__ import annotations

import csv
from pathlib import Path

class CsvWriter:
    """Appends records to a CSV, writing the header only once."""

    def __init__(self, path: Path, columns: list[str], append: bool):
        self.path = path
        # Explicit column list from COLUMNS; empty means "infer from the data".
        self.columns = columns
        # Create data/ before opening the file for writing.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A header is already present only when resuming onto a non-empty file.
        # All three conditions matter: append mode, the file exists, and it has
        # content (an existing but empty file still needs its header).
        self.header_written = append and path.exists() and path.stat().st_size > 0
        # The columns that file already uses, read back before anything is
        # appended. None when starting fresh.
        self.existing_header = self._read_existing_header() if self.header_written else None
        if self.existing_header and self.columns and self.columns != self.existing_header:
            # COLUMNS changed between runs. Appending under the new list would
            # write rows that do not line up with the header already on disk —
            # a silently corrupt CSV. The existing header wins; say so loudly,
            # because the fix is to start a fresh run with RESUME=false.
            print(
                "Aviso: COLUMNS mudou desde a execução anterior. O cabeçalho já gravado "
                f"em {path} tem {len(self.existing_header)} colunas e será mantido; "
                "as colunas novas do .env serão ignoradas nesta retomada. "
                "Para aplicar a nova lista, rode do zero com RESUME=false."
            )
        # "a" preserves earlier rows when resuming; "w" truncates for a fresh run.
        # newline="" is required by the csv module to avoid blank lines on Windows.
        # utf-8-sig writes the BOM Excel needs to show accented text correctly.
        self.handle = path.open("a" if append else "w", newline="", encoding="utf-8-sig")
        # Built lazily on the first non-empty batch, because the fieldnames may
        # have to be taken from the data itself.
        self.writer: csv.DictWriter | None = None
        # Counts only rows written by this run, which is what main.py reports.
        self.rows_written = 0

    def _read_existing_header(self) -> list[str] | None:
        """Returns the column names already in the file, or None if unreadable.

        Opened separately from the append handle and closed straight away: this
        is one short read at startup, before a single row is written.
        """
        try:
            with self.path.open("r", newline="", encoding="utf-8-sig") as handle:
                return next(csv.reader(handle), None)
        except OSError as error:
            # An unreadable file is not fatal here — write() falls back to
            # COLUMNS, and the append itself will fail later if it truly cannot
            # be written to.
            print(f"Aviso: não foi possível ler o cabeçalho de {self.path} ({error}).")
            return None

    def write(self, records: list[dict]) -> None:
        """Appends one page of records and flushes it to disk."""
        if not records:
            # Nothing to write, and nothing to infer fieldnames from either.
            return

        if self.writer is None:
            # First batch: decide the columns. The header already on disk wins,
            # so a resumed run keeps writing the schema the file was started
            # with; then COLUMNS; then the first record's keys.
            fieldnames = self.existing_header or self.columns or list(records[0].keys())
            # extrasaction="ignore" drops API fields outside the chosen columns
            # instead of raising, so COLUMNS can be a subset and new fields
            # added by the API upstream cannot break the run.
            self.writer = csv.DictWriter(self.handle, fieldnames=fieldnames, extrasaction="ignore")
            if not self.header_written:
                self.writer.writeheader()
                self.header_written = True

        self.writer.writerows(records)
        # Flush per batch: the checkpoint must never claim rows the OS is still
        # holding in a buffer.
        self.handle.flush()
        self.rows_written += len(records)

    def close(self) -> None:
        """Releases the file handle; called from collect()'s finally block."""
        self.handle.close()
