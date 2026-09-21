# Practices

Conventions adopted in this project. The goal is that anyone can predict where
a change belongs and what it should look like.

## Documentation

### Bilingual structure

Every `docs/` folder keeps two complete, equivalent versions:

```
docs/
├── english/
│   ├── EXECUTION.md
│   ├── ARCHITECTURE.md
│   ├── PRACTICES.md
│   └── decisions/
│       ├── README.md
│       └── adr-template.md
└── portuguese/
    ├── EXECUCAO.md
    ├── ARQUITETURA.md
    ├── PRATICAS.md
    └── decisions/
        ├── README.md
        └── adr-template.md
```

Three rules apply:

1. **The filename is translated along with the content.** `EXECUCAO.md` in
   Portuguese corresponds to `EXECUTION.md` in English.
2. **Formatting is identical across versions.** Same sections, same order,
   same tables, same code blocks. Only the language changes.
3. **Both versions change together.** Editing one language without its
   counterpart leaves the documentation inconsistent.

### `README.md` is the one exception

`README.md` stays at the repository root as a single file holding both
languages, and its filename is never translated. It carries the full document
twice: Portuguese first, then a horizontal rule, then the same document in
English. Both halves must have the same sections in the same order, the same
tables, and the same links.

Because the headings repeat across the two halves, their anchor slugs collide.
Give the English half explicit `<a name="...">` anchors wherever a link has to
reach it, and put a language switcher at the top of each half.

### Skill and plugin material stays in one language

Anything produced by or for a skill or a plugin is exempt from the bilingual
rule. That covers `docs/superpowers/` — the design specs and implementation
plans written by the brainstorming and planning skills — and any other
directory a tool owns.

These are working artifacts of a workflow, not documentation the project
publishes. They are written in the language the work happens in, which for this
project is Portuguese, and they are never mirrored.

### Filenames

Use ASCII characters only. `EXECUCAO.md`, never `EXECUÇÃO.md`: accents in
filenames cause problems across different file systems, URLs, and
command-line tools.

### Style

The complete guide ships with the `docs-writer` skill, as
`references/style-guide.md` inside the skill folder. It lives outside this
repository because the skill is installed for the user, not for the project.
The points that apply most here:

- Active voice. "The system sends a notification," not "a notification is
  sent."
- Present tense to describe behaviour.
- Second person when addressing the reader.
- Sentence case headings, with the hierarchy respected.
- Wrap text at 80 characters, except for long links and tables.
- `code font` for filenames, commands, and API elements.
- Descriptive link text. Never "click here."
- Numbered lists for sequential steps, bullets for everything else.

### Code references

Always point at the file and line, using a relative path:

```markdown
[src/main.py:49](../../src/main.py#L49)
```

This keeps the link clickable and makes it quick to check whether the
documentation still matches the code.

## Decision records

Architectural decisions that shape the project are recorded under
`docs/<language>/decisions/`, in [MADR](https://adr.github.io/madr/) format.

### When to write an ADR

Write one when the decision is expensive to reverse, when someone is likely to
ask "why is it like this?" in six months, or when real alternatives were in
contention. Don't write one for obvious or trivial choices.

### How to write one

1. Copy `adr-template.md` to `adr-NNN-short-title.md`, where `NNN` is
   sequential and zero-padded.
2. Fill in the context, the options considered, and the outcome.
3. Record the negative consequences honestly. An ADR that lists only upsides
   is not describing a decision, it is advertising.
4. Create the version in the other language, with the same number.

An ADR is never edited after it is accepted. If the decision changes, write a
new one that supersedes it and mark the old one as superseded.

## Code

### Organisation

- `src/main.py` holds the collector's orchestration and nothing else.
- `src/prepare.py` holds the pipeline's orchestration and nothing else.
- `src/classes/` holds one class per file, each with a single responsibility.
- `src/pipeline/` holds one stage per file, each testable on its own.
- `src/read_type_methods.py` holds the typed `.env` readers.

A new durable responsibility earns a file in `classes/`. A new pipeline stage
earns a file in `pipeline/`. A helper used by only one entry point stays in
that entry point.

### Comments

Comments explain **why**, not **what**. The code already says what it does.

```python
# Good: explains the reason
# 4xx means the request itself is wrong and would fail identically forever,
# so fail immediately instead of burning the retry budget.

# Bad: restates the code
# Check whether the status is below 500
```

### Languages in code

- Comments and docstrings in English.
- Messages aimed at whoever runs the program in Portuguese.
- API filter keys in Portuguese, because they are the API contract.
- Variable and function names in English.

### Configuration

Every new parameter follows the same path:

1. Add the key to `src/.env.example`, with a comment explaining the default.
2. Add the field to `Settings` (collector) or `PipelineSettings` (pipeline),
   with a type annotation.
3. Read the key in that class's `from_env()`, using the appropriate typed
   reader.
4. Validate in `from_env()` anything the API or the stage would reject.
5. Document the key in the matching table in both `EXECUTION.md` and
   `EXECUCAO.md`.

No module other than those two `from_env()` methods calls `os.getenv`. The two
classes are separate on purpose: a pipeline run does not need the collector's
validation to pass, and the other way round.

### Error handling

- A configuration error raises `ConfigError` and becomes a readable message,
  not a stack trace.
- A recoverable network failure enters the retry policy.
- A permanent failure raises `RuntimeError`, which travels up to `main()`.
- `main()` is the only place that decides the process exit code.

Never call `sys.exit()` outside `main()`. Doing so would prevent the `finally`
blocks from closing the CSV, leaving the file inconsistent with the
checkpoint.

### Durability

In the collector, two invariants must not be broken:

1. A chunk is marked in the checkpoint only after all of its rows have been
   written and flushed to disk.
2. The checkpoint and the CSV are always cleared together.

Any change touching `collect()`, `CsvWriter`, or `Checkpoint` must preserve
both.

In the pipeline, three invariants are asserted in `prepare.py` between the
stages, and must keep holding:

1. Cleaning splits the frame, it never shrinks it:
   `len(kept) + len(quarantined) == len(raw)`.
2. The panel is a complete rectangle:
   `len(panel) == weeks × combinations`.
3. Aggregation preserves the sum of the values.

They are `assert` statements, deliberately: a failure here is a code defect,
not bad user input, and it must stop the run loudly.

### Data handling

Three rules apply to every pipeline stage:

- **`data/raw/` is never edited.** It is the witness. Every derived artefact
  goes to `interim/` or `processed/`, so deleting both and running again
  rebuilds everything.
- **Nothing is discarded in silence.** A removed row comes back in
  `quarentena.parquet` with a `motivo` column.
- **Nothing the model consumes may be pre-fitted.** Transformers come out
  unfitted, for scikit-learn to refit inside each fold. A mean computed over
  train and test together is leakage, and the symptom is a score that looks
  too good.

## Git

### Commit messages

Use the imperative mood and keep the first line under 72 characters:

```
Fix relative imports in settings.py

The imports used `..src`, which climbs above the top-level package.
Replaced with the absolute form already used in main.py.
```

### What not to version

- `venv/` — virtual environment
- `data/` — generated CSV and checkpoint
- `__pycache__/` — bytecode
- `src/.env` — local configuration, possibly holding sensitive filters

`.env.example` is versioned; `.env` never is.
