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

**Spec:** `docs/superpowers/specs/2026-09-20-pipeline-tratamento-data-design.md`

## Global Constraints

- Comentários e docstrings em inglês; mensagens ao usuário em português. Regra
  registrada em `docs/english/PRACTICES.md`, seção "Languages in code".
- Toda configuração mora em `src/.env`, lida pelos auxiliares `_read_*` de
  `src/read_type_methods.py`. Nenhum `os.getenv` fora deles.
- `data/raw/` nunca é editada. É a testemunha.
- Nada é descartado em silêncio: linhas removidas vão para
  `data/interim/quarantined.parquet` com a coluna `motivo`.
- Códigos de saída: `0` sucesso (inclusive "nada sobreviveu aos filtros"), `1`
  erro de configuração ou entrada inválida, `130` Ctrl+C.
- Grão do painel: `semana × materialOuServicoNome × classe`. `PANEL_FREQ=W`.
- Regra de plausibilidade: teto absoluto no valor de um item de linha,
  `VALUE_CEILING=10000000000` (R$ 10 bi). Medido no ano inteiro: remove 6 itens
  de 1.440.492 e preserva os contratos legítimos auditados. A regra de
  quantidade por classe foi implementada, medida e descartada — ela não pegava
  o maior erro da base e o que pegava sozinha era compra legítima em escala.
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
  `panel_freq: str`, `top_classes: int`, `value_ceiling: float`,
  `status_filter: str`, `read_chunk_rows: int`, e o
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
# STATUS_FILTER      situação considerada gasto efetivo.
# READ_CHUNK_ROWS    linhas lidas por fatia do CSV bruto.
# DATA_DIR           raiz das três camadas de dados (raw, interim, processed).
# RAW_CSV_NAME       nome do CSV que o coletor grava dentro de DATA_DIR/raw.
# FIGURES_DIR        onde os gráficos PNG são gravados.
# VALUE_CEILING      teto do valor de UM item de linha, em reais. Medido no ano
#                    inteiro: R$ 10 bi remove 6 itens de 1.440.492 e preserva
#                    os três contratos legítimos auditados. A regra de
#                    quantidade por classe, sozinha, não pega a maior linha da
#                    base (z = 3,41 contra limiar 8).
# ===========================================================================
PANEL_FREQ=W
TOP_CLASSES=50
STATUS_FILTER=Homologado
READ_CHUNK_ROWS=200000
DATA_DIR=data
RAW_CSV_NAME=contract_items.csv
FIGURES_DIR=reports/figures
VALUE_CEILING=10000000000
```

- [ ] **Step 3: escrever o teste que falha**

`tests/conftest.py`:

```python
"""Puts src/ on the import path, the same way `python src/main.py` does."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
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


def test_reads_the_defaults(monkeypatch):
    for key in ("PANEL_FREQ", "TOP_CLASSES", "VALUE_CEILING",
                  "STATUS_FILTER", "READ_CHUNK_ROWS"):
        monkeypatch.delenv(key, raising=False)
    cfg = PipelineSettings.from_env()
    assert cfg.panel_freq == "W"
    assert cfg.top_classes == 50
    assert cfg.status_filter == "Homologado"


def test_paths_derive_from_the_data_root(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/tmp/dados-teste")
    cfg = PipelineSettings.from_env()
    assert cfg.raw_csv.as_posix() == "/tmp/dados-teste/raw/contract_items.csv"
    assert cfg.interim_dir.as_posix() == "/tmp/dados-teste/interim"
    assert cfg.processed_dir.as_posix() == "/tmp/dados-teste/processed"


def test_env_path_is_passed_to_load_dotenv(monkeypatch):
    """Guards the behaviour, not the constant.

    Asserting only that ENV_PATH points at src/.env would still pass if someone
    kept the constant and reverted the call to a bare load_dotenv() — which is
    the very defect this task closes. So the test checks that load_dotenv is
    called WITH the anchored path.
    """
    import importlib

    import dotenv

    calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: calls.append((a, k)))

    import classes.pipeline_settings as module
    # reload re-executes `from dotenv import load_dotenv`, so the module binds
    # the patched function instead of the one captured at first import.
    importlib.reload(module)

    assert calls, "load_dotenv não foi chamado"
    assert calls[0][0], "load_dotenv foi chamado sem argumento — o .env seria ignorado"
    assert calls[0][0][0] == module.ENV_PATH
    assert module.ENV_PATH.name == ".env"
    assert module.ENV_PATH.parent.name == "src"


def test_rejects_top_classes_zero(monkeypatch):
    monkeypatch.setenv("TOP_CLASSES", "0")
    try:
        PipelineSettings.from_env()
        assert False, "deveria ter levantado ConfigError"
    except ConfigError as error:
        assert "TOP_CLASSES" in str(error)
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
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    print(f"Aviso: {ENV_PATH} não existe; usando apenas os valores padrão.")


@dataclass
class PipelineSettings:
    """Validated configuration for one pipeline run."""

    raw_csv: Path
    interim_dir: Path
    processed_dir: Path
    figures_dir: Path
    panel_freq: str = "W"
    top_classes: int = 50
    status_filter: str = "Homologado"
    read_chunk_rows: int = 200_000
    value_ceiling: float = 10_000_000_000.0  # R$ per line item

    @classmethod
    def from_env(cls) -> "PipelineSettings":
        """Builds a PipelineSettings from .env, validating as it goes."""
        # One root for all three layers, so a test run redirects everything by
        # setting a single variable.
        root = Path(_read_text("DATA_DIR", "data"))
        return cls(
            raw_csv=root / "raw" / _read_text("RAW_CSV_NAME", "contract_items.csv"),
            interim_dir=root / "interim",
            processed_dir=root / "processed",
            figures_dir=Path(_read_text("FIGURES_DIR", "reports/figures")),
            panel_freq=_read_text("PANEL_FREQ", "W"),
            # A floor of 1 everywhere a zero would make the stage meaningless:
            # zero classes leaves nothing to group by, a zero threshold flags
            # every row, and a zero chunk makes pandas raise.
            top_classes=_read_int_min("TOP_CLASSES", 50, 1),
            status_filter=_read_text("STATUS_FILTER", "Homologado"),
            read_chunk_rows=_read_int_min("READ_CHUNK_ROWS", 200_000, 1),
            # Ceiling on one line item's awarded value. Measured on a full
            # year: R$ 10 bi removes 6 items out of 1.440.492 and all three
            # audited legitimate contracts survive. Raising it lets the six
            # impossible rows back in; lowering it towards R$ 100 mi starts
            # taking real public works.
            value_ceiling=_read_float_min("VALUE_CEILING", 10_000_000_000.0, 1.0),
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
- Produces: `load_raw(path: Path, cfg: PipelineSettings) -> pd.DataFrame`.
  Devolve o grão de item, sem duplicatas, sem as três colunas mortas, filtrado
  por `cfg.status_filter`. As colunas numéricas (`quantidade`,
  `valorUnitarioEstimado`, `valorTotal`, `valorTotalResultado`) vêm como
  `float64` com `NaN` onde não havia valor. `dataInclusaoPncp` vem como
  `datetime64[ns]`. `codigoClasse` vem como `string` sem o sufixo `.0`.
  Também exporta as constantes `DEAD_COLUMNS: list[str]`,
  `NUMERIC_COLUMNS: list[str]` e `TEXT_COLUMNS: list[str]`.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_load.py`:

```python
import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.load import load_raw

HEADER = ("idCompraItem,dataInclusaoPncp,codigoClasse,materialOuServicoNome,"
             "situacaoCompraItemNome,itemCategoriaNome,temResultado,codigoGrupo,"
             "quantidade,valorUnitarioEstimado,valorTotal,valorTotalResultado\n")


def _row(ident, classe="7010.0", status="Homologado", qtd="10"):
    return (f"{ident},2025-09-22T00:04:59,{classe},Material,{status},"
            f"Informática (TIC),True,,{qtd},100.0,1000.0,900.0\n")


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "raw" / "contract_items.csv"
    path.parent.mkdir(parents=True)
    path.write_text(
        HEADER
        + _row("a1", qtd="10")
        # Mesma chave, quantidade diferente. Deliberado: se as duas linhas
        # fossem idênticas, um drop_duplicates() SEM subset passaria no teste
        # igualmente, e o teste não provaria nada sobre a chave.
        + _row("a1", qtd="99")
        + _row("a2")
        + _row("a3", status="Fracassado")     # filtrada pelo status
        , encoding="utf-8-sig")
    return PipelineSettings(
        raw_csv=path, interim_dir=tmp_path / "interim",
        processed_dir=tmp_path / "processed", figures_dir=tmp_path / "fig",
        read_chunk_rows=2)


def test_drops_duplicate_ids(cfg):
    """A deduplicação é pela CHAVE, não pela linha inteira.

    As duas linhas "a1" do fixture diferem em `quantidade`, então um
    `drop_duplicates()` sem subset deixaria as duas e este teste falharia. É o
    caso real: 23,4% do arquivo são re-downloads de um bloco interrompido, e
    nada garante que o valor de um item não mudou entre as tentativas.
    """
    df = load_raw(cfg.raw_csv, cfg)
    assert df["idCompraItem"].is_unique
    assert set(df["idCompraItem"]) == {"a1", "a2"}
    # keep="first": a linha mantida é a primeira que apareceu no arquivo
    mantida = df[df["idCompraItem"] == "a1"]["quantidade"].iloc[0]
    assert mantida == 10.0, "esperava a primeira ocorrência, não a segunda"


def test_drops_the_three_dead_columns(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    for morta in ("itemCategoriaNome", "temResultado", "codigoGrupo"):
        assert morta not in df.columns


def test_filters_by_status(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    assert (df["situacaoCompraItemNome"] == "Homologado").all()


def test_types_and_normalisation(cfg):
    df = load_raw(cfg.raw_csv, cfg)
    assert df["quantidade"].dtype == "float64"
    assert pd.api.types.is_datetime64_any_dtype(df["dataInclusaoPncp"])
    # o CSV traz "7010.0"; o código é identificador, não número
    assert df["codigoClasse"].iloc[0] == "7010"


def _cfg_for(path):
    return PipelineSettings(
        raw_csv=path, interim_dir=path.parent / "i",
        processed_dir=path.parent / "p", figures_dir=path.parent / "f")


def test_reports_skipped_lines(tmp_path, capsys):
    """Uma linha com campo SOBRANDO é descartada — e o pandas diz qual.

    Medido no pandas 3.0.5: `on_bad_lines` descarta a linha com campos a mais,
    e só essa. Campo faltando é preenchido com NaN e mantido, por isso
    truncamento tem detecção própria nos dois testes seguintes.

    A mensagem vem do pandas, não de uma contagem nossa: contar por bytes
    errava nesta base, porque `descricaoResumida` tem newline dentro de campo
    citado — 218.100 deles — e todo run anunciava 218.100 linhas puladas sem
    que nada tivesse sido pulado.
    """
    path = tmp_path / "contract_items.csv"
    path.write_text(
        HEADER
        + _row("b1")
        + _row("b2").rstrip("\n") + ",campo,a,mais\n"   # campos sobrando
        + _row("b3"),
        encoding="utf-8-sig")

    df = load_raw(path, _cfg_for(path))

    assert set(df["idCompraItem"]) == {"b1", "b3"}
    out = capsys.readouterr().out
    assert "leitor de CSV" in out
    assert "Skipping line" in out


def test_embedded_newlines_do_not_raise_a_false_alarm(tmp_path, capsys):
    """Newline dentro de campo citado não é linha pulada.

    A regressão que este teste guarda: uma contagem por bytes veria três
    newlines onde o CSV tem duas linhas, e acusaria uma linha inexistente de
    malformada.
    """
    path = tmp_path / "contract_items.csv"
    campo_com_quebra = '"Notebook\ncom descrição em duas linhas"'
    linha = (f"c2,2025-09-22T00:04:59,7010,Material,Homologado,"
             f"Informática (TIC),True,,10,100.0,1000.0,900.0\n")
    path.write_text(
        HEADER
        + linha.replace("Informática (TIC)", campo_com_quebra)
        + _row("c1"),
        encoding="utf-8-sig")

    df = load_raw(path, _cfg_for(path))
    out = capsys.readouterr().out

    assert len(df) == 2
    # Duas afirmações, uma por regressão possível. "puladas" é a palavra da
    # contagem por bytes que foi deletada: se alguém a reinstalar, a mensagem
    # dela ("...foram puladas por estarem malformadas") reaparece aqui — e ela
    # NÃO contém "leitor de CSV", então afirmar só esse prefixo deixaria a
    # regressão passar.
    assert "puladas" not in out
    assert "leitor de CSV" not in out


def test_drops_a_partial_last_row(tmp_path, capsys):
    """A linha pela metade é descartada, não apenas contada.

    É a forma que o coletor produz ao ser morto no meio de uma gravação: sem
    newline final, campos faltando. O pandas a preencheria com NaN e a
    manteria; com o id intacto ela sobreviveria à deduplicação, somaria zero em
    tudo e subestimaria o painel em silêncio.
    """
    path = tmp_path / "contract_items.csv"
    path.write_text(
        HEADER
        + _row("c1")
        + "c2,2025-09-22T00:04:59,7010,Mat",   # cortada no meio, sem newline
        encoding="utf-8-sig")

    df = load_raw(path, _cfg_for(path))

    assert set(df["idCompraItem"]) == {"c1"}
    assert "pela metade" in capsys.readouterr().out


def test_file_changing_mid_read_discards_nothing(tmp_path, capsys, monkeypatch):
    """Se o arquivo muda durante a leitura, nenhuma linha é descartada.

    O motivo de existir: a foto de "termina no meio de uma linha" é tirada
    antes do parse. Se o coletor completa a escrita nesse intervalo, o sinal
    fica velho e o descarte joga fora uma linha legítima. Checar depois do
    parse não resolve — só move a janela para o erro simétrico.
    """
    from pipeline import load as modulo

    path = tmp_path / "contract_items.csv"
    # A linha parcial é cortada DEPOIS da coluna de situação, senão o filtro de
    # status a removeria por conta própria e o teste não provaria nada.
    parcial = ("e2,2025-09-22T00:04:59,7010,Material,Homologado,"
               "Informática (TIC),True,,10,100.0")
    path.write_text(HEADER + _row("e1") + parcial, encoding="utf-8-sig")

    fotos = iter([(1, 1), (2, 2)])          # duas fotos diferentes = mudou
    monkeypatch.setattr(modulo, "_snapshot", lambda _: next(fotos))

    df = load_raw(path, _cfg_for(path))

    out = capsys.readouterr().out
    assert "mudou durante a leitura" in out
    assert "nenhuma linha foi descartada" in out
    # a parcial continua ali: o sinal que mandaria descartá-la era velho
    assert set(df["idCompraItem"]) == {"e1", "e2"}


def test_truncation_inside_a_quoted_field_gives_a_clear_error(tmp_path):
    """on_bad_lines não pega este caso: o pandas levanta ParserError.

    Sem tratamento, load_raw morre com um traceback do tokenizador que não diz
    nada a quem roda. A mensagem tem de nomear a causa e o que fazer.
    """
    path = tmp_path / "contract_items.csv"
    path.write_text(
        HEADER + _row("d1") + 'd2,2025-09-22T00:04:59,"classe sem fecho',
        encoding="utf-8-sig")

    with pytest.raises(RuntimeError, match="RESUME=true"):
        load_raw(path, _cfg_for(path))


def test_no_message_when_nothing_is_skipped(cfg, capsys):
    """O caminho silencioso também precisa ser afirmado, não só acontecer."""
    load_raw(cfg.raw_csv, cfg)
    assert "leitor de CSV" not in capsys.readouterr().out


def test_missing_file_gives_a_clear_message(cfg, tmp_path):
    with pytest.raises(FileNotFoundError, match="src/main.py"):
        load_raw(tmp_path / "nao-existe.csv", cfg)
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
        print("Aviso: o arquivo mudou durante a leitura — o coletor está rodando? "
              "Nem a contagem de linhas puladas nem a detecção de linha parcial "
              "valem para esta execução, e nenhuma linha foi descartada por "
              "isso. Rode de novo quando a coleta terminar.")
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
        # catch_warnings(record=True) records every category, and
        # simplefilter only controls deduplication for the one it names — so
        # without this guard a FutureWarning from a dependency would be
        # announced to the reader as "the CSV reader discarded rows".
        if issubclass(warning.category, pd.errors.ParserWarning):
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

### Task 3: `clean.py` — plausibilidade por valor

**Files:**
- Create: `src/pipeline/clean.py`
- Test: `tests/pipeline/test_clean.py`

**Interfaces:**
- Consumes: o DataFrame de `load_raw()` (Task 2), `PipelineSettings` (Task 1)
- Produces: `clean(df: pd.DataFrame, cfg: PipelineSettings) -> tuple[pd.DataFrame, pd.DataFrame]`.
  Devolve `(kept, quarantined)`. A quarentena tem todas as colunas de entrada
  mais `motivo: str`. Invariante: `len(kept) + len(quarantined) == len(df)`.
  Também exporta `REASON_VALUE: str`.

**Por que a regra é esta, e não a que o spec trazia antes.** O desenho original
media quantidade implausível dentro de cada `codigoClasse`, por z robusto sobre
`log10`. Implementei, testei e rodei contra o ano inteiro — 1.440.492 itens
homologados, R$ 732,7 bi — e ela reprovou em duas frentes:

1. **Não pegava o maior erro.** A linha de 1.713.940 unidades de serviço postal
   a R$ 132.000 cada, R$ 226 bilhões, 31% do total, tem `z = 3,41` contra um
   limiar de 8. As linhas sem `codigoClasse` são 638.294 itens com quantidades
   de 1 a 29 bilhões, e o MAD desse grupo é uma ordem de magnitude inteira.
   Nenhum limiar separa: o que pega essa linha (3,0) remove 49,57% do valor.
2. **O que ela pegava sozinha era legítimo.** Medido: 177 itens, R$ 0,31 bi,
   0,04% do valor — e entre eles 28.000.000 doses de vacina (z 8,11), 8.800.000
   munições (z 11,97) e 8.797 livros didáticos (z 8,16). Compras públicas de
   grande escala, não erro de digitação. Os z dos falsos positivos se sobrepõem
   aos dos verdadeiros, então não há limiar que salve.

A absurdidade está no **produto**, não na quantidade: 1,7 milhão de unidades não
chama atenção; 1,7 milhão de unidades a R$ 132.000 cada, sim. Inspecionei as 50
linhas acima de R$ 500 mi: de R$ 500 mi a R$ 10 bi a faixa é majoritariamente
legítima — merenda escolar a R$ 24 a refeição com 68 a 260 milhões de unidades,
vacina a R$ 105 a dose, contratos bancários e concessões com quantidade 1. Acima
de R$ 10 bi as 6 linhas são todas impossíveis.

**Limitação assumida:** dois erros conhecidos ficam dentro — 867.796.000 kg de
carne de caprino (R$ 3,3 bi) e 850.000 notebooks (R$ 4,4 bi). Juntos, 1% do
total. Alcançá-los exigiria um teto que também removeria a merenda escolar.

- [ ] **Step 0: acertar a configuração**

`VALUE_CEILING` é consumido aqui, mas mora nos arquivos da Task 1, que já está
commitada. As linhas exatas, para não haver dúvida — o brief de uma tarefa só
extrai a seção dela, então elas ficam aqui e não lá.

Em `src/classes/pipeline_settings.py`, no dataclass, depois de
`read_chunk_rows`:

```python
    value_ceiling: float = 10_000_000_000.0  # R$ per line item
```

E em `from_env()`, depois da leitura de `READ_CHUNK_ROWS`:

```python
            # Ceiling on one line item's awarded value. Measured on a full
            # year: R$ 10 bi removes 6 items out of 1.440.492 and all three
            # audited legitimate contracts survive. Raising it lets the six
            # impossible rows back in; lowering it towards R$ 500 mi starts
            # taking the school meal programme.
            value_ceiling=_read_float_min("VALUE_CEILING", 10_000_000_000.0, 1.0),
```

Se `qty_mad_threshold` ou `min_class_items` ainda estiverem no dataclass ou em
`from_env()`, remova: a regra que os usava foi descartada e configuração morta é
defeito. O mesmo para `QTY_MAD_THRESHOLD` e `MIN_CLASS_ITEMS` em `src/.env` e
`src/.env.example`, onde `VALUE_CEILING=10000000000` deve existir. Preserve CRLF
nos dois `.env`.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_clean.py`:

```python
import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.clean import REASON_VALUE, clean


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path,
        value_ceiling=10_000_000_000.0)


def _frame(rows):
    return pd.DataFrame(rows, columns=[
        "idCompraItem", "codigoClasse", "materialOuServicoNome",
        "quantidade", "valorUnitarioEstimado", "valorTotalResultado"])


def test_quarantines_the_impossible_total(cfg):
    """O caso real: 1.713.940 unidades de serviço postal a R$ 132.000 cada."""
    entry = _frame([
        ("normal", "7010", "Material", 10.0, 100.0, 1_000.0),
        ("correios", None, "Serviço", 1_713_940.0, 132_000.0, 226_240_080_000.0),
    ])
    kept, quarantined = clean(entry, cfg)
    assert list(quarantined["idCompraItem"]) == ["correios"]
    assert quarantined["motivo"].iloc[0] == REASON_VALUE
    assert list(kept["idCompraItem"]) == ["normal"]


def test_spares_audited_legitimate_contracts(cfg):
    """Os contratos que auditamos à mão, e a escala pública que parece absurda.

    As três primeiras linhas são contratos reais grandes. As duas últimas são o
    que a regra anterior colocava em quarentena por engano: 28 milhões de doses
    de vacina e 8,8 milhões de munições não são erro de digitação.
    """
    entry = _frame([
        ("obras", None, "Serviço", 1.0, 616_720_624.99, 604_989_321.0),
        ("ambulancia", "7010", "Material", 3_000.0, 277_807.0, 824_931_000.0),
        ("ressonancia", "7010", "Material", 50.0, 8_254_384.14, 303_286_600.0),
        ("vacina", "6505", "Material", 28_000_000.0, 1.42, 39_760_000.0),
        ("municao", "1305", "Material", 8_800_000.0, 2.62, 23_040_000.0),
    ])
    kept, quarantined = clean(entry, cfg)
    assert quarantined.empty
    assert len(kept) == 5


def test_quantity_alone_never_quarantines(cfg):
    """Quantidade enorme com total modesto passa — é compra em massa.

    Esta é a regressão que importa: a regra anterior marcava estas linhas.
    """
    entry = _frame([
        ("merenda", None, "Serviço", 250_800_000.0, 24.0, 6_019_200_000.0),
        ("vale", None, "Serviço", 3_432_000_000.0, 3.0, 9_000_000_000.0),
    ])
    kept, quarantined = clean(entry, cfg)
    assert quarantined.empty
    assert len(kept) == 2


def test_the_ceiling_is_exclusive(cfg):
    """Exatamente no teto passa; um centavo acima, não."""
    entry = _frame([
        ("no_teto", "7010", "Material", 1.0, 1.0, 10_000_000_000.0),
        ("acima", "7010", "Material", 1.0, 1.0, 10_000_000_000.01),
    ])
    kept, quarantined = clean(entry, cfg)
    assert list(kept["idCompraItem"]) == ["no_teto"]
    assert list(quarantined["idCompraItem"]) == ["acima"]


def test_missing_value_is_kept(cfg):
    """valorTotalResultado nulo não pode ser tratado como acima do teto."""
    entry = _frame([("sem_valor", "7010", "Material", 5.0, 100.0, None)])
    kept, quarantined = clean(entry, cfg)
    assert quarantined.empty
    assert len(kept) == 1


def test_nothing_evaporates(cfg):
    """A invariante que pegaria uma linha perdida no caminho."""
    entry = _frame([
        ("a", "7010", "Material", 1.0, 1.0, 1.0),
        ("b", None, "Serviço", 1.0, 1.0, 226_240_080_000.0),
        ("c", "8905", "Material", 2.0, 2.0, 4.0),
    ])
    kept, quarantined = clean(entry, cfg)
    assert len(kept) + len(quarantined) == len(entry)


def test_reports_what_it_removed(cfg, capsys):
    """Nada sai em silêncio: a mensagem diz quantos itens e quanto valor."""
    entry = _frame([
        ("ok", "7010", "Material", 1.0, 1.0, 1.0),
        ("fora", None, "Serviço", 1.0, 1.0, 226_240_080_000.0),
    ])
    clean(entry, cfg)
    out = capsys.readouterr().out
    assert "quarentena" in out
    assert "1 item" in out
```

- [ ] **Step 2: rodar e confirmar que falha**

Run: `venv/bin/python -m pytest tests/pipeline/test_clean.py -v`
Expected: FAIL com `ImportError: cannot import name 'REASON_VALUE'`

- [ ] **Step 3: implementar `clean.py`**

`src/pipeline/clean.py`:

```python
"""
The plausibility filter, and the only stage that removes rows on judgement.

