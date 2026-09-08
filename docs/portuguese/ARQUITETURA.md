# Arquitetura

Este documento descreve como o projeto está organizado, o que cada arquivo
faz, quais decisões estruturais foram tomadas e onde estão os pontos fracos.

## O problema que a arquitetura resolve

Três restrições moldam todo o desenho do sistema:

1. **Volume.** Uma janela de um ano são aproximadamente 5 milhões de itens,
   distribuídos em cerca de 10.000 requisições. O conjunto não cabe em
   memória.
2. **Duração.** Uma coleta completa leva horas. Interrupções são certeza, não
   possibilidade.
3. **Instabilidade da origem.** A API pública limita tráfego e derruba
   conexões sob carga.

As três decisões centrais respondem diretamente a essas restrições:
processamento em fluxo contínuo, checkpoint por bloco e política de novas
tentativas com espera crescente.

## Estrutura em camadas

O programa é organizado da camada mais externa para a mais interna. Cada
camada conhece apenas a imediatamente inferior.

```
main()          lê a configuração, imprime o plano, define o código de saída
  └─ collect()      percorre os blocos, controla checkpoint e escritor
       └─ fetch_chunk()   pagina um intervalo de datas
            └─ fetch_page()   uma única requisição HTTP, com tentativas
  └─ summarize()    relê o CSV pronto e imprime os rankings
```

Essa hierarquia é o que permite que um erro nascido no fundo de `fetch_page()`
seja relatado de forma limpa em `main()`, sem `sys.exit()` espalhado pelo
código.

## Fluxo de dados

```
.env
  │
  ▼
Settings.from_env()  ──► valida tudo antes da primeira requisição
  │
  ▼
iter_date_chunks()   ──► divide a janela em blocos contíguos,
  │                       ancorados numa grade absoluta de calendário
  ▼
ThreadPoolExecutor   ──► MAX_WORKERS blocos por vez
  │
  ▼
┌───────── por bloco, numa thread de trabalho ──────┐
│  fetch_chunk() ──► fetch_page() ──► API           │
│        │                                          │
│        ▼                                          │
│  lock_csv ──► CsvWriter.write() ──► disco (flush) │
│        │                                          │
│        ▼                                          │
│  se o bloco já fechou:                            │
│    lock_checkpoint ──► Checkpoint.mark() ──► json │
└───────────────────────────────────────────────────┘
  │
  ▼
summarize()  ──► lê o CSV em fatias ──► rankings no terminal
```

O ponto essencial: nenhuma seta volta para a memória. Cada página vai para o
disco assim que chega, e o checkpoint só é marcado depois disso.

Dois detalhes mantêm a versão concorrente segura. As threads compartilham
exatamente dois recursos mutáveis — o arquivo CSV e o checkpoint — e cada um
tem sua própria trava, mantida por microssegundos contra cerca de 300 ms de
espera de rede por requisição. E só um bloco cuja data final já passou é
registrado: um bloco que ainda termina no futuro continua recebendo itens, e
marcá-lo agora faria a próxima execução pular o que ainda não tinha
chegado.

## O que cada arquivo faz

### `src/main.py`

Orquestração e ponto de entrada. Contém seis funções:

| Função | Responsabilidade |
|---|---|
| `iter_date_chunks()` | Divide a janela em blocos consecutivos meio-abertos |
| `fetch_page()` | Executa um `GET`, com tentativas em caso de limitação ou erro do servidor |
| `fetch_chunk()` | Gera uma página de registros por vez, paginando um intervalo |
| `collect()` | Percorre os blocos e mantém checkpoint e CSV consistentes |
| `summarize()` | Relê o CSV em fatias limitadas e imprime três rankings |
| `main()` | Lê a configuração, imprime o plano e devolve o código de saída |

Detalhes que merecem atenção:

- **Blocos meio-abertos.** `iter_date_chunks()` produz intervalos que
  compartilham as fronteiras: o fim de um bloco é o início do próximo. Isso
  garante blocos adjacentes sem lacuna e sem contagem dupla, porque a API trata
  o intervalo da mesma forma.
- **Classificação de erros HTTP.** Respostas 4xx, exceto 408 e 429, falham
  imediatamente. Uma requisição malformada falharia de forma idêntica para
  sempre, então gastar o orçamento de tentativas nela seria desperdício. Já
  408, 429 e toda a faixa 5xx são temporários por definição e entram na fila
  de novas tentativas.
- **Espera linear crescente.** `retry_backoff * attempt` produz 15s, 30s, 45s.
  Cada espera é maior que a anterior, dando à API progressivamente mais espaço
  para se recuperar.
- **`yield` em vez de `return`** em `fetch_chunk()`. O chamador grava a página
  em disco e volta para buscar a próxima, de forma que apenas uma página existe
  em memória por vez.
