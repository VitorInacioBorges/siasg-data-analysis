# Architecture

This document describes how the project is organised, what each file does,
which structural decisions were taken, and where the weak points are.

## The problem the architecture solves

Three constraints shape the entire design:

1. **Volume.** A one-year window is roughly 5 million items spread across
   about 10,000 requests. The dataset does not fit in memory.
2. **Duration.** A full collection takes hours. Interruptions are a certainty,
   not a possibility.
3. **Source instability.** The public API throttles traffic and drops
   connections under load.

The three core decisions answer those constraints directly: streaming
processing, per-chunk checkpointing, and a retry policy with growing backoff.

## Layered structure

The program is organised from the outermost layer inward. Each layer knows
only about the one immediately below it.

```
main()          reads config, prints the plan, sets the exit code
  └─ collect()      walks the chunks, owns the checkpoint and the writer
       └─ fetch_chunk()   pages through one date range
            └─ fetch_page()   a single HTTP request, with retries
  └─ summarize()    reads the finished CSV back and prints the rankings
```

This hierarchy is what lets an error raised deep inside `fetch_page()` be
reported cleanly in `main()`, without `sys.exit()` scattered through the code.

## Data flow

```
.env
  │
  ▼
Settings.from_env()  ──► validates everything before the first request
  │
  ▼
iter_date_chunks()   ──► splits the window into contiguous chunks,
  │                       anchored to an absolute calendar grid
  ▼
ThreadPoolExecutor   ──► MAX_WORKERS chunks at a time
  │
  ▼
┌────────── per chunk, in a worker thread ──────────┐
│  fetch_chunk() ──► fetch_page() ──► API           │
│        │                                          │
│        ▼                                          │
│  lock_csv ──► CsvWriter.write() ──► disk (flush)  │
│        │                                          │
│        ▼                                          │
│  if the chunk has closed:                         │
│    lock_checkpoint ──► Checkpoint.mark() ──► json │
└───────────────────────────────────────────────────┘
  │
  ▼
summarize()  ──► reads the CSV in slices ──► rankings in the terminal
```

The essential point: no arrow points back into memory. Each page goes to disk
as soon as it arrives, and the checkpoint is marked only afterwards.

Two details keep the concurrent version safe. The threads share exactly two
mutable resources — the CSV handle and the checkpoint — and each has its own
lock, held for microseconds against roughly 300 ms of network wait per
request. And only a chunk whose end date has already passed is recorded: a
chunk still ending in the future keeps receiving items, so marking it now
would make the next run skip whatever had not arrived yet.

## What each file does

### `src/main.py`

Orchestration and entry point. It holds six functions:

| Function | Responsibility |
|---|---|
| `iter_date_chunks()` | Splits the window into consecutive half-open chunks |
| `fetch_page()` | Performs one `GET`, retrying on throttling or server errors |
| `fetch_chunk()` | Yields one page of records at a time while paging a range |
| `collect()` | Walks the chunks and keeps the checkpoint and CSV consistent |
| `summarize()` | Reads the CSV back in bounded slices and prints three rankings |
| `main()` | Reads config, prints the plan, and returns the exit code |

Details worth attention:

- **Half-open chunks.** `iter_date_chunks()` produces ranges that share their
  boundaries: one chunk's end is the next one's start. That keeps chunks
  adjacent with no gap and no double counting, since the API treats the range
  the same way.
- **HTTP error classification.** 4xx responses, except 408 and 429, fail
  immediately. A malformed request would fail identically forever, so spending
  the retry budget on it would be waste. 408, 429, and the whole 5xx range are
  temporary by definition and go into the retry queue.
- **Linear growing backoff.** `retry_backoff * attempt` produces 15s, 30s,
  45s. Each wait is longer than the last, giving a throttled API progressively
  more room to recover.
- **`yield` instead of `return`** in `fetch_chunk()`. The caller writes the
  page to disk and comes back for the next one, so only one page is ever held
  in memory.
