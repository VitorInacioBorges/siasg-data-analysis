# Práticas

Convenções adotadas neste projeto. O objetivo é que qualquer pessoa consiga
prever onde uma mudança deve ser feita e como ela deve se parecer.

## Documentação

### Estrutura bilíngue

Toda pasta `docs/` mantém duas versões completas e equivalentes:

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

As regras são três:

1. **O nome do arquivo é traduzido junto com o conteúdo.** `EXECUCAO.md` em
   português corresponde a `EXECUTION.md` em inglês.
2. **A formatação é idêntica nas duas versões.** Mesmas seções, mesma ordem,
   mesmas tabelas, mesmos blocos de código. Apenas o idioma muda.
3. **As duas versões mudam juntas.** Uma alteração em um idioma sem a
   contrapartida no outro deixa a documentação inconsistente.

### `README.md` é a única exceção

O `README.md` fica na raiz do repositório como um único arquivo com os dois
idiomas, e seu nome nunca é traduzido. Ele carrega o documento completo duas
vezes: primeiro em português, depois uma linha horizontal, depois o mesmo
documento em inglês. As duas metades precisam ter as mesmas seções na mesma
ordem, as mesmas tabelas e os mesmos links.

Como os títulos se repetem nas duas metades, as âncoras geradas colidem. Dê à
metade em inglês âncoras explícitas com `<a name="...">` onde algum link
precisar alcançá-la, e coloque um seletor de idioma no topo de cada metade.

### Nomes de arquivo

Use apenas caracteres ASCII. `EXECUCAO.md`, nunca `EXECUÇÃO.md`: acentos em
nomes de arquivo causam problemas em sistemas de arquivos, URLs e ferramentas
de linha de comando distintos.

### Estilo

O guia completo acompanha a skill `docs-writer`, como
`references/style-guide.md` dentro da pasta da skill. Ele fica fora deste
repositório porque a skill é instalada para o usuário, não para o projeto.
Os pontos mais aplicados aqui:

- Voz ativa. "O sistema envia uma notificação", não "uma notificação é
  enviada".
- Tempo presente para descrever comportamento.
- Segunda pessoa ao se dirigir a quem lê.
- Títulos em caixa de sentença, com hierarquia respeitada.
- Quebra de linha em 80 caracteres, exceto links longos e tabelas.
- `fonte de código` para nomes de arquivo, comandos e elementos de API.
- Texto de link descritivo. Nunca "clique aqui".
- Listas numeradas para passos sequenciais, com marcadores para o resto.

### Referências a código

Sempre aponte para o arquivo e a linha, em caminho relativo:

```markdown
[src/main.py:49](../../src/main.py#L49)
```

Isso mantém o link clicável e permite verificar rapidamente se a documentação
ainda corresponde ao código.

## Registros de decisão

Decisões arquiteturais que moldam o projeto são registradas em
`docs/<idioma>/decisions/`, no formato
[MADR](https://adr.github.io/madr/).

### Quando escrever uma ADR

Escreva quando a decisão for cara de reverter, quando alguém provavelmente vai
perguntar "por que isso é assim?" em seis meses, ou quando houve alternativas
reais em disputa. Não escreva para escolhas óbvias ou triviais.

### Como escrever

1. Copie `adr-template.md` para `adr-NNN-titulo-curto.md`, com `NNN`
   sequencial e preenchido com zeros à esquerda.
2. Preencha o contexto, as opções consideradas e o resultado.
3. Registre as consequências negativas com honestidade. Uma ADR que só lista
   vantagens não está descrevendo uma decisão, está fazendo propaganda.
4. Crie a versão no outro idioma, com o mesmo número.

Uma ADR nunca é editada depois de aceita. Se a decisão mudar, escreva uma nova
que substitua a anterior e marque a antiga como substituída.

## Código

### Organização

- `src/main.py` contém a orquestração e nada mais.
- `src/classes/` contém uma classe por arquivo, cada uma com uma única
  responsabilidade.
- `src/read_type_methods.py` contém os leitores tipados do `.env`.

Uma nova responsabilidade durável ganha um arquivo em `classes/`. Uma função
auxiliar usada só por `main.py` fica em `main.py`.

### Comentários

Comentários explicam **por que**, não **o que**. O código já diz o que faz.

```python
# Bom: explica a razão
# 4xx significa que a requisição em si está errada e falharia de forma
# idêntica para sempre, então falha imediatamente em vez de gastar o
# orçamento de tentativas.

# Ruim: repete o código
# Verifica se o status é menor que 500
```

### Idiomas no código

- Comentários e docstrings em inglês.
- Mensagens destinadas a quem executa o programa em português.
- Chaves de filtro da API em português, porque são o contrato da API.
- Nomes de variáveis e funções em inglês.

### Configuração

Todo parâmetro novo passa pelo mesmo caminho:

1. Adicione a chave em `src/.env.example`, com comentário explicando o padrão.
2. Adicione o campo em `Settings`, com anotação de tipo.
3. Leia a chave em `Settings.from_env()` usando o leitor tipado adequado.
4. Valide na `from_env()` tudo que a API rejeitaria.
5. Documente a chave na tabela correspondente em `EXECUCAO.md` e
   `EXECUTION.md`.

Nenhum módulo além de `Settings.from_env()` chama `os.getenv`.

### Tratamento de erros

- Erro de configuração levanta `ConfigError` e vira mensagem legível, não
  rastreamento de pilha.
- Falha de rede recuperável entra na política de novas tentativas.
- Falha permanente levanta `RuntimeError`, que sobe até `main()`.
- `main()` é o único lugar que decide o código de saída do processo.

Nunca chame `sys.exit()` fora de `main()`. Isso impediria os blocos `finally`
de fechar o CSV, e o arquivo ficaria inconsistente com o checkpoint.

### Durabilidade

Duas invariantes não podem ser quebradas:

1. Um bloco só é marcado no checkpoint depois que todas as suas linhas foram
   gravadas e descarregadas em disco.
2. O checkpoint e o CSV são sempre limpos juntos.

Qualquer mudança que toque `collect()`, `CsvWriter` ou `Checkpoint` precisa
preservar as duas.

## Git

### Mensagens de commit

Use o modo imperativo e mantenha a primeira linha abaixo de 72 caracteres:

```
Corrige imports relativos em settings.py

Os imports usavam `..src`, que sobe acima do pacote de topo. Substituídos
pela forma absoluta já usada em main.py.
```

### O que não versionar

- `venv/` — ambiente virtual
- `data/` — CSV e checkpoint gerados
- `__pycache__/` — bytecode
- `src/.env` — configuração local, possivelmente com filtros sensíveis

O `.env.example` é versionado; o `.env` nunca.