- **Resumo em fatias.** `summarize()` usa `chunksize` no `read_csv`, o que
  transforma a leitura em um iterador de quadros. O pico de memória fica
  proporcional a uma fatia, não ao arquivo inteiro. Os totais são acumulados
  com `.add(..., fill_value=0)`, porque um grupo presente em uma fatia e
  ausente em outra viraria `NaN` sem isso.
- **Degradação em vez de falha.** O resumo agrupa apenas pelas dimensões que o
  CSV realmente contém, de modo que uma lista `COLUMNS` reduzida enfraquece o
  relatório em vez de quebrá-lo.

### `src/read_type_methods.py`

Leitores tipados para os valores do `.env`. Define `ConfigError` e sete
funções auxiliares internas.

| Função | Converte para |
|---|---|
| `_read_text()` | `str`, base sobre a qual todas as outras são construídas |
| `_read_int()` | `int`, para tamanhos de página, tentativas e contagens de dias |
| `_read_float()` | `float`, para pausas com fração de segundo |
| `_read_bool()` | `bool`, aceitando grafias em inglês e português |
| `_read_date()` | `date`, no formato ISO `AAAA-MM-DD` |
| `_read_optional()` | `str | None`, para filtros que podem simplesmente não ser enviados |
| `_read_list()` | `list[str]`, a partir de uma lista separada por vírgulas |

Cada função faz as mesmas três coisas: lê a string bruta, decide se ela está
ausente e, caso contrário, converte. Um valor presente porém inválido levanta
`ConfigError` imediatamente, em vez de falhar horas depois dentro de um laço
de requisições.

Duas escolhas valem destaque:

- **Ausente, vazio e só espaços são a mesma coisa.** É por isso que `CHAVE=`
  no `.env` se comporta exatamente como omitir a linha.
- **`_read_bool()` rejeita valores desconhecidos** em vez de tratá-los como
  falso silenciosamente. Isso impede que `RESUME=talvez` apague uma coleta
  existente sem aviso.

### `src/classes/settings.py`

O objeto imutável que carrega todos os parâmetros de uma execução.

A regra de desenho é que o `.env` é lido exatamente uma vez, na inicialização,
por `Settings.from_env()`. Todo o restante do programa recebe uma instância já
validada e nunca mais toca em `os.getenv`.

Duas propriedades derivadas evitam estados contraditórios:

- `start_date` é calculada como `end_date - window_days`, e não configurada.
  As duas nunca podem discordar, e uma janela de 365 dias continua com 365 dias
  independentemente de anos bissextos.
- `items_url` junta host e caminho tolerando barras sobrando ou faltando dos
  dois lados.

`from_env()` valida o que a própria API rejeitaria: `PAGE_SIZE` fora do
intervalo aceito, `WINDOW_DAYS` menor que 1, `CHUNK_DAYS` menor que 1 (que
faria `iter_date_chunks` girar para sempre) e `MATERIAL_OR_SERVICE` fora de
`M` e `S`.

As chaves dos filtros permanecem em português porque são enviadas literalmente
como parâmetros de consulta da API. Os nomes no `.env` ao redor delas estão em
inglês, para quem lê o código.

### `src/classes/csv_writer.py`

O destino em fluxo contínuo dos registros baixados. Garante duas regras das
quais o resto do programa depende:

1. O cabeçalho aparece exatamente uma vez, não importa quantos lotes sejam
   gravados.
2. Cada lote é descarregado em disco imediatamente, para que uma execução
   interrompida deixe um CSV coerente com o checkpoint.

Escolhas técnicas relevantes:

- `newline=""` é exigido pelo módulo `csv` para evitar linhas em branco no
  Windows.
- `utf-8-sig` grava o BOM que o Excel precisa para exibir acentuação
  corretamente.
- `extrasaction="ignore"` descarta campos da API fora das colunas escolhidas,
  em vez de levantar exceção. Assim `COLUMNS` pode ser um subconjunto, e campos
  novos adicionados pela API não quebram a execução.
- O escritor é construído preguiçosamente, no primeiro lote não vazio, porque
  os nomes das colunas podem precisar vir dos próprios dados.

### `src/classes/checkpoint.py`

A contabilidade que permite retomar após uma queda. Guarda um único fato: o
conjunto de blocos de datas cujas linhas já estão seguras no CSV.

A unidade de progresso é sempre o bloco inteiro, nunca a página. Um bloco é
registrado apenas depois que sua última página foi gravada, então uma queda no
meio de um bloco custa o redownload daquele bloco — algumas requisições
duplicadas, em vez do risco de uma lacuna nos dados.

`mark()` reescreve o arquivo inteiro a cada bloco concluído. Isso é
deliberado: o arquivo tem poucos kilobytes, e gravá-lo por completo significa
que o estado em disco é sempre um retrato válido e completo, nunca uma escrita
parcial.