The measured problem: six rows out of 1.440.492 carry 53,77% of the total
value, and they are data-entry errors at the source. The largest is 1.713.940
units of postal service at R$ 132.000 each — R$ 226 bilhões, 31% of the dataset
in one row. Left in, the year reads R$ 735 bi; taken out, R$ 340 bi.

The rule reads the awarded total, not the quantity, because the absurdity is in
the product. An earlier design measured implausible quantity within each class
and was dropped after being measured against a full year: it missed that largest
row entirely (z = 3,41 against a threshold of 8), and the 177 rows it caught on
its own were legitimate public purchases at scale — 28 million vaccine doses,
8,8 million rounds of ammunition, 8.797 textbooks. Quantity within a class does
not separate bulk from typo.

Known limitation, accepted: two real errors stay in — 867.796.000 kg of goat
meat (R$ 3,3 bi) and 850.000 notebooks (R$ 4,4 bi), together 1% of the total.
Reaching them would need a ceiling that also removes the school meal programme.

Nothing is deleted. Removed rows come back as a second frame with the reason
attached, so the caller can write them to data/interim/quarentena.parquet.
"""

from __future__ import annotations

import pandas as pd

from classes.pipeline_settings import PipelineSettings
# Reused rather than duplicated: the messages here are Portuguese too, and one
# number formatter for the package is one place to fix it.
from pipeline.load import _pt_br

REASON_VALUE = "valor total implausível para um item de linha"


def clean(df: pd.DataFrame, cfg: PipelineSettings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits the frame into (kept, quarantined). Removes nothing silently."""
    # NaN > x is False, so an item that was never awarded a value is kept
    # rather than treated as exceeding the ceiling.
    suspect = df["valorTotalResultado"] > cfg.value_ceiling

    quarantined = df[suspect].copy()
    quarantined["motivo"] = REASON_VALUE
    kept = df[~suspect]

    if len(quarantined):
        total = quarantined["valorTotalResultado"].sum()
        print(f"{_pt_br(len(quarantined))} item(ns) em quarentena — {REASON_VALUE} "
              f"— somando R$ {_pt_br(total, 2)}.")

    return kept.reset_index(drop=True), quarantined.reset_index(drop=True)
