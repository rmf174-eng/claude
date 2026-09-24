---
name: transcribe
description: Transcreve vídeo ou áudio via Deepgram, gerando transcript com timestamps por palavra e por utterance. Use quando precisar transcrever um vídeo baixado, um arquivo de áudio, ou como etapa 2 do pipeline de benchmarking (depois do video-download, antes do content-analysis).
---

# transcribe

Bloco 2 do pipeline: **mídia → `transcript.json` + `transcript.md`**.

## Como executar

```bash
# recebe o dir do post (usa <dir>/video.mp4, grava no próprio dir):
.claude/skills/transcribe/scripts/transcribe.sh data/adhoc/instagram-ABC123/

# ou um arquivo direto:
.claude/skills/transcribe/scripts/transcribe.sh caminho/video.mp4 [outdir]
```

Requer `DEEPGRAM_API_KEY`. Configure uma vez com
`python3 "$PWD/tools/pacote/chaves.py" --pedir DEEPGRAM_API_KEY`; o transcritor resolve
primeiro o ambiente e depois `$ILHA_HOME/.env`, sem `source` manual e sem
imprimir o valor. Custo ~US$0,005/min.

## Contrato de saída

```
<outdir>/
├── audio.mp3        # mono 16kHz (gerado se input era vídeo)
├── transcript.json  # resposta bruta Deepgram: palavras + timestamps + confiança + utterances
└── transcript.md    # legível: texto completo + utterances [mm:ss–mm:ss]
```

- `transcript.json` → `.results.channels[0].alternatives[0].words[]` tem cada palavra com `start`/`end` em segundos — use pra mapear momentos exatos do vídeo.
- `.results.utterances[]` tem os blocos semânticos — granularidade ideal pra análise de beats.
- Idempotente: reusa `audio.mp3` se já existir.
- `metadata.benchmark_transcribe` (contrato `benchmark.transcribe/v1`) guarda o que
  o **engine declarou** por parte, as costuras e o veredito da verificação. É o par
  "declarado pelo engine × medido no arquivo" que impede a checagem de virar
  circular. **Aditivo e retrocompatível**: `metadata.duration` mantém significado e
  valor (duração real do arquivo), `metadata._partes` continua sendo escrito, e
  `words[]`/`paragraphs`/`utterances` não mudam.

## ⚠️ Áudio longo: o Deepgram trunca sem avisar

**Medido em 2026-08-05.** Um mp3 de **2h00m40s (7.240s)**, íntegro — decodifica
inteiro sem um erro e tem áudio até os 116 min — foi aceito, respondeu **200**, e
voltou com a transcrição de **apenas 62 minutos**. O `metadata.duration` do
transcript dizia `3726`. Nada no retorno indica falha.

**E é intermitente.** `data/adhoc/aula-longa-01` (8.181s, 2h16) passou completo
em passe único, 17.230 palavras. Um arquivo maior que o que truncou passou inteiro.
É por isso que a proteção precisa ser **automática**: "olhar o número quando
lembrar" não funciona contra um defeito que só aparece às vezes.

```bash
.claude/skills/transcribe/scripts/transcribe-longo.sh <dir> [--parte 3000] [--overlap 30]
```

Mesmo contrato de saída do `transcribe.sh` (`transcript.json`/`.md`), mais o bloco
`metadata.benchmark_transcribe` descrito abaixo.

### O que o script faz, e por que cada parte é assim

| passo | por quê |
|---|---|
| fatia em partes de `--parte` **com `--overlap` segundos de sobra** | a sobra é o que dá margem para escolher a emenda num silêncio, em vez de cortar onde calhar |
| cacheia cada parte em `<outdir>/.partes/pN/` | uma call de 2h que falha na parte 3 de 3 evaporava ≈US$0,40 de API com o `mktemp` + `trap rm -rf` antigos. Parte já transcrita é pulada |
| costura em **vale de silêncio** (`remontar.py`) | ver abaixo |
| verifica o resultado (`verificar-transcricao.py`) | ver a seção seguinte |

`--parte 3000` e não 3600: **3.600s está do lado errado do único truncamento que
medimos** (o retorno veio com 3.726s). 3.000s é o valor que passou completo no
caso medido.

