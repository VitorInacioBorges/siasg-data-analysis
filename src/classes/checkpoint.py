"""
Crash-resume bookkeeping for the download.

A full year of items is thousands of requests and hours of runtime, so an
interruption must not mean starting over. This class holds the one fact needed
to resume: the set of date chunks whose rows are already safely in the CSV.

The unit of progress is the whole chunk, never a page. A chunk is recorded only
after its last page is written, so a crash mid-chunk simply re-downloads that
chunk — costing a few duplicate requests instead of risking a gap in the data.
"""

# Postpones evaluation of type annotations, matching the rest of the package.
from __future__ import annotations

import json
import os  # os.replace, the atomic rename mark() relies on
from pathlib import Path  # path construction methods


class Checkpoint:
    """Records which date chunks are already on disk, so a run can resume."""

    def __init__(self, path: Path):
        # Where the progress file lives; nothing is read or written yet.
        self.path = path
        # Chunk keys already finished, in the "START_END" form main.py builds.
        # Starts empty: load() fills it, reset() clears it back to this state.
        self.done: set[str] = set()

    def load(self) -> None:
        """Restores progress from a previous run (called only when RESUME is on)."""
        if not self.path.exists():
            # First run, or the file was deleted — an empty set is correct.
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            # .get() with a default tolerates a file written by an older version.
            self.done = set(payload.get("completed_chunks", []))
        except (json.JSONDecodeError, OSError) as error:
            # Should no longer happen now that mark() writes atomically, but a
            # file damaged by something else is still not worth aborting for:
            # warn and re-download rather than lose the run.
            print(f"Aviso: não foi possível ler o checkpoint ({error}). Começando do zero.")
            self.done = set()

    def mark(self, key: str) -> None:
        """Records one finished chunk and flushes the whole set to disk.

        Rewriting the entire file on every chunk is deliberate: it is a few
        kilobytes at most, and writing it whole avoids a partially appended
        file. The write goes to a temporary file first and is then renamed over
        the real one, because os.replace is atomic: a kill at any instant
        leaves either the previous complete snapshot or the new one, never a
        truncated file. Writing in place would leave a half-written JSON, and
        load() would answer that by discarding *all* recorded progress.
        """
        self.done.add(key)
        # The data/ directory may not exist on a first run.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # sorted() keeps the file stable and readable across runs.
        payload = {"completed_chunks": sorted(self.done)}
        # Same directory as the target: os.replace is only atomic within one
        # filesystem, and a temp dir could sit on another one.
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def reset(self) -> None:
        """Discards all progress — used when the run is starting fresh.

        Pairs with deleting the CSV in collect(): the checkpoint and the CSV
        must always describe the same download, or resume would append rows on
        top of a file that no longer matches.
        """
        self.done = set()
        # missing_ok keeps this a no-op when there is nothing to delete.
        self.path.unlink(missing_ok=True)
        # A temp file left behind by a kill mid-write would otherwise linger.
        self.path.with_name(self.path.name + ".tmp").unlink(missing_ok=True)
