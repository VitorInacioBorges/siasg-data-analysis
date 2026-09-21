# Pipeline de tratamento de dados — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** transformar o CSV bruto do coletor num painel semanal limpo, agregado e
com features, pronto para um modelo scikit-learn consumir.

**Architecture:** dois regimes separados pelo painel. Até o painel, estágios em
arquivo que rodam uma vez sobre ~640 mil linhas (determinísticos: deduplicar e
filtrar por plausibilidade dão o mesmo resultado sempre). Do painel em diante,
um `Pipeline` do scikit-learn ajustado por dobra da validação cruzada, porque a
média de um `StandardScaler` calculada com dados de teste é vazamento.

**Tech Stack:** Python 3.14, pandas 3.0.5, scikit-learn 1.9.0, matplotlib 3.11.1,
pyarrow, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-pipeline-tratamento-dados-design.md`

## Global Constraints

- Comentários e docstrings em inglês; mensagens ao usuário em português. Regra
  registrada em `docs/english/PRACTICES.md`, seção "Languages in code".
- Toda configuração mora em `src/.env`, lida pelos auxiliares `_read_*` de
  `src/read_type_methods.py`. Nenhum `os.getenv` fora deles.
- `data/raw/` nunca é editada. É a testemunha.
- Nada é descartado em silêncio: linhas removidas vão para
  `data/interim/quarentena.parquet` com a coluna `motivo`.
- Códigos de saída: `0` sucesso (inclusive "nada sobreviveu aos filtros"), `1`
  erro de configuração ou entrada inválida, `130` Ctrl+C.
- Grão do painel: `semana × materialOuServicoNome × classe`. `PANEL_FREQ=W`.
- Regra de plausibilidade: unilateral (só quantidade alta), em `log10`, por
  `codigoClasse`, com `QTY_MAD_THRESHOLD=8` e `MIN_CLASS_ITEMS=30`.
- Paleta dos gráficos: `#2a78d6` (azul) e `#eb6834` (laranja). Validada pelas
  seis checagens da skill `dataviz` em modo claro; não substituir sem revalidar.
- Arquivos sob `docs/superpowers/` ficam só em português.

---

### Task 1: Dependências e configuração

**Files:**
- Create: `requirements.txt`
- Create: `src/classes/pipeline_settings.py`
- Create: `tests/conftest.py`
- Create: `pytest.ini`
- Modify: `src/.env` (acrescentar 6 chaves ao fim)
- Modify: `src/.env.example` (as mesmas 6 chaves)
- Test: `tests/test_pipeline_settings.py`

**Interfaces:**
- Consumes: `_read_text`, `_read_int_min`, `_read_float_min` de `src/read_type_methods.py`
- Produces: `PipelineSettings` com os campos `raw_csv: Path`,
  `interim_dir: Path`, `processed_dir: Path`, `figures_dir: Path`,
  `panel_freq: str`, `top_classes: int`, `qty_mad_threshold: float`,
  `min_class_items: int`, `status_filter: str`, `read_chunk_rows: int`, e o
  construtor `PipelineSettings.from_env() -> PipelineSettings`

- [ ] **Step 1: instalar as dependências e registrá-las**

```bash
cd /home/vitor_inacio_borges/siasg-data-analysis
venv/bin/pip install pyarrow pytest
cat > requirements.txt <<'EOF'
pandas>=3.0
requests>=2.34
python-dotenv>=1.0
matplotlib>=3.11
scikit-learn>=1.9
pyarrow>=16.0
pytest>=8.0
EOF
```

- [ ] **Step 2: acrescentar as chaves ao `.env` e ao `.env.example`**

Ao fim dos dois arquivos (o `.env` usa CRLF — preserve):

```
# ===========================================================================
# Pipeline de tratamento (src/prepare.py)
# PANEL_FREQ         grão temporal do painel. W = semanal.
# TOP_CLASSES        classes mantidas por valor; o resto vira "Outras".
# QTY_MAD_THRESHOLD  corte de plausibilidade, em z robusto sobre log10(qtd).
# MIN_CLASS_ITEMS    abaixo disso a classe não tem MAD confiável.
# STATUS_FILTER      situação considerada gasto efetivo.
# READ_CHUNK_ROWS    linhas lidas por fatia do CSV bruto.
# ===========================================================================
PANEL_FREQ=W
TOP_CLASSES=50
QTY_MAD_THRESHOLD=8
MIN_CLASS_ITEMS=30
STATUS_FILTER=Homologado
READ_CHUNK_ROWS=200000
```

- [ ] **Step 3: escrever o teste que falha**

`tests/conftest.py`:

```python
"""Puts src/ on the import path, the same way `python src/main.py` does."""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
```

`pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

`tests/test_pipeline_settings.py`:

```python
from classes.pipeline_settings import PipelineSettings
from read_type_methods import ConfigError


def test_le_os_padroes(monkeypatch):
    for chave in ("PANEL_FREQ", "TOP_CLASSES", "QTY_MAD_THRESHOLD",
                  "MIN_CLASS_ITEMS", "STATUS_FILTER", "READ_CHUNK_ROWS"):
        monkeypatch.delenv(chave, raising=False)
    cfg = PipelineSettings.from_env()
    assert cfg.panel_freq == "W"
    assert cfg.top_classes == 50
    assert cfg.qty_mad_threshold == 8.0
    assert cfg.min_class_items == 30
    assert cfg.status_filter == "Homologado"


