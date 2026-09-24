# Blocos — a taxonomia por objetivo, e por que ela existe

O estilo tem dois níveis: `eixos` (a peça inteira) e `por_bloco`. Esta é a
taxonomia de bloco, que depende do **objetivo**, nunca da pessoa.

| objetivo | blocos |
|---|---|
| `venda` (VSL, anúncio longo) | `abertura` · `corpo` · `oferta` · `fechamento` |
| `educativo` (reel, aula) | `gancho` · `desenvolvimento` · `payoff` · `cta` |
| `autoridade`, `bastidor` | `abertura` · `corpo` · `fechamento` |
| `captura` | `gancho` · `promessa` · `cta` |
| `anuncio` | `gancho` · `problema` · `solucao` · `cta` |

Rótulo fora da lista não quebra nada — o `medir-ref.py` aceita o que o operador
declarar. A lista existe para que **as mesmas fronteiras se chamem do mesmo jeito
entre referências**, senão `por_bloco` não agrega: um corpus com `oferta` numa ref
e `cta2-desconto` na outra tem dois blocos de N=1 em vez de um de N=2.

## De onde saem os marcos

Duas fontes, nesta ordem:

1. **O `player-map.md` da VSL**, quando existe (`data/advertisers/*/vsl/*/`). A
   `model-edit/SKILL.md:47-48` já manda alinhar os marcos aos **CTAs**, não a
   divisões redondas: o que interessa é o ritmo *do bloco de oferta*, não o do
   minuto 20.
2. **O operador**, com o mesmo formato do `ritmo.py`:

```
--marcos 0:00-1:22=abertura 1:22-20:45=corpo 20:45-25:31=oferta
```

## O critério de entrada em `por_bloco`

Um `Param` só ganha entrada num bloco quando a variação **por bloco** é maior que
a variação **entre referências**:

```
inclui em por_bloco[b][k]  ⟺  |mediana_bloco(b,k) − mediana_global(k)| > iqr_global(k)/2
                              E  o sinal da diferença é o mesmo em >= ceil(2N/3) refs
```

Empate **não** conta como concordância: uma ref cujo bloco é igual à sua própria
mediana não testemunha direção nenhuma.

Sem esse critério, `por_bloco` vira ruído de amostragem repetido três vezes.

### O que isso custa, medido

No corpus das 4 VSLs (`intelligence/estilos/vsl-venda-frio-teste/`) o achado
manual *"o plano **sempre** fica mais longo no bloco de oferta"*
(`intelligence/edicao/vsl-rede-ref-E.md:62`) **não sobrevive** ao critério:
`plano_medio_s` na oferta desloca `+0,40 s` contra uma `iqr_global/2` de `0,92 s`.
Três das quatro refs concordam na direção — mas as quatro são de temperaturas
diferentes, e a diferença **entre elas** engole a diferença **entre blocos**.

Isso não é o critério falhando; é o critério dizendo a verdade sobre **este**
corpus. O efeito de bloco é intra-referência, e um corpus heterogêneo não o
sustenta. Para vê-lo, agregue peças da mesma temperatura — que é exatamente o que
o veredito de coerência manda fazer.

E o mecanismo tem dentes: num corpus de 3 refs homogêneas com `oferta` plantada
3 s mais longa, as quatro entradas de bloco saem com `conf: alta` e `3 de 3 refs
concordam na direção` — e o bloco `corpo`, plantado igual à mediana, é
corretamente rejeitado.

## O estilo muda DENTRO da peça — a evidência

- `remotion-compositor/references/sistema-vsl-trafego-pago.md:34-50` — elementos/10s
  × punch-ins × legenda por bloco (abertura/corpo/oferta) em 4 peças.
- `intelligence/edicao/vsl-rede-ref-E.md:51-68` — a curva de ritmo dentro da
  peça, **e** a Imersão 7D invertendo a curva por ser peça de público quente
  (corpo a 4,8/min, oferta a 17,1/min). A exceção aparece como ref discordante em
  `por_ref`; ela não some numa média.