- **Summary in slices.** `summarize()` passes `chunksize` to `read_csv`, which
  turns the read into an iterator of frames. Peak memory stays proportional to
  one slice, not to the whole file. Totals accumulate through
  `.add(..., fill_value=0)`, because a group present in one slice and absent in
  another would otherwise become `NaN`.
- **Degrade instead of crash.** The summary groups only by the dimensions the
  CSV actually contains, so a narrowed `COLUMNS` list weakens the report rather
  than breaking it.

### `src/read_type_methods.py`

Typed readers for `.env` values. Defines `ConfigError` and seven internal
helpers.

| Function | Converts to |
|---|---|
| `_read_text()` | `str`, the base every other reader builds on |
| `_read_int()` | `int`, for page sizes, retries, and day counts |
| `_read_float()` | `float`, for sub-second delays |
| `_read_bool()` | `bool`, accepting English and Portuguese spellings |
| `_read_date()` | `date`, in ISO `YYYY-MM-DD` form |
| `_read_optional()` | `str | None`, for filters that may simply not be sent |
| `_read_list()` | `list[str]`, from a comma-separated list |

Each function does the same three things: read the raw string, decide whether
it is absent, and otherwise convert it. A value that is present but invalid
raises `ConfigError` immediately, instead of failing hours later deep inside a
request loop.

Two choices stand out:

- **Absent, empty, and whitespace-only are the same thing.** That is why
  `KEY=` in the `.env` file behaves exactly like leaving the line out.
- **`_read_bool()` rejects unknown values** rather than silently reading them
  as false. This stops `RESUME=maybe` from quietly wiping an existing
  download.

### `src/classes/settings.py`

The immutable object carrying every parameter for one run.

The design rule is that the `.env` file is read exactly once, at startup, by
`Settings.from_env()`. Everything downstream receives an already validated
instance and never touches `os.getenv` again.

Two derived properties prevent contradictory state:

- `start_date` is computed as `end_date - window_days` rather than configured.
  The two can never disagree, and a 365-day window stays 365 days regardless
  of leap years.
- `items_url` joins host and path while tolerating extra or missing slashes on
  either side.

`from_env()` validates what the API itself would reject: `PAGE_SIZE` outside
the accepted range, `WINDOW_DAYS` below 1, `CHUNK_DAYS` below 1 (which would
make `iter_date_chunks` loop forever), and `MATERIAL_OR_SERVICE` outside `M`
and `S`.

Filter keys stay in Portuguese because they are sent verbatim as API query
parameters. The `.env` names around them are English, for the reader's
benefit.

### `src/classes/csv_writer.py`

The streaming sink for downloaded records. It guarantees the two rules the
rest of the program depends on:

1. The header appears exactly once, no matter how many batches are written.
2. Each batch is flushed to disk immediately, so an interrupted run leaves a
   CSV consistent with the checkpoint.

Relevant technical choices:

- `newline=""` is required by the `csv` module to avoid blank lines on
  Windows.
- `utf-8-sig` writes the BOM Excel needs to display accented text correctly.
- `extrasaction="ignore"` drops API fields outside the chosen columns instead
  of raising. That lets `COLUMNS` be a subset, and means new fields added
  upstream by the API cannot break the run.
- The writer is built lazily, on the first non-empty batch, because the
  fieldnames may have to come from the data itself.

### `src/classes/checkpoint.py`

The bookkeeping that makes crash recovery possible. It holds one fact: the set
of date chunks whose rows are already safely in the CSV.

The unit of progress is always the whole chunk, never the page. A chunk is
recorded only after its last page is written, so a crash mid-chunk costs a
re-download of that chunk — a few duplicate requests, rather than the risk of
a gap in the data.

`mark()` rewrites the entire file on every completed chunk. This is
deliberate: the file is a few kilobytes at most, and writing it whole means
the on-disk state stays a complete, valid snapshot rather than a partial
write.

`reset()` pairs with deleting the CSV in `collect()`. The two must always
describe the same download, or resuming would append rows on top of a file
that no longer matches.

## The data preparation pipeline

The collector delivers a raw CSV. The pipeline turns it into a weekly panel
with features, ready for a scikit-learn model. The entry point is
`src/prepare.py`, and each stage is a function in `src/pipeline/`, testable on
its own.

