# Architecture decision records

This folder records the architectural decisions taken on this project, in
[MADR](https://adr.github.io/madr/) format.

## Why they exist

Code shows what a project does. It doesn't show what was considered and
rejected, or why. An architecture decision record captures the reasoning at
the moment the choice was made, so a future reader — including you, months
from now — can tell a deliberate decision from an accident.

## When to write one

Write a record when a decision is hard to reverse, affects more than one file,
or has a plausible alternative that a reader might otherwise assume you
overlooked. Examples from this project: streaming to CSV instead of holding
the dataset in memory, recording progress per chunk rather than per page, and
capping concurrency at a measured ceiling instead of the largest value that
runs.

Don't write one for choices the code already explains on its own.

## How to add a record

1. Copy [adr-template.md](adr-template.md) to `NNNN-short-title.md`, where
   `NNNN` is the next number in sequence, starting at `0001`.
2. Fill in the context, the options considered, and the consequences —
   including the negative ones.
3. Add the record to the index below.
4. Write the same record in
   [../../portuguese/decisions/](../../portuguese/decisions/), keeping the
   filename and the structure identical. Only the prose language changes.

A record is never edited to reflect a change of mind. Write a new one and mark
the old record as superseded by it.

## Index

| Number | Title | Status |
|---|---|---|
| — | No records yet | — |
