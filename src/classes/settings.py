"""
This is a docstring
Every knob the program has, in one immutable object.

The design rule here is that the .env file is read exactly once, at startup, by
Settings.from_env(). Everything downstream — the request loop, the writer, the
summary — receives a validated Settings instance and never touches os.getenv
again. A bad configuration therefore fails in the first second of the run,
before a single request is sent, instead of hours in.

Filter keys are kept in Portuguese because they are sent verbatim as API query
parameters; the .env names around them are English for the reader's benefit.
"""

# Postpones evaluation of type annotations, matching the rest of the package.
from __future__ import annotations

from dataclasses import dataclass, field # dataclass and dataclasses fields
from pathlib import Path                 # Path object to read paths
from datetime import date, timedelta     # date methods
from dotenv import load_dotenv           # reads .env

# read_type_methods.py sits in src/, the directory main.py runs from, so it is
# imported by its plain module name — exactly as main.py imports it.
from read_type_methods import (
    ConfigError,
    _read_bool,
    _read_date,
    _read_float,
    _read_float_min,
    _read_int,
    _read_int_min,
    _read_list,
    _read_optional,
    _read_text,
)

# Loads .env into the environment so the _read_* helpers can see it. main.py
# calls this too; the second call is harmless, it simply finds the same file.
# module level function calls execute right after the import
load_dotenv()