### Two regimes, separated by the panel

This is the decision that organises everything else.

Up to the panel, the stages run **once over the whole dataset** and write the
result to a file. That is correct because they are deterministic:
deduplicating by `idCompraItem` and applying a value ceiling give the same
answer regardless of which cross-validation fold is running.

From the panel onwards, nothing can be precomputed. A `StandardScaler`'s mean
computed over train and test together carries the future into the training
set — that is leakage, and it produces a flattering score with a useless
model. So `transform.py` returns the transformer **unfitted**: the caller
embeds it in a `Pipeline`, and scikit-learn refits it inside every fold.

The boundary between the two regimes is exactly
`data/processed/painel.parquet`.

### The stages

| Stage | Module | What it writes |
|---|---|---|
| `load` | `pipeline/load.py` | — (in memory) |
| `clean` | `pipeline/clean.py` | `interim/itens_limpos.parquet`, `interim/quarentena.parquet` |
| `aggregate` | `pipeline/aggregate.py` | `processed/painel.parquet` |
| `features` | `pipeline/features.py` | `processed/painel_features.parquet` |
| `plots` | `pipeline/plots.py` | `reports/figures/*.png` |

`split.py` and `transform.py` are not stages: they write nothing and do not
run during a `prepare.py` execution. They are the pieces the modelling step
will consume.

### What each file does

#### `src/prepare.py`

Orchestration and entry point, in the same shape as `main.py`: `main()` reads
the configuration and decides the exit code, `run_stages()` runs the stages in
order. The `--ate` option stops at a stage, which lets you inspect one step
before going further.

What sets this module apart are the **invariants it asserts between stages**,
which fail loudly rather than silently:

- cleaning splits the frame, it never shrinks it:
  `len(kept) + len(quarantined)` must equal `len(raw)`;
- the panel is a rectangle: `len(panel)` must equal `weeks × combinations`;
- aggregation preserves the sum: the panel total must match the cleaned-items
  total.

The first one would have caught the duplicate rows the day they appeared.

#### `src/classes/pipeline_settings.py`

Sibling of `Settings`: same contract, different concern. `Settings` configures
the collector that produces `data/raw/`; this configures the stages that
consume it. They are separate classes because they are read at different
times by different entry points, and a run of one does not need the other's
validation to pass.

One detail is worth recording: this module's `load_dotenv()` is anchored to
the file, not to the caller's frame. Without that, under `python -c` there is
no calling file, the search falls back to the working directory, finds
nothing, and every value silently becomes the dataclass default. Measured: a
`.env` saying `MAX_WORKERS=2` read back as 3. For a data pipeline that is the
worst kind of failure, because the run succeeds with the wrong configuration.

#### `src/pipeline/load.py`

Typed reading in slices, deduplication by `idCompraItem`, and a status filter.
Three non-obvious details:

- **`on_bad_lines="warn"`, not `"skip"`.** Both discard a row with extra
  fields; the first makes pandas say so in its own words instead of leaving
  you to infer it.
- **Truncation detection.** A CSV interrupted inside a quoted field makes
  pandas raise, and `on_bad_lines` does not catch it. The module trades the
  traceback for a message that says what to do.
- **Race with the collector.** A snapshot of the file is taken before and
  after the read. If the file moved in between, the partial-row heuristic is
  discarded rather than applied, because no check is exact on a file being
  appended to — and acting on a stale measurement has discarded a legitimate
  row before.

#### `src/pipeline/clean.py`

The only stage that removes rows on judgement. The rule reads the **awarded
total**, not the quantity, because the absurdity is in the product.

The measured problem: 6 rows out of 1,440,492 carry 53.77% of the total value,
and they are data-entry errors at the source. The largest is 1,713,940 units
of postal service at R$ 132,000 each — R$ 226 billion, 31% of the dataset in
one row. Left in, the year reads R$ 735 bn; taken out, R$ 340 bn.

