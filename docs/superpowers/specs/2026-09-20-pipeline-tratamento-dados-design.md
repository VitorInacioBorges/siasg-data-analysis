# Design: pipeline de tratamento de dados

**Data:** 20 de setembro de 2026
**Estado:** aprovado, aguardando plano de implementação
**Objetivo do consumidor:** alimentar um modelo scikit-learn que estime o custo
total de compras públicas federais do próximo ano e a divisão entre materiais e
serviços.

## 1. Problema

O coletor (`src/main.py`) grava itens de contratação em `data/raw/`. Esses dados
não servem a um modelo como estão, por quatro motivos medidos em 639.573 linhas
reais coletadas entre 15/09/2025 e 05/11/2025:

1. **23,4% das linhas estão duplicadas.** Um bloco interrompido deixa suas
   linhas no CSV sem ser marcado no checkpoint, e é rebaixado inteiro na
   retomada. O bloco ainda aberto é rebaixado por desenho, a cada execução.
2. **Oito linhas concentram 78,7% do valor, e são erros de digitação na
   origem.** A maior — 1.713.940 unidades de serviço postal a R$ 132.000 cada,
   R$ 226 bilhões — vale 65,3% de toda a base sozinha.
3. **Três colunas são inúteis.** `itemCategoriaNome` tem um único valor distinto
   ("Informática (TIC)") num conjunto que contém carne de caprino e
   paliperidona; `temResultado` é sempre `True`; `codigoGrupo` está 87,5% vazio.
4. **O grão está errado.** Uma linha por item comprado não responde "quanto por
   período".

O efeito prático do item 2: anualizando sem limpeza, a base afirma
R$ 2,6 trilhões em itens de compra federal — impossível. Com teto de
plausibilidade, R$ 548 bilhões — plausível. A limpeza não é refinamento, é o que
separa um número utilizável de um número absurdo.

## 2. Decisões

| # | decisão | alternativas descartadas |
|---|---|---|
| 1 | **Grão:** `semana × materialOuServicoNome × codigoClasse` | Série temporal pura (sem categóricas, metade do pipeline sem função); nível de item (não prevê — exigiria saber quais itens existirão) |
| 2 | **Regra de plausibilidade:** quantidade implausível dentro da classe | Teto no valor total (em R$ 100 mi removeria 73 itens, quase todos legítimos); revisão manual (não escala) |
| 3 | **Alvos:** `valor_total` e `n_itens` | Só valor (não responde a divisão M/S por contagem); contagem como feature (exigiria conhecer o futuro dela) |
| 4 | **Janela:** 365 dias | ~900 dias desde abr/2024 (todo o histórico denso, mas 4h20 de coleta); ~990 dias com indicadora de regime (risco de aprender tendência falsa) |
| 5 | **Grão temporal:** semanal | Mensal (12 passos de tempo é pouco demais); diário (~30% das células em zero) |
| 6 | **Estrutura:** `src/pipeline/` + `src/prepare.py` | Pasta `etl/` na raiz (exigiria resolver `sys.path`); módulos planos em `src/` (10 arquivos no mesmo nível) |
| 7 | **Orquestração:** híbrida — arquivos até o painel, `Pipeline` sklearn depois | Tudo em arquivo (vazamento difícil de evitar); tudo em `Pipeline` (reprocessa 640k linhas por dobra) |
| 8 | **Camada aritmética de limpeza:** descartada | Pegava 119 linhas somando R$ 10 milhões — 0,0% do valor; não paga o custo de manutenção |

A deduplicação por `idCompraItem` não é decisão de plausibilidade: é conserto de
um defeito do coletor, e se aplica sempre.

## 3. Arquitetura

A fronteira do pipeline cai no painel, e separa dois regimes com naturezas
diferentes.

