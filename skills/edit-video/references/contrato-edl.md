# Contrato da EDL — `benchmark.edl/v2` e `benchmark.timeline-real/v1`

> **Legado ainda lido**: `benchmark.edl/v1` — a EDL como ARRAY nu, sem envelope.
> `edl_io.py` a aceita e a nomeia na saída (`:517`); nada a escreve desde a
> SPEC-05. Está declarada aqui porque o `doc-check.py --contratos` confere que
> toda versão viva em código existe neste arquivo (achado A23), e uma versão
> que o código lê é uma versão viva.


> Origem: **SPEC-05**. Este arquivo é o contrato versionado que os consumidores
> leem. Quem for escrever código que toca `edl.json` lê isto antes.
>
> Implementação: `scripts/edl_io.py` · teste: `scripts/tests/test_edl_v2.py`.

---

## 0. As três frases que resumem tudo

1. **Frames e amostras são inteiros e são a verdade.** Os segundos são derivados
   (`start_frame / fps`) e existem para leitura humana. **Nunca some segundos
   para achar posição.**
2. **A origem é o segmento renderizado, nunca a EDL.** `frames` vem do ffprobe
   dos `segs/` (ou do que o `audio-exato.py` mediu para cortar o áudio);
   `width/height/fps` vêm do mesmo probe. Nada aqui é prescrito por perfil, por
   flag ou por constante.
3. **Se a EDL mudar, a timeline morre.** Duas defesas, as duas obrigatórias: o
   `bordas.py` remove o bloco ao reescrever, e `edl_io.timeline()` aborta quando
   o `edl_fingerprint` não bate.

---

## 1. O envelope

```jsonc
{
  "schema": "benchmark.edl/v2",
  "perfil": null,                 // nome do PERFIL DE PEÇA (SPEC-00) ou null.
                                  // Esta camada só PRESERVA a chave; quem a
                                  // interpreta é o perfil.py.
  "segments": [ /* §2 */ ],
  "timeline_real": { /* §3 — ausente até o montar.sh rodar */ }
}
```

**Chave de topo desconhecida é preservada na ida e volta.** `carregar(gravar(env))
== env` é critério de aceite (§7.3 da SPEC-05), e vale para chaves que ninguém
previu — `anotacao_do_editor`, o que a spec seguinte inventar. O `gravar` ordena
`schema · perfil · segments · timeline_real` e depois o resto em ordem alfabética,
só para o diff de git ficar legível.

### O que `gravar` RECUSA

| entrada | por quê |
|---|---|
| `segments` ausente, `null` ou não-lista | 📏 medido: `jq -c '(.segments? // .)[]'` sobre `{"segments": null}` cai no objeto inteiro e itera os **valores** dele em silêncio — o `montar.sh` montaria lixo sem uma linha de erro |
| `segments: []` | não há o que montar; falhar aqui é mais barato que um render vazio |

---

## 2. O segmento

```json
{"src": "input/IMG_6700.MOV", "start": 27.61, "end": 30.72,
 "fala": "Mulher casada…", "beat": "gancho-1",
 "zoom": 1.0, "cx": 0.5, "cy": 0.5,
 "quem": "creator-2", "gain_db": -1.5, "fadeOut": 0.04}
```

Cinco campos são canônicos (`src`, `start`, `end`, `fala`, `beat`). **Todo o resto
é passthrough**: o `bordas.py` opera por **lista NEGRA** — os oito campos que são
insumo do resolvedor de bordas (`asr_ini`, `asr_fim`, `pre_extra`, `post_extra`,
`limite_pre`, `limite_pos`, `start_fixo`, `end_fixo`) morrem lá; **qualquer** outro
campo do `janelas.json` atravessa para a EDL.

Duas regras que valem a linha de código:

- **`src`/`start`/`end` nunca são sobrescritos** pelo `janelas.json`. Um `start`
  escrito lá é o operador descrevendo o ASR, não a borda resolvida.
- **O passthrough não é silencioso.** O `bordas.py` imprime no stderr quantos
  segmentos receberam cada campo extra e nomeia o beat cujo conjunto de extras
  difere do resto — é assim que um `gaindb` digitado errado aparece (1/23) em vez
  de atravessar até um consumidor que o ignora.

### `gain_db` — o único passthrough que é CONSUMIDO (SPEC-08)

Passthrough quase sempre quer dizer "atravessa e alguém lá na frente talvez leia".
`gain_db` é a exceção: ele tem consumidor obrigatório, contrato fechado e
validação **fatal**.