An earlier design measured implausible quantity within each class and was
dropped after being measured against a full year: it missed that largest row
entirely (z = 3.41 against a threshold of 8), and the 177 rows it caught on
its own were legitimate public purchases at scale — 28 million vaccine doses,
8.8 million rounds of ammunition, 8,797 textbooks. Quantity within a class
does not separate bulk from typo.

Known limitation, accepted: two real errors stay in — 867,796,000 kg of goat
meat and 850,000 laptops, together 1% of the total. Reaching them would need a
ceiling that also removes the school meal programme.

Nothing is deleted. Removed rows come back as a second frame with a `motivo`
column, which the caller writes to `interim/quarentena.parquet`.

#### `src/pipeline/aggregate.py`

Where the grain changes: one row per item becomes one row per period. This is
the stage that makes forecasting possible at all, because at the item grain
there is no "next week" — only items. The panel puts time on the row.

Two details decide whether the result is usable:

- **Classes are reduced to the largest by value.** The real data has 434 of
  them, and the top 50 already cover 94.1% of the money. One-hot encoding all
  434 would add more columns than the panel has time steps. The rest goes to
  the `Outras` bucket; a missing class gets its own bucket, `Sem classe`,
  because the two mean different things.
- **The panel must come out a complete rectangle.** After a `groupby`, a week
  in which a class bought nothing simply does not exist, and a lag would reach
  three weeks back instead of one. A week with no purchase is a zero, not a
  gap — but the median of an empty set stays null, because there was no price
  to observe, which is not the same as a price of zero.

#### `src/pipeline/features.py`

Makes implicit information explicit, because a model only sees its columns.
**Every feature here looks backwards.** A column that peeked forward would be
the leak that produces a high score and a useless model.

- The week number also goes in as sine and cosine, because week 52 and week 1
  are neighbours, which a raw integer cannot express.
- Lags and rolling means are computed **per combination**. The grouping is
  what stops one class's lag from reaching into another's history.
- The rolling mean applies `shift(1)` before `rolling`: including the week
  being predicted would be exactly the leak this module avoids.
- `numeric_features(cfg)` is a function, not a constant. With `PANEL_FREQ=M`
  the annual lag is called `valor_lag_12`, and a fixed list would point at
  columns that do not exist.

**A structural limitation, not an accidental one:** with a 365-day collection
window the panel has 52 weekly steps, so `valor_lag_52` comes out entirely
null. Forecasting a year ahead needs a lag of 52 or more, because the model
cannot be handed a value it will not know at prediction time. Short horizons,
one to eight weeks, are well served by the short lags. Widening `WINDOW_DAYS`
populates `lag_52` without changing a line of this module.

#### `src/pipeline/split.py`

The temporal split, and the reason it cannot be scikit-learn's
`TimeSeriesSplit` alone. The panel holds about 53 rows per week, one per
combination. `TimeSeriesSplit` cuts by row position, so it lands in the middle
of a week and puts half of that week's classes in train and the other half in
test. The model then sees part of the very period it is being scored on.

So the split is taken over the distinct weeks and only then expanded to rows.

#### `src/pipeline/transform.py`

A factory, not a fitted object — for the reason explained in "two regimes"
above. It imputes the median on the numeric columns, because lags are null for
the first weeks of every combination and dropping those rows would throw away
the start of every series. It encodes the categoricals with
`handle_unknown="ignore"`, because under a temporal split a class that appears
only late in the year is exactly the case of a category missing from training.

It asks `features.py` for the column list rather than repeating it, so the two
modules cannot drift apart.

#### `src/pipeline/plots.py`

The four figures, and one rule they all obey: **raw and clean appear side by
side.** Six rows carry more than half of the value, so a chart of the cleaned
series alone would hide the most consequential decision in the pipeline.

The palette has two categorical slots, `#2a78d6` and `#eb6834`, validated
against the six checks of the `dataviz` method on the light surface. Do not
substitute without revalidating.

## Strengths

**Constant memory usage.** Nothing accumulates. One page lives in memory
during collection, one slice during the summary. The program handles 5 million
records with the same footprint it would use for 5 thousand.