```
┌─ REGIME DE ARQUIVO ──── roda uma vez, ~640k linhas, determinístico ─┐
│  data/raw/contract_items.csv          (o coletor produz, intocado)  │
│    load.py       leitura em fatias, tipos, dedup, filtro de status  │
│    clean.py      plausibilidade  ──►  interim/quarentena.parquet    │
│    aggregate.py  agrega para semana × M/S × classe                  │
│  data/processed/painel.parquet        (~2.800 linhas)               │
│    features.py   defasagens, calendário, razões                     │
│  data/processed/painel_features.parquet                             │
└──────────────────────────────────────────────────────────────────────┘
┌─ REGIME SKLEARN ──── roda a cada dobra da validação cruzada ────────┐
│    split.py      corte temporal sobre semanas distintas             │
│    transform.py  ColumnTransformer ajustado SÓ no treino            │
└──────────────────────────────────────────────────────────────────────┘
```

Acima da linha nada depende de qual dobra está rodando: deduplicar e filtrar por
plausibilidade dão o mesmo resultado sempre. Abaixo da linha tudo depende — a
média de um `StandardScaler` calculada com dados de teste é vazamento. Separar
nesse ponto dá reprocessamento barato e validação honesta ao mesmo tempo.

### Camadas de dados

| camada | conteúdo | regra |
|---|---|---|
| `data/raw/` | saída do coletor | nunca editada; é a testemunha |
| `data/interim/` | itens limpos e quarentena | onde se audita o que saiu e por quê |
| `data/processed/` | painel e painel com features | o que o modelo lê |

A quarentena é `interim/quarentena.parquet` com coluna `motivo`. Revisar o
limiar depois é mudar parâmetro e reprocessar, sem recoletar.

## 4. Configuração

Chaves novas no mesmo `src/.env`, lidas pelos auxiliares `_read_*` existentes,
numa classe `PipelineSettings` irmã de `Settings`.

| chave | padrão | função |
|---|---|---|
| `PANEL_FREQ` | `W` | grão temporal do painel |
| `TOP_CLASSES` | `50` | classes mantidas; o resto vira `"Outras"` |
| `VALUE_CEILING` | `10000000000` | teto do valor de um item de linha, em reais |
| `STATUS_FILTER` | `Homologado` | situação considerada gasto efetivo |
| `READ_CHUNK_ROWS` | `200000` | linhas lidas por fatia do CSV bruto |
| `DATA_DIR` | `data` | raiz das três camadas |
| `RAW_CSV_NAME` | `contract_items.csv` | nome do CSV que o coletor grava |
| `FIGURES_DIR` | `reports/figures` | onde os PNG são gravados |

Manter no `.env` respeita a regra do projeto e é o que torna ampliar a janela uma
mudança de configuração, não de código.

## 5. Módulos

### `src/pipeline/load.py`

```python
def carregar(caminho: Path, cfg: PipelineSettings) -> pd.DataFrame
```

Lê em fatias (`chunksize`) com tipos explícitos: `string` para CNPJ e códigos,
preservando zeros à esquerda; `category` para colunas de baixa cardinalidade.
Faz três coisas: deduplica por `idCompraItem`, descarta as três colunas mortas,
filtra por `STATUS_FILTER`. Devolve o grão de item.

### `src/pipeline/clean.py`

```python
def limpar(df: pd.DataFrame, cfg: PipelineSettings) -> tuple[pd.DataFrame, pd.DataFrame]
```

A limpeza tem **uma regra**, e chegar a ela custou implementar e descartar outra.

**Regra: valor total implausível para um item de linha.**

```
suspeito se valorTotalResultado > VALUE_CEILING     (padrão R$ 10 bi)
```

Medido no ano inteiro — 1.440.492 itens homologados, R$ 732,7 bi — o teto remove
**6 itens** (0,0004%) que carregam 53,77% do valor, e todos os seis são
impossíveis: R$ 226 bilhões de serviço postal, R$ 3,2 bilhões por unidade de
perícia, R$ 10 bilhões por uma unidade de consultoria, 3,4 bilhões de unidades a
R$ 3. Sem o teto o ano lê R$ 735 bi; com ele, R$ 340 bi.

### A regra que foi descartada, e por quê

