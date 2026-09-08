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
├── src/
│   ├── main.py                 # orquestração: coleta, nova tentativa, resumo
│   ├── read_type_methods.py    # leitores tipados para valores do .env
│   ├── .env.example            # template documentado do .env
│   └── classes/
│       ├── settings.py         # configuração validada de uma execução
│       ├── csv_writer.py       # gravação de CSV em fluxo
│       └── checkpoint.py       # controle de retomada após interrupção
└── docs/
    ├── english/
    └── portuguese/
```

## Requisitos

- Python 3.9 ou posterior
- `requests`, `pandas` e `python-dotenv`
- Sem chave de API: o endpoint é público

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
├── src/
│   ├── main.py                 # orchestration: collect, retry, summarize
│   ├── read_type_methods.py    # typed readers for .env values
│   ├── .env.example            # documented template for .env
│   └── classes/
│       ├── settings.py         # validated configuration for one run
│       ├── csv_writer.py       # streaming CSV sink
│       └── checkpoint.py       # crash-resume bookkeeping
└── docs/
    ├── english/
    └── portuguese/
```

<a name="requirements"></a>

## Requirements

- Python 3.9 or later
- `requests`, `pandas`, and `python-dotenv`
- No API key: the endpoint is public

<a name="license-and-data-source"></a>

## License and data source

The data belongs to the Brazilian federal government and is published as open
data under the Open Government Partnership commitment. The API documentation
is at
[dadosabertos.compras.gov.br](https://dadosabertos.compras.gov.br/swagger-ui/index.html).
