# Alinhamento forçado local — o registro de medição (SPEC-04)

> 2026-08-08 · Apple M4, macOS 25.3, python 3.14.2, torch 2.13.0, torchaudio 2.11.0,
> `torchaudio.pipelines.MMS_FA`, `--device mps`.
> Tudo aqui foi medido nesta máquina, contra material deste repo. Nada veio de
> segunda mão.

**O que este bloco é**: o Deepgram nova-3 continua sendo o engine de **texto**
(`&keyterm` e `language=multi` não têm substituto local). O `alinhar.py` é o
engine de **tempo**: recebe áudio + as palavras que o ASR já achou e mede, contra
o próprio áudio, onde cada uma começa. Os dois não se misturam, e o
`transcript.json` não é reescrito.

---

## 0. A regra que governa este arquivo

🔴 **Nenhum número de acurácia aparece aqui sem dizer contra o quê foi medido.**

É o erro que a SPEC-04 §1.5 documenta no ref-A: eles publicam *"93% das palavras
caem dentro de uma região real de fala"* e *"o fim da fala é marcado com 10 ms de
erro"*, ambos medidos contra o `speech_regions.py` **da própria casa** — um
`silencedetect` com `--noise` fixo em `-33 dB` (`speech_regions.py:73`). Medir um
detector contra outro detector seu mede concordância, não acurácia. E "dentro de
uma região" é teste binário de contenção: satisfeito por qualquer timestamp
aproximadamente certo, não informa erro de fronteira.

Por isso toda tabela abaixo traz a `--ref` ao lado, e nenhuma traz "% dentro".

---

## 1. O problema que o bloco ataca: a grade de 80 ms

Medido em 4 transcripts reais (reproduzir com a SPEC-04 §8.1):

| transcript | limites distintos | múltiplos exatos de 80 ms | menor duração de palavra |
|---|---|---|---|
| `peca-03/take-A/` | 304 | 94,1% | 80 ms |
| `peca-09/` | 729 | 97,4% | 80 ms |
| `instagram-post-ref-C-1/` | 503 | 96,8% | 80 ms |
| `youtube-K4_ddX8gx8c/` | 5.860 | 97,4% | 80 ms |

80 ms = **2,4 frames a 30 fps**. O stride do MMS_FA, medido nas execuções abaixo,
é **20,00–20,01 ms** — grade **4× mais fina**.

---

## 2. Desempenho do bloco (informativo — depende da máquina)

Máquina: **Apple M4**, `--device mps`, `--chunk 180`, `--pad 1.0`, `--star` (default).

| produção | duração | palavras | chunks | tempo | ×realtime | alinhadas |
|---|---|---|---|---|---|---|
| `peca-03/take-A` | 279,1 s | 267 | 2 | 9,5 s | **0,034×** | 261 (97,8%) |
| `peca-01/take-conteudo` | 90,0 s | 209 | 1 | 2,6 s | **0,029×** | 196 (93,8%) |
| `peca-09` | 188,6 s | 689 | 2 | 6,7 s | **0,036×** | 674 (97,8%) |
| `modelagem-edicao/quase-original` | 41,5 s | 58 | 1 | 1,0 s | **0,023×** | 56 (96,6%) |

Bootstrap: `torch`+`torchaudio`+`numpy` = ~575 MB de venv; pesos do MMS_FA =
1,26 GB no cache do torch. Segunda execução do `bootstrap-aligner.sh`: **1,31 s**.

⚠️ Estes números são **desta** máquina com **este** modelo já baixado. Não são
portão: em outra máquina o número não vale. O aceite §7.5/§7.6 da spec (≤0,10×
realtime, RSS < 4 GB) está registrado como informativo por decisão de execução.

---

## 3. A política de `end_ctc` — o alinhador NÃO mede a soltura da palavra

Medido em `peca-03/take-A`, alinhado × Deepgram, **n=261 palavras alinhadas**:

| campo | mediana do delta (alinhado − ASR) |
|---|---|
| `start` | **−53 ms** |
| `end_ctc` | **−141 ms** |

Na janela de 20–90 s citada na SPEC-04 §3.1 (n=65): `start` −47 ms, `end_ctc` −149 ms.

O `end` do alinhador vem sistematicamente **141 ms antes**. Não é erro: é a
definição. CTC marca o **último frame em que o token ainda é emitido**, não a
soltura acústica. O `decay_relativo()` do `bordas.py:95-120` existe justamente
para achar a soltura, e o docstring dele mede que a cauda de "disso."/"mundo."
vive 0,3–0,4 s depois disso.