| propriedade | valor |
|---|---|
| tipo | número (int ou float), em **dB** |
| ausente | equivale a `0.0` |
| faixa válida | `[−24.0, +12.0]` — fora disso é **erro fatal**, nomeando o beat |
| semântica | **ABSOLUTO**: substitui, nunca acumula entre execuções |
| ponto de aplicação | `audio-exato.py`, sobre o slice do bruto, **antes** dos micro-fades |
| afeta o vídeo? | **não** — e é por isso que ele não entra no sidecar de procedência |
| quem escreve | o operador/agente, no **`janelas.json`** |
| quem sugere | `qc-nivel.py achado` (`ganho_sugerido_db`) — **sugere, nunca escreve** |
| quem aplica | `audio-exato.py` via `nivel.ler_gain_db` + `nivel.ganho_linear` |
| quem registra | `<dir>/nivel-aplicado.json` (`benchmark.nivel-aplicado/v1`) |

```json
{"src": "input/take-conteudo.MOV", "start": 27.610, "end": 30.870,
 "fala": "…", "beat": "gancho", "zoom": 1.0, "cx": 0.5, "cy": 0.5,
 "gain_db": 3.5}
```

🔴 **Escreva no `janelas.json`, não no `edl.json`.** O `bordas.py` reescreve a
`edl.json` inteira a cada execução: um `gain_db` editado direto lá evapora na
próxima passada de borda. Escrever direto na EDL é aceitável só quando se sabe
que o `bordas.py` não vai rodar de novo — é uma escolha, não o caminho.

🔴 **Chave parecida é erro fatal, não aviso.** Com a lista NEGRA, um `"gaindb": 6`
atravessa **intacto** até um consumidor que o ignora: o operador vê o campo no
arquivo e o áudio não muda. `nivel.ler_gain_db` recusa `gain`, `gaindb`, `ganho`,
`ganho_db`, `gain_dB` com "você quis dizer `gain_db`?". É a segunda linha de
defesa — a primeira é o resumo do stderr do `bordas.py`, que mostra o campo
aparecendo em `1/23` segmentos, que é a forma que um typo tem.

🎯 **Mudar `gain_db` NÃO invalida os `segs/`.** O sidecar de procedência do
`montar.sh` grava `src,start,end,zoom,cx,cy` e o ganho não toca um pixel. O ciclo
de ajuste de nível é *editar → rodar só o `audio-exato.py` → ouvir*, de segundos,
sem re-render. Isso é intencional: **não** "conserte" adicionando `gain_db` ao
sidecar — incluí-lo forçaria re-render de 29 segmentos a cada ajuste de 0,5 dB e
faria a EDL de nível "mudar o corte" aos olhos do guard, que é ruído no exato
mecanismo que protege contra segmento órfão.

⚠️ **O teto NÃO é campo de EDL.** `gain_db` é do segmento; o teto (`teto_dbfs`,
`lookahead_ms`, `release_ms`) é da **peça** e vive em `perfil.audio.limiter`, com
fallback em `nivel.py`. Ganho é por segmento, limitador é da trilha — confundir
os dois é o "compressor global" que bombeia os takes que já estavam certos.

### Campos de DIAGNÓSTICO — escritos pela ilha, nunca lidos por ela

Há uma terceira classe, além de canônico e passthrough: campos que um script
**nosso** escreve para registrar o que mediu. Eles são aditivos, opcionais e
**nenhum consumidor precisa lê-los** — quem os lê é o humano e o QC.

| campo | unidade | quem escreve | o que é |
|---|---|---|---|
| `cauda_ms` | inteiro, **milissegundos** | `bordas.py` (SPEC-09) | silêncio contínuo medido no fim de `[start, end]`, varrendo PRA TRÁS a partir do `end` até a primeira janela acima do piso |
| `cauda_aparada_ms` | inteiro, **milissegundos** | `bordas.py` (SPEC-09) | quanto desse silêncio o `--cauda` removeu. `0` no modo `medir` (o default) e sempre que uma guarda barrou |

```json
{"src": "input/take-conteudo.MOV", "start": 13.530, "end": 17.690,
 "fala": "…", "beat": "depende", "zoom": 1.7, "cx": 0.42, "cy": 0.38,
 "cauda_ms": 420, "cauda_aparada_ms": 360}
```

⚠️ **A unidade é milissegundo INTEIRO de propósito.** O resto da EDL é segundos
com 3 casas; um campo em unidade diferente, com o nome dizendo qual, não é
confundido com tempo de corte por quem lê rápido — nem por um `jq` que somasse a
coluna errada.

⚠️ **`cauda_ms` descreve o corte que está no arquivo AGORA.** Depois do aparo,
`end` já é o novo valor e `cauda_ms` continua sendo o que foi medido **antes**
dele: `end_original == end + cauda_aparada_ms/1000`. É registro da decisão, não
entrada de cálculo — reprocessar a EDL com base nele soma o aparo duas vezes.

---

## 3. `timeline_real` — a timeline da SAÍDA

