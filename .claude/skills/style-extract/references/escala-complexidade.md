# Escala de complexidade — `versao_escala: 1`

> **Os números NÃO moram aqui.** Eles moram em `_schema.json`, bloco
> `x_escala_complexidade`, e o `complexidade.py` lê de lá. Este arquivo explica;
> ele não redefine.
>
> A razão é medida: `bordas.py:196` tinha `PRE,POST = 0.02,0.06` enquanto a
> `edit-video/SKILL.md:44` afirmava `0.12/0.20` como default. A divergência
> doc↔código obrigou a migração da SPEC-00 a congelar o valor do CÓDIGO para não
> mudar o ritmo de toda produção antiga em silêncio
> (`docs/specs/ACHADOS-DO-CODIGO.md §3.4`). Escala em dois lugares vira duas
> escalas.

---

## O que o IC responde

O creator-1 pediu isto em uma frase: *"a gente tem edições mais simples e edições
mais complexas"*. "Simples" e "complexa" viram **um número de 0 a 100**, com a
escala declarada junto — em vez de adjetivo que cada pessoa lê de um jeito.

## Os cinco componentes

| componente | de onde vem | âncora | peso |
|---|---|---|---|
| `densidade` = `elementos_por_10s` | `deep-edit.densidade.elementos_por_10s` | 8,0 | 0,30 |
| `camadas` = `max_simultaneos` | `deep-edit.densidade.max_simultaneos` | 4 | 0,20 |
| `recursos` = nº de `tipo` distintos | `deep-edit.timeline_elementos[].tipo` | 10 | 0,25 |
| `corte` = `cortes_por_min` | `ritmo.py` | 30 | 0,15 |
| `texto` = `presente_pct_do_tempo / 100` | `tipografia.py` | 1,0 | 0,10 |

```
s_i  = min(1, x_i / ancora_i)
IC   = round(100 · Σ w_i · s_i)
```

Faixas: **enxuto** `IC < 30` · **médio** `30 ≤ IC < 60` · **denso** `IC ≥ 60`.

## De onde vêm as âncoras — e o que elas NÃO são

São **convenção da escala**, não constante da natureza.

- **8,0 elem/10s** — o mais denso que este repo já mediu é **7,4** no vídeo de
  oferta da ref-C (`intelligence/edicao/ref-C-oferta.md`; o bloco de
  objeção dela chega a 9,9). A âncora é o teto redondo logo acima.
- **30 cortes/min** — o mais rápido medido é **27,9** no ref-G
  (`data/advertisers/_ritmo/ref-G-var1.json`). Mesmo raciocínio.
- **4 camadas simultâneas · 10 recursos distintos · 100% de texto na tela** —
  convenção. Não têm extremo medido por trás.

Por isso o artefato carrega `complexidade.versao_escala`. **Dois estilos só são
comparáveis se a `versao_escala` bate.**

## Três coisas que o IC não é

1. **Não é percentual.** "Esta edição é 44% complexa" é frase sem sentido — não
   escreva isso em lugar nenhum. IC é **ordinal dentro da escala**.
2. **Não é qualidade.** IC alto não é edição melhor. O vídeo de oferta mais denso
   deste repo é o mesmo que zera punch-ins: densidade e sofisticação são eixos
   diferentes.
3. **Não é comparável entre versões da escala.** Se as âncoras mudarem, `versao`
   sobe e os IC antigos não migram.

## Sem IC quando falta componente

Se **qualquer** um dos cinco componentes não foi medido, `complexidade.py`
devolve `ic: null` e `componentes_faltando` nomeia quais. Renormalizar os pesos
sobre os componentes presentes daria um número plausível a partir de amostra
parcial — que é exatamente o erro que este repo registrou três vezes
(`docs/EDICAO-CAPACIDADES.md:39`, `:65-67`, `:168-171`).

Na prática: rodar `medir-ref.py --sem-semantico` deixa o estilo **sem IC**, porque
três dos cinco componentes vêm do `deep-edit`. Isso é o comportamento certo.

## Como auditar a escala

```bash
python3 .claude/skills/style-extract/scripts/complexidade.py \
  --avulso --elem10s 7.4 --simultaneos 3 --recursos 8 --cortes-min 5.1 --texto-pct 34.1
```

Os dois casos de calibração do repo, com resposta conhecida:

| peça | elem/10s | cortes/min | IC |
|---|---|---|---|
| ref-C — vídeo de oferta | 7,4 | 5,1 | **69** (denso) |
| ref-D | 0,9 | 15,6 | **38** (médio) |

A separação de **31 pontos** entre os dois é o que a escala existe para produzir:
uma edição em que a variedade vem 100% de overlay contra uma em que ela vem do
corte. (Os `simultaneos`, `recursos` e o `texto-pct` do ref-D são
estimativa do operador — o que está calibrado é a **ordem e a separação**, não o
valor absoluto.)