Os três parâmetros de operação também saem por ambiente, que é o gancho por onde o
perfil de peça os preenche sem que nenhum script conheça o conceito de perfil:
`BENCH_TRANSCRIBE_PARTE`, `BENCH_TRANSCRIBE_OVERLAP`, `BENCH_TRANSCRIBE_LACUNA_MAX`.

### Por que a costura é por TEMPO e não por texto

O script antigo fatiava em `i*PARTE` sem overlap e o merge era concatenação pura
(`words.extend(...)`). A fronteira caía no meio do que estivesse acontecendo —
inclusive no meio de uma palavra, que ia partida para dois requests diferentes.
Assinatura medida em `data/adhoc/aula-longa-02`: a última palavra de cada parte
tem `end` **3000,835s e 6001,050s em chunks de 3.000,0s** — o engine esticando a
palavra para além do fim do arquivo que recebeu.

A correção **não** é alinhar as strings da zona de overlap. Isso parece a solução
óbvia e é a armadilha que este repo já pagou: comparar transcrição com transcrição
dá falso positivo em toda gagueira, repetição e estrangeirismo (rodada 4 do
omni-insert — o `qc-fala.py` teve que ser reescrito por isso, "transcrição não é
verdade acústica"). Medido agora: numa janela de 400s do `dia02`, o remontado tem
**18 trigramas repetidos, exatamente os mesmos 18 da fonte** — repetição natural da
fala, que qualquer deduplicador por texto teria comido.

O que o `remontar.py` faz é escolher um instante `T` que cai **no silêncio**. Aí o
corte é trivialmente exato: nenhuma palavra atravessa `T`, logo não há o que
deduplicar nem o que perder.

```
janela de busca = [b + 3s, b + overlap - 3s]        b = início da parte seguinte
1. vale acústico mais LONGO da janela                 → metodo = "vale"
2. senão, maior buraco que seja buraco NOS DOIS lados  → metodo = "gap-asr"
3. senão, o meio da zona de overlap                    → metodo = "meio", suspeita
```

O piso de silêncio é **percentil, nunca número fixo** (`envelope.py`, cópia adaptada
do nosso `edit-video/scripts/bordas.py:27-38` e `:123-126`). Piso absoluto pressupõe
sala silenciosa: no bruto gravado num café o piso real das pausas é **−44 dB** contra
o default de −52, e o gate absoluto lê ruído de sala como fala em 23 de 23 segmentos.

**Palavra nunca desaparece.** Se `T` cair sobre uma palavra (só acontece nos métodos
`gap-asr`/`meio`), ela fica com o lado cujo chunk a contém inteira e o corte do outro
lado anda para o fim dela. Medido: forçando o fallback `metodo="meio"`, o resultado
tem **as mesmas 808 palavras** e similaridade **1,0** contra o caminho `vale`.

⚠️ Não use `-c copy` pra cortar as partes: o corte tem que ser exato, senão o offset
não bate e os timestamps derivam ao longo da peça.

⚠️ Os transcripts em `.partes/` ficam **sem offset**. O offset é aplicado na
remontagem, a cada execução — é isso que torna `--remontar` repetível de graça
(aplicar offset in-place duas vezes dobraria o deslocamento).

```bash
# refaz só a costura, a partir do cache, sem tocar na API:
.claude/skills/transcribe/scripts/transcribe-longo.sh <dir> --remontar
```

## A verificação — e por que a antiga nunca acusou nada

🔴 **A checagem que existia aqui era circular.** O `transcribe-longo.sh` gravava o
ffprobe do arquivo dentro de `metadata.duration` e depois "conferia"
`metadata.duration` contra o mesmo ffprobe. A conta era `abs(x-x)/x < 0.02`: sempre
0, sempre OK. A cópia dela no ingest de call — o consumidor
mais crítico, calls de 2h, exatamente o caminho longo — tinha o mesmo defeito.

Impressão digital, medida em **172 transcripts** do repo com áudio ao lado:
`ffprobe − metadata.duration` fica entre **−0,105s e −0,045s** em todos (o engine
declara um pouco a mais, padding do mp3). O **único** com delta exatamente
**+0,000s** é `data/adhoc/aula-longa-02` — o único produzido pelo
`transcribe-longo.sh`. O zero perfeito é a assinatura da sobrescrita.

```bash
python3 .claude/skills/transcribe/scripts/verificar-transcricao.py <dir|transcript.json> \
    [--audio PATH] [--rapido] [--estrito] [--nao-gravar] \
    [--tolerancia-s 1.0] [--lacuna-max 20] [--retrocesso-max-s 1.0] [--json]
```

Quatro checagens, nenhuma circular. A referência independente é o **áudio**, não o
número que o engine declarou:

| | o que mede | reprova quando | medido no corpus |
|---|---|---|---|
| **C1** | ffprobe do chunk × duração **declarada pelo engine** para aquele chunk | delta `> --tolerancia-s` | maior \|delta\| = **0,105s** contra tolerância de 1,0s (**9,5×** de margem), **0 reprovados em 172** |
| **C2** | regiões de fala do envelope × palavras do transcript | maior região de fala sem nenhuma palavra `> --lacuna-max` | `dia01` 1,4s · `dia02` 2,6s · VSL com trilha 0,0s — e **179,2s** no `dia02` truncado em 3.726s |
| **C3** | cada `T` de costura caiu em silêncio ≥ 0,20s e nenhuma palavra a atravessa | aviso; erro com `--estrito` | — |
| **C4** | `words[i].start >= words[i-1].start` | maior retrocesso `> --retrocesso-max-s` | ver a nota abaixo |

**C1 e C2 são independentes de propósito.** C1 pega o truncamento que o engine
confessa no `metadata`; C2 pega o que ele não confessa — bloco de áudio pulado no
meio, parte que voltou vazia, e também o truncamento. ⚠️ **Nunca "calibre" C2 pelo
que C1 já aprovou**: um detector que seleciona por limiar nunca converge a zero, e
C2 existe justamente para ser a referência independente de C1. Se alguém amarrar os
dois, a proteção morre.

⚠️ **C4 e os 8 retrocessos do corpus (medido em 2026-08-08).** O corpus **não** tem
0 retrocessos: tem **8 em 171 arquivos**, e são de duas naturezas. Seis são micro
(0,005 – 0,165s), uma palavra que o `smart_format` sobrepõe à seguinte. Dois são
grandes — **6,960s** e **10,400s** — e são palavra **solta** com timestamp absurdo
(`'em'` a 99,24s no meio de uma corrida a 88,6s). Todos em transcript de **passe
único**, nenhum passou por emenda. Por isso o limiar do C4 é de **magnitude**, não
de contagem: o defeito que ele existe para pegar (parte emendada fora de ordem,
offset não aplicado) devolve um retrocesso da ordem do overlap. O default de 1,0s
fica 6× acima do maior micro-glitch e 30× abaixo do overlap default. Reprovar
"qualquer retrocesso" faria a checagem acusar 4,7% do corpus, e ruído é o que faz
gente exportar `BENCH_TRANSCRIBE_SEM_VERIFICAR=1` e matar a proteção inteira.

⚠️ **Falso positivo do C2 em música, aplauso ou ruído contínuo sem fala.** A VSL com
trilha (`pg-f100kd-vimeo`) dá lacuna máxima de 0,0s, então o default de 20s aguenta.
Mas peça com bloco musical longo (abertura de VSL, vinheta) vai acusar. É para isso
que `--lacuna-max` existe, e é por isso que C2 **reporta o intervalo** em
`c2_lacuna_em`: o operador confere ouvindo aquele trecho, **não desliga a checagem**.

**Modos.** `--rapido` roda só C1 e C4 e não decodifica áudio — é o que o
`transcribe.sh` usa no atalho de idempotência. Sem `--rapido`, roda as quatro.
Transcript antigo, sem o bloco `benchmark_transcribe`, roda em **modo legado**: C1
compara `metadata.duration` × ffprobe, que é a checagem correta no caminho de passe
único, e o relatório traz `"legado": true`.

**Exit**: `0` ok (pode ter avisos) · `1` falha dura (C1/C2/C4, ou C3 com `--estrito`)
· `2` erro de uso.

🔴 **Mudança de comportamento:** o `transcribe.sh` passou a chamar o verificador no
fim e no atalho de idempotência, e o `transcribe-longo.sh` no arquivo final. Um
pipeline que hoje segue com transcrição truncada passa a **parar com exit 1**. É o
objetivo. Escape: `BENCH_TRANSCRIBE_SEM_VERIFICAR=1` (o verificador decodifica o
áudio, e há chamada em lote onde isso pesa).

## Dois derivados que o `.md` não entrega

O `transcript.md` é texto corrido. Serve pra ler e pra `content-analysis`, mas **não serve
pra decupar timeline** (em que segundo entra a oferta, quanto dura o bloco de prova, onde o
preço cai). Dois scripts cobrem isso, ambos offline e sem custo de API:

### `timestamped.py` — fala com timestamp

```bash
python3 .claude/skills/transcribe/scripts/timestamped.py <dir-ou-transcript.json> \
  [--paragrafos|--utterances|--silencio [S]] [--sem-pontuacao] [--precisao 1|2] [--janela=30]
```

**Dois modos, e eles servem a leitores diferentes.**

**1. Parágrafo (default)** — gera `transcript-ts.md` com blocos
`**[MM:SS–MM:SS]** texto`. Em peça longa (VSL de 25–40 min) use `--janela=30` pra
agrupar em blocos de ~30 s: sem isso são 300+ parágrafos e o agente que for ler
perde a estrutura no ruído. É o modo de **decupar** — onde entra a oferta, onde
cai o preço.

**2. `--silencio [S]` — a view de leitura por FRASE (SPEC-27)**. Quebra em
`gap ≥ S` **OU pontuação final (.?!)** **OU** troca de falante, e imprime
`[000.00-004.09] texto` com resolução decimal. É o modo de **escolher take, achar
o gancho e propor janela**.

`S` omitido → `ritmo.gap_min` do `perfil.json` que estiver ao lado da produção →
`FALLBACK 0.35` com aviso no stderr. O script lê o `perfil.json` como arquivo e
**não importa nada de `edit-video/`** — `transcribe` continua sendo bloco
independente, usável em benchmark de terceiro sem perfil nenhum.

📏 **A unidade é 4,1–6,0 s por bloco**, medida em 7 peças de 4 formatos (reels
montado, VSL montada, take de café, entrevista, aula de 2 h 16), contra
**18,0–32,0 s** do parágrafo do Deepgram nas mesmas 7. Um bloco de 4 s é candidato
a corte; um de 27 s não é candidato a nada. **Essa é a razão de o modo existir — e
é a única.**

🔴 **Ele NÃO economiza token: custa 1,16× a 1,42× MAIS** que o `transcript-ts.md`
de hoje (medido em 5 peças). Os "1/10 dos tokens" que a fonte original promete
são contra o **JSON cru**, e contra o cru o modo parágrafo já entrega 40× a 56×. O
ganho anunciado nós já tínhamos, por outro caminho.

⚠️ **A fronteira de frase é CANDIDATA, não ponto de corte** — e o cabeçalho do
arquivo gerado carrega essa linha para quem só lê o artefato. Medido: 86 % dos gaps
entre palavras consecutivas do Deepgram são exatamente **0,000 s** (ele estica a
última palavra para dentro do silêncio); contra o envelope RMS de
`take-conteudo.MOV` o recall é de **70 %** (14 gaps ≥0,5 s no transcript para 20
silêncios acústicos ≥0,5 s) e o início da frase cai em média **+98 ms** para dentro
do silêncio real. Quem acha borda de corte é o `bordas.py`, no envelope. Baixar o
limiar não compra recall: de 0,50 para 0,25 s o recall vai de 70 % para 85 % e o
que entra são respiros de 0,3 s, não as pausas perdidas.

**Por que gap OU pontuação, e não só gap** (que é o critério do ref-A): no MONTADO
o `bordas.py` já tirou o ar, e só-gap devolve **1 unidade para 189 s de VSL** e
**1 para os 66 s da `peca-03`**. Com pontuação: 32 e 15. A pontuação é o sinal que
o nosso ASR entrega e o Scribe (ElevenLabs) não — lá o silêncio vem explícito em
entradas `spacing`. `--sem-pontuacao` reproduz o critério literal deles, para
comparação e debug. E a pontuação do Deepgram é **aposta do modelo, não medição**:
por isso é desligável e por isso o cabeçalho declara quantas quebras vieram de cada
critério.

**Retrocompatível por construção**: sem `--silencio`, o `transcript-ts.md` sai
**byte a byte** igual ao de antes — verificado em **796 comparações de md5** (199
`transcript.json` do acervo de medição × 4 modos legados), **0 divergências**.
O nome do arquivo de saída também não muda: mudá-lo quebraria o `ingest-call.sh` da
ingest de call e a decupagem de VSL, que leem esse caminho.

**Teste**: `python3 .claude/skills/transcribe/scripts/tests/test_timestamped.py`
(autocontido, material sintético; congela a saída legada como golden e planta o
defeito de 1 caractere que o golden tem que acusar).

### `diff-versoes.py` — o que mudou entre duas versões da mesma peça

```bash
python3 .claude/skills/transcribe/scripts/diff-versoes.py <dirA> <dirB> \
  --palavras --min-bloco 10
```

Quando o anunciante mantém duas versões no ar (A/B vivo, ou a nova no tráfego pago e a velha
na bio), o diff é a evidência mais limpa do que ele considera resolvido e do que acha que é o
gargalo.

⚠️ **Use sempre `--palavras`.** O modo sentença (default) tem um falso positivo grave: quando
o ASR quebra a MESMA fala em pontos diferentes nas duas versões, o diff acusa "trocado" sem
que uma palavra tenha mudado. Medido no ref-G: 65,5% de similaridade por sentença
contra **92,6% por palavra** — a leitura por sentença sugeria reescrita geral, quando a
divergência real estava toda nos primeiros 105 segundos.

Precedente: `intelligence/vsl-metodo-executado.md` §4 — três operações diferentes construindo
a VSL como lead removível + corpo congelado, descoberto por esse diff.

## Engine e idioma

- Default: `nova-3` + `language=multi` — lida com PT, EN e code-switching (comum em conteúdo de creator).
- ⚠️ **Estrangeirismo/nome próprio/marca some do transcript** (caso "peca-04", 2026-07-22: a palavra virou buraco e travou 3 iterações de corte). Se o roteiro tem termo assim, passar **`&keyterm=<termo>`** na query (nova-3; repetível pra vários termos) — com o boost o Deepgram transcreve certinho. Sinal de alerta: burst de energia (RMS) sem palavra correspondente nas words = palavra não reconhecida, não ruído.
- Forçar português puro: `BENCH_DG_MODEL=nova-2 BENCH_DG_LANG=pt-BR`.
- Trocar de engine (ex.: OpenAI Whisper API como fallback se a Deepgram cair): este bloco é o único lugar que precisa mudar — o contrato de saída (`transcript.json`/`.md`) é o que os blocos seguintes consomem. Mantenha os campos `words[].start/end` e o formato do `.md`.

## Composição

Próximo bloco típico: `content-analysis` (recebe `transcript.md` + `meta.json` e gera a análise de gancho/estrutura/roteiro).

## Alinhamento forçado local (tempos) — `alinhar.py`

O Deepgram entrega o **texto** certo em cima de uma **grade de tempo de 80 ms**.
Medido em 4 transcripts deste repo: 94–97% dos limites distintos são múltiplos
exatos de 80 ms, e a menor duração de palavra é exatamente 80 ms. **80 ms = 2,4
frames a 30 fps** — uma palavra pode acender na legenda dois frames longe de onde
a boca fala. E o erro não é simétrico: a energia da próxima palavra já sobe 30 a
260 ms antes do `start` informado (`edit-video/SKILL.md:73`).

`alinhar.py` é o engine de **tempo**, e só isso. Ele **não transcreve**: recebe o
áudio e as palavras que o Deepgram já achou, e mede contra o próprio áudio onde
cada uma começa — alinhamento forçado CTC com `torchaudio.pipelines.MMS_FA`
(multilíngue, roda em MPS). Stride medido: **20,0 ms**, quatro vezes mais fino.

**O `transcript.json` não é reescrito.** O `alignment.json` nasce ao lado dele.

```bash
# uma vez (venv ~575 MB + pesos 1,26 GB; 2ª execução sai em ~1,3 s)
.claude/skills/transcribe/scripts/bootstrap-aligner.sh --baixar-modelo

.claude/skills/transcribe/scripts/alinhar.py <dir-da-produção>/
# stdout = caminho do alignment.json · stderr = resumo · idempotente (--force refaz)
```

Contrato `benchmark.alignment/v1`, um item por palavra, na mesma ordem e no mesmo
número do `transcript.json`:

```jsonc
{"i": 0, "word": "cá", "token": "ca",
 "start": 20.180,      // ALINHADO — segundos, float. Nunca frames.
 "end_ctc": 20.240,    // ⚠️ fim do span CTC, NÃO a soltura acústica
 "score": 0.91,        // 0-1 — É O PORTÃO. Ver abaixo.
 "fonte": "align"}     // "align" | "asr" (sem token: herdou fronteira do vizinho)
```

Invariantes garantidos por `assert` (o script morre se não baterem): nenhuma
palavra some (`len == len`), `words[i].i == i`, `start` monotônico, `end_ctc >=
start`, e toda palavra sem token tem `fonte == "asr"`.

### 🔴 As três regras de uso

1. **`end_ctc` NÃO é borda de corte.** Medido, n=261: ele vem **141 ms antes** do
   `end` do Deepgram, e isso não é erro — CTC marca o último frame em que o token
   ainda é emitido, não a soltura do som. Usá-lo como corte decepa a cauda de toda
   frase. Borda de corte continua sendo `edit-video/scripts/bordas.py`
   (`decay_relativo()` existe exatamente para achar a soltura).
   Legenda karaokê usa o `start` alinhado e estende a palavra até o `start` da próxima.
2. **`score` é o portão.** Palavra com score baixo não tem posição confiável.
   Medido: com `--chunk 25`, a palavra "Comente" escorregou **4,1 s** para trás e
   o score caiu de 0,944 para **0,014**. Filtrando `score >= 0,30`, o erro máximo
   entre chunkings volta de 1.215 ms para 28 ms.
3. **`--star` é o default, e mexer nele custa caro.** O `--pad` traz áudio que não
   está na lista de tokens; sem o `<star>` para absorvê-lo o CTC empurra a
   fronteira para dentro do pad. Medido: `--sem-star --pad 3.0` leva o erro máximo
   entre chunkings a **1.542 ms**, contra 36,9 ms no default.

### A régua, e por que ela existe

```bash
.claude/skills/transcribe/scripts/medir-alinhamento.py <dir> [--ref envelope|fonemas|edl|todas]
```

Responde *"o alinhador erra menos que o ASR nesta fronteira, e por quanto?"*,
offline e sem custo de API. Imprime, para os **dois** candidatos e em cada
referência: **n · mediana |erro| · p90 |erro| · viés · dispersão · taxa de
vitória**. Nunca "% dentro de região" — é o número que o ref-A publicou e que não
mede nada (medir um detector contra outro detector seu mede concordância, não
acurácia; e "dentro de uma região" é teste binário de contenção).

Cinco controles rodam sempre e todos imprimem `n`. Dois deles existem só para
pegar régua circular: **CONTROLE-D** desloca o **áudio** e exige que a
*referência* ande junto; **CONTROLE-E** cruza cada candidato com a referência de
outra fronteira e exige que o erro exploda. Uma régua que devolvesse o próprio
candidato passaria nos outros três e reprovaria nesses dois.

**Estado de adoção: `alinhar.py` está disponível e não está ligado em nada.**
Nenhum consumidor deste repo lê `alignment.json` hoje — o `captions.json`
continua saindo do `transcript.json` cru. O veredito medido é **"adotar só onde
X"**, com o X, os números das 3 produções × 2 referências e o que falta para
mudar isso em **`references/alinhamento.md`**.
