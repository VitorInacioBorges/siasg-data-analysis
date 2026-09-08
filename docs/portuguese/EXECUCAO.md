# Execução

Este guia descreve como preparar o ambiente, configurar e executar o coletor
de dados de contratações públicas.

## Pré-requisitos

- Python 3.9 ou superior
- Acesso à internet (a API é pública e não exige chave)
- Espaço em disco: uma janela de um ano gera um CSV de vários gigabytes

## 1. Preparar o ambiente

No Ubuntu ou WSL:

```bash
# Atualiza o sistema e instala o Python
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv python3-dev -y

# Cria o ambiente virtual na pasta venv/
python3 -m venv venv

# Ativa o ambiente virtual (repita a cada nova sessão de terminal)
source venv/bin/activate
```

Para sair do ambiente virtual, execute `deactivate`.

## 2. Instalar as dependências

O coletor usa apenas três bibliotecas externas:

```bash
pip install requests pandas python-dotenv
```

Se você pretende avançar para a etapa de análise e machine learning, instale
também o conjunto completo:

```bash
pip install numpy matplotlib scikit-learn seaborn tqdm
```

Para verificar se o `pip` e o `python` apontam para o mesmo ambiente:

```bash
which python
which pip
```

Ambos devem apontar para dentro da pasta `venv/`. Se não apontarem, o ambiente
virtual não está ativo.

## 3. Configurar

Toda a configuração vive em um arquivo `.env` dentro de `src/`. Comece a
partir do template documentado:

```bash
cp src/.env.example src/.env
```

O arquivo `.env` é lido uma única vez, na inicialização, por
`Settings.from_env()`. Um valor inválido interrompe a execução no primeiro
segundo, antes de qualquer requisição ser enviada.

### Chaves de configuração

#### API

| Chave | Padrão | Descrição |
|---|---|---|
| `API_BASE_URL` | `https://dadosabertos.compras.gov.br` | Host da API |
| `ITEMS_ENDPOINT` | `/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133` | Caminho do endpoint de itens |

#### Janela de tempo

| Chave | Padrão | Descrição |
|---|---|---|
| `END_DATE` | hoje | Último dia da janela, no formato `AAAA-MM-DD`. Vazio significa hoje |
| `WINDOW_DAYS` | `365` | Tamanho fixo da janela em dias, contados para trás a partir de `END_DATE` |
| `CHUNK_DAYS` | `7` | Largura de cada bloco baixado. Menor significa mais seguro e mais requisições |

A data inicial não é configurável: ela é derivada de
`END_DATE - WINDOW_DAYS`, o que impede que as duas se contradigam.

#### Paginação

| Chave | Padrão | Descrição |
|---|---|---|
| `PAGE_SIZE` | `500` | Registros por requisição. Maior significa menos requisições para os mesmos dados |
| `PAGE_SIZE_MIN` | `10` | Limite inferior aceito, verificado na inicialização |
| `PAGE_SIZE_MAX` | `500` | Limite superior aceito, verificado na inicialização |

`PAGE_SIZE_MIN` e `PAGE_SIZE_MAX` são os limites que a própria API impõe.
Aumentar `PAGE_SIZE_MAX` não faz a API aceitar uma página maior; apenas troca
uma mensagem clara na inicialização por um HTTP 400 no meio da execução.

#### Filtros opcionais

Deixe em branco para trazer tudo. Volume medido em um único dia, para
dimensionar sua execução:

| Filtro aplicado | Itens por dia | Estimativa anual |
|---|---|---|
| nenhum | ~13.800 | ~5,0 milhões |
| `ITEM_STATUS=2` | ~11.000 | ~4,0 milhões |
| `MATERIAL_OR_SERVICE=S` | ~3.600 | ~1,3 milhão |

| Chave | Descrição |
|---|---|
| `MATERIAL_OR_SERVICE` | `M` para material, `S` para serviço |
| `ITEM_STATUS` | `1` em andamento, `2` homologado, `3` anulado ou revogado |
| `HAS_RESULT` | `true` traz apenas itens com fornecedor adjudicado |
| `ORGAN_CNPJ` | CNPJ do órgão contratante, apenas dígitos |
| `UNIT_CODE` | Código UASG da unidade contratante |
| `ITEM_GROUP` | Código de grupo CATMAT/CATSER |
| `ITEM_CLASS` | Código de classe CATMAT/CATSER |
| `CATALOG_ITEM` | Código específico do item de catálogo |
| `SUPPLIER_ID` | CNPJ ou CPF do fornecedor |

#### Colunas

| Chave | Padrão | Descrição |
|---|---|---|
| `COLUMNS` | subconjunto de 19 colunas | Lista separada por vírgulas. Vazio traz os 45 campos da API |

O subconjunto sugerido no template cobre a análise de "no que o governo
gastou" e reduz o arquivo final a aproximadamente um terço do tamanho total.

#### Comportamento HTTP

| Chave | Padrão | Descrição |
|---|---|---|
| `REQUEST_TIMEOUT` | `60` | Segundos até uma requisição desistir |
| `REQUEST_DELAY` | `0` | Pausa em segundos entre requisições bem-sucedidas |
| `MAX_RETRIES` | `5` | Tentativas por página antes de falhar a execução |
| `RETRY_BACKOFF` | `15` | Segundos de espera base, multiplicados pelo número da tentativa |
| `MAX_WORKERS` | `3` | Blocos baixados ao mesmo tempo |

A espera cresce linearmente: 15s, 30s, 45s, e assim por diante.

`MAX_WORKERS` controla quantos blocos de data o coletor baixa em paralelo.
Medido contra esta API, o teto útil fica entre 2 e 4: em 8 a vazão degrada, e
acima disso a API devolve HTTP 429 em massa, ponto em que o backoff deixa a
execução mais lenta que a sequencial. Se aparecerem mensagens de 429
repetidas, reduza para `2`.

