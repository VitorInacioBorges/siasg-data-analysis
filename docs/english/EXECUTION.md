# Execution

This guide covers preparing the environment, configuring the project, and
running the procurement data collector.

## Prerequisites

- Python 3.9 or later
- Internet access (the API is public and needs no key)
- Disk space: a one-year window produces a CSV of several gigabytes

## 1. Prepare the environment

On Ubuntu or WSL:

```bash
# Update the system and install Python
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv python3-dev -y

# Create the virtual environment in venv/
python3 -m venv venv

# Activate it (repeat in every new terminal session)
source venv/bin/activate
```

To leave the virtual environment, run `deactivate`.

## 2. Install the dependencies

The collector uses only three external libraries:

```bash
pip install requests pandas python-dotenv
```

If you plan to move on to the analysis and machine learning stage, install the
full set as well:

```bash
pip install numpy matplotlib scikit-learn seaborn tqdm
```

To confirm that `pip` and `python` point at the same environment:

```bash
which python
which pip
```

Both must resolve inside `venv/`. If they don't, the virtual environment is
not active.

## 3. Configure

All configuration lives in a `.env` file inside `src/`. Start from the
documented template:

```bash
cp src/.env.example src/.env
```

`Settings.from_env()` reads the `.env` file exactly once, at startup. An
invalid value stops the run in the first second, before a single request goes
out.

### Configuration keys

#### API

| Key | Default | Description |
|---|---|---|
| `API_BASE_URL` | `https://dadosabertos.compras.gov.br` | API host |
| `ITEMS_ENDPOINT` | `/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133` | Path of the items endpoint |

#### Time window

| Key | Default | Description |
|---|---|---|
| `END_DATE` | today | Last day of the window, in `YYYY-MM-DD` form. Empty means today |
| `WINDOW_DAYS` | `365` | Fixed window length in days, counted back from `END_DATE` |
| `CHUNK_DAYS` | `7` | Width of each downloaded chunk. Smaller means safer and more requests |

The start date is not configurable: it is derived from
`END_DATE - WINDOW_DAYS`, so the two can never disagree.

#### Pagination

| Key | Default | Description |
|---|---|---|
| `PAGE_SIZE` | `500` | Records per request. Bigger means fewer requests for the same data |
| `PAGE_SIZE_MIN` | `10` | Lower bound accepted, checked at startup |
| `PAGE_SIZE_MAX` | `500` | Upper bound accepted, checked at startup |

`PAGE_SIZE_MIN` and `PAGE_SIZE_MAX` are the limits the API itself enforces.
Raising `PAGE_SIZE_MAX` does not make the API accept a larger page; it only
turns a clear message at startup into an HTTP 400 in the middle of the run.

#### Optional filters

Leave empty to fetch everything. Measured volume for a single day, to size
your run:

| Filter applied | Items per day | Yearly estimate |
|---|---|---|
| none | ~13,800 | ~5.0 million |
| `ITEM_STATUS=2` | ~11,000 | ~4.0 million |
| `MATERIAL_OR_SERVICE=S` | ~3,600 | ~1.3 million |

| Key | Description |
|---|---|
| `MATERIAL_OR_SERVICE` | `M` for material, `S` for service |
| `ITEM_STATUS` | `1` in progress, `2` awarded, `3` annulled or revoked |
| `HAS_RESULT` | `true` returns only items with an awarded supplier |
| `ORGAN_CNPJ` | CNPJ of the contracting body, digits only |
| `UNIT_CODE` | UASG code of the contracting unit |
| `ITEM_GROUP` | CATMAT/CATSER group code |
| `ITEM_CLASS` | CATMAT/CATSER class code |
| `CATALOG_ITEM` | Specific catalog item code |
| `SUPPLIER_ID` | Supplier CNPJ or CPF |

#### Columns

| Key | Default | Description |
|---|---|---|
| `COLUMNS` | 19-column subset | Comma-separated list. Empty returns all 45 API fields |

The subset suggested in the template covers a "what did the government spend
on" analysis and cuts the output file to roughly a third of the full size.

#### HTTP behaviour

| Key | Default | Description |
|---|---|---|
| `REQUEST_TIMEOUT` | `60` | Seconds before a single request gives up |
| `REQUEST_DELAY` | `0` | Pause in seconds between successful requests |
| `MAX_RETRIES` | `5` | Attempts per page before the run fails |
| `RETRY_BACKOFF` | `15` | Base seconds to wait, multiplied by the attempt number |
| `MAX_WORKERS` | `3` | Chunks downloaded at the same time |

The wait grows linearly: 15s, 30s, 45s, and so on.

`MAX_WORKERS` controls how many date chunks the collector downloads in
parallel. Measured against this API, the useful ceiling is 2 to 4: at 8 the
throughput degrades, and beyond that the API returns HTTP 429 in bulk, at
which point the backoff makes the run slower than a sequential one. If you see
repeated 429 messages, lower it to `2`.

