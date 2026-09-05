from dataclasses import dataclass, field
from pathlib import Path # path construction methods
from dataclasses import dataclass, field
from ..src.read_type_methods import ConfigError
from ..src.read_type_methods import _read_int
from ..src.read_type_methods import _read_optional
from ..src.read_type_methods import _read_text
from ..src.read_type_methods import _read_bool
from ..src.read_type_methods import _read_float
from ..src.read_type_methods import _read_date
from ..src.read_type_methods import _read_list

@dataclass
class Settings:
    base_url: str
    items_endpoint: str
    end_date: date
    window_days: int
    chunk_days: int
    page_size: int
    filters: dict[str, str] = field(default_factory=dict)
    columns: list[str] = field(default_factory=list)
    request_timeout: int = 60
    request_delay: float = 0.2
    max_retries: int = 5
    retry_backoff: int = 15
    output_csv: Path = Path("data/contract_items.csv")
    checkpoint_file: Path = Path("data/checkpoint.json")
    resume: bool = True
    top_items: int = 20

    @property
    def start_date(self) -> date:
        return self.end_date - timedelta(days=self.window_days)

    @property
    def items_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.items_endpoint.lstrip('/')}"

    @classmethod
    def from_env(cls) -> "Settings":
        page_size = _read_int("PAGE_SIZE", PAGE_SIZE_MAX)
        if not PAGE_SIZE_MIN <= page_size <= PAGE_SIZE_MAX:
            raise ConfigError(
                f"'PAGE_SIZE' precisa estar entre {PAGE_SIZE_MIN} e {PAGE_SIZE_MAX} "
                f"(recebido: {page_size}). A API rejeita valores fora desse intervalo."
            )

        window_days = _read_int("WINDOW_DAYS", 365)
        if window_days < 1:
            raise ConfigError(f"'WINDOW_DAYS' precisa ser maior que zero (recebido: {window_days})")

        chunk_days = _read_int("CHUNK_DAYS", 7)
        if chunk_days < 1:
            raise ConfigError(f"'CHUNK_DAYS' precisa ser maior que zero (recebido: {chunk_days})")

        material_or_service = _read_optional("MATERIAL_OR_SERVICE")
        if material_or_service and material_or_service.upper() not in {"M", "S"}:
            raise ConfigError(
                f"'MATERIAL_OR_SERVICE' aceita apenas M (material) ou S (serviço) "
                f"— recebido: {material_or_service!r}"
            )

        # Only non-empty filters are forwarded to the API.
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

        return cls(
            base_url=_read_text("API_BASE_URL", "https://dadosabertos.compras.gov.br"),
            items_endpoint=_read_text(
                "ITEMS_ENDPOINT",
                "/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133",
            ),
            end_date=_read_date("END_DATE", date.today()),
            window_days=window_days,
            chunk_days=chunk_days,
            page_size=page_size,
            filters={k: v for k, v in optional_filters.items() if v},
            columns=_read_list("COLUMNS"),
            request_timeout=_read_int("REQUEST_TIMEOUT", 60),
            request_delay=_read_float("REQUEST_DELAY", 0.2),
            max_retries=_read_int("MAX_RETRIES", 5),
            retry_backoff=_read_int("RETRY_BACKOFF", 15),
            output_csv=Path(_read_text("OUTPUT_CSV", "data/contract_items.csv")),
            checkpoint_file=Path(_read_text("CHECKPOINT_FILE", "data/checkpoint.json")),
            resume=_read_bool("RESUME", True),
            top_items=_read_int("TOP_ITEMS", 20),
        )