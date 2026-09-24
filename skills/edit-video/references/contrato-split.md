# `split-plano.json` — o contrato do enquadramento no split-screen

> Schema `benchmark.split-plano/v1`. Vive na pasta da produção, ao lado do
> `v1-montado.mp4`. Nenhum artefato existente muda por causa dele; a `edl.json`
> **não é tocada**.

---

## Para que ele existe

O `split-broll.py` empurrava a base para baixo por uma constante (`--desloca-base
25`). `pad`+`crop` é translação pura: **onde o rosto aterrissa era efeito
colateral de um número copiado de uma referência**. Medido no material entregue
do estudo `modelagem-ref-D` (matte de pessoa, 35 amostras): o topo da cabeça
caía dentro da rampa de alpha, com **mediana de 12,20 % e máximo de 13,48 % de
b-roll sobre o cabelo**.

Com plano, os mesmos 35 samples dão **0,00 %**.

A conta que substitui a constante:

```
cabeça_saida = topo_da_cabeça_na_base · escala + deslocamento
```

resolvida preferindo `escala = 1` — deslocar é de graça, escalar é upscale de um
vídeo que já está na largura de saída.

---

## Quem produz, quem consome

| | |
|---|---|
| **produz** | `split-plano.py <dir> --janela T0 T1` |
| **consome** | `split-broll.py … --plano split-plano.json` · `qc-split.py <saida> --plano …` |
| **mede a cabeça** | `matte.py` (Apple Vision, SPEC-03) na **base**, a `split.amostras_por_s` |
| **mede a janela** | `edl_io.timeline()` / `medir_timeline()` — o timeline REAL, contado em frames dos `segs/` |

---

## Os campos que decidem alguma coisa

```jsonc
{
  "schema": "benchmark.split-plano/v1",
  "base": "v1-montado.mp4",
  "base_sha1_8": "60a9de7e",      // procedência: sem isso, plano de outra geração compõe em silêncio
  "formato": {"largura": …, "altura": …, "fps": "30/1"},
  "mascara": {"opaco_pct": …, "fim_pct": …, "curva": …, "y_op": …, "y_fim": …, "alvo": …},
  "medidor": {"nome": "matte|manual", "engine": "vision", "amostras_por_s": 4},
  "janela": {"t0_pedido": …, "t1_pedido": …, "t0": …, "t1": …,
             "fonte_do_encaixe": "timeline_real|pedido"},
  "segmentos": [{
    "i": 2, "t0": …, "t1": …,
    "samples": 12, "samples_rejeitados": [{"t": …, "razao": "area<3%"}],
    "cabeca_p5": …, "cabeca_mediana": …, "queixo_p95": …,
    "deslocamento_px": 621, "deslocamento_pct": 0.3234, "escala": 1.0,
    "cabeca_saida": 1048.3, "alpha_broll_previsto": 0.0, "perda_base_pct": 0.3234,
    "motivo": "deslocamento", "guardas": {…}
  }],
  "avisos": []
}
```

`motivo` ∈ `cabeca-ja-baixa · deslocamento · deslocamento+escala · herdado ·
manual · janela-unica · nao-resolvido`.

---

## Os cinco guardas, e o que cada um faz quando morde

| # | guarda | quando morde |
|---|---|---|
| 1 | `S ≤ y_op` | o solver troca de ramo: `escala > 1` (declarado em `motivo`) |
| 2 | `cabeça_saida ≥ alvo` | `guardas.alvo.ok = false` — nunca em silêncio |
| 3 | `z ≤ split.escala_max` | **exit 1**, `motivo: "teto"`, nenhum frame renderizado, e a mensagem traz as duas saídas reais (`fim_pct` menor · reenquadrar na EDL e remontar) |
| 4 | `queixo·z + S ≤ H·(1 − margem_queixo_pct)` | reduz `S` até caber; se colidir com (2), `alvo.ok = false` |
| 5 | `perda_base ≤ split.perda_base_max_pct` | avisa **sempre**, e sem `--forcar` sai 1 com a curva de troca (`fim_pct` que caberia). É decisão editorial, não técnica |