🔴 **Por isso o campo se chama `end_ctc` e o contrato PROÍBE usá-lo como borda de
corte.** Quem quer borda de corte usa `bordas.py`. Quem quer legenda karaokê usa
o `start` alinhado e estende a palavra até o `start` da próxima.

📏 **Divergência registrada, não corrigida**: a SPEC-04 §3.4 previa `start`
mediana **−24 ms** (n=35). Esta implementação mede **−53 ms** (n=261) e **−47 ms**
(n=65, a mesma janela). O `end_ctc` reproduz exatamente (−141 ms). Sinal, ordem de
grandeza e a política que deles decorre são os mesmos; o número exato do `start`
não reproduziu, e o subconjunto de 35 palavras da medição original não está
identificado. Não "consertei" nada por causa disso.

---

## 4. A régua: `medir-alinhamento.py`

**A fronteira medida** é o `start` de palavra **precedida de pausa** (default
`--gap 0.15`). É a única fronteira onde existe onset acústico para detectar:
dentro de fala corrida não há o que medir, e fingir que há é o erro da §0.

**A referência é escolhida pelo ponto médio dos dois candidatos** (ASR e
alinhado), para não favorecer nenhum dos dois.

Três famílias independentes de evidência:

- **`envelope`** — onset por RMS de 10 ms com piso local adaptativo (percentil 15
  num raio de 0,6 s, +10 dB): o mesmo critério do `piso_para(--floor auto)` do
  `bordas.py`. Independente de qualquer modelo de linguagem.
  ⚠️ **Cego para fricativa surda e nasal** — e a saída do script diz isso.
- **`fonemas`** — silêncio/surdo/vozeado pela razão (3–9 kHz)/(150–900 Hz),
  a lógica do `qc-fonemas.py`. Pega o que o envelope não pega.
- **`edl`** — fronteiras de um editor humano externo. Ver §6: **recusada**.

---

## 5. Os números

Três produções acusticamente diferentes × duas referências independentes.
`--gap 0.15`, `--janela 0.30`, `--score-min 0.0`. Toda linha traz o `n` varrido e a `--ref`.

**Reproduzir** (o `peca-01` e o `vsl` não têm `audio.mp3` no dir da
produção — o áudio vem de `input/`, por isso o `--audio`):

```bash
T=.claude/skills/transcribe/scripts
$T/alinhar.py creators/creator-2/producao/peca-03/take-A/
$T/medir-alinhamento.py creators/creator-2/producao/peca-03/take-A/ --ref todas

$T/alinhar.py creators/creator-2/producao/peca-01/take-conteudo/ \
   --audio creators/creator-2/producao/peca-01/input/take-conteudo.wav --out /tmp/al-mesa.json
$T/medir-alinhamento.py creators/creator-2/producao/peca-01/take-conteudo/ \
   --alignment /tmp/al-mesa.json \
   --audio creators/creator-2/producao/peca-01/input/take-conteudo.wav --ref todas

$T/alinhar.py creators/creator-1/producao/peca-09/ \
   --audio creators/creator-1/producao/peca-09/input/vsl-original.mp4 --out /tmp/al-vsl.json
$T/medir-alinhamento.py creators/creator-1/producao/peca-09/ \
   --alignment /tmp/al-vsl.json \
   --audio creators/creator-1/producao/peca-09/input/vsl-original.mp4 --ref todas
```

### 5.1 `peca-03/take-A` — sala silenciosa (piso −66 dB)

| candidato | `--ref` | n | mediana \|erro\| | p90 \|erro\| | viés | dispersão 50/90 |
|---|---|---|---|---|---|---|
| ASR cru | **envelope** | 34 | 50,0 ms | 153,5 ms | +10,0 ms | 47,5 / 153,5 ms |
| ALINHADO | **envelope** | 34 | **31,2 ms** | **69,7 ms** | +28,0 ms | **27,5 / 53,5 ms** |
| ASR cru | **fonemas** | 28 | 36,4 ms | 145,7 ms | +2,4 ms | 38,9 / 144,8 ms |
| ALINHADO | **fonemas** | 28 | **27,7 ms** | **71,7 ms** | +26,5 ms | **24,1 / 48,7 ms** |