```

- [ ] **Step 4: rodar e confirmar que passa**

Run: `venv/bin/python -m pytest tests/pipeline/test_clean.py -v`
Expected: 7 passed

- [ ] **Step 5: commit**

```bash
git add src/pipeline/clean.py tests/pipeline/test_clean.py         src/classes/pipeline_settings.py src/.env src/.env.example
git commit -m "feat(pipeline): filtro de plausibilidade por valor total

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `aggregate.py` — a mudança de grão

**Files:**
- Create: `src/pipeline/aggregate.py`
- Test: `tests/pipeline/test_aggregate.py`

**Interfaces:**
- Consumes: `kept` de `clean()` (Task 3), `PipelineSettings` (Task 1)
- Produces: `to_panel(df: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame`
  com as colunas `semana` (`period[W]`), `materialOuServicoNome` (str),
  `classe` (str), `valor_total`, `n_itens`, `qtd_total`, `qtd_mediana`,
  `preco_unitario_mediano`, `valor_estimado_total`, `taxa_desconto`,
  `n_fornecedores`, `n_orgaos`. Retângulo completo: exatamente
  `n_weeks × n_combinações` linhas. Também exporta
  `BUCKET_OTHER: str = "Outras"` e `BUCKET_NO_CLASS: str = "Sem classe"`.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_aggregate.py`:

```python
import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.aggregate import BUCKET_OTHER, BUCKET_NO_CLASS, to_panel


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path,
        panel_freq="W", top_classes=2)