def test_caminhos_derivam_da_raiz_de_dados(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/tmp/dados-teste")
    cfg = PipelineSettings.from_env()
    assert cfg.raw_csv.as_posix() == "/tmp/dados-teste/raw/contract_items.csv"
    assert cfg.interim_dir.as_posix() == "/tmp/dados-teste/interim"
    assert cfg.processed_dir.as_posix() == "/tmp/dados-teste/processed"


def test_env_e_ancorado_no_modulo():
    """O .env precisa ser achado mesmo sem arquivo chamador (python -c, pytest)."""
    from classes.pipeline_settings import CAMINHO_ENV
    assert CAMINHO_ENV.name == ".env"
    assert CAMINHO_ENV.parent.name == "src"


def test_recusa_top_classes_zero(monkeypatch):
    monkeypatch.setenv("TOP_CLASSES", "0")
    try:
        PipelineSettings.from_env()
        assert False, "deveria ter levantado ConfigError"
    except ConfigError as erro:
        assert "TOP_CLASSES" in str(erro)
```

- [ ] **Step 4: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/test_pipeline_settings.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'classes.pipeline_settings'`

- [ ] **Step 5: implementar `PipelineSettings`**

`src/classes/pipeline_settings.py`:

```python
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
```

- [ ] **Step 6: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/test_pipeline_settings.py -v`
Expected: 4 passed

- [ ] **Step 7: commit**

```bash
git add requirements.txt pytest.ini tests/conftest.py \
        tests/test_pipeline_settings.py src/classes/pipeline_settings.py \
        src/.env src/.env.example
git commit -m "feat(pipeline): configuração e dependências do ETL

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `load.py` — leitura fiel

**Files:**
- Create: `src/pipeline/load.py`
- Test: `tests/pipeline/test_load.py`

**Interfaces:**
- Consumes: `PipelineSettings` da Task 1
- Produces: `carregar(caminho: Path, cfg: PipelineSettings) -> pd.DataFrame`.
  Devolve o grão de item, sem duplicatas, sem as três colunas mortas, filtrado
  por `cfg.status_filter`. As colunas numéricas (`quantidade`,
  `valorUnitarioEstimado`, `valorTotal`, `valorTotalResultado`) vêm como
  `float64` com `NaN` onde não havia valor. `dataInclusaoPncp` vem como
  `datetime64[ns]`. `codigoClasse` vem como `string` sem o sufixo `.0`.
  Também exporta as constantes `COLUNAS_MORTAS: list[str]`,
  `COLUNAS_NUMERICAS: list[str]` e `COLUNAS_TEXTO: list[str]`.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_load.py`:

```python
import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.load import carregar

CABECALHO = ("idCompraItem,dataInclusaoPncp,codigoClasse,materialOuServicoNome,"
             "situacaoCompraItemNome,itemCategoriaNome,temResultado,codigoGrupo,"
             "quantidade,valorUnitarioEstimado,valorTotal,valorTotalResultado\n")


def _linha(ident, classe="7010.0", status="Homologado", qtd="10"):
    return (f"{ident},2025-09-22T00:04:59,{classe},Material,{status},"
            f"Informática (TIC),True,,{qtd},100.0,1000.0,900.0\n")


@pytest.fixture
def cfg(tmp_path):
    caminho = tmp_path / "raw" / "contract_items.csv"
    caminho.parent.mkdir(parents=True)
    caminho.write_text(
        CABECALHO
        + _linha("a1")
        + _linha("a1")                          # duplicata exata
        + _linha("a2")
        + _linha("a3", status="Fracassado")     # filtrada pelo status
        , encoding="utf-8-sig")
    return PipelineSettings(
        raw_csv=caminho, interim_dir=tmp_path / "interim",
        processed_dir=tmp_path / "processed", figures_dir=tmp_path / "fig",
        read_chunk_rows=2)


def test_remove_duplicatas_por_id(cfg):
    df = carregar(cfg.raw_csv, cfg)
    assert df["idCompraItem"].is_unique
    assert set(df["idCompraItem"]) == {"a1", "a2"}


def test_descarta_as_tres_colunas_mortas(cfg):
    df = carregar(cfg.raw_csv, cfg)
    for morta in ("itemCategoriaNome", "temResultado", "codigoGrupo"):
        assert morta not in df.columns


def test_filtra_pelo_status(cfg):
    df = carregar(cfg.raw_csv, cfg)
    assert (df["situacaoCompraItemNome"] == "Homologado").all()


def test_tipos_e_normalizacao(cfg):
    df = carregar(cfg.raw_csv, cfg)
    assert df["quantidade"].dtype == "float64"
    assert pd.api.types.is_datetime64_any_dtype(df["dataInclusaoPncp"])
    # o CSV traz "7010.0"; o código é identificador, não número
    assert df["codigoClasse"].iloc[0] == "7010"


def test_arquivo_ausente_da_mensagem_clara(cfg, tmp_path):
    with pytest.raises(FileNotFoundError, match="src/main.py"):
        carregar(tmp_path / "nao-existe.csv", cfg)
```

- [ ] **Step 2: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/pipeline/test_load.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pipeline'`

- [ ] **Step 3: implementar `load.py`**

`src/pipeline/load.py`:

```python
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
COLUNAS_MORTAS = ["itemCategoriaNome", "temResultado", "codigoGrupo"]

# Identifiers, never arithmetic: read as text so a CNPJ keeps its leading zero.
COLUNAS_TEXTO = ["idCompraItem", "orgaoEntidadeCnpj", "unidadeOrgaoCodigoUnidade",
                 "codigoClasse", "codItemCatalogo"]

COLUNAS_NUMERICAS = ["quantidade", "valorUnitarioEstimado", "valorTotal",
                     "valorTotalResultado"]

# Few distinct values each, repeated millions of times: `category` stores the
# labels once and an integer per row, which is what keeps this in memory.
COLUNAS_CATEGORIA = ["materialOuServicoNome", "materialOuServico", "unidadeMedida",
                     "situacaoCompraItemNome", "nomeFornecedor"]


def carregar(caminho: Path, cfg: PipelineSettings) -> pd.DataFrame:
    """Reads the raw CSV, deduplicates it, and returns the item grain."""
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} não existe. Rode o coletor primeiro: python src/main.py"
        )

    fatias = pd.read_csv(
        caminho,
        encoding="utf-8-sig",
        chunksize=cfg.read_chunk_rows,
        # The collector may be appending right now, leaving the last line half
        # written. Skipping it is right; doing so silently is not — the count
        # is reported below.
        on_bad_lines="skip",
        parse_dates=["dataInclusaoPncp"],
        dtype={c: "string" for c in COLUNAS_TEXTO},
        low_memory=False,
    )
    df = pd.concat(list(fatias), ignore_index=True)

    lidas = len(df)
    # One extra pass over the file, a few seconds, to tell a skipped line from a
    # line that was never there.
    with caminho.open("rb") as fh:
        no_arquivo = sum(1 for _ in fh) - 1
    if no_arquivo > lidas:
        print(f"Aviso: {no_arquivo - lidas:,} linha(s) do CSV foram puladas por "
              f"estarem malformadas (provavelmente a última, se o coletor está rodando).")

    df = df.drop(columns=[c for c in COLUNAS_MORTAS if c in df.columns])

    # Rule 0: the collector re-downloads an interrupted chunk and appends its
    # rows a second time, so the raw layer legitimately holds duplicates.
    # idCompraItem is the API's unique key.
    antes = len(df)
    df = df.drop_duplicates("idCompraItem", keep="first")
    if antes > len(df):
        print(f"{antes - len(df):,} linha(s) duplicada(s) removida(s) "
              f"({(antes - len(df)) / antes:.1%} do arquivo).")

    for coluna in COLUNAS_NUMERICAS:
        # errors="coerce": an empty cell becomes NaN instead of raising. Items
        # that were never awarded have no valorTotalResultado at all.
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

    # The API writes class codes as floats ("7010.0"). They are identifiers.
    if "codigoClasse" in df.columns:
        df["codigoClasse"] = (df["codigoClasse"]
                              .str.replace(r"\.0$", "", regex=True)
                              .astype("string"))

    for coluna in COLUNAS_CATEGORIA:
        if coluna in df.columns:
            df[coluna] = df[coluna].astype("category")

    antes = len(df)
    df = df[df["situacaoCompraItemNome"] == cfg.status_filter]
    print(f"{antes - len(df):,} linha(s) fora de '{cfg.status_filter}' removida(s); "
          f"{len(df):,} restantes.")

    return df.reset_index(drop=True)
```

- [ ] **Step 4: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/pipeline/test_load.py -v`
Expected: 5 passed

- [ ] **Step 5: commit**

```bash
git add src/pipeline/load.py tests/pipeline/test_load.py
git commit -m "feat(pipeline): leitura tipada com deduplicação

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `clean.py` — plausibilidade por quantidade

**Files:**
- Create: `src/pipeline/clean.py`
- Test: `tests/pipeline/test_clean.py`

**Interfaces:**
- Consumes: o DataFrame de `carregar()` (Task 2), `PipelineSettings` (Task 1)
- Produces: `limpar(df: pd.DataFrame, cfg: PipelineSettings) -> tuple[pd.DataFrame, pd.DataFrame]`.
  Devolve `(limpos, quarentena)`. A quarentena tem todas as colunas de entrada
  mais `motivo: str` e `z_quantidade: float`. Invariante:
  `len(limpos) + len(quarentena) == len(df)`.
  Também exporta `MOTIVO_QUANTIDADE: str = "quantidade implausível na classe"`.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_clean.py`:

```python
import numpy as np
import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.clean import MOTIVO_QUANTIDADE, limpar


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path,
        qty_mad_threshold=8.0, min_class_items=30)


def _frame(linhas):
    return pd.DataFrame(linhas, columns=[
        "idCompraItem", "codigoClasse", "materialOuServicoNome",
        "quantidade", "valorUnitarioEstimado", "valorTotalResultado"])


@pytest.fixture
def base():
    """40 compras normais de informática, para a classe ter mediana e MAD."""
    rng = np.random.default_rng(7)
    normais = [(f"n{i}", "7010", "Material", float(q), 2000.0, q * 2000.0)
               for i, q in enumerate(rng.integers(1, 500, 40))]
    return _frame(normais)


def test_quarentena_pega_quantidade_impossivel(cfg, base):
    # o caso real: 11.880.000 tablets a R$ 1.550
    suspeito = _frame([("tablet", "7010", "Material",
                        11_880_000.0, 1550.0, 18_414_000_000.0)])
    limpos, quarentena = limpar(pd.concat([base, suspeito], ignore_index=True), cfg)
    assert list(quarentena["idCompraItem"]) == ["tablet"]
    assert quarentena["motivo"].iloc[0] == MOTIVO_QUANTIDADE
    assert "tablet" not in set(limpos["idCompraItem"])


def test_legitimos_sobrevivem(cfg, base):
    # 50 ressonâncias a R$ 8,25 mi e 3.000 ambulâncias a R$ 277 mil
    legitimos = _frame([
        ("ressonancia", "7010", "Material", 50.0, 8_254_384.14, 303_286_600.0),
        ("ambulancia", "7010", "Material", 3000.0, 277_807.0, 824_931_000.0),
    ])
    limpos, quarentena = limpar(pd.concat([base, legitimos], ignore_index=True), cfg)
    assert {"ressonancia", "ambulancia"} <= set(limpos["idCompraItem"])
    assert quarentena.empty


def test_mad_zero_nao_dispara(cfg):
    """Classe de serviço onde toda quantidade é 1: MAD = 0, regra não se aplica."""
    servicos = _frame([(f"s{i}", "sem-classe", "Serviço", 1.0, 1000.0, 1000.0)
                       for i in range(40)])
    obra = _frame([("obra", "sem-classe", "Serviço",
                    1.0, 616_720_624.99, 604_989_321.0)])
    limpos, quarentena = limpar(pd.concat([servicos, obra], ignore_index=True), cfg)
    assert quarentena.empty
    assert "obra" in set(limpos["idCompraItem"])


def test_regra_e_unilateral(cfg, base):
    """Quantidade muito BAIXA não é marcada: não infla total nenhum."""
    minusculo = _frame([("fracao", "7010", "Material", 0.001, 2000.0, 2.0)])
    limpos, quarentena = limpar(pd.concat([base, minusculo], ignore_index=True), cfg)
    assert quarentena.empty
    assert "fracao" in set(limpos["idCompraItem"])


def test_nada_evapora(cfg, base):
    suspeito = _frame([("tablet", "7010", "Material",
                        11_880_000.0, 1550.0, 18_414_000_000.0)])
    entrada = pd.concat([base, suspeito], ignore_index=True)
    limpos, quarentena = limpar(entrada, cfg)
    assert len(limpos) + len(quarentena) == len(entrada)