O desenho aprovado no brainstorming media **quantidade implausível dentro de
cada `codigoClasse`**, por z robusto sobre `log10`, com limiar 8 e fallback para
a estatística global em classes pequenas. Foi implementada, testada com seis
casos e rodada contra os dados reais. Reprovou em duas frentes independentes:

**Não pegava o maior erro.** A linha de 1.713.940 unidades de serviço postal a
R$ 132.000 cada tem `z = 3,41`. As linhas sem `codigoClasse` são 638.294 itens —
44,3% da base — com quantidades de 1 a 29 bilhões, e o MAD desse grupo é uma
ordem de magnitude inteira. Nenhum limiar separa o caso: o que pega essa linha
(3,0) remove 49,57% do valor e 11.122 itens. Limitar o MAD por um teto dá o
mesmo resultado, e um teto de quantidade não alcança 1,7 milhão de unidades sem
levar 47,51% junto.

**O que pegava sozinha era legítimo.** Medido: 177 itens, R$ 0,31 bi, 0,04% do
valor. Entre eles, 28.000.000 doses de vacina (z 8,11), 8.800.000 munições
(z 11,97) e 8.797 livros didáticos (z 8,16). Compras públicas de grande escala,
não erro de digitação. Os z dos falsos positivos (8,11 a 11,97) se sobrepõem aos
dos verdadeiros, então não existe limiar que salve a regra.

A lição, que vale para o resto do projeto: **quantidade dentro de uma classe não
separa compra em massa legítima de erro de digitação.** A absurdidade está no
produto. 1,7 milhão de unidades não chama atenção; 1,7 milhão de unidades a
R$ 132.000 cada, sim.

### Onde o teto fica, e por que não desce

Inspecionadas as 50 linhas acima de R$ 500 mi: de R$ 500 mi a R$ 10 bi a faixa é
majoritariamente **legítima** — merenda escolar a R$ 24 a refeição com 68 a 260
milhões de unidades, vacina contra dengue a R$ 105 a dose, contratos bancários,
concessões e obras civis com `quantidade = 1`. Acima de R$ 10 bi as seis linhas
são todas impossíveis. Descer o teto começa a remover programa público real.

### Limitação assumida

Dois erros conhecidos ficam dentro: 867.796.000 kg de carne de caprino
(R$ 3,3 bi) e 850.000 notebooks (R$ 4,4 bi). Juntos, 1% do total. Alcançá-los
exigiria um teto que também removeria a merenda escolar — um erro pior que o que
corrige.

Devolve as duas metades. Nada é apagado em silêncio.

### `src/pipeline/aggregate.py`

```python
def para_painel(df: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame
```

Reduz `codigoClasse` às `TOP_CLASSES` por valor, com os baldes `"Outras"` e
`"Sem classe"` (os 19% vazios, que incluem as obras civis). Agrupa por
`semana × M/S × classe`:

| coluna | agregação | papel |
|---|---|---|
| `valor_total` | soma de `valorTotalResultado` | alvo |
| `n_itens` | contagem | alvo |
| `qtd_total`, `qtd_mediana` | soma, mediana | feature |
| `preco_unitario_mediano` | mediana de `valorUnitarioEstimado` | nível de preço |
| `taxa_desconto` | `valor_total / valor_estimado_total` | poder de barganha (medido: 0,826) |
| `n_fornecedores`, `n_orgaos` | `nunique` | concentração |

`materialOuServicoNome` **permanece na chave de agrupamento**, e isso não é
redundância. Para as classes nomeadas, material ou serviço é determinado pela
própria classe — mas os baldes `"Outras"` e `"Sem classe"` misturam os dois, e
sem a coluna na chave a divisão material/serviço deixaria de ser recuperável
exatamente nas linhas onde ela é menos óbvia. O tamanho esperado do painel é
~54 combinações (50 classes nomeadas mais quatro dos dois baldes) por 52
semanas, cerca de 2.800 linhas.

**O painel precisa ser um retângulo completo.** Depois do `groupby`,
combinações sem nenhum item não existem; sem `reindex` no produto cartesiano de
semanas por classes, a defasagem da semana 10 pega a semana 7 sem avisar.