Taxa de vitória: **70,6%** (24/34) `--ref envelope` · **71,4%** (20/28) `--ref fonemas`.

### 5.2 `peca-01/take-conteudo` — café (piso −44 dB de mediana)

| candidato | `--ref` | n | mediana \|erro\| | p90 \|erro\| | viés | dispersão 50/90 |
|---|---|---|---|---|---|---|
| ASR cru | **envelope** | 28 | 90,0 ms | 279,0 ms | −40,0 ms | 92,5 / 239,0 ms |
| ALINHADO | **envelope** | 28 | **32,8 ms** | 285,4 ms | +22,1 ms | **33,2** / 263,3 ms |
| ASR cru | **fonemas** | 21 | 91,7 ms | 209,6 ms | −15,9 ms | 83,1 / 193,7 ms |
| ALINHADO | **fonemas** | 21 | **39,9 ms** | 284,9 ms | +31,1 ms | **20,9** / 253,8 ms |

Taxa de vitória: **67,9%** (19/28) `--ref envelope` · **71,4%** (15/21) `--ref fonemas`.

### 5.3 `peca-09` — locução contínua (23 pausas ≥ 150 ms em 689 palavras)

| candidato | `--ref` | n | mediana \|erro\| | p90 \|erro\| | viés | dispersão 50/90 |
|---|---|---|---|---|---|---|
| ASR cru | **envelope** | 22 | 52,5 ms | 161,0 ms | +35,0 ms | 65,0 / 153,5 ms |
| ALINHADO | **envelope** | 22 | **27,5 ms** | **153,9 ms** | **−3,0 ms** | **27,5 / 151,2 ms** |
| ASR cru | **fonemas** | 19 | 56,4 ms | 143,8 ms | +48,3 ms | 52,0 / 120,8 ms |
| ALINHADO | **fonemas** | 19 | **27,7 ms** | **121,0 ms** | **+9,9 ms** | **25,5 / 111,2 ms** |

Taxa de vitória: **72,7%** (16/22) `--ref envelope` · **73,7%** (14/19) `--ref fonemas`.

### 5.4 Leitura das 6 medições

As "6 medições" são **3 produções × 2 referências independentes** (`--ref envelope`
e `--ref fonemas`). Em cada célula, o par de números é sempre nessa ordem.

| eixo | resultado (todas as 6: `--ref envelope` e `--ref fonemas`) |
|---|---|
| **mediana \|erro\|** | alinhado ganha em **6/6**, por 1,3× a 2,8× |
| **dispersão mediana** | alinhado ganha em **6/6** (0,25× a 0,60× a do ASR cru) |
| **taxa de vitória** | 67,9% a 73,7% — **6/6 acima do limiar de 65%** |
| **p90 \|erro\|** | razão alinhado/ASR, `--ref envelope` · `--ref fonemas`: 0,45 · 0,49 (peca-03) — 1,02 · 1,36 (mesa) — 0,96 · 0,84 (vsl). **Só a sala silenciosa passa do limiar de 0,80** |

⚠️ **Cautela sobre o p90, que é o eixo que reprova.** Nas duas produções onde ele
reprova, a própria referência é menos confiável: no café a fala está a ~22 dB do
piso, e na locução contínua só **1** fronteira em 689 palavras tem pausa ≥ 0,5 s.
O p90 nesses regimes mede tanto o ruído da régua quanto o erro do candidato.
Não é prova de que o alinhador erra mais — é prova de que **esta régua não decide** ali.

---

## 6. `--ref edl` — recusada, com o número

A única referência externa disponível é o par bruto↔editado do ref-D
(`data/adhoc/modelagem-edicao/`). A EDL dele (`edl-medida.json`) tem 12
fronteiras. Medido:

```
fronteiras na EDL: n=12 · coincidem EXATAMENTE com um timestamp do ASR: 12/12 = 100%
```

Os 6 IN batem, palavra por palavra, com um `word.start` do
`quase-original/transcript.json`; os 6 OUT, com um `word.end`. O próprio campo se
chama `raw_asr` e o `RECEITA-EDICAO.md` rotula a coluna *"bruto (ASR)"*.

🔴 **É a alegação circular da §0, na forma mais pura**: medir o ASR contra ela dá
erro **0 por construção**. O script mede a coincidência, imprime o número e
**recusa publicar**. Não inventei referência (SPEC-04 §6, passo 7).