def test_classe_pequena_usa_estatistica_global(cfg, base):
    """Uma classe com 2 itens não tem MAD confiável; cai para o global."""
    pequena = _frame([
        ("p1", "9999", "Material", 5.0, 100.0, 500.0),
        ("p2", "9999", "Material", 50_000_000.0, 100.0, 5_000_000_000.0),
    ])
    limpos, quarentena = limpar(pd.concat([base, pequena], ignore_index=True), cfg)
    assert "p2" in set(quarentena["idCompraItem"])
    assert "p1" in set(limpos["idCompraItem"])
```

- [ ] **Step 2: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/pipeline/test_clean.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pipeline.clean'`

- [ ] **Step 3: implementar `clean.py`**

`src/pipeline/clean.py`:

```python
"""
The plausibility filter, and the only stage that removes rows on judgement.

The measured problem: eight rows out of 488.740 carry 78,7% of the value, and
they are data entry errors at the source — 11.880.000 tablets, 867.796.000 kilos
of goat meat, 1.713.940 units of postal service. Summing them annualises to
R$ 2,6 trillion in federal line items, which is impossible.

The errors live in the quantity, not in the total. Legitimate large contracts
appear with quantity 1 (the whole contract in the unit price) or with dozens of
units. That is why the rule reads quantity and not value: a ceiling on value
would remove real road works and MRI scanners along with the typos.

Nothing is deleted. Removed rows are returned as a second frame with the reason
attached, so the caller can write them to data/interim/quarentena.parquet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from classes.pipeline_settings import PipelineSettings

MOTIVO_QUANTIDADE = "quantidade implausível na classe"

# Scale factor that makes the median absolute deviation a consistent estimator
# of the standard deviation for normally distributed data. Without it the
# threshold would not be comparable to a z-score.
ESCALA_MAD = 1.4826


def _mad(serie: pd.Series) -> float:
    """Median absolute deviation: a spread measure the outliers cannot inflate."""
    return float((serie - serie.median()).abs().median())


def limpar(df: pd.DataFrame, cfg: PipelineSettings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits the frame into (kept, quarantined). Removes nothing silently."""
    trabalho = df.copy()

    # log10 because quantities span nine orders of magnitude, from 1 unit to
    # 867 million. On the linear scale the median is meaningless.
    trabalho["_log_qtd"] = np.log10(
        trabalho["quantidade"].where(trabalho["quantidade"] > 0)
    )

    # dropna=False keeps the missing-class rows as their own group: 19% of the
    # data has no codigoClasse, and it includes the civil works contracts.
    grupo = trabalho.groupby("codigoClasse", dropna=False, observed=True)["_log_qtd"]
    mediana = grupo.transform("median")
    mad = grupo.transform(_mad)
    tamanho = grupo.transform("size")

    mediana_global = trabalho["_log_qtd"].median()
    mad_global = _mad(trabalho["_log_qtd"].dropna())

    # A class whose quantities are all identical has MAD 0, and dividing by it
    # would flag every row that differs at all. Service classes are like this —
    # quantity is 1 on nearly every contract — and they are exactly where the
    # legitimate R$ 604 million works sit. The rule simply does not apply there.
    sem_estatistica = mad.isna() | (mad == 0)

    # A class with a handful of items has a median and a MAD, but neither means
    # anything. Borrow the global distribution instead.
    classe_pequena = (tamanho < cfg.min_class_items) & ~sem_estatistica

    mediana_efetiva = mediana.where(~classe_pequena, mediana_global)
    mad_efetivo = mad.where(~classe_pequena, mad_global)

    z = (trabalho["_log_qtd"] - mediana_efetiva) / (ESCALA_MAD * mad_efetivo)

    # One-sided on purpose. A quantity that is too small understates a total and
    # cannot produce the R$ 226 billion artefact; and quantity 1 is the norm for
    # works and continuing services. Only the high tail is suspect.
    # NaN comparisons are False, so rows without a usable quantity are kept.
    suspeito = (z > cfg.qty_mad_threshold) & ~sem_estatistica
    if mad_global == 0:
        # Degenerate input: every quantity in the frame is identical.
        suspeito = pd.Series(False, index=trabalho.index)

    quarentena = trabalho[suspeito].copy()
    quarentena["motivo"] = MOTIVO_QUANTIDADE
    quarentena["z_quantidade"] = z[suspeito]

    limpos = trabalho[~suspeito].drop(columns="_log_qtd")
    quarentena = quarentena.drop(columns="_log_qtd")

    if len(quarentena):
        valor = quarentena["valorTotalResultado"].sum()
        print(f"{len(quarentena):,} item(ns) em quarentena por quantidade "
              f"implausível, somando R$ {valor:,.2f}.")

    return limpos.reset_index(drop=True), quarentena.reset_index(drop=True)
```

- [ ] **Step 4: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/pipeline/test_clean.py -v`
Expected: 6 passed

- [ ] **Step 5: commit**

```bash
git add src/pipeline/clean.py tests/pipeline/test_clean.py
git commit -m "feat(pipeline): filtro de plausibilidade por quantidade na classe

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `aggregate.py` — a mudança de grão

**Files:**
- Create: `src/pipeline/aggregate.py`
- Test: `tests/pipeline/test_aggregate.py`

**Interfaces:**
- Consumes: `limpos` de `limpar()` (Task 3), `PipelineSettings` (Task 1)
- Produces: `para_painel(df: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame`
  com as colunas `semana` (`period[W]`), `materialOuServicoNome` (str),
  `classe` (str), `valor_total`, `n_itens`, `qtd_total`, `qtd_mediana`,
  `preco_unitario_mediano`, `valor_estimado_total`, `taxa_desconto`,
  `n_fornecedores`, `n_orgaos`. Retângulo completo: exatamente
  `n_semanas × n_combinações` linhas. Também exporta
  `BALDE_OUTRAS: str = "Outras"` e `BALDE_SEM_CLASSE: str = "Sem classe"`.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_aggregate.py`:

```python
import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.aggregate import BALDE_OUTRAS, BALDE_SEM_CLASSE, para_painel


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path,
        panel_freq="W", top_classes=2)


def _itens(linhas):
    df = pd.DataFrame(linhas, columns=[
        "dataInclusaoPncp", "codigoClasse", "materialOuServicoNome",
        "quantidade", "valorUnitarioEstimado", "valorTotal",
        "valorTotalResultado", "nomeFornecedor", "orgaoEntidadeCnpj"])
    df["dataInclusaoPncp"] = pd.to_datetime(df["dataInclusaoPncp"])
    return df


def test_soma_preservada(cfg):
    itens = _itens([
        ("2025-01-02", "A", "Material", 2.0, 50.0, 100.0, 90.0, "f1", "o1"),
        ("2025-01-03", "A", "Material", 4.0, 50.0, 200.0, 180.0, "f2", "o1"),
    ])
    painel = para_painel(itens, cfg)
    assert painel["valor_total"].sum() == pytest.approx(270.0)
    assert painel["n_itens"].sum() == 2


def test_painel_e_retangulo_completo(cfg):
    """Uma classe compra na semana 1, a outra na semana 3. O painel tem as duas
    em todas as três semanas, com zero onde não houve compra."""
    itens = _itens([
        ("2025-01-02", "A", "Material", 1.0, 10.0, 10.0, 10.0, "f1", "o1"),
        ("2025-01-16", "B", "Serviço", 1.0, 20.0, 20.0, 20.0, "f2", "o2"),
    ])
    painel = para_painel(itens, cfg)
    n_semanas = painel["semana"].nunique()
    n_combos = painel[["materialOuServicoNome", "classe"]].drop_duplicates().shape[0]
    assert len(painel) == n_semanas * n_combos
    assert n_semanas == 3
    assert (painel["valor_total"] == 0).sum() == len(painel) - 2


def test_reduz_para_top_classes(cfg):
    """top_classes=2: as duas maiores por valor ficam, o resto vira "Outras"."""
    itens = _itens([
        ("2025-01-02", "A", "Material", 1.0, 1.0, 1.0, 1000.0, "f", "o"),
        ("2025-01-02", "B", "Material", 1.0, 1.0, 1.0, 500.0, "f", "o"),
        ("2025-01-02", "C", "Material", 1.0, 1.0, 1.0, 10.0, "f", "o"),
        ("2025-01-02", "D", "Material", 1.0, 1.0, 1.0, 5.0, "f", "o"),
    ])
    painel = para_painel(itens, cfg)
    classes = set(painel["classe"])
    assert {"A", "B", BALDE_OUTRAS} <= classes
    assert "C" not in classes and "D" not in classes


def test_classe_ausente_vira_balde_proprio(cfg):
    itens = _itens([
        ("2025-01-02", None, "Serviço", 1.0, 100.0, 100.0, 100.0, "f", "o"),
    ])
    painel = para_painel(itens, cfg)
    assert BALDE_SEM_CLASSE in set(painel["classe"])


