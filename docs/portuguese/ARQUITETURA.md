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

## O pipeline de tratamento de dados

O coletor entrega um CSV bruto. O pipeline o transforma num painel semanal com
features, pronto para um modelo do scikit-learn. O ponto de entrada é
`src/prepare.py`, e cada estágio é uma função em `src/pipeline/`, testável
isoladamente.

### Dois regimes, separados pelo painel

Esta é a decisão que organiza todo o resto.

Até o painel, os estágios rodam **uma vez sobre o conjunto inteiro** e gravam
o resultado em arquivo. Isso é correto porque eles são determinísticos:
deduplicar por `idCompraItem` e aplicar um teto de valor dão a mesma resposta
independentemente de qual dobra da validação cruzada está rodando.

Do painel em diante, nada pode ser pré-calculado. A média de um
`StandardScaler` calculada sobre treino e teste juntos carrega o futuro para
dentro do treino — é vazamento, e produz uma nota lisonjeira com um modelo
inútil. Por isso `transform.py` devolve o transformador **não ajustado**: quem
chama o embute num `Pipeline`, e o scikit-learn o reajusta dentro de cada
dobra.

A fronteira entre os dois regimes é exatamente `data/processed/painel.parquet`.

### Os estágios

| Estágio | Módulo | O que grava |
|---|---|---|
| `load` | `pipeline/load.py` | — (em memória) |
| `clean` | `pipeline/clean.py` | `interim/itens_limpos.parquet`, `interim/quarentena.parquet` |
| `aggregate` | `pipeline/aggregate.py` | `processed/painel.parquet` |
| `features` | `pipeline/features.py` | `processed/painel_features.parquet` |
| `plots` | `pipeline/plots.py` | `reports/figures/*.png` |

`split.py` e `transform.py` não são estágios: não gravam nada e não rodam numa
execução do `prepare.py`. São as peças que a etapa de modelagem vai consumir.

### O que cada arquivo faz

#### `src/prepare.py`

Orquestração e ponto de entrada, no mesmo formato de `main.py`: `main()` lê a
configuração e decide o código de saída, `run_stages()` roda os estágios em
ordem. A opção `--ate` para em um estágio, o que permite inspecionar um passo
antes de seguir.

O que distingue este módulo são as **invariantes que ele afirma entre os
estágios**, e que falham alto em vez de silenciosamente:

- a limpeza divide o quadro, nunca o encolhe: `len(limpos) + len(quarentena)`
  precisa dar `len(bruto)`;
- o painel é um retângulo: `len(painel)` precisa dar `semanas × combinações`;
- a agregação preserva a soma: o total do painel precisa bater com o total dos
  itens limpos.

A primeira teria pego as linhas duplicadas no dia em que apareceram.

#### `src/classes/pipeline_settings.py`

Irmão de `Settings`: mesmo contrato, outra preocupação. `Settings` configura o
coletor que produz `data/raw/`; este configura os estágios que a consomem. São
classes separadas porque são lidas em momentos diferentes, por pontos de
entrada diferentes, e uma execução de uma não precisa que a validação da outra
passe.

Um detalhe vale registro: o `load_dotenv()` deste módulo é ancorado ao arquivo,
não ao quadro de quem chama. Sem isso, sob `python -c` não existe arquivo
chamador, a busca cai no diretório de trabalho, não acha nada, e todo valor
vira silenciosamente o padrão da dataclass. Medido: um `.env` dizendo
`MAX_WORKERS=2` lido de volta como 3. Para um pipeline de dados esse é o pior
tipo de falha, porque a execução termina com sucesso e a configuração errada.

#### `src/pipeline/load.py`

Leitura tipada em fatias, deduplicação por `idCompraItem` e filtro por
situação. Três detalhes não óbvios:

- **`on_bad_lines="warn"`, não `"skip"`.** Os dois descartam uma linha com
  campos a mais; o primeiro faz o pandas dizer isso com as próprias palavras,
  em vez de nos deixar inferir.
- **Detecção de truncamento.** Um CSV interrompido no meio de um campo entre
  aspas faz o pandas levantar exceção, e `on_bad_lines` não pega. O módulo
  troca o traceback por uma mensagem que diz o que fazer.