O padrão de `REQUEST_DELAY` é `0` porque o espaçamento agora vem de duas
fontes melhores: a própria latência da rede e o backoff que reage a um 429 de
verdade. Aumente apenas se a API passar a recusar uma execução sequencial.

#### Saída

| Chave | Padrão | Descrição |
|---|---|---|
| `OUTPUT_CSV` | `data/contract_items.csv` | Caminho do CSV gerado |
| `CHECKPOINT_FILE` | `data/checkpoint.json` | Caminho do arquivo de progresso |
| `RESUME` | `true` | `true` continua de onde parou; `false` apaga o CSV e recomeça |
| `TOP_ITEMS` | `20` | Quantas linhas cada ranking do resumo imprime |
| `SUMMARY_CHUNK_ROWS` | `200000` | Linhas que o resumo lê por vez |

`SUMMARY_CHUNK_ROWS` mantém o uso de memória do resumo proporcional a uma
fatia, e não ao arquivo inteiro. Reduza em máquinas com pouca RAM.

> **Atenção:** `RESUME=false` apaga o CSV existente antes de começar. O
> checkpoint e o CSV são sempre limpos juntos, porque manter um sem o outro
> produziria linhas duplicadas ou faltantes.

## 4. Executar

```bash
python src/main.py
```

Os caminhos `OUTPUT_CSV` e `CHECKPOINT_FILE` são resolvidos a partir do
diretório de trabalho atual, não do local do script. Execute sempre a partir
da raiz do repositório para que os arquivos caiam sempre em `data/`.

### O que você verá

O programa imprime o plano antes de começar:

```
Período: 2025-09-06 até 2026-09-06 (365 dias, 53 blocos de 7 dias)
Filtros: {'situacaoCompraItem': '2'}
Saída:   data/contract_items.csv
```

Depois, o progresso bloco a bloco:

```
[1/53] 2025-09-06 → 2025-09-13: baixando...
    24.310 itens gravados.
[2/53] 2025-09-13 → 2025-09-20: já baixado, pulando.
```

Ao final, os três rankings do resumo:

```
Gasto total por tipo (Material x Serviço):
  Material     R$   12.345.678.901,23   (2.100.000 itens)
  Serviço      R$    8.765.432.109,87   (1.300.000 itens)

Top 20 categorias por valor:
  R$    1.234.567.890,12  Serviços de engenharia

Top 20 itens por valor:
  R$      987.654.321,00  Contratação de serviço continuado de...
```

## 5. Retomar uma execução interrompida

O coletor grava um checkpoint a cada bloco concluído. Se a execução parar por
qualquer motivo, basta rodar de novo com `RESUME=true` no `.env`:

```bash
python src/main.py
```

Os blocos já baixados são pulados. A unidade de progresso é sempre o bloco
inteiro, nunca a página: um bloco é registrado somente depois que sua última
página foi gravada em disco. Uma queda no meio de um bloco custa apenas o
redownload daquele bloco, em vez de arriscar uma lacuna nos dados.

## Códigos de saída

| Código | Significado |
|---|---|
| `0` | Sucesso, incluindo o caso em que nenhum item corresponde aos filtros |
| `1` | Erro de configuração no `.env`, ou falha da API após esgotar as tentativas |
| `130` | Interrompido com `Ctrl+C`. O CSV foi fechado e continua consistente |

## Resolução de problemas

### Mensagens `status 429` repetidas

A API está recusando o ritmo de requisições. Reduza `MAX_WORKERS` para `2` e,
se as mensagens continuarem, devolva `REQUEST_DELAY` para `0.2`. O progresso
está salvo: rode de novo com `RESUME=true`.

### `Aviso: COLUMNS mudou desde a execução anterior`

Você alterou `COLUMNS` no `.env` entre execuções, e o CSV já gravado tem um
cabeçalho diferente. O coletor mantém o cabeçalho existente, porque gravar
linhas sob uma lista nova produziria em silêncio um arquivo cujas linhas não
correspondem ao próprio cabeçalho. Para aplicar a lista nova, comece uma
execução limpa com `RESUME=false`.

### Um bloco diz "bloco ainda aberto"

Aquele bloco termina no futuro, então ainda está recebendo itens. O coletor o
baixa mas não o registra no checkpoint, e é isso que faz a próxima execução
buscar os itens que chegaram nesse intervalo. Esta mensagem é esperada em toda
execução.

### A API recusou a requisição com status 400

Um filtro ou uma data está malformado. Requisições 4xx falham imediatamente,
sem consumir o orçamento de tentativas, porque falhariam de forma idêntica
para sempre. Revise os filtros no `.env`.

### Falha após 5 tentativas

A API está limitando o tráfego. Reduza `MAX_WORKERS`, aumente
`RETRY_BACKOFF` ou aumente `REQUEST_DELAY`. O progresso está salvo: rode de
novo com `RESUME=true`.

### O CSV não abre corretamente no Excel

O arquivo é gravado em `utf-8-sig`, que inclui o BOM exigido pelo Excel para
exibir acentuação corretamente. Se ainda houver problema, verifique se o
separador configurado no Excel é a vírgula.

### `Aviso: não foi possível ler o checkpoint`

O arquivo de checkpoint está ilegível. Desde que `Checkpoint.mark()` passou a
gravar de forma atômica — arquivo temporário seguido de `os.replace` — matar o
processo durante a gravação não produz mais um arquivo truncado, então este
aviso indica dano vindo de outra fonte. Ele não é fatal: a execução recomeça
do zero em vez de abortar.