def test_material_e_servico_permanecem_na_chave(cfg):
    """Os baldes misturam M e S, então a divisão só é recuperável com a coluna
    na chave de agrupamento."""
    itens = _itens([
        ("2025-01-02", None, "Material", 1.0, 1.0, 1.0, 10.0, "f", "o"),
        ("2025-01-02", None, "Serviço", 1.0, 1.0, 1.0, 20.0, "f", "o"),
    ])
    painel = para_painel(itens, cfg)
    sem_classe = painel[painel["classe"] == BALDE_SEM_CLASSE]
    assert set(sem_classe["materialOuServicoNome"]) == {"Material", "Serviço"}


def test_taxa_de_desconto(cfg):
    itens = _itens([
        ("2025-01-02", "A", "Material", 1.0, 100.0, 100.0, 80.0, "f", "o"),
    ])
    painel = para_painel(itens, cfg)
    linha = painel[painel["valor_total"] > 0].iloc[0]
    assert linha["taxa_desconto"] == pytest.approx(0.8)
```

- [ ] **Step 2: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/pipeline/test_aggregate.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pipeline.aggregate'`

- [ ] **Step 3: implementar `aggregate.py`**

`src/pipeline/aggregate.py`:

```python
"""
Where the grain changes: one row per item becomes one row per period.

This is the step that makes forecasting possible at all. At the item grain there
is no "next week" — only items. The panel puts time on the row.

Two details decide whether the result is usable. Classes are reduced to the
largest N by value, because the real data has 434 of them and the top 50 already
cover 94,1% of the money — one-hot encoding all 434 would add more columns than
the panel has time steps. And the panel must come out a complete rectangle:
after a groupby, a week in which a class bought nothing simply does not exist,
and a lag would silently reach three weeks back instead of one.
"""

from __future__ import annotations

import pandas as pd

from classes.pipeline_settings import PipelineSettings

BALDE_OUTRAS = "Outras"
BALDE_SEM_CLASSE = "Sem classe"


def _reduzir_classes(df: pd.DataFrame, cfg: PipelineSettings) -> pd.Series:
    """Keeps the top classes by awarded value; everything else gets a bucket."""
    classe = df["codigoClasse"].astype("object")
    ausente = classe.isna()

    ranking = (df.loc[~ausente]
               .groupby(classe[~ausente], observed=True)["valorTotalResultado"]
               .sum()
               .sort_values(ascending=False))
    mantidas = set(ranking.head(cfg.top_classes).index)

    reduzida = classe.where(classe.isin(mantidas), BALDE_OUTRAS)
    # The missing-class bucket is kept separate from "Outras" because the two
    # mean different things: one is a small class, the other is no class at all.
    return reduzida.mask(ausente, BALDE_SEM_CLASSE).astype("string")


def para_painel(df: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame:
    """Aggregates the item grain into semana × material/serviço × classe."""
    trabalho = df.copy()
    trabalho["semana"] = trabalho["dataInclusaoPncp"].dt.to_period(cfg.panel_freq)
    trabalho["classe"] = _reduzir_classes(trabalho, cfg)
    trabalho["materialOuServicoNome"] = (trabalho["materialOuServicoNome"]
                                         .astype("string"))

    chave = ["semana", "materialOuServicoNome", "classe"]
    painel = trabalho.groupby(chave, observed=True).agg(
        valor_total=("valorTotalResultado", "sum"),
        n_itens=("valorTotalResultado", "size"),
        qtd_total=("quantidade", "sum"),
        qtd_mediana=("quantidade", "median"),
        preco_unitario_mediano=("valorUnitarioEstimado", "median"),
        valor_estimado_total=("valorTotal", "sum"),
        n_fornecedores=("nomeFornecedor", "nunique"),
        n_orgaos=("orgaoEntidadeCnpj", "nunique"),
    ).reset_index()

    # The rectangle. Every observed (material/serviço, classe) pair crossed with
    # every week in the range, so a lag always steps exactly one period back.
    combos = painel[["materialOuServicoNome", "classe"]].drop_duplicates()
    semanas = pd.period_range(painel["semana"].min(), painel["semana"].max(),
                              freq=cfg.panel_freq)
    grade = combos.merge(pd.DataFrame({"semana": semanas}), how="cross")
    painel = grade.merge(painel, on=chave, how="left")

    # A week with no purchase is a zero, not a gap: the money and the count are
    # genuinely zero.
    for coluna in ("valor_total", "n_itens", "qtd_total", "valor_estimado_total",
                   "n_fornecedores", "n_orgaos"):
        painel[coluna] = painel[coluna].fillna(0)
    # Medians of an empty set stay NaN — there was no price to observe, which is
    # not the same as a price of zero.

    # How much of the estimate the government actually paid. Measured median in
    # the real data: 0,826.
    painel["taxa_desconto"] = (painel["valor_total"]
                               / painel["valor_estimado_total"].replace(0, pd.NA))

    return painel.sort_values(["semana"] + chave[1:]).reset_index(drop=True)
```

- [ ] **Step 4: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/pipeline/test_aggregate.py -v`
Expected: 6 passed

- [ ] **Step 5: commit**

```bash
git add src/pipeline/aggregate.py tests/pipeline/test_aggregate.py
git commit -m "feat(pipeline): agregação para o painel semanal

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `features.py` — engenharia de atributos

**Files:**
- Create: `src/pipeline/features.py`
- Test: `tests/pipeline/test_features.py`

**Interfaces:**
- Consumes: o painel de `para_painel()` (Task 4)
- Produces: `criar_features(painel: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame`
  com as colunas de entrada mais `tendencia` (int), `semana_do_ano` (int),
  `mes` (int), `sazonal_sen` (float), `sazonal_cos` (float),
  `valor_lag_1`, `valor_lag_4`, `valor_lag_52`, `itens_lag_1`, `itens_lag_4`,
  `itens_lag_52`, `valor_media_4`, `itens_media_4`. Também exporta
  `COLUNAS_CATEGORICAS: list[str]` e a função
  `colunas_numericas(cfg: PipelineSettings) -> list[str]`, que devolve os nomes
  das features numéricas que `criar_features` produz para a frequência
  configurada. A Task 7 consome as duas. Há uma fonte de verdade só: a função,
  nunca uma constante paralela — com `PANEL_FREQ=M` a defasagem anual se chama
  `valor_lag_12`, e uma lista fixa apontaria para colunas que não existem.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_features.py`:

```python
import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.features import (COLUNAS_CATEGORICAS, colunas_numericas,
                               criar_features)


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path, panel_freq="W")


@pytest.fixture
def painel():
    semanas = pd.period_range("2025-01-06", periods=8, freq="W")
    linhas = []
    for i, semana in enumerate(semanas):
        for combo in (("Material", "A"), ("Serviço", "B")):
            linhas.append({
                "semana": semana, "materialOuServicoNome": combo[0],
                "classe": combo[1], "valor_total": float((i + 1) * 100),
                "n_itens": i + 1, "qtd_total": 10.0, "qtd_mediana": 2.0,
                "preco_unitario_mediano": 50.0,
                "valor_estimado_total": float((i + 1) * 120),
                "n_fornecedores": 2, "n_orgaos": 1, "taxa_desconto": 0.83})
    return pd.DataFrame(linhas)


def test_lags_olham_para_tras(cfg, painel):
    saida = criar_features(painel, cfg)
    linha_a = saida[(saida["classe"] == "A")].sort_values("semana")
    # a terceira semana tem valor 300 e o lag_1 dela é 200
    assert linha_a["valor_total"].iloc[2] == 300.0
    assert linha_a["valor_lag_1"].iloc[2] == 200.0
    # a primeira semana não tem passado
    assert pd.isna(linha_a["valor_lag_1"].iloc[0])


def test_lag_nao_atravessa_combinacoes(cfg, painel):
    """O lag da classe A nunca pega valor da classe B."""
    painel = painel.copy()
    painel.loc[painel["classe"] == "B", "valor_total"] = 9999.0
    saida = criar_features(painel, cfg)
    linha_a = saida[saida["classe"] == "A"].sort_values("semana")
    assert (linha_a["valor_lag_1"].dropna() != 9999.0).all()


def test_lag_52_vazio_com_um_ano(cfg, painel):
    """Documenta a limitação: 8 semanas de painel, lag_52 inteiramente nulo."""
    saida = criar_features(painel, cfg)
    assert saida["valor_lag_52"].isna().all()


def test_features_de_calendario(cfg, painel):
    saida = criar_features(painel, cfg)
    assert saida["tendencia"].min() == 0
    assert saida["semana_do_ano"].between(1, 53).all()
    assert saida["sazonal_sen"].between(-1, 1).all()


def test_listas_de_colunas_existem_na_saida(cfg, painel):
    """Tudo que colunas_numericas() promete precisa existir de fato."""
    saida = criar_features(painel, cfg)
    for coluna in COLUNAS_CATEGORICAS + colunas_numericas(cfg):
        assert coluna in saida.columns, coluna


def test_frequencia_mensal_muda_o_nome_da_defasagem_anual(cfg, painel):
    """A razão de a lista ser função e não constante."""
    import dataclasses
    mensal = dataclasses.replace(cfg, panel_freq="M")
    assert "valor_lag_12" in colunas_numericas(mensal)
    assert "valor_lag_52" not in colunas_numericas(mensal)
    assert "valor_lag_52" in colunas_numericas(cfg)