**Nunca `min(z, teto)` sem um `if` que reporte.** Clamp sem guarda transforma
medição-lixo em recorte plausível e errado — a lição de 2026-07-27, quando o
creator-3 foi parar no canto inferior direito do quadro.

---

## A rejeição de sample, com nome

Um sample é **rejeitado** se: área do matte < 3 % ou > 70 % do quadro · topo da
cabeça < 1 % ou > 55 % da altura · o topo salta > 8 % da altura contra a mediana
móvel de 5.

Um segmento é **não resolvido** com > 25 % de samples rejeitados: ele herda a
**mediana dos `(S, z)` dos segmentos que resolveram**, com `motivo: "herdado"`, e
o stderr nomeia qual foi:

```
seg4: 6/6 samples rejeitados (area<3%×6) — herdou S=621 z=1.000 da mediana de seg2,seg3,seg5
```

Se **nenhum** segmento resolver: **exit 1 e o plano não é escrito**. Não existe
caminho em que um `(S, z)` sem medição por trás chegue ao ffmpeg.

---

## Três coisas que este contrato proíbe

1. **Não escrever `zoom`/`cx`/`cy` na `edl.json`.** Os números daqui vivem no
   sistema de coordenadas do **montado**; a EDL vive no do **bruto**. Levar um
   para o outro é a transformação dupla que já custou um ciclo de remontagem.
2. **Não interpolar `(S, z)` dentro do segmento.** Vira travelling que ninguém
   pediu. A troca acontece **no corte**, onde a troca de enquadramento já é
   gramática aceita.
3. **Não guardar deslocamento no perfil de peça.** O perfil carrega
   **política** (faixa, folga, tetos, percentil, amostragem); o **valor** é
   medido naquela peça. Um perfil com `deslocamento: 25 %` é o defeito de hoje
   com outro nome.

---

## O que o QC mede, e por que não mede na composição

`qc-split.py` **não procura a cabeça no arquivo composto**. Medido em
2026-08-09: o b-roll do estudo é um balcão de fast-food *com gente dentro*, o
Vision segmenta o figurante do apoio junto, e a primeira versão do portão
devolveu `alpha 100 %` em 35/35 amostras de uma composição **certa**. Não existe,
na imagem composta, informação que separe a cabeça do creator da de quem está no
b-roll.

A cadeia que ficou tem três medidas independentes, nenhuma lida do plano:

```
cabeça       matte de pessoa na BASE, todas as amostras
transforma   correlação cruzada da base contra a SAÍDA (busca LARGA, 0..y_fim)
máscara      a rampa do perfil de peça
```

⚠️ **A busca da correlação é larga de propósito.** Ancorada em ±8 px do `S`
planejado, ela devolveu 613 px com correlação 0,26 para um arquivo cujo
deslocamento real era 480 px — e a checagem seguinte usou esse número como se
fosse medida boa e **aprovou o arquivo defeituoso**. Portão ancorado no valor que
ele deveria conferir mede a âncora.

⚠️ **Frame é índice, nunca `-ss`.** `ffmpeg -ss 8.7` devolve frames diferentes da
base e da saída (GOPs diferentes): a correlação caía para 0,981 e acusava 4 px de
erro inexistente.

Réguas medidas em `estudos/modelagem-ref-D` (35 amostras, 4 segmentos):

| arquivo | deslocamento medido | alpha sobre a cabeça | exit |
|---|---|---|---|
| `v2-split.mp4` entregue (constante 25 %) | 480 px (plano: 620–624) | mediana **12,20 %** · máx 13,48 % | **1** |
| com plano, `z = 1,000` | 620–624 px, correlação 0,9997 | mediana **0,00 %** · máx 0,00 % | **0** |
| com plano, ramo `deslocamento+escala` (`z` 1,059–1,068) | 652 px, correlação 0,996–0,9997 | mediana **0,00 %** | **0** |