def _items(rows):
    df = pd.DataFrame(rows, columns=[
        "dataInclusaoPncp", "codigoClasse", "materialOuServicoNome",
        "quantidade", "valorUnitarioEstimado", "valorTotal",
        "valorTotalResultado", "nomeFornecedor", "orgaoEntidadeCnpj"])
    df["dataInclusaoPncp"] = pd.to_datetime(df["dataInclusaoPncp"])
    return df


def test_sum_is_preserved(cfg):
    itens = _items([
        ("2025-01-02", "A", "Material", 2.0, 50.0, 100.0, 90.0, "f1", "o1"),
        ("2025-01-03", "A", "Material", 4.0, 50.0, 200.0, 180.0, "f2", "o1"),
    ])
    panel = to_panel(itens, cfg)
    assert panel["valor_total"].sum() == pytest.approx(270.0)
    assert panel["n_itens"].sum() == 2


def test_panel_is_a_full_rectangle(cfg):
    """Uma classe compra na semana 1, a outra na semana 3. O painel tem as duas
    em todas as três semanas, com zero onde não houve compra."""
    itens = _items([
        ("2025-01-02", "A", "Material", 1.0, 10.0, 10.0, 10.0, "f1", "o1"),
        ("2025-01-16", "B", "Serviço", 1.0, 20.0, 20.0, 20.0, "f2", "o2"),
    ])
    panel = to_panel(itens, cfg)
    n_weeks = panel["semana"].nunique()
    n_combos = panel[["materialOuServicoNome", "classe"]].drop_duplicates().shape[0]
    assert len(panel) == n_weeks * n_combos
    assert n_weeks == 3
    assert (panel["valor_total"] == 0).sum() == len(panel) - 2


def test_reduces_to_top_classes(cfg):
    """top_classes=2: as duas maiores por valor ficam, o resto vira "Outras"."""
    itens = _items([
        ("2025-01-02", "A", "Material", 1.0, 1.0, 1.0, 1000.0, "f", "o"),
        ("2025-01-02", "B", "Material", 1.0, 1.0, 1.0, 500.0, "f", "o"),
        ("2025-01-02", "C", "Material", 1.0, 1.0, 1.0, 10.0, "f", "o"),
        ("2025-01-02", "D", "Material", 1.0, 1.0, 1.0, 5.0, "f", "o"),
    ])
    panel = to_panel(itens, cfg)
    classes = set(panel["classe"])
    assert {"A", "B", BUCKET_OTHER} <= classes
    assert "C" not in classes and "D" not in classes


def test_missing_class_gets_its_own_bucket(cfg):
    itens = _items([
        ("2025-01-02", None, "Serviço", 1.0, 100.0, 100.0, 100.0, "f", "o"),
    ])
    panel = to_panel(itens, cfg)
    assert BUCKET_NO_CLASS in set(panel["classe"])


def test_material_and_service_stay_in_the_key(cfg):
    """Os baldes misturam M e S, então a divisão só é recuperável com a coluna
    na chave de agrupamento."""
    itens = _items([
        ("2025-01-02", None, "Material", 1.0, 1.0, 1.0, 10.0, "f", "o"),
        ("2025-01-02", None, "Serviço", 1.0, 1.0, 1.0, 20.0, "f", "o"),
    ])
    panel = to_panel(itens, cfg)
    no_class = panel[panel["classe"] == BUCKET_NO_CLASS]
    assert set(no_class["materialOuServicoNome"]) == {"Material", "Serviço"}


def test_discount_rate(cfg):
    itens = _items([
        ("2025-01-02", "A", "Material", 1.0, 100.0, 100.0, 80.0, "f", "o"),
    ])
    panel = to_panel(itens, cfg)
    linha = panel[panel["valor_total"] > 0].iloc[0]
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