`REQUEST_DELAY` defaults to `0` because the spacing now comes from two better
sources: the network latency itself, and the backoff that reacts to a real
429. Raise it only if the API starts refusing a sequential run.

#### Output

| Key | Default | Description |
|---|---|---|
| `OUTPUT_CSV` | `data/contract_items.csv` | Path of the generated CSV |
| `CHECKPOINT_FILE` | `data/checkpoint.json` | Path of the progress file |
| `RESUME` | `true` | `true` continues where it stopped; `false` deletes the CSV and starts over |
| `TOP_ITEMS` | `20` | How many rows each summary ranking prints |
| `SUMMARY_CHUNK_ROWS` | `200000` | Rows the summary reads at a time |

`SUMMARY_CHUNK_ROWS` keeps the summary's memory use proportional to one slice
instead of the whole file. Lower it on a machine with little RAM.

> **Warning:** `RESUME=false` deletes the existing CSV before starting. The
> checkpoint and the CSV are always cleared together, because keeping one
> without the other would produce either duplicated or missing rows.

## 4. Run

```bash
python src/main.py
```

`OUTPUT_CSV` and `CHECKPOINT_FILE` resolve relative to the current working
directory, not to the script location. Always run from the repository root so
the files land in `data/` every time.

### What you will see

The program prints the plan before it starts:

```
Período: 2025-09-06 até 2026-09-06 (365 dias, 53 blocos de 7 dias)
Filtros: {'situacaoCompraItem': '2'}
Saída:   data/contract_items.csv
```

Then progress, chunk by chunk:

```
[1/53] 2025-09-06 → 2025-09-13: baixando...
    24.310 itens gravados.
[2/53] 2025-09-13 → 2025-09-20: já baixado, pulando.
```

Finally, the three summary rankings:

```
Gasto total por tipo (Material x Serviço):
  Material     R$   12.345.678.901,23   (2.100.000 itens)
  Serviço      R$    8.765.432.109,87   (1.300.000 itens)

Top 20 categorias por valor:
  R$    1.234.567.890,12  Serviços de engenharia

Top 20 itens por valor:
  R$      987.654.321,00  Contratação de serviço continuado de...
```

Runtime messages are in Portuguese by design; see
[PRACTICES.md](PRACTICES.md#languages-in-code).

## 5. Resume an interrupted run

The collector writes a checkpoint after every completed chunk. If the run
stops for any reason, run it again with `RESUME=true` in the `.env` file:

```bash
python src/main.py
```

Chunks already downloaded are skipped. The unit of progress is always the
whole chunk, never the page: a chunk is recorded only after its last page has
been written to disk. A crash mid-chunk costs only a re-download of that
chunk, rather than risking a gap in the data.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success, including the case where no item matches the filters |
| `1` | Configuration error in `.env`, or API failure after the retries are spent |
| `130` | Interrupted with `Ctrl+C`. The CSV was closed and remains consistent |

## Troubleshooting

### Repeated `status 429` messages

The API is refusing the request rate. Lower `MAX_WORKERS` to `2`, and if the
messages continue, set `REQUEST_DELAY` back to `0.2`. Progress is saved: run
again with `RESUME=true`.

### `Aviso: COLUMNS mudou desde a execução anterior`

You changed `COLUMNS` in `.env` between runs, and the CSV already on disk has
a different header. The collector keeps the existing header, because writing
rows under a new column list would silently produce a file whose rows do not
line up with its own header. To apply the new list, start a fresh run with
`RESUME=false`.

### A chunk says "bloco ainda aberto"

That chunk ends in the future, so it is still receiving items. The collector
downloads it but does not record it in the checkpoint, which is what makes the
next run pick up the items that arrived in the meantime. This message is
expected on every run.

### The API rejected the request with status 400

A filter or a date is malformed. 4xx requests fail immediately, without
consuming the retry budget, because they would fail identically forever.
Review the filters in your `.env` file.

### Failure after 5 attempts

The API is throttling. Lower `MAX_WORKERS`, increase `RETRY_BACKOFF`, or
increase `REQUEST_DELAY`. Progress is saved: run again with `RESUME=true`.

### The CSV doesn't open correctly in Excel

The file is written in `utf-8-sig`, which includes the BOM Excel needs to show
accented text correctly. If the problem persists, check that Excel is
configured to use the comma as the separator.

### `Aviso: não foi possível ler o checkpoint`

The checkpoint file is unreadable. Now that `Checkpoint.mark()` writes
atomically — a temporary file followed by `os.replace` — killing the process
mid-write no longer produces a truncated file, so this warning points at
damage from another source. It is not fatal: the run starts over instead of
aborting.