```jsonc
"timeline_real": {
  "schema": "benchmark.timeline-real/v1",
  "gerado_por": "audio-exato.py",
  "gerado_em": "2026-08-08T21:34:02-03:00",
  "edl_fingerprint": "sha1:64bccdcf07acaf…",   // sha1 do JSON canônico de segments
  "video": {"width": 1080, "height": 1920,
            "fps": 30.0, "fps_num": 30, "fps_den": 1},
  "sample_rate": 48000,
  "samples_por_frame": 1600,        // só existe quando sr % fps == 0
  "total_frames": 1987,
  "total_s": 66.233333,
  "total_samples": 3179200,
  "segments": [
    {"i": 0, "beat": "gancho-1", "src": "input/IMG_6700.MOV",
     "src_start": 27.61, "src_end": 30.72,
     "frames": 94, "start_frame": 0,
     "start_s": 0.0, "dur_s": 3.133333,
     "start_sample": 0, "samples": 150400}
  ]
}
```

### Unidades e origem, campo a campo

| campo | unidade | de onde vem |
|---|---|---|
| `frames`, `total_frames` | frames inteiros | `ffprobe -count_frames` do `segs/segNNN.mp4`, ou o `nf` que o `audio-exato.py` já mediu para travar o áudio |
| `samples`, `total_samples` | amostras **por canal** | o que foi **escrito** no `audio-exato.wav`; sem essa medição, `frames × samples_por_frame` |
| `start_frame`, `start_sample` | inteiros | soma cumulativa dos anteriores |
| `start_s`, `dur_s`, `total_s` | segundos, 6 casas | **derivados** de frames/fps. Leitura humana |
| `width/height/fps` | medidos | ffprobe do próprio segmento. Há produção 1080x1920 e produção 1280x720 no mesmo repo |
| `src_start`, `src_end` | segundos no **bruto** | copiados da EDL. `null` quando a EDL é por frames |

### Invariantes (asseguradas na escrita, conferidas na leitura)

```
start_frame[k]  == Σ frames[0..k-1]        total_frames  == Σ frames
start_sample[k] == start_frame[k] * spf    samples       == frames * spf
start_s == start_frame / fps               dur_s         == frames / fps
total_s == total_frames / fps              total_samples == amostras do WAV
```

`conferir_invariantes()` roda nas duas pontas. A tolerância dos segundos é `1e-6 s`
(o arredondamento em 6 casas erra no máximo `5e-7`); frames e amostras são
comparados por **igualdade exata**, porque são inteiros.

⚠️ `samples_por_frame` **só é gravado quando `sr % fps == 0`**. Aproximar para
"suportar 29,97" é a deriva progressiva de A/V de 2026-07-25 voltando pela porta
nova. Sem divisão exata, o campo não existe e a verdade das amostras é o que o
`audio-exato.py` escreveu.

### Onde ela mora

| EDL no disco | onde a timeline vai |
|---|---|
| v2 (objeto) | **inline**, na chave `timeline_real` |
| v1 (array nu) | **sidecar** `timeline-real.json` na pasta da produção, e o `edl.json` **não é tocado** (md5 idêntico) |

O sidecar existe para não promover em silêncio uma produção histórica cujos
scripts locais (`planos.py`, `legendas.py`, `cenas.py`) iteram o array.
`edl_io.py --migrar <dir>` consolida quando alguém decidir migrar — grava
`edl.v1.bak.json` antes.

---

## 4. Como consumir (o que 07/08/09/10/12/16/21 vão chamar)

```python
import edl_io

segs = edl_io.segmentos(dir)              # v1 ou v2, o chamador não precisa saber
tl   = edl_io.timeline(dir, exigir=False) or edl_io.medir_timeline(dir)
fr   = edl_io.fronteiras(tl)              # n+1 valores
t    = edl_io.t_saida(tl, i, t_no_bruto)  # tempo do bruto → tempo na saída
```

Para quem **escreve**:

```python
env = edl_io.topo(dir)                    # chaves de topo da PEÇA (perfil, anotações)
env["segments"] = novos_segmentos
edl_io.gravar(dir, env, invalida_timeline=True)   # mudou o corte → a timeline morre
```

`topo()` é a única leitura de EDL que não valida nada (arquivo ausente, ilegível ou
corrompido devolve `{}`) — de propósito, para que uma `edl.json` quebrada possa ser
reescrita em vez de travar quem a reescreve. **Nenhum script fora do `edl_io.py`
abre `edl.json`, nem para espiar** (critério 9 da SPEC-05; hoje o grep dá **0**).

- **`fronteiras(tl)`** devolve `[start_s de cada segmento] + [total_s]`, ou seja
  **n+1** valores. A emenda entre o segmento `i` e o `i+1` é `fronteiras[i+1]`;
  `fronteiras[0]` é 0,0 e `fronteiras[n]` é o fim da peça.