### `src/pipeline/features.py`

```python
def criar_features(painel: pd.DataFrame, cfg: PipelineSettings) -> pd.DataFrame
```

Calendário (semana do ano, mês, seno e cosseno), tendência linear, médias
móveis, defasagens. Toda feature olha só para trás.

O comprimento do ciclo sazonal e a defasagem anual derivam de
`cfg.panel_freq`, não de um 52 cravado: com `PANEL_FREQ=M` a defasagem anual é
12, e um valor fixo calcularia um ciclo doze vezes longo demais. O módulo
também exporta `colunas_numericas(cfg) -> list[str]`, que é a **única** fonte
dos nomes das features numéricas — `transform.py` pede a lista em vez de
carregar uma constante paralela, para que os dois não possam divergir.

### `src/pipeline/split.py`

```python
def dividir(painel: pd.DataFrame, n_splits: int) -> Iterator[tuple[np.ndarray, np.ndarray]]
```

`TimeSeriesSplit` puro está errado aqui: o painel tem ~50 linhas por semana, e
um corte por posição de linha parte a semana ao meio, deixando metade das
classes no treino e metade no teste. O corte é feito sobre as **semanas
distintas** e depois expandido para as linhas.

### `src/pipeline/transform.py`

```python
def montar_transformador(cfg: PipelineSettings) -> ColumnTransformer
```

Devolve o transformador **não ajustado**, para ser embutido num `Pipeline` e
ajustado por dobra: `OneHotEncoder(handle_unknown="ignore")` nas categóricas,
`StandardScaler` nas numéricas. É esta função que garante que o scaler nunca vê
o futuro.

### `src/pipeline/plots.py`

```python
def gerar_graficos(bruto, limpo, painel, destino: Path,
                   quarentena: pd.DataFrame | None = None) -> list[Path]
```

Sempre bruto e limpo lado a lado, para o impacto da limpeza nunca ficar
escondido. Série no tempo, distribuição em escala logarítmica, composição
material/serviço, relatório da quarentena. Saída em `reports/figures/`.

### `src/prepare.py`

Ponto de entrada, espelhando `src/main.py`: lê configuração, imprime o plano,
orquestra os estágios, devolve código de saída. Aceita `--ate <estágio>` para
iterar sem refazer tudo.

## 6. Tratamento de erros

| código | significado |
|---|---|
| `0` | sucesso, inclusive "nenhuma linha sobreviveu aos filtros" |
| `1` | erro de configuração no `.env`, ou dado de entrada inválido |
| `130` | interrompido com Ctrl+C |

Falhas previstas e o que fazer:

- **CSV cru sendo escrito durante a leitura.** A última linha pode estar pela
  metade. Ler com `on_bad_lines="skip"` e **avisar quantas linhas foram
  puladas** — silêncio aqui é perda de dado sem rastro.
- **`data/raw/contract_items.csv` ausente.** Mensagem apontando para
  `src/main.py`, não `FileNotFoundError` cru.
- **`pyarrow` ausente.** Cai para CSV com aviso; o pipeline funciona nos dois
  formatos.
- **Painel vazio.** Resultado válido: mensagem clara e saída `0`, como o coletor
  faz quando nenhum item corresponde aos filtros.

### Invariantes verificadas por estágio

| estágio | invariante |
|---|---|
| `load` | nenhum `idCompraItem` repetido na saída |
| `clean` | `len(limpos) + len(quarentena) == len(entrada)` |
| `aggregate` | o painel tem exatamente `n_semanas × n_combinações` linhas |
| `aggregate` | a soma de `valor_total` bate com a soma dos itens limpos |
| `split` | nenhuma semana aparece nos dois lados do corte |

São asserções baratas que falham alto. A do `clean` teria pego as duplicatas na
hora em que surgiram.

## 7. Testes

O projeto não tem testes hoje. O `clean.py` concentra o risco, e é onde começar.

Os fixtures vêm de **linhas reais já conferidas à mão**: as quatro com
quantidade impossível (Correios, tablets, notebooks, carne de caprino) e as
legítimas (obras civis com `qtd=1`, ambulâncias com `qtd=3.000`, ressonância
com `qtd=50`).