```

- [ ] **Step 2: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/pipeline/test_features.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pipeline.features'`

- [ ] **Step 3: implementar `features.py`**

`src/pipeline/features.py`:

```python
"""
Makes implicit information explicit, because a model only sees its columns.

Every feature here looks backwards. A column that peeked forward would be the
leak that produces a flattering score and a useless model — the same failure as
splitting a time series at random.

One limitation is structural rather than accidental: with a 365 day collection
window the panel has 52 weekly steps, so valor_lag_52 comes out entirely null.
Forecasting a year ahead needs a lag of 52 or more, because the model cannot be
handed a value it will not know at prediction time. Short horizons (one to eight
weeks) are well served by the short lags; the one-year horizon rests on trend and
calendar alone until the collection window grows. Widening the window makes
lag_52 populate with no change to this module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from classes.pipeline_settings import PipelineSettings

# Consumed by transform.py to build the ColumnTransformer.
COLUNAS_CATEGORICAS = ["materialOuServicoNome", "classe"]

CHAVE_COMBO = ["materialOuServicoNome", "classe"]

# Periods in one year, per panel frequency. This is what makes the seasonal
# cycle and the annual lag follow PANEL_FREQ instead of assuming weeks: with a
# hardcoded 52 a monthly panel would compute a twelve-times-too-long cycle and
# an annual lag that reaches four years back.
PERIODOS_POR_ANO = {"W": 52, "M": 12, "Q": 4, "D": 365}
PERIODOS_POR_ANO_PADRAO = 52

# Short lags for the near horizon; the annual one is added from the frequency.
DEFASAGENS_CURTAS = (1, 4)
JANELA_MEDIA = 4


def colunas_numericas(cfg: PipelineSettings) -> list[str]:
    """The numeric feature names criar_features() produces for this frequency."""
    periodos = PERIODOS_POR_ANO.get(cfg.panel_freq.upper()[:1], PERIODOS_POR_ANO_PADRAO)
    fixas = ["tendencia", "semana_do_ano", "mes", "sazonal_sen", "sazonal_cos",
             "qtd_total", "qtd_mediana", "preco_unitario_mediano",
             "n_fornecedores", "n_orgaos", "taxa_desconto",
             "valor_media_4", "itens_media_4"]
    defasadas = [f"{alvo}_lag_{d}"
                 for d in DEFASAGENS_CURTAS + (periodos,)
                 for alvo in ("valor", "itens")]
    return fixas + defasadas


def criar_features(painel: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame:
    """Adds calendar, trend, lag, and rolling-mean columns to the panel."""
    saida = painel.sort_values(CHAVE_COMBO + ["semana"]).copy()

    # Calendar. The week number carries seasonality a linear model can use only
    # as a cycle, so it also goes in as sine and cosine — week 52 and week 1 are
    # neighbours, which a raw integer cannot express.
    tempo = saida["semana"].dt.to_timestamp()
    saida["semana_do_ano"] = tempo.dt.isocalendar().week.astype(int)
    saida["mes"] = tempo.dt.month

    # The cycle length comes from the configured frequency, so the sine and
    # cosine describe one real year whatever the panel's grain.
    frequencia = cfg.panel_freq.upper()[:1]
    periodos = PERIODOS_POR_ANO.get(frequencia)
    if periodos is None:
        print(f"Aviso: PANEL_FREQ={cfg.panel_freq!r} não está no mapa de períodos; "
              f"assumindo {PERIODOS_POR_ANO_PADRAO} períodos por ano.")
        periodos = PERIODOS_POR_ANO_PADRAO

    angulo = 2 * np.pi * saida["semana_do_ano"] / periodos
    saida["sazonal_sen"] = np.sin(angulo)
    saida["sazonal_cos"] = np.cos(angulo)

    # Trend, as periods since the start of the panel. Zero-based so the
    # intercept of a linear model reads as "the first week".
    ordinais = saida["semana"].astype("int64")
    saida["tendencia"] = (ordinais - ordinais.min()).astype(int)

    # Lags and rolling means are computed per combination. Grouping is what
    # stops the lag of one class from reaching into another's history — without
    # it, the first week of class B would inherit the last week of class A.
    grupos = saida.groupby(CHAVE_COMBO, observed=True)
    for defasagem in DEFASAGENS_CURTAS + (periodos,):
        saida[f"valor_lag_{defasagem}"] = grupos["valor_total"].shift(defasagem)
        saida[f"itens_lag_{defasagem}"] = grupos["n_itens"].shift(defasagem)

    # shift(1) before rolling: the mean must not include the week being
    # predicted. Including it would be the leak this whole module avoids.
    saida["valor_media_4"] = (grupos["valor_total"]
                              .transform(lambda s: s.shift(1)
                                         .rolling(JANELA_MEDIA).mean()))
    saida["itens_media_4"] = (grupos["n_itens"]
                              .transform(lambda s: s.shift(1)
                                         .rolling(JANELA_MEDIA).mean()))

    vazias = [c for c in saida.columns
              if c.endswith(f"_{periodos}") and saida[c].isna().all()]
    if vazias:
        print(f"Aviso: {', '.join(vazias)} está(ão) inteiramente vazia(s) — o painel "
              f"tem {saida['semana'].nunique()} semanas, menos que a defasagem de 52. "
              f"Amplie WINDOW_DAYS no .env para habilitar o horizonte de um ano.")

    return saida.sort_values(["semana"] + CHAVE_COMBO).reset_index(drop=True)
```

- [ ] **Step 4: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/pipeline/test_features.py -v`
Expected: 5 passed

- [ ] **Step 5: commit**

```bash
git add src/pipeline/features.py tests/pipeline/test_features.py
git commit -m "feat(pipeline): features de calendário, tendência e defasagem

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `split.py` — corte temporal por semana

**Files:**
- Create: `src/pipeline/split.py`
- Test: `tests/pipeline/test_split.py`

**Interfaces:**
- Consumes: o painel com features (Task 5)
- Produces: `dividir(painel: pd.DataFrame, n_splits: int) -> Iterator[tuple[np.ndarray, np.ndarray]]`,
  rendendo pares de arrays de índices posicionais de linha, compatíveis com
  `cross_val_score(cv=...)` do scikit-learn.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_split.py`:

```python
import numpy as np
import pandas as pd
import pytest

from pipeline.split import dividir


@pytest.fixture
def painel():
    semanas = pd.period_range("2025-01-06", periods=10, freq="W")
    linhas = [{"semana": s, "classe": c, "valor_total": 1.0}
              for s in semanas for c in ("A", "B", "C")]
    return pd.DataFrame(linhas)


def test_nenhuma_semana_nos_dois_lados(painel):
    for treino, teste in dividir(painel, n_splits=3):
        semanas_treino = set(painel.iloc[treino]["semana"])
        semanas_teste = set(painel.iloc[teste]["semana"])
        assert not (semanas_treino & semanas_teste)


def test_treino_e_sempre_o_passado(painel):
    for treino, teste in dividir(painel, n_splits=3):
        assert painel.iloc[treino]["semana"].max() < painel.iloc[teste]["semana"].min()


def test_semana_inteira_de_cada_vez(painel):
    """Cada semana traz as três classes juntas: 3 linhas por semana."""
    for treino, teste in dividir(painel, n_splits=3):
        assert len(teste) % 3 == 0


def test_numero_de_dobras(painel):
    assert len(list(dividir(painel, n_splits=3))) == 3


def test_recusa_dobras_demais(painel):
    with pytest.raises(ValueError, match="semanas"):
        list(dividir(painel, n_splits=20))
```

- [ ] **Step 2: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/pipeline/test_split.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pipeline.split'`

- [ ] **Step 3: implementar `split.py`**

`src/pipeline/split.py`:

```python
"""
The temporal split, and the reason it cannot be sklearn's TimeSeriesSplit alone.

The panel holds around fifty rows per week, one per combination. TimeSeriesSplit
cuts by row position, so it lands in the middle of a week and puts half of that
week's classes in train and the other half in test. The model then sees part of
the very period it is being scored on — the leak that makes a random split
produce an R2 of 0,987 on data where the honest answer is 0,339.

So the split is taken over the distinct weeks and only then expanded to rows.
"""

from __future__ import annotations

from typing import Iterator

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit


def dividir(painel: pd.DataFrame, n_splits: int) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yields (train, test) positional row indices, cutting only between weeks."""
    semanas = np.sort(painel["semana"].unique())
    if len(semanas) < n_splits + 1:
        raise ValueError(
            f"{n_splits} dobras exigem pelo menos {n_splits + 1} semanas "
            f"distintas; o painel tem {len(semanas)}."
        )

    # Position of each row's week within the sorted week list, so a week-level
    # decision becomes a row-level mask without a join.
    posicao = pd.Series(painel["semana"]).map(
        {semana: i for i, semana in enumerate(semanas)}
    ).to_numpy()

    for treino_sem, teste_sem in TimeSeriesSplit(n_splits=n_splits).split(semanas):
        treino = np.flatnonzero(np.isin(posicao, treino_sem))
        teste = np.flatnonzero(np.isin(posicao, teste_sem))
        yield treino, teste
```