BUCKET_OTHER = "Outras"
BUCKET_NO_CLASS = "Sem classe"


def _reduce_classes(df: pd.DataFrame, cfg: PipelineSettings) -> pd.Series:
    """Keeps the top classes by awarded value; everything else gets a bucket."""
    classe = df["codigoClasse"].astype("object")
    missing = classe.isna()

    ranking = (df.loc[~missing]
               .groupby(classe[~missing], observed=True)["valorTotalResultado"]
               .sum()
               .sort_values(ascending=False))
    kept_classes = set(ranking.head(cfg.top_classes).index)

    reduced = classe.where(classe.isin(kept_classes), BUCKET_OTHER)
    # The missing-class bucket is kept separate from "Outras" because the two
    # mean different things: one is a small class, the other is no class at all.
    return reduced.mask(missing, BUCKET_NO_CLASS).astype("string")


def to_panel(df: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame:
    """Aggregates the item grain into semana × material/serviço × classe."""
    work = df.copy()
    work["semana"] = work["dataInclusaoPncp"].dt.to_period(cfg.panel_freq)
    work["classe"] = _reduce_classes(work, cfg)
    work["materialOuServicoNome"] = (work["materialOuServicoNome"]
                                         .astype("string"))

    key = ["semana", "materialOuServicoNome", "classe"]
    panel = work.groupby(key, observed=True).agg(
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
    combos = panel[["materialOuServicoNome", "classe"]].drop_duplicates()
    weeks = pd.period_range(panel["semana"].min(), panel["semana"].max(),
                              freq=cfg.panel_freq)
    full_grid = combos.merge(pd.DataFrame({"semana": weeks}), how="cross")
    panel = full_grid.merge(panel, on=key, how="left")

    # A week with no purchase is a zero, not a gap: the money and the count are
    # genuinely zero.
    for column in ("valor_total", "n_itens", "qtd_total", "valor_estimado_total",
                   "n_fornecedores", "n_orgaos"):
        panel[column] = panel[column].fillna(0)
    # Medians of an empty set stay NaN — there was no price to observe, which is
    # not the same as a price of zero.

    # How much of the estimate the government actually paid. Measured median in
    # the real data: 0,826.
    panel["taxa_desconto"] = (panel["valor_total"]
                               / panel["valor_estimado_total"].replace(0, pd.NA))

    return panel.sort_values(["semana"] + key[1:]).reset_index(drop=True)
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
- Consumes: o painel de `to_panel()` (Task 4)
- Produces: `build_features(panel: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame`
  com as colunas de entrada mais `tendencia` (int), `semana_do_ano` (int),
  `mes` (int), `sazonal_sen` (float), `sazonal_cos` (float),
  `valor_lag_1`, `valor_lag_4`, `valor_lag_52`, `itens_lag_1`, `itens_lag_4`,
  `itens_lag_52`, `valor_media_4`, `itens_media_4`. Também exporta
  `CATEGORICAL_FEATURES: list[str]` e a função
  `numeric_features(cfg: PipelineSettings) -> list[str]`, que devolve os nomes
  das features numéricas que `build_features` produz para a frequência
  configurada. A Task 7 consome as duas. Há uma fonte de verdade só: a função,
  nunca uma constante paralela — com `PANEL_FREQ=M` a defasagem anual se chama
  `valor_lag_12`, e uma lista fixa apontaria para colunas que não existem.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_features.py`:

```python
import pandas as pd
import pytest

from classes.pipeline_settings import PipelineSettings
from pipeline.features import (CATEGORICAL_FEATURES, numeric_features,
                               build_features)


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path, panel_freq="W")


@pytest.fixture
def panel():
    weeks = pd.period_range("2025-01-06", periods=8, freq="W")
    rows = []
    for i, semana in enumerate(weeks):
        for combo in (("Material", "A"), ("Serviço", "B")):
            rows.append({
                "semana": semana, "materialOuServicoNome": combo[0],
                "classe": combo[1], "valor_total": float((i + 1) * 100),
                "n_itens": i + 1, "qtd_total": 10.0, "qtd_mediana": 2.0,
                "preco_unitario_mediano": 50.0,
                "valor_estimado_total": float((i + 1) * 120),
                "n_fornecedores": 2, "n_orgaos": 1, "taxa_desconto": 0.83})
    return pd.DataFrame(rows)


def test_lags_look_backwards(cfg, panel):
    out = build_features(panel, cfg)
    row_a = out[(out["classe"] == "A")].sort_values("semana")
    # a terceira semana tem valor 300 e o lag_1 dela é 200
    assert row_a["valor_total"].iloc[2] == 300.0
    assert row_a["valor_lag_1"].iloc[2] == 200.0
    # a primeira semana não tem passado
    assert pd.isna(row_a["valor_lag_1"].iloc[0])


def test_lag_does_not_cross_combinations(cfg, panel):
    """O lag da classe A nunca pega valor da classe B."""
    panel = panel.copy()
    panel.loc[panel["classe"] == "B", "valor_total"] = 9999.0
    out = build_features(panel, cfg)
    row_a = out[out["classe"] == "A"].sort_values("semana")
    assert (row_a["valor_lag_1"].dropna() != 9999.0).all()


def test_lag_52_is_empty_with_one_year(cfg, panel):
    """Documenta a limitação: 8 semanas de painel, lag_52 inteiramente nulo."""
    out = build_features(panel, cfg)
    assert out["valor_lag_52"].isna().all()


def test_calendar_features(cfg, panel):
    out = build_features(panel, cfg)
    assert out["tendencia"].min() == 0
    assert out["semana_do_ano"].between(1, 53).all()
    assert out["sazonal_sen"].between(-1, 1).all()


def test_declared_columns_exist_in_the_output(cfg, panel):
    """Tudo que colunas_numericas() promete precisa existir de fato."""
    out = build_features(panel, cfg)
    for column in CATEGORICAL_FEATURES + numeric_features(cfg):
        assert column in out.columns, column


def test_monthly_frequency_renames_the_annual_lag(cfg, panel):
    """A razão de a lista ser função e não constante."""
    import dataclasses
    mensal = dataclasses.replace(cfg, panel_freq="M")
    assert "valor_lag_12" in numeric_features(mensal)
    assert "valor_lag_52" not in numeric_features(mensal)
    assert "valor_lag_52" in numeric_features(cfg)
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
CATEGORICAL_FEATURES = ["materialOuServicoNome", "classe"]

COMBO_KEY = ["materialOuServicoNome", "classe"]

# Periods in one year, per panel frequency. This is what makes the seasonal
# cycle and the annual lag follow PANEL_FREQ instead of assuming weeks: with a
# hardcoded 52 a monthly panel would compute a twelve-times-too-long cycle and
# an annual lag that reaches four years back.
PERIODS_PER_YEAR = {"W": 52, "M": 12, "Q": 4, "D": 365}
PERIODS_PER_YEAR_DEFAULT = 52

# Short lags for the near horizon; the annual one is added from the frequency.
SHORT_LAGS = (1, 4)
ROLLING_WINDOW = 4


def numeric_features(cfg: PipelineSettings) -> list[str]:
    """The numeric feature names criar_features() produces for this frequency."""
    periods = PERIODS_PER_YEAR.get(cfg.panel_freq.upper()[:1], PERIODS_PER_YEAR_DEFAULT)
    fixed = ["tendencia", "semana_do_ano", "mes", "sazonal_sen", "sazonal_cos",
             "qtd_total", "qtd_mediana", "preco_unitario_mediano",
             "n_fornecedores", "n_orgaos", "taxa_desconto",
             "valor_media_4", "itens_media_4"]
    lagged = [f"{target}_lag_{d}"
                 for d in SHORT_LAGS + (periods,)
                 for target in ("valor", "itens")]
    return fixed + lagged


def build_features(panel: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame:
    """Adds calendar, trend, lag, and rolling-mean columns to the panel."""
    out = panel.sort_values(COMBO_KEY + ["semana"]).copy()

    # Calendar. The week number carries seasonality a linear model can use only
    # as a cycle, so it also goes in as sine and cosine — week 52 and week 1 are
    # neighbours, which a raw integer cannot express.
    stamp = out["semana"].dt.to_timestamp()
    out["semana_do_ano"] = stamp.dt.isocalendar().week.astype(int)
    out["mes"] = stamp.dt.month

    # The cycle length comes from the configured frequency, so the sine and
    # cosine describe one real year whatever the panel's grain.
    frequency = cfg.panel_freq.upper()[:1]
    periods = PERIODS_PER_YEAR.get(frequency)
    if periods is None:
        print(f"Aviso: PANEL_FREQ={cfg.panel_freq!r} não está no mapa de períodos; "
              f"assumindo {PERIODS_PER_YEAR_DEFAULT} períodos por ano.")
        periods = PERIODS_PER_YEAR_DEFAULT

    angle = 2 * np.pi * out["semana_do_ano"] / periods
    out["sazonal_sen"] = np.sin(angle)
    out["sazonal_cos"] = np.cos(angle)

    # Trend, as periods since the start of the panel. Zero-based so the
    # intercept of a linear model reads as "the first week".
    ordinais = out["semana"].astype("int64")
    out["tendencia"] = (ordinais - ordinais.min()).astype(int)

    # Lags and rolling means are computed per combination. Grouping is what
    # stops the lag of one class from reaching into another's history — without
    # it, the first week of class B would inherit the last week of class A.
    groups = out.groupby(COMBO_KEY, observed=True)
    for lag in SHORT_LAGS + (periods,):
        out[f"valor_lag_{lag}"] = groups["valor_total"].shift(lag)
        out[f"itens_lag_{lag}"] = groups["n_itens"].shift(lag)

    # shift(1) before rolling: the mean must not include the week being
    # predicted. Including it would be the leak this whole module avoids.
    out["valor_media_4"] = (groups["valor_total"]
                              .transform(lambda s: s.shift(1)
                                         .rolling(ROLLING_WINDOW).mean()))
    out["itens_media_4"] = (groups["n_itens"]
                              .transform(lambda s: s.shift(1)
                                         .rolling(ROLLING_WINDOW).mean()))

    empty = [c for c in out.columns
              if c.endswith(f"_{periods}") and out[c].isna().all()]
    if empty:
        print(f"Aviso: {', '.join(empty)} está(ão) inteiramente vazia(s) — o painel "
              f"tem {out['semana'].nunique()} semanas, menos que a defasagem de 52. "
              f"Amplie WINDOW_DAYS no .env para habilitar o horizonte de um ano.")

    return out.sort_values(["semana"] + COMBO_KEY).reset_index(drop=True)
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
- Produces: `split_by_week(panel: pd.DataFrame, n_splits: int) -> Iterator[tuple[np.ndarray, np.ndarray]]`,
  rendendo pares de arrays de índices posicionais de linha, compatíveis com
  `cross_val_score(cv=...)` do scikit-learn.

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_split.py`:

```python
import numpy as np
import pandas as pd
import pytest

from pipeline.split import split_by_week


@pytest.fixture
def panel():
    weeks = pd.period_range("2025-01-06", periods=10, freq="W")
    rows = [{"semana": s, "classe": c, "valor_total": 1.0}
              for s in weeks for c in ("A", "B", "C")]
    return pd.DataFrame(rows)


def test_no_week_on_both_sides(panel):
    for train, test in split_by_week(panel, n_splits=3):
        semanas_treino = set(panel.iloc[train]["semana"])
        semanas_teste = set(panel.iloc[test]["semana"])
        assert not (semanas_treino & semanas_teste)


def test_train_is_always_the_past(panel):
    for train, test in split_by_week(panel, n_splits=3):
        assert panel.iloc[train]["semana"].max() < panel.iloc[test]["semana"].min()


def test_whole_weeks_only(panel):
    """Cada semana traz as três classes juntas: 3 linhas por semana."""
    for train, test in split_by_week(panel, n_splits=3):
        assert len(test) % 3 == 0


def test_number_of_folds(panel):
    assert len(list(split_by_week(panel, n_splits=3))) == 3


def test_rejects_too_many_folds(panel):
    with pytest.raises(ValueError, match="semanas"):
        list(split_by_week(panel, n_splits=20))
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


def split_by_week(panel: pd.DataFrame, n_splits: int) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yields (train, test) positional row indices, cutting only between weeks."""
    weeks = np.sort(panel["semana"].unique())
    if len(weeks) < n_splits + 1:
        raise ValueError(
            f"{n_splits} dobras exigem pelo menos {n_splits + 1} semanas "
            f"distintas; o painel tem {len(weeks)}."
        )

    # Position of each row's week within the sorted week list, so a week-level
    # decision becomes a row-level mask without a join.
    position = pd.Series(panel["semana"]).map(
        {semana: i for i, semana in enumerate(weeks)}
    ).to_numpy()

    for train_weeks, test_weeks in TimeSeriesSplit(n_splits=n_splits).split(weeks):
        train = np.flatnonzero(np.isin(position, train_weeks))
        test = np.flatnonzero(np.isin(position, test_weeks))
        yield train, test
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
- Consumes: `CATEGORICAL_FEATURES` e `numeric_features(cfg)` (Task 5)
- Produces: `build_transformer(cfg: PipelineSettings) -> ColumnTransformer`,
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
from pipeline.features import CATEGORICAL_FEATURES, numeric_features
from pipeline.transform import build_transformer


@pytest.fixture
def cfg(tmp_path):
    return PipelineSettings(
        raw_csv=tmp_path / "x.csv", interim_dir=tmp_path,
        processed_dir=tmp_path, figures_dir=tmp_path)


@pytest.fixture
def X(cfg):
    n = 20
    data = {c: np.arange(n, dtype=float) for c in numeric_features(cfg)}
    data["materialOuServicoNome"] = ["Material", "Serviço"] * (n // 2)
    data["classe"] = ["A", "B", "C", "D"] * (n // 4)
    return pd.DataFrame(data)


def test_categoricals_become_binary_columns(cfg, X):
    out = build_transformer(cfg).fit_transform(X)
    # 2 valores de material/serviço + 4 classes + as numéricas
    assert out.shape[1] == 2 + 4 + len(numeric_features(cfg))


def test_unseen_category_does_not_break(cfg, X):
    transformador = build_transformer(cfg).fit(X)
    novo = X.head(1).copy()
    novo.loc[:, "classe"] = "Z"          # classe nunca vista no treino
    assert transformador.transform(novo).shape[1] == transformador.transform(X).shape[1]


def test_scaler_is_fitted_on_train_only(cfg, X):
    """O teste de vazamento: a média do scaler é a do treino, não a do todo."""
    train, test = X.iloc[:10], X.iloc[10:]
    modelo = Pipeline([("prep", build_transformer(cfg)), ("reg", Ridge())])
    modelo.fit(train, np.arange(10, dtype=float))

    # named_transformers_["num"] é o Pipeline (imputa + escala); o scaler
    # está dentro dele.
    scaler = (modelo.named_steps["prep"]
              .named_transformers_["num"].named_steps["escala"])
    expected = train["tendencia"].mean()
    # O índice vem da mesma lista que o transformador recebeu, não de uma
    # constante paralela que poderia estar em outra ordem.
    indice = numeric_features(cfg).index("tendencia")
    assert scaler.mean_[indice] == pytest.approx(expected)
    assert scaler.mean_[indice] != pytest.approx(X["tendencia"].mean())


def test_nan_features_do_not_break(cfg, X):
    """Os lags nascem com NaN nas primeiras semanas; o transformador aguenta."""
    X = X.copy()
    X.loc[0:3, "valor_lag_52"] = np.nan
    out = build_transformer(cfg).fit_transform(X)
    assert not np.isnan(out).any()
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
from pipeline.features import CATEGORICAL_FEATURES, numeric_features


def build_transformer(cfg: PipelineSettings) -> ColumnTransformer:
    """Builds the unfitted ColumnTransformer for the panel's feature columns."""
    # Lags are NaN for the first weeks of every combination, by construction.
    # Imputing the median keeps those rows usable; dropping them would throw
    # away the start of every series.
    numeric_pipe = Pipeline([
        ("imputa", SimpleImputer(strategy="median")),
        # Scaling matters for Ridge, which compares magnitudes, and is
        # harmless for the tree models. Keeping it makes swapping the
        # estimator a one-line change.
        ("escala", StandardScaler()),
    ])

    categorical_pipe = OneHotEncoder(
        # A class present only in the test fold must not raise: with a temporal
        # split, a class that appears late in the year is exactly that.
        handle_unknown="ignore",
        sparse_output=False,
    )

    return ColumnTransformer(
        [
            # Asked of features.py rather than hardcoded, so the annual lag's
            # name follows PANEL_FREQ and the two modules cannot drift apart.
            ("num", numeric_pipe, numeric_features(cfg)),
            ("cat", categorical_pipe, CATEGORICAL_FEATURES),
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
- Produces: `make_figures(raw_items: pd.DataFrame, kept_items: pd.DataFrame, panel: pd.DataFrame, destination: Path, quarantined: pd.DataFrame | None = None) -> list[Path]`,
  devolvendo os caminhos dos PNG escritos. O parâmetro `quarantined` alimenta a
  quarta figura; sem ele, ela sai com a mensagem "Nenhum item em quarentena".

**Design dos gráficos** (a paleta foi validada pelas seis checagens da skill
`dataviz` em modo claro — `#2a78d6` e `#eb6834`, todas PASS, contraste incluído;
não substituir sem revalidar com `scripts/validate_palette.js`):

| arquivo | forma | por quê |
|---|---|---|
| `01-series-raw_items-vs-kept_items.png` | duas linhas | mudança no tempo, duas séries: legenda presente e rótulo direto no fim de cada linha |
| `02-distribuicao-log.png` | histograma, x em log | uma série, sem legenda: o título nomeia o que é |
| `03-composicao-material-servico.png` | barras empilhadas por semana | composição ao longo do tempo, duas categorias |
| `04-quarantined.png` | barras horizontais | magnitude por motivo, com rótulo direto no valor |

- [ ] **Step 1: escrever o teste que falha**

`tests/pipeline/test_plots.py`:

```python
import matplotlib
matplotlib.use("Agg")           # sem display, antes de qualquer import de pyplot

import pandas as pd
import pytest

from pipeline.plots import make_figures


@pytest.fixture
def data():
    weeks = pd.period_range("2025-01-06", periods=6, freq="W")
    itens = pd.DataFrame({
        "dataInclusaoPncp": pd.to_datetime(
            ["2025-01-08", "2025-01-15", "2025-01-22"] * 2),
        "valorTotalResultado": [100.0, 200.0, 300.0, 1e10, 150.0, 250.0],
        "materialOuServicoNome": ["Material", "Serviço"] * 3,
    })
    kept_items = itens.drop(index=3)
    panel = pd.DataFrame([
        {"semana": s, "materialOuServicoNome": m, "classe": "A",
         "valor_total": 100.0 * (i + 1), "n_itens": i + 1}
        for i, s in enumerate(weeks) for m in ("Material", "Serviço")])
    return itens, kept_items, panel


def test_writes_the_four_pngs(data, tmp_path):
    itens, kept_items, panel = data
    quarantined = itens.loc[[3]].assign(motivo="quantidade implausível na classe")
    paths = make_figures(itens, kept_items, panel, tmp_path,
                              quarantined=quarantined)
    assert len(paths) == 4
    for path in paths:
        assert path.exists() and path.stat().st_size > 0
        assert path.suffix == ".png"


def test_empty_quarantine_does_not_break(data, tmp_path):
    itens, kept_items, panel = data
    vazia = itens.head(0).assign(motivo=pd.Series(dtype="object"))
    paths = make_figures(itens, kept_items, panel, tmp_path, quarantined=vazia)
    assert len(paths) == 4
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
SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"
# Text wears text tokens, never the series colour.
INK = "#0b0b0b"
INK_MUTED = "#52514e"
SURFACE = "#fcfcfb"
GRID = "#e3e2de"


def _new_figure(titulo: str, subtitulo: str = "") -> tuple[plt.Figure, plt.Axes]:
    """One figure, styled once: recessive axes, no top/right spines."""
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(titulo, color=INK, fontsize=13, loc="left", pad=16 if subtitulo else 8)
    if subtitulo:
        ax.text(0, 1.02, subtitulo, transform=ax.transAxes,
                color=INK_MUTED, fontsize=10, va="bottom")
    # Recessive grid and axes: the data carries the ink.
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(GRID)
    ax.tick_params(colors=INK_MUTED, labelsize=9)
    return fig, ax


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def _weekly_series(itens: pd.DataFrame) -> pd.Series:
    return (itens.set_index("dataInclusaoPncp")["valorTotalResultado"]
            .resample("W").sum())


def make_figures(raw_items: pd.DataFrame, kept_items: pd.DataFrame, panel: pd.DataFrame,
                   destination: Path, quarantined: pd.DataFrame | None = None) -> list[Path]:
    """Writes the four figures and returns their paths."""
    destination = Path(destination)
    paths: list[Path] = []

    # --- 1. the series, before and after cleaning -------------------------
    before, after = _weekly_series(raw_items), _weekly_series(kept_items)
    fig, ax = _new_figure("Gasto homologado por semana",
                      "Antes e depois do filtro de plausibilidade")
    # 2px lines, per the mark spec.
    ax.plot(before.index, before.to_numpy() / 1e9, color=SERIES_1, linewidth=2,
            label="Bruto")
    ax.plot(after.index, after.to_numpy() / 1e9, color=SERIES_2, linewidth=2,
            label="Limpo")
    # Two series: legend always, and direct labels because there are <= 4.
    for series, color, label in ((before, SERIES_1, "Bruto"), (after, SERIES_2, "Limpo")):
        if len(series):
            ax.annotate(label, (series.index[-1], series.iloc[-1] / 1e9),
                        xytext=(6, 0), textcoords="offset points",
                        color=color, fontsize=9, va="center")
    ax.set_ylabel("R$ bilhões", color=INK_MUTED, fontsize=10)
    ax.legend(frameon=False, labelcolor=INK_MUTED, fontsize=9)
    paths.append(_save(fig, destination / "01-serie-bruto-vs-limpo.png"))

    # --- 2. the distribution, on a log axis -------------------------------
    values = kept_items["valorTotalResultado"].dropna()
    values = values[values > 0]
    fig, ax = _new_figure("Distribuição do valor por item",
                      "Escala logarítmica: a mediana e a média diferem em 271x")
    if len(values):
        # One series: no legend box, the title names it.
        ax.hist(values, bins=np.logspace(np.log10(values.min()),
                                          np.log10(values.max()), 50),
                color=SERIES_1)
        ax.set_xscale("log")
        ax.axvline(values.median(), color=INK_MUTED, linewidth=1.5,
                   linestyle="--")
        ax.annotate(f"mediana R$ {values.median():,.0f}",
                    (values.median(), ax.get_ylim()[1] * 0.9),
                    xytext=(8, 0), textcoords="offset points",
                    color=INK_MUTED, fontsize=9)
    ax.set_xlabel("R$ por item (log)", color=INK_MUTED, fontsize=10)
    ax.set_ylabel("itens", color=INK_MUTED, fontsize=10)
    paths.append(_save(fig, destination / "02-distribuicao-log.png"))

    # --- 3. composition over time -----------------------------------------
    composition = (panel.groupby(["semana", "materialOuServicoNome"], observed=True)
            ["valor_total"].sum().unstack(fill_value=0))
    fig, ax = _new_figure("Composição do gasto por semana",
                      "Material e serviço, sobre os dados limpos")
    if not composition.empty:
        base = np.zeros(len(composition))
        for column, color in zip(composition.columns, (SERIES_1, SERIES_2)):
            height = composition[column].to_numpy() / 1e9
            # A 2px surface gap between stacked segments keeps the boundary
            # readable without a border colour.
            ax.bar(range(len(composition)), height, bottom=base, color=color,
                   label=str(column), width=0.82, linewidth=2,
                   edgecolor=SURFACE)
            base = base + height
        step = max(1, len(composition) // 12)
        ax.set_xticks(range(0, len(composition), step))
        ax.set_xticklabels([str(s) for s in composition.index[::step]], rotation=45,
                           ha="right")
        ax.legend(frameon=False, labelcolor=INK_MUTED, fontsize=9)
    ax.set_ylabel("R$ bilhões", color=INK_MUTED, fontsize=10)
    paths.append(_save(fig, destination / "03-composicao-material-servico.png"))

    # --- 4. what the cleaning removed -------------------------------------
    fig, ax = _new_figure("O que a limpeza removeu",
                      "Valor em quarentena, por motivo")
    if quarantined is not None and len(quarantined):
        by_reason = (quarantined.groupby("motivo")["valorTotalResultado"]
                      .agg(["sum", "size"]).sort_values("sum"))
        positions = range(len(by_reason))
        ax.barh(positions, by_reason["sum"] / 1e9, color=SERIES_2, height=0.6)
        ax.set_yticks(positions)
        ax.set_yticklabels(by_reason.index, fontsize=9)
        # Direct labels on the bars: the magnitude is the message.
        for i, (value, n) in enumerate(zip(by_reason["sum"], by_reason["size"])):
            ax.annotate(f"R$ {value / 1e9:,.1f} bi · {n:,} itens",
                        (value / 1e9, i), xytext=(6, 0),
                        textcoords="offset points", color=INK_MUTED,
                        fontsize=9, va="center")
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
    else:
        ax.text(0.5, 0.5, "Nenhum item em quarentena", transform=ax.transAxes,
                ha="center", color=INK_MUTED, fontsize=11)
        ax.set_axis_off()
    ax.set_xlabel("R$ bilhões", color=INK_MUTED, fontsize=10)
    paths.append(_save(fig, destination / "04-quarentena.png"))

    return paths
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
  `data/interim/quarantined.parquet`, `data/processed/panel.parquet`,
  `data/processed/painel_features.parquet` e os PNG em `reports/figures/`.

- [ ] **Step 1: escrever o teste que falha**

`tests/test_prepare.py`:

```python
import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

import prepare

HEADER = ("idCompraItem,dataInclusaoPncp,codigoClasse,materialOuServicoNome,"
             "situacaoCompraItemNome,itemCategoriaNome,temResultado,codigoGrupo,"
             "quantidade,valorUnitarioEstimado,valorTotal,valorTotalResultado,"
             "nomeFornecedor,orgaoEntidadeCnpj\n")


def _row(i, dia, qtd=10.0):
    return (f"id{i},2025-01-{dia:02d}T10:00:00,7010,Material,Homologado,"
            f"Informática (TIC),True,,{qtd},100.0,1000.0,900.0,forn{i},org1\n")


@pytest.fixture
def environment(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = "".join(_row(i, 2 + (i % 20)) for i in range(60))
    (raw / "contract_items.csv").write_text(HEADER + rows, encoding="utf-8-sig")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIGURES_DIR", str(tmp_path / "fig"))
    monkeypatch.setenv("TOP_CLASSES", "5")
    return tmp_path


def test_full_run_writes_the_artefacts(environment):
    assert prepare.main([]) == 0
    assert (environment / "interim" / "itens_limpos.parquet").exists()
    assert (environment / "interim" / "quarentena.parquet").exists()
    assert (environment / "processed" / "painel.parquet").exists()
    assert (environment / "processed" / "painel_features.parquet").exists()
    assert list((environment / "fig").glob("*.png"))


def test_stops_at_a_stage(environment):
    assert prepare.main(["--ate", "clean"]) == 0
    assert (environment / "interim" / "itens_limpos.parquet").exists()
    assert not (environment / "processed" / "painel.parquet").exists()


def test_missing_csv_returns_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert prepare.main([]) == 1
    assert "src/main.py" in capsys.readouterr().out


def test_panel_sum_matches_the_kept_items(environment):
    prepare.main([])
    kept = pd.read_parquet(environment / "interim" / "itens_limpos.parquet")
    panel = pd.read_parquet(environment / "processed" / "painel.parquet")
    assert panel["valor_total"].sum() == pytest.approx(
        kept["valorTotalResultado"].sum())
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
from pipeline.aggregate import to_panel
from pipeline.clean import clean
from pipeline.features import build_features
from pipeline.load import load_raw
from pipeline.plots import make_figures
from read_type_methods import ConfigError

STAGES = ["load", "clean", "aggregate", "features", "plots"]

EXIT_OK = 0
EXIT_ERROR = 1
# 130 is the conventional shell code for "terminated by SIGINT" (Ctrl+C).
EXIT_INTERRUPTED = 130


def _write(df: pd.DataFrame, path: Path) -> None:
    """Writes Parquet, falling back to CSV when pyarrow is absent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False)
    except ImportError:
        fallback = path.with_suffix(".csv")
        print(f"Aviso: pyarrow não está instalado; gravando {fallback.name} "
              f"em vez de Parquet (arquivo maior e sem tipos preservados).")
        df.to_csv(fallback, index=False, encoding="utf-8-sig")


def run_stages(cfg: PipelineSettings, ate: str) -> int:
    """Runs the stages up to and including `ate`. Returns rows in the panel."""
    limit = STAGES.index(ate)

    print("Lendo", cfg.raw_csv, flush=True)
    raw_items = load_raw(cfg.raw_csv, cfg)
    if limit == 0:
        return len(raw_items)

    kept_items, quarantined = clean(raw_items, cfg)
    # The invariant that would have caught the duplicate rows the day they
    # appeared: cleaning splits the frame, it never shrinks the total.
    assert len(kept_items) + len(quarantined) == len(raw_items), (
        f"limpeza perdeu linhas: {len(raw_items)} entraram, "
        f"{len(kept_items) + len(quarantined)} saíram"
    )
    _write(kept_items, cfg.interim_dir / "itens_limpos.parquet")
    _write(quarantined, cfg.interim_dir / "quarentena.parquet")
    if limit == 1:
        return len(kept_items)

    panel = to_panel(kept_items, cfg)
    n_weeks = panel["semana"].nunique()
    n_combos = panel[["materialOuServicoNome", "classe"]].drop_duplicates().shape[0]
    assert len(panel) == n_weeks * n_combos, (
        f"painel não é retângulo: {len(panel)} linhas para "
        f"{n_weeks} semanas x {n_combos} combinações"
    )
    expected = kept_items["valorTotalResultado"].sum()
    assert abs(panel["valor_total"].sum() - expected) < 1e-6 * max(1.0, abs(expected)), (
        "a agregação não preservou a soma dos valores"
    )
    _write(panel, cfg.processed_dir / "painel.parquet")
    print(f"Painel: {len(panel):,} linhas ({n_weeks} semanas x {n_combos} combinações)")
    if limit == 2:
        return len(panel)

    featured = build_features(panel, cfg)
    _write(featured, cfg.processed_dir / "painel_features.parquet")
    if limit == 3:
        return len(featured)

    figures = make_figures(raw_items, kept_items, panel, cfg.figures_dir,
                             quarantined=quarantined)
    print(f"{len(figures)} figura(s) em {cfg.figures_dir}")
    return len(featured)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code rather than exiting itself."""
    parser = argparse.ArgumentParser(
        description="Prepara o painel semanal a partir do CSV bruto do coletor.")
    parser.add_argument("--ate", choices=STAGES, default=STAGES[-1],
                        help="roda até este estágio, inclusive")
    args = parser.parse_args(argv)

    try:
        cfg = PipelineSettings.from_env()
    except ConfigError as error:
        # A configuration mistake is the user's to fix, so it is reported as a
        # plain message instead of a traceback.
        print(f"Erro de configuração no .env: {error}")
        return EXIT_ERROR

    print(f"Estágios: {' -> '.join(STAGES[:STAGES.index(args.ate) + 1])}")
    print(f"Saída:    {cfg.interim_dir} e {cfg.processed_dir}")

    try:
        rows = run_stages(cfg, args.ate)
    except FileNotFoundError as error:
        print(f"Erro: {error}")
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return EXIT_INTERRUPTED

    if rows == 0:
        print("\nNenhuma linha sobreviveu aos filtros. Revise STATUS_FILTER no .env.")
        return EXIT_OK

    print(f"\nPronto. {rows:,} linhas no artefato final.")
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
