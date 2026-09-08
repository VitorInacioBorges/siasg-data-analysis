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

## Weaknesses

**There is no real Python package.** `__init__.py` files are missing from
`src/` and `src/classes/`. Imports work by accident of the working directory,
and that fragility is exactly what produced the broken relative imports in
`settings.py`.

**There is no `requirements.txt`.** Dependencies are described in prose in the
`README.md`, without pinned versions. Two machines can resolve different
`pandas` versions and produce different results.

**Paths depend on the working directory.** `OUTPUT_CSV` and `CHECKPOINT_FILE`
are relative to wherever the command was launched, not to the script. Running
from `src/` writes to `src/data/`; running from the root writes to `data/`. A
resume launched from the wrong place will not find the earlier progress.

**There are no tests.** No suite covers the chunk arithmetic, the HTTP error
classification, or the resume logic — precisely the three places where a bug
is silent and expensive.

**Messages in two languages.** User-facing errors are in Portuguese, comments
and docstrings in English. It is a defensible choice, but it is recorded
nowhere, and the boundary has already slipped in places.

**`data/` is not in `.gitignore`.** A multi-gigabyte CSV can be committed by
accident. The `venv/` folder has the same problem.

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
   `fetch_page()`, and for the `Checkpoint` lifecycle.
3. Add `__init__.py` to `src/` and `src/classes/`, turning the project into a
   real package.
4. Create `requirements.txt` with pinned versions.
5. Add `data/` and `venv/` to `.gitignore`.
6. Resolve paths relative to the project root rather than the working
   directory.
7. Back off automatically when HTTP 429 becomes frequent, instead of leaving
   `MAX_WORKERS` to be tuned by hand.

## Recorded decisions

Formal architectural decisions live in [decisions/](decisions/), in MADR
format. Use [adr-template.md](decisions/adr-template.md) as the basis for new
records.
