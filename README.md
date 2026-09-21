# siasg-data-analysis

**Português** | [English](#english)

Coleta e analisa dados de compras públicas federais brasileiras a partir da
[API de dados abertos do Compras.gov.br](https://dadosabertos.compras.gov.br/swagger-ui/index.html),
a face pública do sistema SIASG.

Cada registro é um item de contrato público sob a Lei 14.133/2021, já
classificado pela API como **Material** ou **Serviço** e com seu valor. É isso
que permite responder à pergunta pela qual o projeto existe: **no que o
governo tem comprado, e quanto pagou?**

## O que o programa faz

1. Lê toda a configuração de um arquivo `.env` e a valida antes de enviar uma
   única requisição.
2. Divide a janela de tempo pedida em blocos de datas contíguos, ancorados
   numa grade absoluta de calendário.
3. Baixa vários blocos ao mesmo tempo, página por página, com nova tentativa
   em caso de limitação de tráfego e erros de servidor.
4. Grava cada página direto em um arquivo CSV, sem nunca manter o conjunto de
   dados em memória.
5. Registra cada bloco já encerrado em um arquivo de checkpoint, para que uma
   execução interrompida retome em vez de recomeçar.
6. Relê o CSV finalizado em fatias limitadas e imprime três rankings: Material
   contra Serviço, principais categorias por valor e principais itens por
   valor.

Uma janela de um ano sem filtros são aproximadamente **5 milhões de itens em
cerca de 10.000 requisições**, e é por isso que gravar em fluxo e marcar
progresso não são extras opcionais aqui.

## Do CSV ao painel

O projeto tem duas etapas independentes. O coletor acima produz o CSV bruto; o
pipeline de tratamento o transforma num painel semanal pronto para um modelo
consumir.

```bash
python src/prepare.py
```

Os estágios rodam em ordem, e cada um deixa seu artefato em disco:

| Estágio | O que faz | O que grava |
|---|---|---|
| `load` | Lê o CSV com tipos, deduplica e filtra por situação | — (em memória) |
| `clean` | Aplica o teto de valor por item, com quarentena | `data/interim/itens_limpos.parquet`, `data/interim/quarentena.parquet` |
| `aggregate` | Muda o grão para semana × material/serviço × classe | `data/processed/painel.parquet` |
| `features` | Calendário, tendência, defasagens e médias móveis | `data/processed/painel_features.parquet` |
| `plots` | As quatro figuras | `reports/figures/*.png` |

Use `--ate` para parar em um estágio, o que é útil para inspecionar um passo
antes de seguir:

```bash
python src/prepare.py --ate clean
```

Medido sobre o arquivo real de 859 MB, com 3.299.572 linhas: 582.385
duplicatas removidas, 1.276.695 linhas fora de `Homologado`, **6 itens em
quarentena somando R$ 394 bilhões**, e um painel de 2.809 linhas (53 semanas ×
53 combinações). A execução inteira leva cerca de 20 segundos e chega a 3,1 GB
de memória.

Aqueles 6 itens são erros de digitação na origem que carregam mais da metade
do valor do conjunto. O maior é 1.713.940 unidades de serviço postal a
R$ 132.000 cada. É por isso que a primeira figura mostra a série bruta e a
limpa lado a lado: a diferença entre elas é a decisão mais consequente do
pipeline.

## Documentação

A documentação é mantida em dois idiomas com estrutura idêntica.

| Assunto | Português | English |
|---|---|---|
| Como executar o projeto | [EXECUCAO.md](docs/portuguese/EXECUCAO.md) | [EXECUTION.md](docs/english/EXECUTION.md) |
| Arquitetura e passeio arquivo a arquivo | [ARQUITETURA.md](docs/portuguese/ARQUITETURA.md) | [ARCHITECTURE.md](docs/english/ARCHITECTURE.md) |
| Convenções e práticas de trabalho | [PRATICAS.md](docs/portuguese/PRATICAS.md) | [PRACTICES.md](docs/english/PRACTICES.md) |
| Registros de decisão arquitetural | [decisions/](docs/portuguese/decisions/) | [decisions/](docs/english/decisions/) |

## Início rápido

```bash
# 1. Crie e ative o ambiente virtual
python3 -m venv venv
source venv/bin/activate

# 2. Instale as dependências de execução
pip install requests pandas python-dotenv

# 3. Crie sua configuração a partir do template
cp src/.env.example src/.env

# 4. Rode o coletor
python src/main.py

# 5. Prepare o painel a partir do CSV coletado
python src/prepare.py
```

Antes da coleta completa, vale um ensaio curto com uma janela de duas semanas:

```bash
WINDOW_DAYS=14 OUTPUT_CSV=data/teste.csv CHECKPOINT_FILE=data/teste.json \
  RESUME=false python src/main.py
```

As instruções completas de instalação, todas as chaves de configuração e o
procedimento de recuperação de uma execução interrompida estão em
[EXECUCAO.md](docs/portuguese/EXECUCAO.md).

## Desempenho

Três decisões definem quanto tempo uma coleta leva:

| Ajuste | Efeito |
|---|---|
| `MAX_WORKERS` | Blocos baixados em paralelo. O teto útil medido nesta API fica entre 2 e 4; acima disso ela devolve HTTP 429 e a execução fica mais lenta |
| Filtros do `.env` | `MATERIAL_OR_SERVICE=S` reduz de ~5 milhões para ~1,3 milhão de itens por ano |
| `RESUME=true` | Com a grade ancorada no calendário, as chaves dos blocos são estáveis entre execuções, e uma coleta diária só busca o que ainda não fechou |

O bloco que termina no futuro nunca entra no checkpoint: ele ainda está
recebendo itens, então é rebaixado a cada execução. É isso que mantém a coleta
atualizada sem repetir o ano inteiro.

## Estrutura do projeto

```
siasg-data-analysis/
├── README.md
├── requirements.txt
├── src/
│   ├── main.py                 # coletor: baixa a API e grava o CSV bruto
│   ├── prepare.py              # pipeline: do CSV bruto ao painel semanal
│   ├── read_type_methods.py    # leitores tipados para valores do .env
│   ├── .env.example            # template documentado do .env
│   ├── classes/
│   │   ├── settings.py         # configuração do coletor
│   │   ├── pipeline_settings.py # configuração do pipeline
│   │   ├── csv_writer.py       # gravação de CSV em fluxo
│   │   └── checkpoint.py       # controle de retomada após interrupção
│   └── pipeline/
│       ├── load.py             # leitura tipada e deduplicação
│       ├── clean.py            # teto de valor, com quarentena
│       ├── aggregate.py        # muda o grão para o painel semanal
│       ├── features.py         # calendário, tendência e defasagens
│       ├── split.py            # corte temporal que não parte a semana
│       ├── transform.py        # ColumnTransformer não ajustado
│       └── plots.py            # as quatro figuras
├── tests/
├── data/
│   ├── raw/                    # a testemunha: nunca editada
│   ├── interim/                # itens limpos e quarentena
│   └── processed/              # painel e painel com features
├── reports/figures/            # os PNG
└── docs/
    ├── english/
    └── portuguese/
```

## Requisitos

- Python 3.9 ou posterior
- Coletor: `requests`, `pandas` e `python-dotenv`
- Pipeline: `matplotlib`, `scikit-learn` e `pyarrow`, além dos acima
- Testes: `pytest`
- Sem chave de API: o endpoint é público

Tudo de uma vez, com as versões fixadas:

```bash
pip install -r requirements.txt
```

## Licença e fonte dos dados

Os dados pertencem ao governo federal brasileiro e são publicados como dados
abertos sob o compromisso da Open Government Partnership. A documentação da
API está em
[dadosabertos.compras.gov.br](https://dadosabertos.compras.gov.br/swagger-ui/index.html).

---

<a name="english"></a>

# siasg-data-analysis

[Português](#siasg-data-analysis) | **English**

Collects and analyses Brazilian federal procurement data from the
[Compras.gov.br open data API](https://dadosabertos.compras.gov.br/swagger-ui/index.html),
the public face of the SIASG system.

Each record is one item of a public contract under Law 14.133/2021, already
classified by the API as **Material** or **Service** and carrying its value.
That is what makes it possible to answer the question the project exists for:
**what has the government been buying, and how much did it pay?**

<a name="what-the-program-does"></a>

## What the program does

1. Reads every setting from a `.env` file and validates it before sending a
   single request.
2. Splits the requested time window into contiguous date chunks, anchored to
   an absolute calendar grid.
3. Downloads several chunks at a time, page by page, retrying on throttling
   and server errors.
4. Streams every page straight to a CSV file, never holding the dataset in
   memory.
5. Records each closed chunk in a checkpoint file, so an interrupted run
   resumes instead of starting over.
6. Reads the finished CSV back in bounded slices and prints three rankings:
   Material versus Service, top categories by value, and top items by value.

An unfiltered one-year window is roughly **5 million items across about 10,000
requests**, which is why streaming and checkpointing are not optional extras
here.

<a name="from-csv-to-panel"></a>

## From CSV to panel

The project has two independent stages. The collector above produces the raw
CSV; the preparation pipeline turns it into a weekly panel a model can consume.

```bash
python src/prepare.py
```

The stages run in order, and each one leaves its artefact on disk:

| Stage | What it does | What it writes |
|---|---|---|
| `load` | Reads the CSV with types, deduplicates, and filters by status | — (in memory) |
| `clean` | Applies the per-item value ceiling, with quarantine | `data/interim/itens_limpos.parquet`, `data/interim/quarentena.parquet` |
| `aggregate` | Changes the grain to week × material/service × class | `data/processed/painel.parquet` |
| `features` | Calendar, trend, lags, and rolling means | `data/processed/painel_features.parquet` |
| `plots` | The four figures | `reports/figures/*.png` |

Use `--ate` to stop at a stage, which helps when you want to inspect one step
before going further:

```bash
python src/prepare.py --ate clean
```

Measured on the real 859 MB file, with 3,299,572 rows: 582,385 duplicates
removed, 1,276,695 rows outside `Homologado`, **6 items quarantined totalling
R$ 394 billion**, and a panel of 2,809 rows (53 weeks × 53 combinations). The
whole run takes about 20 seconds and peaks at 3.1 GB of memory.

Those 6 items are data-entry errors at the source that carry more than half of
the dataset's value. The largest is 1,713,940 units of postal service at
R$ 132,000 each. That is why the first figure shows the raw and the cleaned
series side by side: the gap between them is the most consequential decision
in the pipeline.

<a name="documentation"></a>

## Documentation

Documentation is maintained in two languages with identical structure.

| Topic | Português | English |
|---|---|---|
| How to run the project | [EXECUCAO.md](docs/portuguese/EXECUCAO.md) | [EXECUTION.md](docs/english/EXECUTION.md) |
| Architecture and file-by-file tour | [ARQUITETURA.md](docs/portuguese/ARQUITETURA.md) | [ARCHITECTURE.md](docs/english/ARCHITECTURE.md) |
| Conventions and working practices | [PRATICAS.md](docs/portuguese/PRATICAS.md) | [PRACTICES.md](docs/english/PRACTICES.md) |
| Architecture decision records | [decisions/](docs/portuguese/decisions/) | [decisions/](docs/english/decisions/) |

<a name="quick-start"></a>

## Quick start

```bash
# 1. Create and activate the virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install the runtime dependencies
pip install requests pandas python-dotenv

# 3. Create your configuration from the template
cp src/.env.example src/.env

# 4. Run the collector
python src/main.py

# 5. Prepare the panel from the collected CSV
python src/prepare.py
```

Before the full collection, a short two-week rehearsal is worth the minute it
takes:

```bash
WINDOW_DAYS=14 OUTPUT_CSV=data/teste.csv CHECKPOINT_FILE=data/teste.json \
  RESUME=false python src/main.py
```

Full setup instructions, every configuration key, and the recovery procedure
for an interrupted run are in [EXECUTION.md](docs/english/EXECUTION.md).

<a name="performance"></a>

## Performance

Three decisions determine how long a collection takes:

| Setting | Effect |
|---|---|
| `MAX_WORKERS` | Chunks downloaded in parallel. The measured useful ceiling for this API is 2 to 4; beyond that it returns HTTP 429 and the run gets slower |
| `.env` filters | `MATERIAL_OR_SERVICE=S` cuts the year from ~5 million to ~1.3 million items |
| `RESUME=true` | With the calendar-anchored grid, chunk keys stay stable across runs, so a daily collection fetches only what has not closed yet |

The chunk that ends in the future never enters the checkpoint: it is still
receiving items, so it is downloaded again on every run. That is what keeps
the collection current without repeating the whole year.

<a name="project-layout"></a>

## Project layout

```
siasg-data-analysis/
├── README.md
├── requirements.txt
├── src/
│   ├── main.py                 # collector: downloads the API into a raw CSV
│   ├── prepare.py              # pipeline: raw CSV to weekly panel
│   ├── read_type_methods.py    # typed readers for .env values
│   ├── .env.example            # documented template for .env
│   ├── classes/
│   │   ├── settings.py         # collector configuration
│   │   ├── pipeline_settings.py # pipeline configuration
│   │   ├── csv_writer.py       # streaming CSV sink
│   │   └── checkpoint.py       # crash-resume bookkeeping
│   └── pipeline/
│       ├── load.py             # typed reading and deduplication
│       ├── clean.py            # value ceiling, with quarantine
│       ├── aggregate.py        # changes the grain to the weekly panel
│       ├── features.py         # calendar, trend, and lags
│       ├── split.py            # temporal split that never cuts a week
│       ├── transform.py        # unfitted ColumnTransformer
│       └── plots.py            # the four figures
├── tests/
├── data/
│   ├── raw/                    # the witness: never edited
│   ├── interim/                # cleaned items and quarantine
│   └── processed/              # panel and panel with features
├── reports/figures/            # the PNGs
└── docs/
    ├── english/
    └── portuguese/
```

<a name="requirements"></a>

## Requirements

- Python 3.9 or later
- Collector: `requests`, `pandas`, and `python-dotenv`
- Pipeline: `matplotlib`, `scikit-learn`, and `pyarrow`, on top of the above
- Tests: `pytest`
- No API key: the endpoint is public

Everything at once, with pinned versions:

```bash
pip install -r requirements.txt
```

<a name="license-and-data-source"></a>

## License and data source

The data belongs to the Brazilian federal government and is published as open
data under the Open Government Partnership commitment. The API documentation
is at
[dadosabertos.compras.gov.br](https://dadosabertos.compras.gov.br/swagger-ui/index.html).