O que faria dela uma referência de verdade: medir os instantes de corte no vídeo
**editado** por descontinuidade de imagem/áudio e mapear para o bruto. Isso é
`scdet` + transiente — **SPEC-26**, não esta.

---

## 7. Os controles — a prova de dentes

Verde sem prova de dentes não vale nada (`edit-video/SKILL.md:160`). Cinco
controles rodam em toda referência, e **todos imprimem `n`**:

| controle | o que faz | tem que ler | leu (6 medições) |
|---|---|---|---|
| **0** | candidato = a própria referência | 0 ms | **0,0 ms** em 6/6 |
| **A** | candidato = referência **+100 ms** | 100 ± 20 ms | **100,0 ms** em 6/6 |
| **B** | alinhado **+100 ms** | viés desloca +100 ± 20 | **+100,0 ms** em 6/6 |
| **D** | **áudio** prefixado com 103 ms de silêncio | a *referência* anda +103 ± 20 | **+100,0 ms** (envelope) e **+103,0 ms** (fonemas) |
| **E** | candidato × referência **de outra fronteira** | tem que explodir | **3.035 a 8.675 ms** |

**Por que o D usa 103 ms e não 100**: 100 ms é múltiplo exato da janela de 10 ms
do envelope — deslocar o áudio nesse valor move a grade junto e o controle passa
limpo demais. Com 103 ms o resíduo do envelope é −3,0 ms (a quantização da própria
grade, correta) e o do detector de fonemas, que tem passo de 2 ms, é 0,0 ms.

**Por que o D e o E existem**: uma régua circular — que devolvesse o próprio
candidato como "referência" — passaria em 0, A e B, e **reprovaria** em D e E.
São os dois únicos controles que testam a independência da referência.

---

## 8. Chunking — onde o bloco quebra, medido

Régua da SPEC-04 §8.5: os tempos **não podem depender do chunking**; p99 do
\|delta\| < 20 ms (um frame do modelo). Medido em `peca-03/take-A` (267 palavras),
comparando `--chunk 180` contra chunks menores:

| config | 180 vs 90 (p99 / max) | 180 vs 45 (p99 / max) | 180 vs 25 (p99 / max) |
|---|---|---|---|
| `--sem-star --pad 1.0` | 35,2 / **118,3 ms** | — | — |
| `--sem-star --pad 3.0` | **965,8 / 1.542,0 ms** | — | — |
| **default** (`--star --pad 1.0`) | **29,7 / 36,9 ms** | 29,0 / 35,8 ms | 110,8 / **1.215,8 ms** |
| default + `score ≥ 0,05` | 30,6 / 36,9 ms | 25,8 / 35,8 ms | 27,6 / 267,2 ms |
| default + `score ≥ 0,30` | 31,6 / 36,9 ms | 27,5 / 35,8 ms | **25,9 / 28,4 ms** |

Quatro coisas medidas, três delas contrariando o que a spec previa:

1. 🔴 **A remediação prevista na §8.5 — *"o `--pad` precisa crescer"* — está
   invertida.** Sem o token `<star>`, crescer o pad de 1,0 s para 3,0 s leva o
   erro máximo de 118 ms para **1.542 ms**. O pad traz áudio que não está na lista
   de tokens; sem um token para absorvê-lo, o CTC o distribui pelas palavras que
   tem. **Por isso `--star` é o default** (`--sem-star` desliga).
2. **A mediana de ~9 ms é irredutível**: é a fase da grade de frames do modelo
   (stride 20 ms) mudando com o `t_ini` de cada chunk. Meio frame.
3. **`--chunk 25` quebra**, e o `score` denuncia: a palavra "Comente", encostada
   num silêncio de 4,22 s, escorregou **4.121 ms** para trás — com `score` caindo
   de **0,944** para **0,014**. Com `score ≥ 0,30` o máximo volta a 28,4 ms.
4. **Um `--pad` grande combinado com `--chunk` pequeno é o pior caso** (`--pad 2.0
   --chunk 45`: max 5.019 ms). Tentei limitar o pad a metade do gap do corte:
   **não resolveu e piorou** o caso 180 vs 90 (36,9 → 122,2 ms). Revertido — o
   remédio que funciona é o `score`, não a geometria da janela.

➡️ **Consequência para quem consumir o `alignment.json`**: o `score` **é** o
portão. Palavra com score baixo não tem posição confiável, e nenhuma outra
salvaguarda deste bloco cobre isso. Em `take-A` com `--chunk 180`, `score < 0,05`
são 5,7% das palavras alinhadas e `score < 0,30` são 25,3%.