| teste | garante |
|---|---|
| `test_dedup_remove_repetidos` | duplicatas somem, o resto fica |
| `test_quarentena_pega_os_quatro` | os quatro erros conhecidos saem |
| `test_legitimos_sobrevivem` | obras, ambulâncias e ressonância ficam |
| `test_mad_zero_nao_dispara` | classe com `qtd=1` sempre não quebra a regra |
| `test_regra_e_unilateral` | quantidade baixa não é marcada |
| `test_painel_e_retangulo` | semanas sem compra viram zero, não sumiço |
| `test_soma_preservada_na_agregacao` | agregar não cria nem destrói dinheiro |
| `test_lags_olham_para_tras` | nenhuma feature usa informação futura |
| `test_split_nao_parte_semana` | nenhuma semana nos dois lados |
| `test_scaler_ajustado_so_no_treino` | a média do scaler é a do treino |

O último é o teste de vazamento, e é o mais importante da lista.

## 8. Limitações conhecidas

**Previsão de um ano à frente não é sustentada pelos dados atuais.** Com 52
semanas de janela, `lag_52` é inteiramente vazio: prever a semana `t+52`
exigiria conhecer `t`, que é a primeira da série. A consequência:

- horizonte de 1 a 8 semanas: defasagens funcionam, modelo bem fundamentado
- horizonte de um ano: só tendência e calendário, sem memória — mais
  extrapolação do que previsão

Isso é consequência aceita da decisão 4. Quando a janela for ampliada para ~900
dias, `lag_52` passa a existir e o horizonte longo fica viável **sem alterar
`features.py`**.

**Sazonalidade anual não é aprendível.** Um ano de dados dá uma única
observação de cada semana do calendário; é impossível separar "dezembro é alto"
de "aquele dezembro foi alto". Exigiria três ciclos ou mais.

**Os dados densos começam em abril de 2024.** A Lei 14.133 passou a ser
obrigatória em 30/12/2023 e a adoção se completou no primeiro semestre de 2024.
Medições em dias úteis: 2023-06 com 3.088 itens/dia, 2024-02 com 2.524,
2024-04 com 9.387, 2024-06 com 11.057, 2025-06 com 12.112. Coletar antes de
abril de 2024 traz período de adoção parcial, que um modelo leria como
tendência de alta inexistente. O histórico denso máximo é de ~29 meses, não de
vários anos.

**A concentração extrema sobrevive à limpeza.** Depois de remover os erros, a
mediana é R$ 2.666 e a média R$ 721.939 — razão de 271x. Prever a soma continua
mais próximo de prever eventos raros do que de ajustar uma curva. É por isso que
`n_itens` é alvo junto com `valor_total`: a contagem é uma série bem-comportada
e serve de rede de segurança.

**Fim de semana é quase zero.** O grão semanal absorve isso; se algum dia o
grão diário for adotado, exigirá features de calendário.

## 9. Dependências novas

| pacote | função | estado |
|---|---|---|
| `pyarrow` | Parquet em `interim` e `processed` | não instalado |
| `pytest` | os testes da seção 7 | não instalado |
| `scikit-learn` | `ColumnTransformer`, `Pipeline`, `TimeSeriesSplit` | instalado (1.9.0) |

Criar `requirements.txt` junto: o `ARQUITETURA.md` já lista a ausência dele como
fraqueza, e o projeto passa a ter dependências não óbvias.

## 10. Defeito do coletor a corrigir em separado

A retomada de um bloco interrompido anexa suas linhas ao CSV uma segunda vez —
a origem das 23,4% de duplicatas. O `ARQUITETURA.md` afirma hoje que um crash no
meio de um bloco custa "requisições duplicadas"; custa **linhas duplicadas**.

A deduplicação no `load.py` resolve o consumo dos dados, e a camada `raw`
permanece um registro fiel do que a API devolveu. Corrigir o coletor e a
documentação é trabalho separado deste pipeline.