- **`timeline(dir, exigir=False)`** devolve `None` quando a timeline **não
  existe** (produção anterior a esta spec). O que `exigir=False` **não** afrouxa é
  o fingerprint: timeline velha é sempre fatal, porque descreve um corte que não é
  mais o do arquivo.
- **O fallback certo é `medir_timeline`, nunca `Σ(end−start)`.** É a disciplina
  do `verify_cut.py:150-158` do ref-A: lê o bloco persistido quando ele existe,
  mede quando não existe, e nunca soma o nominal.

### 📏 Por que `Σ(end−start)` está proibido — o número

Medido em 2026-08-08 nos `segs/` que estão no disco deste repo:

| produção | segs | Σ(end−start) | Σ frames/fps | erro no fim | erro médio/emenda |
|---|---|---|---|---|---|
| `creator-2/peca-03` | 20 | 65,880 s | 66,233 s | **+353,3 ms** | +17,7 ms |
| `creator-2/peca-01` | 29 | 70,450 s | 70,767 s | **+316,7 ms** | +10,9 ms |
| `creator-2/peca-04` | 17 | 62,835 s | 63,133 s | **+298,3 ms** | +17,5 ms |

O erro é **monotônico e sempre no mesmo sentido** (o nominal é sempre mais curto):
é arredondamento para frame acumulando. Em `peca-03`, o deslocamento de cada
fronteira vai de **+23,3 ms** na primeira a **+343,3 ms** na última usada — e
"descentrada" é exatamente o que faz um QC de emenda ler a palavra errada dos dois
lados do corte.

É o anti-pattern que o SKILL.md do ref-A proíbe na linha 513 e que o código deles
comete assim mesmo (`render.py:809`, `captions_for_remotion.py:85` — 4,433 s de
erro num caso de 20 takes). **Eles têm o dado certo gravado e leem o errado.**

---

## 5. Retrocompatibilidade — a regra em uma frase

> **LER v1 sempre; ESCREVER v2 só onde o `bordas.py` escreve.**

| situação | comportamento |
|---|---|
| `edl.json` é array (v1) | `carregar` envelopa **em memória**; nada é gravado |
| `montar.sh` sobre v1 | monta normal (`jq 'if type=="array" then . else .segments end \| .[]'`) |
| timeline sobre v1 | sidecar `timeline-real.json`; `edl.json` intocado |
| `bordas.py` roda | escreve v2 **sem** `timeline_real` (o corte mudou) |
| script local de produção que faz `json.load` e itera | **quebra** se a EDL for v2 — falha ruidosa, não silenciosa. É o único caso de quebra, e só acontece se alguém rodar o `bordas.py` naquela pasta |

⚠️ **As produções históricas ficam em v1 e não são convertidas.** Elas têm scripts
locais que iteram o array e entregas já publicadas.

📏 **Medido no jq 1.8.1 desta máquina** — as duas formas "óbvias" estão erradas:

| expressão | array v1 | `{"segments": null}` |
|---|---|---|
| `(.segments // .)[]` | **erro**: "Cannot index array with string" | itera o objeto |
| `(.segments? // .)[]` | ok | **itera os valores do objeto em silêncio** |
| `if type=="array" then . else .segments end \| .[]` | ok | **erro** (é o que se quer) |

---

## 6. CLI

```
edl_io.py --ver    <dir>    # schema · nº de segmentos · timeline fresca/ausente/VELHA
edl_io.py --medir  <dir>    # imprime o bloco timeline_real em stdout, NÃO grava
edl_io.py --migrar <dir>    # v1 → v2 no arquivo (backup edl.v1.bak.json)
```

`--medir` é read-only sobre `segs/`: serve para auditar produção histórica sem
escrever nada nela. Ele **recusa** medir quando `len(segs/) != len(segments)` — é
o segmento **órfão**, e medir ali gravaria uma timeline coerente com o vídeo
errado (foi o bug que deixou o `c-completo` do creator-3 6,25 s mais longo com todos
os QCs verdes). `creators/creator-2/producao/ovo-de-pascoa` é o caso real: 22 segs no
disco contra 21 na EDL.

---

## 7. O que esta camada NÃO faz

- **Não decide formato.** `width/height/fps` são medidos, nunca prescritos; o
  `scale=…`/`fps=…` do `montar.sh` é assunto do perfil de peça (SPEC-00).
- **Não substitui a conferência nominal do `montar.sh`.** As duas ficam, e medem
  coisas diferentes: a **nominal** (Σ da EDL × render, tolerância folgada) é o
  único detector de **segmento órfão**; a **real** (timeline × render, ± 2 frames)
  detecta erro de encoder/container. Um órfão passa na real **por construção** —
  a timeline foi medida dos próprios segs errados.
- **Não reescreve caminhos.** `segments[].src` continua relativo à pasta da
  produção, como já estava.