- **Corrida com o coletor.** Um instantâneo do arquivo é tirado antes e depois
  da leitura. Se o arquivo mudou no meio, a heurística de linha parcial é
  descartada em vez de aplicada, porque nenhuma checagem é exata sobre um
  arquivo que está sendo escrito — e agir com base numa medição obsoleta já
  descartou linha legítima antes.

#### `src/pipeline/clean.py`

O único estágio que remove linhas por julgamento. A regra lê o **valor total
adjudicado**, não a quantidade, porque o absurdo está no produto.

O problema medido: 6 linhas em 1.440.492 carregam 53,77% do valor total, e são
erros de digitação na origem. A maior é 1.713.940 unidades de serviço postal a
R$ 132.000 cada — R$ 226 bilhões, 31% do conjunto em uma linha. Com elas
dentro, o ano lê R$ 735 bi; sem elas, R$ 340 bi.

Um desenho anterior media quantidade implausível dentro de cada classe e foi
descartado depois de medido contra um ano inteiro: ele perdia justamente a
maior linha (z = 3,41 contra um limiar de 8), e as 177 linhas que pegava por
conta própria eram compras públicas legítimas em escala — 28 milhões de doses
de vacina, 8,8 milhões de munições, 8.797 livros didáticos. Quantidade dentro
de uma classe não separa volume de erro de digitação.

Limitação conhecida e aceita: dois erros reais continuam dentro — 867.796.000
kg de carne de cabra e 850.000 notebooks, juntos 1% do total. Alcançá-los
exigiria um teto que também remove o programa de merenda escolar.

Nada é apagado. As linhas removidas voltam como um segundo quadro com a coluna
`motivo`, que o chamador grava em `interim/quarentena.parquet`.

#### `src/pipeline/aggregate.py`

Onde o grão muda: uma linha por item vira uma linha por período. É o estágio
que torna a previsão possível, porque no grão do item não existe "próxima
semana" — existem itens. O painel põe o tempo na linha.

Dois detalhes decidem se o resultado é utilizável:

- **As classes são reduzidas às maiores por valor.** O dado real tem 434
  delas, e as 50 maiores já cobrem 94,1% do dinheiro. Codificar as 434 em
  one-hot acrescentaria mais colunas do que o painel tem passos de tempo. O
  resto vai para o balde `Outras`; a ausência de classe tem balde próprio,
  `Sem classe`, porque as duas coisas significam coisas diferentes.
- **O painel precisa sair um retângulo completo.** Depois de um `groupby`, uma
  semana em que uma classe não comprou simplesmente não existe, e uma
  defasagem alcançaria três semanas atrás em vez de uma. Semana sem compra é
  zero, não lacuna — mas a mediana de um conjunto vazio continua nula, porque
  não houve preço a observar, o que não é o mesmo que preço zero.

#### `src/pipeline/features.py`

Torna explícito o que estava implícito, porque um modelo só enxerga suas
colunas. **Toda feature aqui olha para trás.** Uma coluna que espiasse adiante
seria o vazamento que produz nota alta e modelo inútil.

- O número da semana entra também como seno e cosseno, porque a semana 52 e a
  semana 1 são vizinhas, e um inteiro cru não expressa isso.
- Defasagens e médias móveis são calculadas **por combinação**. O agrupamento
  é o que impede a defasagem de uma classe de alcançar o histórico de outra.
- A média móvel leva `shift(1)` antes do `rolling`: incluir a semana que está
  sendo prevista seria exatamente o vazamento que o módulo evita.
- `numeric_features(cfg)` é uma função, não uma constante. Com `PANEL_FREQ=M`
  a defasagem anual se chama `valor_lag_12`, e uma lista fixa apontaria para
  colunas que não existem.

**Limitação estrutural, não acidental:** com uma janela de coleta de 365 dias
o painel tem 52 passos semanais, então `valor_lag_52` sai inteiramente nulo.
Prever um ano à frente exige uma defasagem de 52 ou mais, porque o modelo não
pode receber um valor que não conhecerá no momento da previsão. Horizontes
curtos, de uma a oito semanas, são bem servidos pelas defasagens curtas.
Ampliar `WINDOW_DAYS` preenche a `lag_52` sem mudar uma linha deste módulo.

#### `src/pipeline/split.py`

