# Registros de decisões arquiteturais

Esta pasta registra as decisões arquiteturais tomadas neste projeto, no
formato [MADR](https://adr.github.io/madr/).

## Por que existem

O código mostra o que um projeto faz. Ele não mostra o que foi considerado e
descartado, nem por quê. Um registro de decisão arquitetural captura o
raciocínio no momento em que a escolha foi feita, para que um leitor futuro —
inclusive você, daqui a alguns meses — consiga distinguir uma decisão
deliberada de um acidente.

## Quando escrever um

Escreva um registro quando a decisão for difícil de reverter, afetar mais de
um arquivo, ou tiver uma alternativa plausível que o leitor poderia supor que
você deixou passar. Exemplos deste projeto: gravar o CSV em fluxo em vez de
manter o conjunto de dados em memória, registrar o progresso por bloco e não
por página, e limitar a concorrência a um teto medido em vez do maior valor
que executa.

Não escreva um registro para escolhas que o próprio código já explica.

## Como acrescentar um registro

1. Copie [adr-template.md](adr-template.md) para `NNNN-titulo-curto.md`, onde
   `NNNN` é o próximo número da sequência, começando em `0001`.
2. Preencha o contexto, as opções consideradas e as consequências —
   inclusive as negativas.
3. Acrescente o registro ao índice abaixo.
4. Escreva o mesmo registro em
   [../../english/decisions/](../../english/decisions/), mantendo o nome do
   arquivo e a estrutura idênticos. Apenas o idioma do texto muda.

Um registro nunca é editado para refletir uma mudança de ideia. Escreva um
novo e marque o antigo como substituído por ele.

## Índice

| Número | Título | Situação |
|---|---|---|
| — | Nenhum registro ainda | — |