⚠️ **Não medido**: a régua p99 < 20 ms **não passa** nem na melhor configuração
(29,7 ms = 1,5 frame). Fica registrado como limite conhecido, não como aprovação.

---

## 9. 🔴 VEREDITO

> ## **adotar só onde X**
>
> — com o **X** medido, em três cláusulas:

**X.1 — só o `start`, nunca o `end_ctc`.** O `end_ctc` vem 141 ms antes da
soltura (§3, n=261). Como borda de corte ele decepa a cauda de toda frase, que é
exatamente a classe de defeito que o creator-1 ouve e os QCs não pegam. Borda de
corte continua sendo `bordas.py`.

**X.2 — só com `score` acima do piso.** O `score` é o que separa "medido" de
"escorregou": no caso do `--chunk 25`, 0,944 → 0,014 numa palavra que andou 4,1 s
(§8). Quem consumir sem olhar o `score` reintroduz o defeito. A régua aplica esta
cláusula com `--score-min` (ex.: `--score-min 0.30` em `peca-03/take-A`,
`--ref envelope`, cai de n=34 para n=23 e a taxa de vitória fica em 69,6%).

**X.3 — para a palavra típica, não para a pior palavra.** O alinhado ganha em
**6/6** medições na mediana (1,3× a 2,8×), na dispersão (0,25× a 0,60×) e na taxa
de vitória (67,9% a 73,7%, todas acima de 65%). **Não** ganha na cauda fora de sala
silenciosa: razão de p90 0,45/0,49 em `peca-03`, mas 1,02/1,36 em `peca-01`
e 0,96/0,84 em `peca-09`.

**Por que não é *"adotar na legenda"* já:** o critério da SPEC-04 §7.12 para essa
frase exige taxa de vitória ≥ 65% **e** p90 do alinhado ≤ 80% do p90 do ASR **nas
3 produções**. A taxa de vitória passa em 6/6; o p90 passa em **1 de 3** produções.

**Por que não é *"não adotar"*:** o ganho de mediana e de dispersão é consistente
em 6/6 medições, contra duas referências independentes, com cinco controles
verdes. A medição preliminar da spec (52% de vitória, §3.1) **não se confirmou** —
com a régua não circular e o `--star` ligado, a vitória é de 67,9% a 73,7%.

**O que falta para virar *"adotar na legenda"***, e é trabalho de outra spec:
uma régua de cauda que decida no café e na locução contínua (hoje ela não decide,
§5.4), e o QC de sincronia de legenda que **não existe** neste repo — nenhum QC
daqui mede sincronia: `qc-cor.py` mede cor, `flicker-scan.py` mede luminância,
`qc-fonemas.py` mede borda de corte.

🔴 **A migração do `captions.json` NÃO acontece nesta spec** (SPEC-04 §9.1), e não
por causa do número acima: `createTikTokStyleCaptions` agrupa através de buraco, e
a legenda tem que sair das palavras da EDL do **bruto**, não do montado. Um
`alignment.json` do bruto entra nesse mapeamento, não no lugar dele.

---

## 10. Procedência

- **Mecanismo** (alinhamento forçado como estágio separado de tempo): a tese do
  ref-A, `tools/referencias/ref-A/helpers/transcribe.py:1-30` e `:112-125`.
  **Nenhuma linha de código portada.**
- **O contraexemplo arquitetural**: `transcribe.py:62-75` trava device em
  CPU/int8 em Apple Silicon por causa do CTranslate2 (que nós não usamos) e
  `transcribe.py:109` não tem gancho de vocabulário nenhum. As duas consequências
  do acoplamento, e a razão de **separar** em vez de copiar.
- **A cautela de não perder palavra**: `transcribe.py:196-201` descarta a palavra
  com um `continue`. Aqui o invariante é duro — `len(words) ==
  len(transcript.words)`, verificado com `assert`, e o script morre se não bater.
- **`MMS_FA`** vem do `torchaudio` (BSD-2-Clause, Meta/PyTorch); os pesos são do
  projeto MMS da Meta, **baixados em runtime**, não redistribuídos por nós.
- **Nosso**: a decisão de manter o Deepgram no texto e o motivo dela; a política
  de `end_ctc`; o desenho da régua não circular e os cinco controles; o chunking
  por gap de palavra; e todas as medições deste arquivo.