O corte temporal, e a razão de não poder ser o `TimeSeriesSplit` do
scikit-learn sozinho. O painel tem cerca de 53 linhas por semana, uma por
combinação. O `TimeSeriesSplit` corta por posição de linha, então cai no meio
de uma semana e põe metade das classes daquela semana no treino e metade no
teste. O modelo passa a ver parte do próprio período em que está sendo
avaliado.

Por isso o corte é tomado sobre as semanas distintas e só depois expandido
para linhas.

#### `src/pipeline/transform.py`

Uma fábrica, não um objeto ajustado — pela razão explicada em "dois regimes"
acima. Imputa a mediana nas numéricas, porque as defasagens nascem nulas nas
primeiras semanas de cada combinação e descartar essas linhas jogaria fora o
começo de toda série. Codifica as categóricas com `handle_unknown="ignore"`,
porque numa divisão temporal uma classe que aparece só no fim do ano é
exatamente o caso de uma categoria ausente do treino.

Pede a lista de colunas ao `features.py` em vez de repeti-la, para que os dois
módulos não possam divergir.

#### `src/pipeline/plots.py`

As quatro figuras, e uma regra que todas obedecem: **bruto e limpo aparecem
lado a lado.** Seis linhas carregam mais da metade do valor, então um gráfico
só da série limpa esconderia a decisão mais consequente do pipeline.

A paleta tem dois espaços categóricos, `#2a78d6` e `#eb6834`, validados contra
as seis checagens do método `dataviz` na superfície clara. Não substitua sem
revalidar.

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

**O vazamento é impedido por construção, não por disciplina.** O transformador
sai não ajustado e o corte é por semana inteira. Não há como um colaborador
distraído ajustar um scaler sobre o conjunto todo sem reescrever o módulo.

**As invariantes falham alto.** `prepare.py` afirma entre os estágios que a
limpeza não perdeu linhas, que o painel é retângulo e que a agregação preservou
a soma. Um erro nessas três coisas seria silencioso e caríssimo.

**Nada é descartado em silêncio.** Toda linha removida pela limpeza volta em
`quarentena.parquet` com o motivo, e a quarta figura mostra quanto valor saiu.

## Pontos fracos

**Não existe um pacote Python de verdade.** Faltam arquivos `__init__.py` em
`src/` e em `src/classes/`. Os imports funcionam por acidente do diretório de
trabalho, e é exatamente essa fragilidade que produziu os imports relativos
quebrados em `settings.py`.

**Caminhos dependem do diretório de trabalho.** `OUTPUT_CSV` e
`CHECKPOINT_FILE` são relativos ao diretório de onde o comando foi disparado,
não ao script. Rodar de `src/` grava em `src/data/`; rodar da raiz grava em
`data/`. Uma retomada executada do lugar errado não encontra o progresso
anterior.

**O coletor não tem testes.** O pipeline tem 49, mas nenhum cobre
`iter_date_chunks()`, a classificação de erros HTTP em `fetch_page()` ou o
ciclo de vida do `Checkpoint` — justamente as três partes do coletor onde um
erro é silencioso e caro.

**`valor_lag_52` sai vazia com a janela atual.** É consequência da janela de
365 dias, não defeito do código, e está documentada em `features.py`. O efeito
prático é que o horizonte de um ano se apoia só em tendência e calendário até
a janela de coleta crescer.

**Mensagens em duas línguas.** Os erros voltados ao usuário estão em
português, os comentários e docstrings em inglês. É uma escolha defensável,
mas não está registrada em lugar nenhum, e a fronteira já escorregou em alguns
pontos.

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
   HTTP em `fetch_page()` e para o ciclo de vida do `Checkpoint`, levando o
   coletor ao mesmo patamar do pipeline.
3. Adicionar `__init__.py` a `src/`, `src/classes/` e `src/pipeline/`,
   transformando o projeto em um pacote de verdade.
4. Resolver caminhos relativos à raiz do projeto, e não ao diretório de
   trabalho.
5. Recuar automaticamente quando o HTTP 429 ficar frequente, em vez de deixar
   `MAX_WORKERS` para ser ajustado à mão.
6. Ampliar `WINDOW_DAYS` para além de um ano, habilitando `valor_lag_52` e com
   ela o horizonte de previsão anual.

## Decisões registradas

Decisões arquiteturais formais ficam em [decisions/](decisions/), no formato
MADR. Use [adr-template.md](decisions/adr-template.md) como base para novos
registros.
