"""
Every knob the data pipeline has, in one object.

Sibling of Settings: same contract, different concern. Settings configures the
collector that produces data/raw/; this configures the stages that consume it.
They are separate classes because they are read at different times by different
entry points, and a run of one does not need the other's validation to pass.
"""

# Postpones evaluation of type annotations, matching the rest of the package.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from read_type_methods import _read_float_min, _read_int_min, _read_text

# Anchored to this file, not to the caller's frame. `load_dotenv()` with no
# argument walks up from whoever called it, and under `python -c` there is no
# calling file at all — it falls back to the working directory, finds nothing,
# and every value silently becomes the dataclass default. Measured: a .env
# saying MAX_WORKERS=2 read back as 3. For a data pipeline that is the worst
# kind of failure, because the run succeeds with the wrong configuration.
CAMINHO_ENV = Path(__file__).resolve().parent.parent / ".env"
if CAMINHO_ENV.exists():
    load_dotenv(CAMINHO_ENV)
else:
    print(f"Aviso: {CAMINHO_ENV} não existe; usando apenas os valores padrão.")


@dataclass
class PipelineSettings:
    """Validated configuration for one pipeline run."""

    raw_csv: Path
    interim_dir: Path
    processed_dir: Path
    figures_dir: Path
    panel_freq: str = "W"
    top_classes: int = 50
    qty_mad_threshold: float = 8.0
    min_class_items: int = 30
    status_filter: str = "Homologado"
    read_chunk_rows: int = 200_000

    @classmethod
    def from_env(cls) -> "PipelineSettings":
        """Builds a PipelineSettings from .env, validating as it goes."""
        # One root for all three layers, so a test run redirects everything by
        # setting a single variable.
        raiz = Path(_read_text("DATA_DIR", "data"))
        return cls(
            raw_csv=raiz / "raw" / _read_text("RAW_CSV_NAME", "contract_items.csv"),
            interim_dir=raiz / "interim",
            processed_dir=raiz / "processed",
            figures_dir=Path(_read_text("FIGURES_DIR", "reports/figures")),
            panel_freq=_read_text("PANEL_FREQ", "W"),
            # A floor of 1 everywhere a zero would make the stage meaningless:
            # zero classes leaves nothing to group by, a zero threshold flags
            # every row, and a zero chunk makes pandas raise.
            top_classes=_read_int_min("TOP_CLASSES", 50, 1),
            qty_mad_threshold=_read_float_min("QTY_MAD_THRESHOLD", 8.0, 0.1),
            min_class_items=_read_int_min("MIN_CLASS_ITEMS", 30, 1),
            status_filter=_read_text("STATUS_FILTER", "Homologado"),
            read_chunk_rows=_read_int_min("READ_CHUNK_ROWS", 200_000, 1),
        )