@dataclass
class Settings:
    """Validated configuration for one run.

    Transforms .env variables into real type objects like date, Path, int, bool, str, etc.
    Doing a Settings dataclass makes it impossible to notice a .env missing argument in the end of the execution
    It automatically gives you an error if the Settings dataclass is wrong
    """

    base_url: str            # API host, e.g. https://dadosabertos.compras.gov.br
    items_endpoint: str      # path of the items endpoint, joined onto base_url
    end_date: date           # last day of the window; start_date is derived
    window_days: int         # how far back from end_date to go
    chunk_days: int          # width of each downloaded slice (crash granularity)
    page_size: int           # records per request, capped by the API (API defines 500 records per request by default)

    # `field(default_factory=...)` is required for mutable defaults: a plain
    # `= {}` would share one dict across every Settings instance.
    filters: dict[str, str] = field(default_factory=dict)   # extra query params
    columns: list[str] = field(default_factory=list)        # CSV column subset
    request_timeout: int = 60                               # seconds before a single request gives up
    request_delay: float = 0.2                              # pause between requests, to stay under throttling
    max_retries: int = 5                                    # attempts per page before the run fails
    retry_backoff: int = 15                                 # seconds; multiplied by the attempt number
    output_csv: Path = Path("data/contract_items.csv")
    checkpoint_file: Path = Path("data/checkpoint.json")
    resume: bool = True                                     # continue a previous run instead of restarting
    top_items: int = 20                                     # how many rows each summary ranking prints
    summary_chunk_rows: int = 200_000                       # rows summarize() reads per slice
    max_workers: int = 3                                    # chunks downloaded in parallel

    @property # decorator that treats a method as an attribute
    def start_date(self) -> date:
        """First day of the window, derived rather than configured.

        Storing only end_date + window_days means the two can never disagree,
        and a fixed 365-day window stays 365 days regardless of leap years.
        """
        return self.end_date - timedelta(days=self.window_days)

    @property
    def items_url(self) -> str:
        """Full endpoint URL.

        The strip calls make the join tolerant of how the two halves are written
        in .env: with or without a trailing/leading slash, the result has
        exactly one separator.
        """
        return f"{self.base_url.rstrip('/')}/{self.items_endpoint.lstrip('/')}"

    @classmethod # decorator that treats a method to be called inside the class without the need of an object
    def from_env(cls) -> "Settings":
        """Builds a Settings from .env, validating as it goes.

        The only constructor used in practice. Values the API itself would
        reject are checked here so the failure is a clear message rather than an
        HTTP 400 after the run has started.
        """
        # The accepted page-size range comes from the .env too, so the bound
        # and the value it guards are documented side by side in one file. The
        # defaults are the range the API itself accepts; widening them past
        # what the API allows only turns a clear message here into an HTTP 400
        # in the middle of the run.
        page_size_min = _read_int("PAGE_SIZE_MIN", 10)
        page_size_max = _read_int("PAGE_SIZE_MAX", 500)
        if page_size_min > page_size_max:
            raise ConfigError(
                f"'PAGE_SIZE_MIN' ({page_size_min}) não pode ser maior que "
                f"'PAGE_SIZE_MAX' ({page_size_max})."
            )

        page_size = _read_int("PAGE_SIZE", page_size_max)
        if not page_size_min <= page_size <= page_size_max:
            raise ConfigError(
                f"'PAGE_SIZE' precisa estar entre {page_size_min} e {page_size_max} "
                f"(recebido: {page_size}). A API rejeita valores fora desse intervalo."
            )

        # A zero or negative window would produce no chunks at all, and the run
        # would silently "succeed" having downloaded nothing.
        window_days = _read_int_min("WINDOW_DAYS", 365, 1)

        # A zero chunk width would make iter_date_chunks loop forever, since the
        # cursor would never advance past `current`.
        chunk_days = _read_int_min("CHUNK_DAYS", 7, 1)

        # Validated before upper-casing below, so an invalid code is reported
        # exactly as the user typed it.
        material_or_service = _read_optional("MATERIAL_OR_SERVICE")
        if material_or_service and material_or_service.upper() not in {"M", "S"}:
            raise ConfigError(
                f"'MATERIAL_OR_SERVICE' aceita apenas M (material) ou S (serviço) "
                f"— recebido: {material_or_service!r}"
            )

        # Only non-empty filters are forwarded to the API.
        # Keys are the API's own parameter names; each value is None when the
        # corresponding .env key is blank, and the comprehension below drops it.
        optional_filters = {
            "materialOuServico": material_or_service.upper() if material_or_service else None,
            "situacaoCompraItem": _read_optional("ITEM_STATUS"),
            "temResultado": _read_optional("HAS_RESULT"),
            "orgaoEntidadeCnpj": _read_optional("ORGAN_CNPJ"),
            "unidadeOrgaoCodigoUnidade": _read_optional("UNIT_CODE"),
            "codigoGrupo": _read_optional("ITEM_GROUP"),
            "codigoClasse": _read_optional("ITEM_CLASS"),
            "codItemCatalogo": _read_optional("CATALOG_ITEM"),
            "codFornecedor": _read_optional("SUPPLIER_ID"),
        }

        # Each argument pairs an .env key with the default used when it is
        # absent; these defaults are the ones documented in .env.example.
        return cls(
            base_url=_read_text("API_BASE_URL", "https://dadosabertos.compras.gov.br"),
            items_endpoint=_read_text(
                "ITEMS_ENDPOINT",
                "/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133",
            ),
            # An empty END_DATE means "up to today", so the window follows the clock.
            end_date=_read_date("END_DATE", date.today()),
            window_days=window_days,
            chunk_days=chunk_days,
            page_size=page_size,
            # This is where the None-valued filters are discarded: an unset
            # filter is left out of the request entirely rather than sent empty.
            filters={k: v for k, v in optional_filters.items() if v},
            columns=_read_list("COLUMNS"),
            # Each of these has a floor because a value below it breaks the
            # run in a way that is hard to read from the failure: a timeout of
            # zero gives up instantly, MAX_RETRIES=0 skips the retry loop
            # entirely and lands on its "unreachable" error, and a negative
            # delay makes time.sleep raise in the middle of the download.
            request_timeout=_read_int_min("REQUEST_TIMEOUT", 60, 1),
            request_delay=_read_float_min("REQUEST_DELAY", 0.2, 0.0),
            max_retries=_read_int_min("MAX_RETRIES", 5, 1),
            retry_backoff=_read_int_min("RETRY_BACKOFF", 15, 0),
            output_csv=Path(_read_text("OUTPUT_CSV", "data/contract_items.csv")),
            checkpoint_file=Path(_read_text("CHECKPOINT_FILE", "data/checkpoint.json")),
            resume=_read_bool("RESUME", True),
            top_items=_read_int_min("TOP_ITEMS", 20, 1),
            # Read in slices so summarize() never loads the whole CSV; a slice
            # of zero rows would make pandas raise instead of iterating.
            summary_chunk_rows=_read_int_min("SUMMARY_CHUNK_ROWS", 200_000, 1),
            # Chunks downloaded at the same time. Measured against this API,
            # the useful ceiling is 2-4: at 8 it degrades, and above that it
            # returns 429 in bulk, at which point fetch_page's backoff makes
            # the run slower than sequential.
            max_workers=_read_int_min("MAX_WORKERS", 3, 1),
        )
