# Fixtures da bateria da SPEC-24 (§8.2)

Material **sintético**, do produto. Nenhum bruto, nenhuma imagem, nenhuma fala de
creator — é a separação que a FRONTEIRA §3 exige entre fixture de material real
(nossa) e autoteste (produto).

| arquivo | papel |
|---|---|
| `perfis/teste.json` | a **camada 1** da bateria. Valores distintos dos do `reels` de propósito: um caso que passa porque bateu com o catálogo real não mediu nada |
| `catalogo.json` | a **camada 2**. Fixture própria, e não o `catalogo.json` da SPEC-15 — portão absoluto sobre arquivo de outra spec mede o vizinho, não a si mesmo |
| `estilos/teste/a` | a **camada 3**. Seta `ritmo.pads.pre`, `ritmo.gramatica_plano`, `cor.grade`, `picks.legenda`, `picks.gancho: null` (o grupo **desligado**, ≠ ausente) e `parametros` |
| `estilos/teste/b` | herda de `a` e sobrescreve só `cor.grade` — os casos 5 e 6 (o pai vence onde o filho é silencioso; o filho vence onde escreve) |
| `estilos/teste/formato` | o estilo que tenta escrever `video.fps` — caso 10 |
| `eventos/*-estilo-*.json` | a **camada 4**, `benchmark.edit-estilo/v1` escrito à mão. É o caminho "sem servidor" que a SPEC-16 §3.12 já prevê, não é gambiarra |
| `eventos/*-ajustes-1.json` | `benchmark.edit-ajustes/v1` — existe para provar que correção de timeline vira classe `peca` e **não** conta para promoção |
| `receita-minima.json` | o mapeamento `--de-receita` (§4.4) sem depender de nenhum arquivo de `data/` |

## Por que `teste.json` e não `_teste.json`

A §8.2 escreve `_teste.json`. Em `perfil.py`, `_*.json` é **camada interna do
catálogo** (`_base`, `_ritmos`, `_schema`) e não aparece na lista de perfis
válidos — um estilo declarando `perfis: ["_teste"]` seria recusado pela própria
validação que a bateria existe para exercitar.

## `ritmo.gramatica_plano` é o path do caso 4, e não é escolha estética

É o **único** caminho do escopo que as quatro camadas sabem escrever de verdade:
o perfil (enum `fixa|alternada|punch-pontual`), o estilo, o campo
`gramatica_plano` do `benchmark.edit-estilo/v1` da UI, e o pedido compilado. Um
caso rotulado "4 camadas" em que só duas escrevem o path não mede precedência
nenhuma — mede duas.