`reset()` faz par com a remoção do CSV em `collect()`. Os dois precisam sempre
descrever a mesma coleta, ou a retomada acrescentaria linhas sobre um arquivo
que não corresponde mais.

## Pontos fortes

**Consumo de memória constante.** Nada acumula. Uma página existe em memória
durante a coleta, uma fatia durante o resumo. O programa processa 5 milhões de
registros com o mesmo consumo com que processaria 5 mil.

**Retomada confiável e barata.** O custo máximo de uma interrupção é um bloco.
Com o padrão de 7 dias, isso são minutos de trabalho perdido em uma execução
de horas.

**A configuração falha cedo.** Um erro de digitação no `.env` interrompe a
execução no primeiro segundo, não depois de duas horas de download.

**Erros classificados corretamente.** A distinção entre falha permanente (4xx)
e temporária (408, 429, 5xx) evita tanto tentativas inúteis quanto desistências
prematuras.

**Camadas com responsabilidade única.** Cada arquivo em `classes/` tem uma
razão para existir e uma razão para mudar. `CsvWriter` não sabe o que é um
bloco de datas; `Checkpoint` não sabe o que é HTTP.

**Documentação no código.** Os comentários explicam o porquê das decisões, não
o que a linha faz. Um leitor descobre por que `min()` está ali sem precisar
reconstruir o raciocínio.

**Degradação graciosa no resumo.** Reduzir `COLUMNS` enfraquece o relatório em
vez de quebrá-lo.

## Pontos fracos

**Não existe um pacote Python de verdade.** Faltam arquivos `__init__.py` em
`src/` e em `src/classes/`. Os imports funcionam por acidente do diretório de
trabalho, e é exatamente essa fragilidade que produziu os imports relativos
quebrados em `settings.py`.

**Não existe `requirements.txt`.** As dependências estão descritas em prosa no
`README.md`, sem versões fixadas. Duas máquinas podem resolver versões
diferentes de `pandas` e produzir resultados distintos.

**Caminhos dependem do diretório de trabalho.** `OUTPUT_CSV` e
`CHECKPOINT_FILE` são relativos ao diretório de onde o comando foi disparado,
não ao script. Rodar de `src/` grava em `src/data/`; rodar da raiz grava em
`data/`. Uma retomada executada do lugar errado não encontra o progresso
anterior.

**Não existem testes.** Nenhuma suíte cobre a aritmética de blocos, a
classificação de erros HTTP ou a lógica de retomada — justamente as três
partes onde um erro é silencioso e caro.

**Mensagens em duas línguas.** Os erros voltados ao usuário estão em
português, os comentários e docstrings em inglês. É uma escolha defensável,
mas não está registrada em lugar nenhum, e a fronteira já escorregou em alguns
pontos.

**`data/` não está no `.gitignore`.** Um CSV de vários gigabytes pode ser
adicionado ao repositório por acidente. A pasta `venv/` tem o mesmo problema.

**O checkpoint não valida a configuração.** Retomar após alterar `CHUNK_DAYS`
ou os filtros no `.env` produz um CSV que mistura duas coletas diferentes.
Alterar `CHUNK_DAYS` desloca todas as fronteiras da grade, então as chaves dos
blocos deixam de corresponder ao que já foi baixado. O `CsvWriter` detecta o
caso mais restrito de um `COLUMNS` alterado e avisa, mas o checkpoint em si
não registra nada sobre a configuração que o gerou.

**A concorrência é limitada pela API, não pelo código.** `MAX_WORKERS` acima
de 4 faz a API devolver HTTP 429 em massa, ponto em que o backoff deixa a
execução mais lenta que a sequencial. O coletor não detecta isso e se ajusta;
você é quem precisa reduzir o valor.

## Evolução sugerida

Em ordem de retorno sobre esforço:

1. Registrar no checkpoint a configuração que o gerou, e recusar retomadas
   incompatíveis.
2. Escrever testes para `iter_date_chunks()`, para a classificação de status
   HTTP em `fetch_page()` e para o ciclo de vida do `Checkpoint`.
3. Adicionar `__init__.py` a `src/` e `src/classes/`, transformando o projeto
   em um pacote de verdade.
4. Criar `requirements.txt` com versões fixadas.
5. Acrescentar `data/` e `venv/` ao `.gitignore`.
6. Resolver caminhos relativos à raiz do projeto, e não ao diretório de
   trabalho.
7. Recuar automaticamente quando o HTTP 429 ficar frequente, em vez de deixar
   `MAX_WORKERS` para ser ajustado à mão.

## Decisões registradas

Decisões arquiteturais formais ficam em [decisions/](decisions/), no formato
MADR. Use [adr-template.md](decisions/adr-template.md) como base para novos
registros.
