import csv
from pathlib import Path

class CsvWriter:
    """Appends records to a CSV, writing the header only once."""

    def __init__(self, path: Path, columns: list[str], append: bool):
        self.path = path
        self.columns = columns
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.header_written = append and path.exists() and path.stat().st_size > 0
        self.handle = path.open("a" if append else "w", newline="", encoding="utf-8-sig")
        self.writer: csv.DictWriter | None = None
        self.rows_written = 0

    def write(self, records: list[dict]) -> None:
        if not records:
            return

        if self.writer is None:
            fieldnames = self.columns or list(records[0].keys())
            self.writer = csv.DictWriter(self.handle, fieldnames=fieldnames, extrasaction="ignore")
            if not self.header_written:
                self.writer.writeheader()
                self.header_written = True

        self.writer.writerows(records)
        self.handle.flush()
        self.rows_written += len(records)

    def close(self) -> None:
        self.handle.close()