- [ ] **Step 4: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/pipeline/test_split.py -v`
Expected: 5 passed

- [ ] **Step 5: commit**

```bash
git add src/pipeline/split.py tests/pipeline/test_split.py
git commit -m "feat(pipeline): corte temporal que não parte a semana

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: `transform.py` — o transformador do modelo

**Files:**
- Create: `src/pipeline/transform.py`
- Test: `tests/pipeline/test_transform.py`

**Interfaces:**
- Consumes: `COLUNAS_CATEGORICAS` e `colunas_numericas(cfg)` (Task 5)
- Produces: `montar_transformador(cfg: PipelineSettings) -> ColumnTransformer`,
  **não ajustado**, para ser embutido num `sklearn.pipeline.Pipeline`.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_transform.py`:

```python
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from classes.pipeline_settings import PipelineSettings
from pipeline.features import COLUNAS_CATEGORICAS, colunas_numericas
from pipeline.transform import montar_transformador


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path)


@pytest.fixture
def X(cfg):
    n = 20
    dados = {c: np.arange(n, dtype=float) for c in colunas_numericas(cfg)}
    dados["materialOuServicoNome"] = ["Material", "Serviço"] * (n // 2)
    dados["classe"] = ["A", "B", "C", "D"] * (n // 4)
    return pd.DataFrame(dados)


def test_categoricas_viram_colunas_binarias(cfg, X):
    saida = montar_transformador(cfg).fit_transform(X)
    # 2 valores de material/serviço + 4 classes + as numéricas
    assert saida.shape[1] == 2 + 4 + len(colunas_numericas(cfg))


def test_categoria_nova_no_teste_nao_quebra(cfg, X):
    transformador = montar_transformador(cfg).fit(X)
    novo = X.head(1).copy()
    novo.loc[:, "classe"] = "Z"          # classe nunca vista no treino
    assert transformador.transform(novo).shape[1] == transformador.transform(X).shape[1]


def test_scaler_ajustado_so_no_treino(cfg, X):
    """O teste de vazamento: a média do scaler é a do treino, não a do todo."""
    treino, teste = X.iloc[:10], X.iloc[10:]
    modelo = Pipeline([("prep", montar_transformador(cfg)), ("reg", Ridge())])
    modelo.fit(treino, np.arange(10, dtype=float))

    # named_transformers_["num"] é o Pipeline (imputa + escala); o scaler
    # está dentro dele.
    scaler = (modelo.named_steps["prep"]
              .named_transformers_["num"].named_steps["escala"])
    esperado = treino["tendencia"].mean()
    # O índice vem da mesma lista que o transformador recebeu, não de uma
    # constante paralela que poderia estar em outra ordem.
    indice = colunas_numericas(cfg).index("tendencia")
    assert scaler.mean_[indice] == pytest.approx(esperado)
    assert scaler.mean_[indice] != pytest.approx(X["tendencia"].mean())


def test_nan_nas_features_nao_quebra(cfg, X):
    """Os lags nascem com NaN nas primeiras semanas; o transformador aguenta."""
    X = X.copy()
    X.loc[0:3, "valor_lag_52"] = np.nan
    saida = montar_transformador(cfg).fit_transform(X)
    assert not np.isnan(saida).any()
```

- [ ] **Step 2: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/pipeline/test_transform.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pipeline.transform'`

- [ ] **Step 3: implementar `transform.py`**

`src/pipeline/transform.py`:

```python
"""
The model-facing transformer, and the boundary where leakage is prevented.

Everything above this module runs once over the whole dataset, because
deduplicating and filtering by plausibility give the same answer regardless of
which fold is running. This one cannot: a StandardScaler's mean computed over
train and test together carries the future into the training set.

So this module returns the transformer UNFITTED. The caller embeds it in a
Pipeline, and sklearn refits it inside every fold. That is the whole reason the
file exists as a factory rather than as a fitted object.
"""

from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from classes.pipeline_settings import PipelineSettings
from pipeline.features import COLUNAS_CATEGORICAS, colunas_numericas


def montar_transformador(cfg: PipelineSettings) -> ColumnTransformer:
    """Builds the unfitted ColumnTransformer for the panel's feature columns."""
    # Lags are NaN for the first weeks of every combination, by construction.
    # Imputing the median keeps those rows usable; dropping them would throw
    # away the start of every series.
    numericas = Pipeline([
        ("imputa", SimpleImputer(strategy="median")),
        # Scaling matters for Ridge, which compares magnitudes, and is
        # harmless for the tree models. Keeping it makes swapping the
        # estimator a one-line change.
        ("escala", StandardScaler()),
    ])

    categoricas = OneHotEncoder(
        # A class present only in the test fold must not raise: with a temporal
        # split, a class that appears late in the year is exactly that.
        handle_unknown="ignore",
        sparse_output=False,
    )

    return ColumnTransformer(
        [
            # Asked of features.py rather than hardcoded, so the annual lag's
            # name follows PANEL_FREQ and the two modules cannot drift apart.
            ("num", numericas, colunas_numericas(cfg)),
            ("cat", categoricas, COLUNAS_CATEGORICAS),
        ],
        # Anything not named is dropped: the targets and the key columns must
        # never reach the model as features.
        remainder="drop",
    )
```

- [ ] **Step 4: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/pipeline/test_transform.py -v`
Expected: 4 passed

- [ ] **Step 5: commit**

```bash
git add src/pipeline/transform.py tests/pipeline/test_transform.py
git commit -m "feat(pipeline): ColumnTransformer ajustado só no treino

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: `plots.py` — os gráficos

**Files:**
- Create: `src/pipeline/plots.py`
- Test: `tests/pipeline/test_plots.py`

**Interfaces:**
- Consumes: os itens brutos (Task 2), os limpos e a quarentena (Task 3), o
  painel (Task 4)
- Produces: `gerar_graficos(bruto: pd.DataFrame, limpo: pd.DataFrame, painel: pd.DataFrame, destino: Path, quarentena: pd.DataFrame | None = None) -> list[Path]`,
  devolvendo os caminhos dos PNG escritos. O parâmetro `quarentena` alimenta a
  quarta figura; sem ele, ela sai com a mensagem "Nenhum item em quarentena".

**Design dos gráficos** (a paleta foi validada pelas seis checagens da skill
`dataviz` em modo claro — `#2a78d6` e `#eb6834`, todas PASS, contraste incluído;
não substituir sem revalidar com `scripts/validate_palette.js`):

| arquivo | forma | por quê |
|---|---|---|
| `01-serie-bruto-vs-limpo.png` | duas linhas | mudança no tempo, duas séries: legenda presente e rótulo direto no fim de cada linha |
| `02-distribuicao-log.png` | histograma, x em log | uma série, sem legenda: o título nomeia o que é |
| `03-composicao-material-servico.png` | barras empilhadas por semana | composição ao longo do tempo, duas categorias |
| `04-quarentena.png` | barras horizontais | magnitude por motivo, com rótulo direto no valor |

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_plots.py`:

```python
import matplotlib
matplotlib.use("Agg")           # sem display, antes de qualquer import de pyplot

import pandas as pd
import pytest

from pipeline.plots import gerar_graficos


@pytest.fixture
def dados():
    semanas = pd.period_range("2025-01-06", periods=6, freq="W")
    itens = pd.DataFrame({
        "dataInclusaoPncp": pd.to_datetime(
            ["2025-01-08", "2025-01-15", "2025-01-22"] * 2),
        "valorTotalResultado": [100.0, 200.0, 300.0, 1e10, 150.0, 250.0],
        "materialOuServicoNome": ["Material", "Serviço"] * 3,
    })
    limpo = itens.drop(index=3)
    painel = pd.DataFrame([
        {"semana": s, "materialOuServicoNome": m, "classe": "A",
         "valor_total": 100.0 * (i + 1), "n_itens": i + 1}
        for i, s in enumerate(semanas) for m in ("Material", "Serviço")])
    return itens, limpo, painel


def test_gera_os_quatro_png(dados, tmp_path):
    itens, limpo, painel = dados
    quarentena = itens.loc[[3]].assign(motivo="quantidade implausível na classe")
    caminhos = gerar_graficos(itens, limpo, painel, tmp_path,
                              quarentena=quarentena)
    assert len(caminhos) == 4
    for caminho in caminhos:
        assert caminho.exists() and caminho.stat().st_size > 0
        assert caminho.suffix == ".png"


def test_quarentena_vazia_nao_quebra(dados, tmp_path):
    itens, limpo, painel = dados
    vazia = itens.head(0).assign(motivo=pd.Series(dtype="object"))
    caminhos = gerar_graficos(itens, limpo, painel, tmp_path, quarentena=vazia)
    assert len(caminhos) == 4
```

- [ ] **Step 2: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/pipeline/test_plots.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pipeline.plots'`

- [ ] **Step 3: implementar `plots.py`**

`src/pipeline/plots.py`:

```python
"""
The figures, and one rule they all obey: raw and clean are shown side by side.

Eight rows out of 488.740 carry 78,7% of the value in the real data, so a chart
of the cleaned series alone would hide the single most consequential decision in
this pipeline. Every figure that can show both, shows both.

Palette: two categorical slots, #2a78d6 and #eb6834, validated against the six
checks of the dataviz method on the light surface (lightness band, chroma floor,
CVD separation, normal-vision floor, contrast — all pass). Do not substitute
without re-running that validator.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Categorical slots 1 and 2. Identity, not magnitude, so two distinct hues.
SERIE_1 = "#2a78d6"
SERIE_2 = "#eb6834"
# Text wears text tokens, never the series colour.
TINTA = "#0b0b0b"
TINTA_FRACA = "#52514e"
SUPERFICIE = "#fcfcfb"
GRADE = "#e3e2de"


def _figura(titulo: str, subtitulo: str = "") -> tuple[plt.Figure, plt.Axes]:
    """One figure, styled once: recessive axes, no top/right spines."""
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=SUPERFICIE)
    ax.set_facecolor(SUPERFICIE)
    ax.set_title(titulo, color=TINTA, fontsize=13, loc="left", pad=16 if subtitulo else 8)
    if subtitulo:
        ax.text(0, 1.02, subtitulo, transform=ax.transAxes,
                color=TINTA_FRACA, fontsize=10, va="bottom")
    # Recessive grid and axes: the data carries the ink.
    ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(GRADE)
    ax.tick_params(colors=TINTA_FRACA, labelsize=9)
    return fig, ax


def _salvar(fig: plt.Figure, caminho: Path) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, dpi=150, bbox_inches="tight", facecolor=SUPERFICIE)
    plt.close(fig)
    return caminho


def _serie_semanal(itens: pd.DataFrame) -> pd.Series:
    return (itens.set_index("dataInclusaoPncp")["valorTotalResultado"]
            .resample("W").sum())


def gerar_graficos(bruto: pd.DataFrame, limpo: pd.DataFrame, painel: pd.DataFrame,
                   destino: Path, quarentena: pd.DataFrame | None = None) -> list[Path]:
    """Writes the four figures and returns their paths."""
    destino = Path(destino)
    caminhos: list[Path] = []

    # --- 1. the series, before and after cleaning -------------------------
    antes, depois = _serie_semanal(bruto), _serie_semanal(limpo)
    fig, ax = _figura("Gasto homologado por semana",
                      "Antes e depois do filtro de plausibilidade")
    # 2px lines, per the mark spec.
    ax.plot(antes.index, antes.to_numpy() / 1e9, color=SERIE_1, linewidth=2,
            label="Bruto")
    ax.plot(depois.index, depois.to_numpy() / 1e9, color=SERIE_2, linewidth=2,
            label="Limpo")
    # Two series: legend always, and direct labels because there are <= 4.
    for serie, cor, rotulo in ((antes, SERIE_1, "Bruto"), (depois, SERIE_2, "Limpo")):
        if len(serie):
            ax.annotate(rotulo, (serie.index[-1], serie.iloc[-1] / 1e9),
                        xytext=(6, 0), textcoords="offset points",
                        color=cor, fontsize=9, va="center")
    ax.set_ylabel("R$ bilhões", color=TINTA_FRACA, fontsize=10)
    ax.legend(frameon=False, labelcolor=TINTA_FRACA, fontsize=9)
    caminhos.append(_salvar(fig, destino / "01-serie-bruto-vs-limpo.png"))

    # --- 2. the distribution, on a log axis -------------------------------
    valores = limpo["valorTotalResultado"].dropna()
    valores = valores[valores > 0]
    fig, ax = _figura("Distribuição do valor por item",
                      "Escala logarítmica: a mediana e a média diferem em 271x")
    if len(valores):
        # One series: no legend box, the title names it.
        ax.hist(valores, bins=np.logspace(np.log10(valores.min()),
                                          np.log10(valores.max()), 50),
                color=SERIE_1)
        ax.set_xscale("log")
        ax.axvline(valores.median(), color=TINTA_FRACA, linewidth=1.5,
                   linestyle="--")
        ax.annotate(f"mediana R$ {valores.median():,.0f}",
                    (valores.median(), ax.get_ylim()[1] * 0.9),
                    xytext=(8, 0), textcoords="offset points",
                    color=TINTA_FRACA, fontsize=9)
    ax.set_xlabel("R$ por item (log)", color=TINTA_FRACA, fontsize=10)
    ax.set_ylabel("itens", color=TINTA_FRACA, fontsize=10)
    caminhos.append(_salvar(fig, destino / "02-distribuicao-log.png"))

    # --- 3. composition over time -----------------------------------------
    comp = (painel.groupby(["semana", "materialOuServicoNome"], observed=True)
            ["valor_total"].sum().unstack(fill_value=0))
    fig, ax = _figura("Composição do gasto por semana",
                      "Material e serviço, sobre os dados limpos")
    if not comp.empty:
        base = np.zeros(len(comp))
        for coluna, cor in zip(comp.columns, (SERIE_1, SERIE_2)):
            altura = comp[coluna].to_numpy() / 1e9
            # A 2px surface gap between stacked segments keeps the boundary
            # readable without a border colour.
            ax.bar(range(len(comp)), altura, bottom=base, color=cor,
                   label=str(coluna), width=0.82, linewidth=2,
                   edgecolor=SUPERFICIE)
            base = base + altura
        passo = max(1, len(comp) // 12)
        ax.set_xticks(range(0, len(comp), passo))
        ax.set_xticklabels([str(s) for s in comp.index[::passo]], rotation=45,
                           ha="right")
        ax.legend(frameon=False, labelcolor=TINTA_FRACA, fontsize=9)
    ax.set_ylabel("R$ bilhões", color=TINTA_FRACA, fontsize=10)
    caminhos.append(_salvar(fig, destino / "03-composicao-material-servico.png"))

    # --- 4. what the cleaning removed -------------------------------------
    fig, ax = _figura("O que a limpeza removeu",
                      "Valor em quarentena, por motivo")
    if quarentena is not None and len(quarentena):
        por_motivo = (quarentena.groupby("motivo")["valorTotalResultado"]
                      .agg(["sum", "size"]).sort_values("sum"))
        posicoes = range(len(por_motivo))
        ax.barh(posicoes, por_motivo["sum"] / 1e9, color=SERIE_2, height=0.6)
        ax.set_yticks(posicoes)
        ax.set_yticklabels(por_motivo.index, fontsize=9)
        # Direct labels on the bars: the magnitude is the message.
        for i, (valor, n) in enumerate(zip(por_motivo["sum"], por_motivo["size"])):
            ax.annotate(f"R$ {valor / 1e9:,.1f} bi · {n:,} itens",
                        (valor / 1e9, i), xytext=(6, 0),
                        textcoords="offset points", color=TINTA_FRACA,
                        fontsize=9, va="center")
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRADE, linewidth=0.8)
    else:
        ax.text(0.5, 0.5, "Nenhum item em quarentena", transform=ax.transAxes,
                ha="center", color=TINTA_FRACA, fontsize=11)
        ax.set_axis_off()
    ax.set_xlabel("R$ bilhões", color=TINTA_FRACA, fontsize=10)
    caminhos.append(_salvar(fig, destino / "04-quarentena.png"))

    return caminhos
```

- [ ] **Step 4: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/pipeline/test_plots.py -v`
Expected: 2 passed

- [ ] **Step 5: olhar os gráficos**

O validador confere cor, não geometria. Gere as figuras com dados reais e
abra-as, procurando rótulo sobreposto, eixo cortado e estouro:

```bash
venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "src")
from pathlib import Path
import pandas as pd
from classes.pipeline_settings import PipelineSettings
from pipeline.load import carregar
from pipeline.clean import limpar
from pipeline.aggregate import para_painel
from pipeline.plots import gerar_graficos

cfg = PipelineSettings.from_env()
bruto = carregar(cfg.raw_csv, cfg)
limpo, quarentena = limpar(bruto, cfg)
painel = para_painel(limpo, cfg)
for c in gerar_graficos(bruto, limpo, painel, Path("reports/figures"),
                        quarentena=quarentena):
    print(c)
EOF
```

- [ ] **Step 6: commit**

```bash
git add src/pipeline/plots.py tests/pipeline/test_plots.py
git commit -m "feat(pipeline): gráficos com bruto e limpo lado a lado

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: `prepare.py` — orquestração

**Files:**
- Create: `src/prepare.py`
- Test: `tests/test_prepare.py`

**Interfaces:**
- Consumes: todos os módulos das Tasks 2 a 8
- Produces: `main(argv: list[str] | None = None) -> int`, com os códigos de
  saída `0`, `1` e `130`. Escreve `data/interim/itens_limpos.parquet`,
  `data/interim/quarentena.parquet`, `data/processed/painel.parquet`,
  `data/processed/painel_features.parquet` e os PNG em `reports/figures/`.

- [ ] **Step 1: escrever o teste que falha**

`tests/test_prepare.py`:

```python
import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

import prepare

CABECALHO = ("idCompraItem,dataInclusaoPncp,codigoClasse,materialOuServicoNome,"
             "situacaoCompraItemNome,itemCategoriaNome,temResultado,codigoGrupo,"
             "quantidade,valorUnitarioEstimado,valorTotal,valorTotalResultado,"
             "nomeFornecedor,orgaoEntidadeCnpj\n")


def _linha(i, dia, qtd=10.0):
    return (f"id{i},2025-01-{dia:02d}T10:00:00,7010,Material,Homologado,"
            f"Informática (TIC),True,,{qtd},100.0,1000.0,900.0,forn{i},org1\n")


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    linhas = "".join(_linha(i, 2 + (i % 20)) for i in range(60))
    (raw / "contract_items.csv").write_text(CABECALHO + linhas, encoding="utf-8-sig")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIGURES_DIR", str(tmp_path / "fig"))
    monkeypatch.setenv("TOP_CLASSES", "5")
    return tmp_path


def test_execucao_completa_grava_os_artefatos(ambiente):
    assert prepare.main([]) == 0
    assert (ambiente / "interim" / "itens_limpos.parquet").exists()
    assert (ambiente / "interim" / "quarentena.parquet").exists()
    assert (ambiente / "processed" / "painel.parquet").exists()
    assert (ambiente / "processed" / "painel_features.parquet").exists()
    assert list((ambiente / "fig").glob("*.png"))


def test_parada_em_estagio(ambiente):
    assert prepare.main(["--ate", "clean"]) == 0
    assert (ambiente / "interim" / "itens_limpos.parquet").exists()
    assert not (ambiente / "processed" / "painel.parquet").exists()


def test_csv_ausente_devolve_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert prepare.main([]) == 1
    assert "src/main.py" in capsys.readouterr().out


def test_soma_do_painel_bate_com_os_itens_limpos(ambiente):
    prepare.main([])
    limpos = pd.read_parquet(ambiente / "interim" / "itens_limpos.parquet")
    painel = pd.read_parquet(ambiente / "processed" / "painel.parquet")
    assert painel["valor_total"].sum() == pytest.approx(
        limpos["valorTotalResultado"].sum())
```

- [ ] **Step 2: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/test_prepare.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'prepare'`

- [ ] **Step 3: implementar `prepare.py`**

`src/prepare.py`:

```python
"""
Turns the collector's raw CSV into a model-ready weekly panel.

Shape of the program, outermost first:
    main()      reads config, prints the plan, handles the exit code
    executar()  runs the stages in order and writes each artefact
Each stage is a function in src/pipeline/, testable on its own.

Stages, and what each one leaves on disk:
    load       -> (in memory) typed item grain, deduplicated
    clean      -> interim/itens_limpos.parquet, interim/quarentena.parquet
    aggregate  -> processed/painel.parquet
    features   -> processed/painel_features.parquet
    plots      -> reports/figures/*.png

Every setting lives in the .env file — see .env.example.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from classes.pipeline_settings import PipelineSettings
from pipeline.aggregate import para_painel
from pipeline.clean import limpar
from pipeline.features import criar_features
from pipeline.load import carregar
from pipeline.plots import gerar_graficos
from read_type_methods import ConfigError

ESTAGIOS = ["load", "clean", "aggregate", "features", "plots"]

EXIT_OK = 0
EXIT_ERRO = 1
# 130 is the conventional shell code for "terminated by SIGINT" (Ctrl+C).
EXIT_INTERROMPIDO = 130


def _gravar(df: pd.DataFrame, caminho: Path) -> None:
    """Writes Parquet, falling back to CSV when pyarrow is absent."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(caminho, index=False)
    except ImportError:
        alternativa = caminho.with_suffix(".csv")
        print(f"Aviso: pyarrow não está instalado; gravando {alternativa.name} "
              f"em vez de Parquet (arquivo maior e sem tipos preservados).")
        df.to_csv(alternativa, index=False, encoding="utf-8-sig")


def executar(cfg: PipelineSettings, ate: str) -> int:
    """Runs the stages up to and including `ate`. Returns rows in the panel."""
    limite = ESTAGIOS.index(ate)

    print("Lendo", cfg.raw_csv, flush=True)
    bruto = carregar(cfg.raw_csv, cfg)
    if limite == 0:
        return len(bruto)

    limpo, quarentena = limpar(bruto, cfg)
    # The invariant that would have caught the duplicate rows the day they
    # appeared: cleaning splits the frame, it never shrinks the total.
    assert len(limpo) + len(quarentena) == len(bruto), (
        f"limpeza perdeu linhas: {len(bruto)} entraram, "
        f"{len(limpo) + len(quarentena)} saíram"
    )
    _gravar(limpo, cfg.interim_dir / "itens_limpos.parquet")
    _gravar(quarentena, cfg.interim_dir / "quarentena.parquet")
    if limite == 1:
        return len(limpo)

    painel = para_painel(limpo, cfg)
    n_semanas = painel["semana"].nunique()
    n_combos = painel[["materialOuServicoNome", "classe"]].drop_duplicates().shape[0]
    assert len(painel) == n_semanas * n_combos, (
        f"painel não é retângulo: {len(painel)} linhas para "
        f"{n_semanas} semanas x {n_combos} combinações"
    )
    esperado = limpo["valorTotalResultado"].sum()
    assert abs(painel["valor_total"].sum() - esperado) < 1e-6 * max(1.0, abs(esperado)), (
        "a agregação não preservou a soma dos valores"
    )
    _gravar(painel, cfg.processed_dir / "painel.parquet")
    print(f"Painel: {len(painel):,} linhas ({n_semanas} semanas x {n_combos} combinações)")
    if limite == 2:
        return len(painel)

    com_features = criar_features(painel, cfg)
    _gravar(com_features, cfg.processed_dir / "painel_features.parquet")
    if limite == 3:
        return len(com_features)

    figuras = gerar_graficos(bruto, limpo, painel, cfg.figures_dir,
                             quarentena=quarentena)
    print(f"{len(figuras)} figura(s) em {cfg.figures_dir}")
    return len(com_features)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code rather than exiting itself."""
    parser = argparse.ArgumentParser(
        description="Prepara o painel semanal a partir do CSV bruto do coletor.")
    parser.add_argument("--ate", choices=ESTAGIOS, default=ESTAGIOS[-1],
                        help="roda até este estágio, inclusive")
    args = parser.parse_args(argv)

    try:
        cfg = PipelineSettings.from_env()
    except ConfigError as erro:
        # A configuration mistake is the user's to fix, so it is reported as a
        # plain message instead of a traceback.
        print(f"Erro de configuração no .env: {erro}")
        return EXIT_ERRO

    print(f"Estágios: {' -> '.join(ESTAGIOS[:ESTAGIOS.index(args.ate) + 1])}")
    print(f"Saída:    {cfg.interim_dir} e {cfg.processed_dir}")

    try:
        linhas = executar(cfg, args.ate)
    except FileNotFoundError as erro:
        print(f"Erro: {erro}")
        return EXIT_ERRO
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return EXIT_INTERROMPIDO

    if linhas == 0:
        print("\nNenhuma linha sobreviveu aos filtros. Revise STATUS_FILTER no .env.")
        return EXIT_OK

    print(f"\nPronto. {linhas:,} linhas no artefato final.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/test_prepare.py -v`
Expected: 4 passed

- [ ] **Step 5: rodar a suíte inteira e o pipeline nos dados reais**

```bash
venv/bin/python -m pytest -v
cd /home/vitor_inacio_borges/siasg-data-analysis && venv/bin/python src/prepare.py
```

Expected: todos os testes passam; o pipeline imprime o número de duplicatas
removidas, os itens em quarentena, o tamanho do painel e as quatro figuras.

- [ ] **Step 6: commit**

```bash
git add src/prepare.py tests/test_prepare.py
git commit -m "feat(pipeline): ponto de entrada do ETL com invariantes

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Cobertura do spec

| seção do spec | tarefa |
|---|---|
| 3. Arquitetura — três camadas | Tasks 1 (caminhos), 9 (gravação) |
| 4. Configuração — 6 chaves | Task 1 |
| 5. `load.py` | Task 2 |
| 5. `clean.py` | Task 3 |
| 5. `aggregate.py` | Task 4 |
| 5. `features.py` | Task 5 |
| 5. `split.py` | Task 6 |
| 5. `transform.py` | Task 7 |
| 5. `plots.py` | Task 8 |
| 5. `prepare.py` | Task 9 |
| 6. Erros — códigos de saída | Task 9 |
| 6. Erros — CSV em escrita, ausente, pyarrow, painel vazio | Tasks 2 e 9 |
| 6. Invariantes — dedup, soma, retângulo, semana | Tasks 2, 6, 9 |
| 7. Testes — os 10 nomeados | Tasks 2 a 7 |
| 8. Limitação `lag_52` | Task 5 (aviso em tempo de execução e docstring) |
| 9. Dependências | Task 1 |
| 10. Defeito do coletor | fora deste plano, por decisão do spec |