**Reliable and cheap resume.** The maximum cost of an interruption is one
chunk. At the 7-day default, that is minutes of lost work in a run measured in
hours.

**Configuration fails early.** A typo in `.env` stops the run in the first
second, not after two hours of downloading.

**Correctly classified errors.** Distinguishing permanent failure (4xx) from
temporary failure (408, 429, 5xx) avoids both useless retries and premature
surrender.

**Single-responsibility layers.** Each file in `classes/` has one reason to
exist and one reason to change. `CsvWriter` knows nothing about date chunks;
`Checkpoint` knows nothing about HTTP.

**Documentation in the code.** The comments explain why decisions were made,
not what a line does. A reader learns why `min()` is there without rebuilding
the reasoning.

**Graceful degradation in the summary.** Narrowing `COLUMNS` weakens the
report instead of breaking it.

**Leakage is prevented by construction, not by discipline.** The transformer
comes out unfitted and the split cuts whole weeks. There is no way for a
distracted contributor to fit a scaler over the whole dataset without
rewriting the module.

**The invariants fail loudly.** `prepare.py` asserts between stages that
cleaning lost no rows, that the panel is a rectangle, and that aggregation
preserved the sum. A bug in those three would be silent and very expensive.

**Nothing is discarded in silence.** Every row the cleaning removes comes back
in `quarentena.parquet` with its reason, and the fourth figure shows how much
value left.

## Weaknesses

**There is no real Python package.** `__init__.py` files are missing from
`src/` and `src/classes/`. Imports work by accident of the working directory,
and that fragility is exactly what produced the broken relative imports in
`settings.py`.

**Paths depend on the working directory.** `OUTPUT_CSV` and `CHECKPOINT_FILE`
are relative to wherever the command was launched, not to the script. Running
from `src/` writes to `src/data/`; running from the root writes to `data/`. A
resume launched from the wrong place will not find the earlier progress.

**The collector has no tests.** The pipeline has 49, but none of them cover
`iter_date_chunks()`, the HTTP error classification in `fetch_page()`, or the
`Checkpoint` lifecycle — precisely the three places in the collector where a
bug is silent and expensive.

**`valor_lag_52` comes out empty with the current window.** This follows from
the 365-day window rather than from a defect, and it is documented in
`features.py`. The practical effect is that the one-year horizon rests on
trend and calendar alone until the collection window grows.

**Messages in two languages.** User-facing errors are in Portuguese, comments
and docstrings in English. It is a defensible choice, but it is recorded
nowhere, and the boundary has already slipped in places.

**The checkpoint does not validate the configuration.** Resuming after
changing `CHUNK_DAYS` or the filters in `.env` produces a CSV that mixes two
different collections. Changing `CHUNK_DAYS` moves every grid boundary, so the
chunk keys stop matching what was already downloaded. `CsvWriter` catches the
narrower case of a changed `COLUMNS` and warns, but the checkpoint itself
records nothing about the configuration that produced it.

**Concurrency is capped by the API, not by the code.** `MAX_WORKERS` above 4
makes the API return HTTP 429 in bulk, at which point the retry backoff makes
the run slower than a sequential one. The collector does not detect this and
adjust; you have to lower the setting yourself.

## Suggested evolution

In order of return on effort:

1. Record in the checkpoint the configuration that produced it, and refuse
   incompatible resumes.
2. Write tests for `iter_date_chunks()`, for the HTTP status classification in
   `fetch_page()`, and for the `Checkpoint` lifecycle, bringing the collector
   up to the pipeline's level.
3. Add `__init__.py` to `src/`, `src/classes/`, and `src/pipeline/`, turning
   the project into a real package.
4. Resolve paths relative to the project root rather than the working
   directory.
5. Back off automatically when HTTP 429 becomes frequent, instead of leaving
   `MAX_WORKERS` to be tuned by hand.
6. Widen `WINDOW_DAYS` beyond one year, which populates `valor_lag_52` and
   with it the annual forecasting horizon.

## Recorded decisions

Formal architectural decisions live in [decisions/](decisions/), in MADR
format. Use [adr-template.md](decisions/adr-template.md) as the basis for new
records.
