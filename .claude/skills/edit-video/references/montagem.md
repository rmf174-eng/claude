# Montagem — etapas 0 a 2

> O corpo das etapas **0 (o bruto é mesmo um take?)**, **1 (ingestão)** e **2 (montagem)**, mais o J-cut, o contrato da EDL v2 com a `timeline_real` e a cauda do segmento. O núcleo diz o que rodar e qual é a régua; este arquivo diz **por que a régua é essa e o que já deu errado**.

---

### 0. 🚨 O bruto é mesmo UM TAKE? (rodar ANTES de qualquer coisa)

`scripts/cortes-do-bruto.py <arquivo.mp4>` — **toda esta skill assume take contínuo**, e essa premissa quebrou em 2026-07-27: a creator-2 entregou o vídeo **já montado por ela, com 20 jump cuts** (um no fim de cada frase).

✅ **Bruto já montado E sem gordura = pule a montagem inteira** (caso `peca-05`, 2026-07-29): 5 cortes dela, todos em fronteira de frase, e **um único** word-gap ≥0,30s em 134 palavras. Sem EDL, sem `montar.sh` — e com isso somem *por construção* a deriva de A/V, a emenda suja e o segmento órfão (o QC mediu lag **0,0 ms sem deriva**). Antes de assumir que há corte a fazer, **varra os word-gaps**: se não há gordura, o trabalho é só camada gráfica + áudio + cor.
⚠️ **O `fps` do bruto não é o da entrega.** O `cortes-do-bruto.py` tinha `FPS = 30.0` fixo; num bruto de **60fps** ele devolvia todo corte no **dobro** do tempo (o último saía em "50,000s" num vídeo de 46,8s). Corrigido (`fps_de()` lê o fps real); a distância de "plano curto" continua medida na timeline de **entrega** (30fps), que é onde o flash é visto. O defeito que isso produziu: ela tinha um corte em 5,200 e eu pus o meu em 5,310, sobrando **3 frames** de um plano intermediário — 110 ms de imagem que entra e sai, que o olho lê como flash. **Nenhum QC de áudio pega**, porque o áudio está perfeito.

Se o bruto tiver cortes:
- **Cada corte dele é uma emenda que você não fez** — e pode já vir com resquício sonoro (o corte da creator-2 deixou um transiente surdo de 24 ms que o creator-1 ouviu e que **não era nosso**: provado comparando o montado com o bruto amostra a amostra, diferença −72,8 dB).
- 🔴 **Corte seu a menos de ~8 frames de um corte dele = flash.** A saída quase sempre é **alinhar o seu ao dele** ou desistir do seu. Aqui reverter o corte de uma muleta custou 0,6 s e resolveu.
- ✅ **Corte do bruto é o melhor lugar pra trocar o enquadramento** (`zoom`/`cx`/`cy`): a troca cai num corte que já existe, então sai de graça.
- Segmentos partidos num corte do bruto ficam **contíguos** (`fadeOut`/`fadeIn` = 0 no `audio-exato.py`): o áudio atravessa sem emenda.
- ⚠️ O `cortes-do-bruto.py` roda também contra a EDL (`<dir-producao>`) e acusa PLANO-CURTO.

### 1. Ingestão
- **Pedir o ROTEIRO** (ou pelo menos a frase do gancho) se não veio com o pedido — o roteiro é a fonte de verdade da fala; o transcript é aproximação. A saga peca-04: 3 iterações de corte brigando com um "de solto" que era "de peca-04" — o Deepgram NÃO transcreve estrangeirismo/nome próprio e a palavra vira buraco no transcript.
- Criar `creators/<nome>/producao/<slug>/` e mover/copiar brutos pra `input/` local.
- `transcribe` cada bruto (Deepgram word-level) → `take-A/`, `take-B/`...
- ⚠️ **Burst de energia sem palavra no transcript = palavra não reconhecida, não ruído**: antes de descartar trechos "sem fala", conferir o envelope RMS contra as words — se tem energia de fala e o ASR pulou, é estrangeirismo/nome/marca. Casar com o roteiro e incluir na EDL (e injetar o token manualmente no captions.json).

### 2. Montagem (bruto → v1-montado.mp4)
A decisão editorial de corte, registrada em `edl.json` — desde 2026-08-08 o envelope **`benchmark.edl/v2`** (`{schema, perfil, segments, timeline_real}`), que lê EDL antiga em array sem conversão. Contrato inteiro em **`references/contrato-edl.md`**; nenhum script abre `edl.json` na mão, todos passam por `scripts/edl_io.py`:
- ⚠️ **CHECK DE GANCHO 0–5s (obrigatório, ANTES de montar)**: ler as primeiras frases do transcript e perguntar "os 3 primeiros segundos fecham uma tensão específica?". Saudação, warm-up, frase de série ("vem cá, deixa eu te contar uma coisa"), respiro ou contexto sem tensão na abertura = **ALERTA ao creator-1 + proposta de corte** pra o vídeo abrir direto na frase-gancho. Validado por teste A/B da própria creator-2 no ovo de Páscoa (2026-07-24, prints em `creators/creator-2/producao/ovo-de-pascoa/teste-ab/`): a versão sem os ~3s de "vem cá..." fez **1.468 views/17s de tempo médio** vs **181 views/7s e 68,8% de skip** da versão original. O material cortado pode sobreviver como transição pós-gancho se for identidade da série — mas nunca como abertura.
- **Escolher takes**: em repetição, o retake é o intencional (heurística validada); cortar rejeições faladas ("não", "pera") e gagos (corte por palavra na 2ª ocorrência).
- **Cortar respiros por word-gap** (pausas ≥0.35–0.5s entre palavras), NÃO por silencedetect (falha com música).
- **Pads: vêm do PERFIL DE PEÇA, não da memória de quem chama.** Até 2026-08-08 os pads eram digitados na mão em cada chamada do `bordas.py`, e o default do código (0,02/0,06) discordava do default da doc (0,12/0,20) — quem esquecesse a flag pegava o ritmo da creator-2 sem saber. Agora: `perfil.py resolver <dir> --perfil reels --creator creator-2` grava `<dir>/perfil.json` e o `bordas.py` lê dali. As flags de CLI continuam válidas e **vencem** o perfil.
  - Ritmos nomeados em `perfis/_ritmos.json`, referenciáveis por `"ritmo": "colado"`: **`normal`** 0,12/0,20 (o default do perfil `reels`) · **`dinamico`** 0,02/0,06 (a creator-2 — agora em `creators/creator-2/perfil-overrides.json`) · **`colado`** 0,02/0,02 `--cap 0.25 --rel 10` (modelado do ref-D, 2026-07-25).
  - ⚠️ **Produção sem `perfil.json` continua com 0,02/0,06**, o default histórico do código. É o `FALLBACK_REELS` do `perfil.py`, e ele é uma cópia congelada do presente de propósito: se o fallback adotasse o `normal` da doc, toda produção antiga remontada mudaria de ritmo em silêncio.
- 🆕 **`--cap` e `--rel` no `bordas.py`** (nasceram da modelagem do ref-D, 2026-07-25):
  - `--cap S` (default 0.25) — **teto** da correção acústica. A busca no envelope existe pra REFINAR o ASR, não pra passear: sem teto o decay caminhava +0,46s atrás de cauda de reverb e a EDL saía **38% mais gorda** que a do editor de referência.
  - `--rel N` — corta a cauda N dB abaixo do **pico do corpo da palavra** (ritmo "colado"). O piso absoluto nunca corta a soltura de uma vogal, que fica ~20dB acima do ruído de sala. Calibrado em **10 dB**. ⚠️ Meça o pico nos 0,6s ANTES do end do ASR — medi-lo dentro da própria cauda faz o corte ESTICAR (testado e reprovado).
  - ⚠️ Com `--rel`, o `audit-emendas.py` vai acusar **CLIP-FIM em quase todo segmento** — é por construção (você está cortando na soltura de propósito). Nesse modo a régua é o **ASR do montado** (procurar sílaba fantasma), não o flag.
- 🐛 **Sílaba fantasma no início do segmento** (achado 2026-07-25): quando o `onset` não encontra silêncio dentro da janela de busca, ele **não** deve estender — "sem silêncio antes da frase" quase sempre significa que a fala anterior (o take rejeitado, a gagueira) está encostada ali. A versão antiga devolvia a extensão MÁXIMA e engolia a cauda do descarte: o transcript da montagem saiu *"porque é **o porque é** o melhor hambúrguer"*. Corrigido no `bordas.py`.
🔴 **OS TRÊS SCRIPTS DE ENQUADRAMENTO NÃO EMBARCAM — e nunca embarcaram.**
(Achado A-6 do teste de campo da v0.12, 2026-08-12; declarado em 2026-08-12 pela
SPEC-48/H48-6.) As notas desta seção citam `enquadrar.py --bruto`,
`folha-enquadramento.py` (dita "obrigatória") e `dividir-planos.py` (com "ordem
obrigatória"). **Nenhum dos três existe em `scripts/`** — nem no pacote, nem nesta
árvore. Eles eram scripts DE PRODUÇÃO, escritos dentro das pastas de duas peças de
2026-07 e nunca generalizados; o que sobrou deles é o conhecimento escrito aqui.

Medido: `find` pelos três nomes na árvore que embarca devolve **0 arquivos**; as
citações são 8, em 6 arquivos. Quem instalou a ilha e seguiu a receita ao pé da
letra bateu num `command not found` no meio da montagem.

O que continua VERDADE e é executável hoje:

- `zoom` / `cx` / `cy` **na linha da EDL** são lidos pelo `montar.sh` e recortam o
  bruto — o mecanismo de reenquadramento está no produto, inteiro. O que não
  existe é o script que MEDE a cabeça e ESCREVE esses números para você.
- partir uma janela longa em planos contíguos é **editar a EDL** (dois segmentos
  com o mesmo `src`, `end` de um igual ao `start` do outro). O `montar.sh` monta
  isso corretamente, e desde a SPEC-48 ele REPROVA a sobreposição que essa edição
  feita à mão costuma produzir.
- a folha de verificação é `previews-peca.py` + o still por plano: olhar a imagem
  continua obrigatório (RD-14), só não sai de um script com aquele nome.

⚠️ Enquanto os três não existirem, tudo nesta seção que diga "rode X" é HISTÓRIA
do método, não instrução. Está mantido porque o *porquê* de cada armadilha (medir
no bruto e não no recortado, clamp que transforma lixo em recorte válido, planos
irmãos com zoom diferente) é o que custou os defeitos — e isso vale mesmo quando
quem executa é uma pessoa editando o JSON.

- 🆕 **REENQUADRAMENTO por segmento** (`zoom` / `cx` / `cy` na linha da EDL, passa por `bordas.py` e é aplicado pelo `montar.sh`): recorta o BRUTO 4K e reescala pra 1080x1920 — punch-in real, sem perda de nitidez. **Alternar `zoom: 1.0` e `zoom: ~1.25` entre segmentos faz o jump cut LER como troca de plano** (gramática medida no ref-D: 6 planos em 23s alternando 1,00 ↔ 1,22–1,31). Para descobrir o zoom de uma referência: `reframe.py` da skill `model-edit` imprime o `{"zoom","cx","cy"}` pronto.
  🔴 **NUNCA meça o enquadramento sobre um vídeo que JÁ tem enquadramento aplicado.** Defeito entregue em 2026-07-27: na 2ª passada eu medi a posição do creator-3 no `v1-sdr` que já estava recortado — as coordenadas saíram no sistema do CROP e foram aplicadas de novo por cima. O `cx`/`cy` bateram no clamp (0,27 = metade da janela) e o recorte ficou preso no canto superior esquerdo, jogando ele pro **canto inferior direito, cortado**. Medir sempre no BRUTO, com a LUT aplicada na amostragem (`enquadrar.py --bruto`) — de quebra elimina a passada de montagem que só existia pra ter o que medir.
  🔴 **Clamp sem guarda transforma medição-lixo em recorte "válido", em silêncio.** O clamp existe pra impedir janela fora do quadro; quando a medição falha, ele entrega um enquadramento plausível e errado. Regra: se `cx`/`cy` **encostam no limite**, isso é sintoma de falha (pessoa falando não fica na borda) — rejeitar a medição e cair na MEDIANA dos beats que passaram, gritando qual foi rejeitado.
  🔴 **Janela longa não cabe num enquadramento só — parta em planos.** Nas versões COMPLETAS dos criativos do creator-3 as janelas nascem partidas nas pausas reais e chegam a **40s**; num take em que ele ANDA pela sala, nenhum recorte contém a cabeça dele por 40 segundos (a folha de verificação mostrou cabeça cortada em vários blocos). Abrir o zoom é a correção errada — deixa ele minúsculo o vídeo inteiro. O certo é o que o `peca-07` já fazia: **dividir o segmento em planos contíguos e enquadrar cada um** (`dividir-planos.py`, a partir de ~8s). Como os pedaços são contíguos no bruto, **o áudio é idêntico** e a EDL soma o mesmo em tempo contínuo. ⚠️ **Mas a legenda MUDA mesmo assim**: cada plano é renderizado com nº inteiro de frames, então mais planos = mais arredondamento, e o total anda alguns frames (medido: 129,267s → 129,400s ao ir de 6 pra 17 planos). Depois de dividir é obrigatório **refazer captions/cenas e re-renderizar o alpha** — o guarda de duração do `compor.sh` (|graphics − vídeo| < 0,05s) existe exatamente pra não deixar isso passar. De quebra, 40s de plano fixo viram troca de plano, que é melhor editorialmente. ⚠️ Ordem obrigatória: `bordas` → `dividir-planos` → `enquadrar --aplicar` → `montar` (rodar o bordas de novo reescreve a EDL e apaga a divisão). E planos irmãos precisam de zoom DIFERENTE (1,45 ↔ 1,62), senão a troca não lê e o corte vira defeito.
  🔴 **A folha de verificação amostra o `v1-sdr` COMO ELE É — nunca reaplique o crop nela.** O `v1-sdr` já sai enquadrado do `montar.sh`; recortar de novo na hora de conferir mostra a cabeça cortada em todo plano e inventa um defeito que não existe (aconteceu, e custou um ciclo de remontagem). É a mesma transformação dupla da medição, cometida na régua. E **miniatura engana nos dois sentidos** — confirmar em tamanho real antes de agir.
  🔴 **A folha de verificação de enquadramento é obrigatória e tem que ser refeita a cada mudança de método** — 3 instantes por plano, não 1. Eu tinha olhado uma folha; era a da versão ANTERIOR da medição, e nunca refiz depois de trocar o algoritmo. Virou script pra não depender de lembrar: `folha-enquadramento.py`.  → RD-14
  📚 **É um ESTILO do arsenal, não a nova regra** (decisão do creator-1, 2026-07-25). Três gramáticas de plano convivem — **fixa** (default histórico da creator-2: um enquadramento, jump cut assumido), **alternada** (esta) e **punch-in pontual** (um zoom num beat de ênfase). A escolha vira uma linha do `PLANO-EDICAO.md` ("gramática de plano: alternada 1,00/1,27") e é aprovada como qualquer decisão editorial. O que a regra de 2026-07-23 proíbe é **efeito improvisado fora do plano**, não a técnica.
  🆕 **`punch-pontual` + `tracking`: o zoom que segue o rosto.** O punch-in é a única gramática com margem para seguir alguém — `MotionKit.CameraSegue` com `z = 1` tem deslocamento máximo 0 e não move nada. Quando a galeria vem com o interruptor **`tracking` ligado**, a ordem é: `rastrear-rosto.py <dir>` (grava `track-rosto.json`, contrato `benchmark.track-rosto/v1`) e depois passar o track ao punch por `MotionKit.CameraSegue track=`. Com `tracking` desligado o punch é no CENTRO do quadro, e é exatamente aí que a cabeça de quem se move sai de enquadramento — o mesmo defeito que a folha de verificação acima pega. O detector existe desde a SPEC-28 e o dado morria no disco: nenhuma etapa, catálogo ou interruptor o oferecia até 2026-08-11.
- **Snap de janela**: incluir palavra que COMEÇA dentro da janela (senão corta palavra no meio — bug da iteração 2).
- 🆕 **Capítulo de YouTube se declara AQUI, no `janelas.json`** (SPEC-21): `"capitulo": "O que é X"` na janela que ABRE a seção. O campo atravessa o `bordas.py` sozinho (lista negra da SPEC-05) e chega à EDL; o `capitulos.py` o ancora em `timeline_real.segments[i].start_s`. Para capítulo que **não** cai em início de segmento — comum em longform, onde um segmento tem 40 s —, escreva `<dir>/capitulos.json` com `{"i_seg": 7, "src_t": 412.30, "titulo": "…"}`; as duas entradas se somam. Contrato em `references/contrato-publicacao.md`.
- 🆕 **A LEGENDA `.srt` SAI DAQUI TAMBÉM, e pela mesma razão.** `scripts/srt.py` lê as palavras do transcript do BRUTO (via `scripts/palavras.py`) e as posiciona pela `timeline_real` — nunca transcrevendo o montado, nunca somando `Σ(end−start)`. É a mesma conta que a `peca-10-27-07/legendas.py` fazia à mão, agora uma vez só na skill.
- ⚠️ **O start/end do ASR NÃO é verdade acústica — e erra pros DOIS lados.** Não escreva `edl.json` na mão a partir dos timestamps do Deepgram: monte `janelas.json` (`{src, asr_ini, asr_fim, beat, fala[, pre_extra, post_extra]}`) e rode **`scripts/bordas.py <dir>`**, que acha a borda real no envelope (RMS 10ms, piso −52dB) e aplica os pads do creator. Medido na produção peca-03: o ASR **atrasou o start em 0,13s** e cortar nele **decepava o "M" de "Mulher"** (o pior lugar possível — primeira palavra do gancho); e **atrasou o end em até 0,29s**, deixando silêncio na cauda de "telepatia"/"silêncio" — aparar isso tirou **3,0s de gordura sem tocar em nenhuma palavra**. O Deepgram também quantiza timestamps em **80ms**: nunca trate um delta de ±0,08s como sinal.
- 🔴 🆕 **BRUTO GRAVADO EM LUGAR PÚBLICO: use `--floor auto`.** O piso default de −52 dB pressupõe sala silenciosa de casa. Medido na produção `peca-01` (2026-07-31, creator-2 e uma amiga num café): o piso das pausas reais é **−44 dB de mediana (p90 −37)**. Com o default o `decay` lê ruído ambiente como fala, nunca acha o fim da frase e devolve **o teto (`--cap`) em 23 de 23 segmentos** — 5,75s de sala colados no fim de cada frase, o oposto do ritmo "encostado" da creator; e o `onset` nunca acha silêncio, então a proteção do primeiro fonema **não roda**. Baixar o número na mão não resolve (com −34 ainda sobravam +0,45s em 6 segmentos: um respiro tardio já basta pro decay esticar). `--floor auto` usa o critério que os guardas de ataque/cauda já usavam, `piso_local` (percentil 15 num raio de 0,6s) + 10 dB, que acompanha a sala. Combinado com `--cap 0.15` a pausa audível mediana ficou em **50 ms**. ⚠️ **Meça o piso antes de montar** (RMS 10ms nas pausas do ASR): se a mediana estiver acima de −50 dB, o default está errado pra esse material.
- **Micro-fade de áudio 15ms** nas bordas de cada segmento (sem isso, corte encostado dá click) — já embutido no `audio-exato.py`, com a duração e o **modo** vindos de `ritmo.fade_borda_s` / `ritmo.fade_modo` do perfil. ⚠️ **`fade_modo: so-descontinuidade` é obrigatório em EDL de troca-de-plano**: com `por-segmento` (o FALLBACK histórico) uma borda contígua leva fade e vira **dip audível numa emenda que não existe** — foram 18 deles na VSL do produto-1. Com `jcut.json` presente, o plano grava `fade_in_s: 0` / `fade_out_s: 0` em cada borda contígua e essa decisão fica **auditável por junção**, não implícita num modo. Render da montagem: **`scripts/montar.sh <dir-producao>`** (lê `edl.json` e, se existir, `jcut.json`; idempotente por segmento).
- 🐛 ⚠️ **DERIVA DE A/V — o bug que existia em TODAS as montagens até 2026-07-25.** O `montar.sh` antigo dava a cada segmento sua própria trilha AAC e concatenava com `-c copy`: delay de encoder + quantização de frame (1024 amostras) **acumulam** ~13ms por emenda, e com 20 segmentos o áudio chegava **0,28s atrasado** no fim (prova visual na produção peca-03: lábios em 60,77s, som em 61,01s). O `NOTAS.md` da peca-04 registrava o sintoma como "a soma da EDL difere 0,1–0,2s do render (frame-snap)" — era isto, e não era inofensivo. **Corrigido**: os segmentos saem **sem áudio** (`-an`) e a trilha é montada depois por **`scripts/audio-exato.py`**, cortando do bruto exatamente `frames_do_segmento/30` (1600 amostras por frame). `soma_audio == soma_video` por construção. **Teste obrigatório se mexer na montagem**: vale de energia do áudio em cada emenda vs fronteira de frames do vídeo → ±3ms **sem tendência** ao longo do vídeo (antes: +0,04 na 1ª metade → +0,17 na 2ª).  → RD-3
  📌 **Onde o fix VIVE e onde ainda NÃO chegou** (escopo exato, auditado 2026-07-25): corrigido no script canônico desta skill (`scripts/montar.sh` + `scripts/audio-exato.py`) e na produção `peca-03/`. As **cópias locais anteriores continuam com o bug** — `creators/creator-2/producao/peca-04/montar.sh`, `creators/creator-1/producao/peca-08/montar-palestra.py`, `creators/creator-1/producao/peca-07/montar-palestra.py` (todas ainda `-c:a aac` por segmento + `concat -c copy`). Não foram migradas de propósito: as entregas delas já foram publicadas e remontar mudaria o arquivo aprovado. **Se for re-renderizar qualquer uma, rode o `montar.sh` da SKILL, não o `.sh` que está na pasta da produção.**  → RD-2
- 🆕 **FECHAMENTO gravado em outro dia/lugar** (aprendido no peca-07, 2026-07-26): ao emendar um take novo no fim de uma produção existente, três coisas que não aparecem numa montagem de take único:
  - **Medir loudness das DUAS pontas** (`loudnorm=print_format=json`). O fechamento gravado no carro veio a −26,77 LUFS contra −24,25 da palestra: 2,5 LUFS de queda, audível na virada. Casar por ganho antes do concat.
  - **Concat sempre DECODIFICADO** (`filter_complex concat=n=2:v=1:a=1`), nunca `-c copy` — é exatamente a porta de entrada da deriva de AAC.
  - **Janelas contíguas do mesmo take viram UMA janela.** Se você dividir em duas, o `decay` da primeira e o `onset` da segunda se sobrepõem (medido: fim 9,65 > início 9,21) e o áudio duplica na emenda.
- ⚠️ **Quando a próxima palavra ENCOSTA na última do segmento** (gap≈0, saga do gancho peca-04): se não há vale real no RMS (coarticulação — consoante sonora fundida na palavra anterior), **aceitar o corte com fade 40ms no ponto de fusão**: o resquício da consoante emenda no ataque do próximo segmento (melhor ainda se começa com o mesmo fonema). O ASR vai sempre "ouvir" a sílaba fantasma — a régua final é o ouvido do creator-1, não o Deepgram.
- ⚠️ **NÃO inserir trecho de outro take no MEIO de uma frase** (reprovado de ouvido na peca-04): a prosódia/melodia de takes diferentes não casa — soa como "erro de gravação" mesmo com a emenda tecnicamente limpa. Splice de retake só em fronteira de FRASE (jump cut entre frases é linguagem padrão de reels). Emendas testadas e reprovadas antes de chegar nisso: splice mid-sentence "falando|sobre isso", splice dentro da palavra "De", overlap/amix da cauda.
- 🐛🔴 **SEGMENTO ÓRFÃO — o bug mais perigoso da montagem, porque nenhum QC acusa.** O `montar.sh` grava o `.mp4` do segmento e SÓ DEPOIS o sidecar de procedência. Execução interrompida (Ctrl-C, kill, timeout) deixa `.mp4` sem sidecar — e a versão antiga do cache só comparava quando os dois existiam, então o segmento órfão era **reusado em silêncio com o corte da geração anterior**. Medido nos criativos do creator-3 (2026-07-27): o `c-completo` saiu **6,25s mais longo** que a soma da própria EDL. ⚠️ **E tudo fica verde**: a trilha é montada a partir dos frames REAIS dos segmentos, então o áudio sincroniza perfeitamente com o vídeo errado — deriva zero, emendas limpas, QC de A/V ok. **Corrigido** (`.mp4` sem sidecar é apagado), e virou conferência de rotina: **soma da EDL vs duração do render**, tolerância de ~1 frame por segmento. Faça essa conta sempre que uma montagem tiver sido interrompida.  → RD-4
- **Auditar TODAS as emendas**: `scripts/audit-emendas.py <dir-producao>` — testa se há **energia de fala real** depois do corte de fim (CLIP-FIM) ou antes do corte de início (CLIP-INICIO), vazamento da próxima palavra, e segmento sem palavras mas com energia (estrangeirismo não reconhecido → `keyterm` no Deepgram). ⚠️ A versão antiga media contra o `end` do ASR e acusava **16 de 20 segmentos** na produção peca-03 — todos falso-positivo. Se um flag sobrar, confirme no envelope antes de mexer: um corte que pega 20ms da rampa de uma fricativa (/s/ subindo de −63 a −44dB) é aceitável; um que pega o ataque de uma vogal não é.
- **Validar emenda crítica por ASR isolado**: transcrever SÓ o segmento (curl Deepgram) — se aparecer sílaba fantasma no fim, o corte tá sujo. Barato (~1s) e pega o que o RMS não mostra.
- 🆕 **`scripts/qc-emendas-asr.py <dir>` — isso, mas em TODAS as emendas de uma vez** (nasceu nos criativos do creator-3, 2026-07-27). Transcreve ±1,2s de cada corte e pergunta duas coisas objetivas: **vazou** palavra que não é de nenhum dos dois lados? **sumiu** a palavra que fecha ou a que abre? Achou 6 defeitos reais num lote de 3 vídeos, todos invisíveis pro `audit-emendas.py` (que no modo `--rel` acusa CLIP-FIM em quase tudo, por construção). Custo ~US$0,01 por vídeo. ⚠️ Roda em **nova-3/multi**: o nova-2 pt-BR devolveu transcrição VAZIA em 3 de 16 janelas de 2,4s, o que lê como "sumiu tudo".
- 🔴 **A REGRA MAIS CARA DESTE PROJETO — o timestamp do ASR NÃO é a borda acústica, e travar o corte nele NÃO basta.** (4 defeitos entregues ao creator-1 em 2026-07-27; ele ouviu "as IAs para trabalhar **[pra]**", "correr logo para conhecer **[em]**", "edição. **Ba** Basicamente".) Medido em 4 emendas: **a energia da próxima palavra já subia 30 a 260 ms antes do `start` que o Deepgram informa.** Cortar ali deixa uma rajada de ~70 ms dentro do segmento — no montado da emenda `reveal→num-600k` ela media **−11 dB**, 50 dB acima do piso que existia 60 ms antes. É a "meia palavra" que se ouve.
  **Correção implementada** (`bordas.py`): depois de travar pelo texto (`limite_pos`), o fim RECUA pelo envelope enquanto estiver `≥12 dB` acima do piso local **E** subindo (`sair_do_ataque`); espelhado no início (`sair_da_cauda`, que sai do decaimento da palavra anterior). Nos 3 criativos do lote isso moveu 27 cortes, o pior deles de **−7,8 dB**.  → RD-6
  ⚠️ **E o `qc-emendas-asr.py` NÃO pega isso**: fragmento de 40–90 ms não vira token, então o ASR dá a emenda como limpa enquanto o ouvido acusa. **ASR pega palavra vazada; envelope pega sílaba vazada. Os dois são obrigatórios.**
- 🔴 **A LEGENDA NÃO PODE SAIR DO TRANSCRIT DO MONTADO.** O ASR lê a emenda como fala contínua e **inventa palavra** pra fazer sentido: a legenda entregue dizia *"Você manda as empresas com o seu sócio"* onde o creator-3 fala *"uma das empresas que eu sou sócio"*. As palavras certas sempre existiram no transcript do BRUTO, onde o reconhecedor tinha contexto dos dois lados. Legenda = **palavras da EDL (bruto) + tempo mapeado linearmente** (`tempo = Σ durações anteriores + (w − início_do_segmento)`, com a duração de cada segmento em `frames/fps`, a mesma conta do `audio-exato.py`). Modelo pronto: `creators/creator-3/producao/peca-10-27-07/legendas.py`. Bônus: some a necessidade de injetar à mão a palavra que o ASR do montado perdia, e economiza uma transcrição por iteração.
- 🔴 **Energia dentro de um "vão" do ASR = palavra não reconhecida, e ela VAI ser decepada.** O criativo C saiu com *"Nós criamos a imersão **Sprin**"*: o Deepgram perdeu a palavra "peca-10" inteira e o que parecia pausa de 1,04s era fala (95,52–96,06, confirmado transcrevendo só o trecho com `keyterm=peca-10`). Como o `limite_pos` é o início da próxima palavra RECONHECIDA, o decay teve 1s de corda e parou no meio da palavra fantasma. A skill já dizia isso pra decidir descarte, mas nada CONFERIA nas bordas — agora o resolvedor de janelas mede o vão e avisa quando há >120 ms de fala nele.
- 🚨 🆕 **`scripts/qc-fonemas.py <dir>` — o único QC que pega borda de corte. RODAR SEMPRE.** (nasceu de um defeito ENTREGUE em 2026-07-27: o creator-1 assistiu e ouviu *"…que acendem ela, RES-"*, um pedaço de "Resumindo", a palavra que a EDL removia.) Os dois QCs que existiam passaram, e por motivos estruturais:
  - **ASR é régua de PALAVRA, não de borda.** Testei 4 pontos de corte diferentes no mesmo trecho e o Deepgram devolveu `'É de forma específica.'` em **todos** — ele completa a palavra pela linguagem. `qc-emendas-asr.py` deu 0 flags nos dois defeitos.
  - **`audit-emendas.py` acusou CLIP-FIM**, que é o flag ESPERADO quando se remove uma palavra do meio (a fala continua depois do corte por construção). Sinal verdadeiro indistinguível do ruído.

  A causa é fonética, e o **RMS de banda larga é cego pros dois lados**:
  - 🔴 **Vale no envelope NÃO é silêncio — pode ser consoante surda.** O /ʁ/ de "Resumindo" começa em 5,320 com RMS −34 dB (piso da sala −66): parece vale, o corte foi pra 5,360 e levou **40 ms de fricativa**, que o ouvido lê como sílaba. Denuncia: a razão (3–9 kHz)/(150–900 Hz) sobe **+13 a +18 dB** sobre o corpo da palavra.
  - 🔴 **Silêncio curto entre fala e fala NÃO é fim de palavra — é OCLUSÃO DE PLOSIVA.** Em "específica" o silêncio de 38,53–38,60 (RMS −65 dB) era a oclusão do /k/: o burst vem em 38,60 e a vogal /a/ em 38,635–38,92. O corte em 38,58 **decepou o "-ca"** e ninguém percebeu, porque o ASR completou a palavra sozinho. Régua: silêncio ≤110 ms com fala antes e bloco vozeado ≥60 ms retomando em ≤120 ms = a palavra não acabou.

  O script classifica cada emenda em silêncio/surdo/vozeado e só grita nesses dois padrões — validado contra a EDL defeituosa (**acusa os 2**) e a corrigida (**0 alertas**), sem falso positivo. Custo: segundos, sem API. `--v` imprime os blocos fonéticos em volta do corte.
- 🔑 **Corte NA fronteira de palavra quase sempre deceppa o primeiro fonema** (6 ocorrências no mesmo lote). O timestamp do Deepgram cai no meio da transição coarticulada, então abrir o beat "na palavra certa" corta o ataque dela: `sou` vira `conselheiro`, `estou` vira `há`, `comecei` vira `recei` — e até plosiva cai (`quero` virou `fazer`). **O que funciona é abrir a janela na palavra ANTERIOR** (mesmo que ela caia fora do corte) e deixar o `onset` achar a borda real no envelope. Contraexemplo que fecha a regra: com artigo coarticulado (`a última`), incluir o artigo é o que PRESERVA a palavra seguinte — abrir em `última` come o "úl". **Método: testar 3 pontos de corte no bruto por ASR isolado antes de decidir** (30 segundos, ~US$0,001), em vez de teorizar.
- Ação/payoff visual sem fala: inserir MUDO (som ambiente).
- Render: ffmpeg trim/concat → 1080x1920@30 (**`-nostdin` no ffmpeg dentro de `while read` — senão ele come o stdin do loop**). A soma da EDL difere ~0.1-0.2s do render (frame-snap) — não corrigir na EDL; o compositor escala.

### 2b. J-cut — a imagem entra antes do som (SPEC-07)

Toda emenda nossa era **butt-join**: o segmento que sai termina, o que entra começa,
encostados. Como a EDL já leva pad nas duas pontas, cada emenda descontínua entrega
dezenas de ms de ar — e **nenhum dos quatro QCs de emenda mede ar**. `audit-emendas`,
`qc-ataque`, `qc-fonemas` e `qc-emendas-asr` procuram *defeito* (sílaba decepada,
fricativa vazada, palavra inventada); uma montagem com 2 s de respiro distribuído passa
com **0 alertas nos quatro** — e passou, em todas as produções até aqui.

O J-cut sobrepõe em vez de encostar: a **imagem** do take que entra aparece `lead`
frames antes, enquanto o **som** do take que sai corre até o fim natural dele.

```
jcut.py <dir> [--modo medido|fixo|off] [--lead-max-ms N] [--fps N]   # planeja → jcut.json
montar.sh <dir>                                                       # detecta o plano sozinho
jcut.py <dir> --medir                                                 # preenche o bloco `saida`
qc-jcut.py <dir>                                                      # 5 testes
```

**Sem `jcut.json` nada muda.** Medido em 2026-08-08 contra os scripts de antes desta
spec, na mesma EDL e no mesmo bruto: `audio-exato.wav` e `v1-montado.mp4` saem com
**md5 idêntico**, e o stdout+stderr do `qc-ataque.py` é byte a byte o mesmo.

#### O lead é MEDIDO por junção, e o teto vive em MILISSEGUNDOS

🔴 **Não copie o lead do ref-A.** Eles usam `JCUT_LEAD_FRAMES = 5` fixo
(`helpers/render.py:521`). Com os nossos pads isso empurraria a imagem ~85 ms **para
dentro da fala** do take que entra — o defeito que o próprio SKILL.md deles alerta. E
lead em **frames** é o que produziu os 206,7 ms de erro deles numa fonte a 25 fps,
quando o `target_fps` caiu para uma constante no caminho longform (`render.py:1143`).

Aqui:

```
lead_s      = min(silêncio_final(k) + silêncio_inicial(k+1), lead_max_ms/1000)
lead_frames = floor(lead_s × fps)          # floor: nunca come mais ar do que existe
```

- o **teto** é `jcut.lead_max_ms` do perfil de peça, em ms, resolvido contra o fps da
  peça — o mesmo teto de 165 ms dá **4 frames a 30 fps** e **3 a 24 fps**;
- o **silêncio** é medido no envelope com **piso adaptativo** (`bordas.piso_local` +
  10 dB), não com limiar absoluto tipo o `silencedetect −33 dB` deles, que lê ruído de
  café como fala;
- numa emenda **sem ar**, `lead = 0` e nada acontece. O J-cut só come o que já era
  respiro — é isso que impede o "entrando no meio da palavra".

⚠️ **O piso adaptativo tem um ponto cego, e ele está fechado.** `piso_local + 10 dB`
sozinho mede o RUÍDO da vizinhança; numa janela SEM contraste (fala do começo ao fim) o
percentil 15 **é** o nível da fala, e o limiar nasce 10 dB acima dela — tudo passa por
"silêncio" e o J-cut comeria 200 ms de fala achando que come ar. Medido em bruto
sintético a 25 fps, 2026-08-08. A régua agora exige **contraste**: o limiar tem que ficar
abaixo do piso (`p15 + margem`) **e** abaixo da fala local (`p85 − margem`); sem os 20 dB
que separam as duas coisas, a resposta é **0 ms**, não um palpite.

#### 🔴 A guarda de contiguidade — o que o original não tem

Um segmento partido por `dividir-planos.py` (ou colado por `limite_pre`/`limite_pos` no
`bordas.py`) é **contíguo no bruto**: o fim de um é o início do outro. Sobrepor ali faz a
mesma fatia de fala tocar **duas vezes, somada consigo mesma** (+6 dB e eco de flanger).
O `plan_jcut` do ref-A (`render.py:588-611`) sobrepõe toda junção `i > 0` sem olhar de
onde vem cada range — eles não têm o conceito de segmento partido. Na `peca-01`
isso aconteceria em **6 das 28 junções** (índices 5, 11, 16, 17, 22 e 24).

O predicado é definido **uma vez**, em `jcut.py`, e importado por quem precisa:

```python
TOL_CONTIGUO = 0.002        # a EDL é gravada com round(...,3)
b["src"] == a["src"] and abs(b["start"] - a["end"]) < TOL_CONTIGUO
```

Em junção contígua o plano grava `lead_frames_in: 0`, `video_skip_frames: 0`,
`fade_in_s: 0`, `fade_out_s: 0` e `motivo_lead: "contiguo"` — e é **auditável no
arquivo**. Mais três guardas: **cabeça curta** (se sobrar menos de 8 frames de imagem,
lead 0 — o mesmo limiar de "plano curto lê como flash" do `cortes-do-bruto.py`), **teto
proporcional** (lead ≤ 25% do take que entra) e **EDL de 1 segmento** (sem junção, sem
J-cut).

#### O par `montar.sh` + `audio-exato.py` é INDIVISÍVEL

- **imagem**: o take que entra é renderizado de `start + skip/fps` até `end`;
- **som**: o take é lido do bruto a partir de `start` (a cabeça **inteira**) e somado na
  saída começando `lead` amostras antes de onde a imagem dele entra.

```
n_audio_k = n_video_k + lead_k        v_off_k = Σ_{j<k} n_video_j
a_off_k   = v_off_k − lead_k          (lead_0 = 0 por definição)
```

Por indução `a_off_k = v_off_k − lead_k`, então no primeiro frame de imagem do take k o
áudio está exatamente `lead_k` amostras dentro dele. **Sincronia por construção**, e o
total fecha sozinho: `soma_audio == soma_video` continua valendo, sem `-shortest` e sem
`-t` de trava. Medido no bruto sintético a 25 fps: **lag 0 amostras em 6 de 6 takes,
tendência +0,0000 amostra por take** (a referência do ref-A é +5,0 ms constante). A régua
detecta um deslocamento plantado de **5 amostras (0,104 ms)**.

🔴 **`video_skip_frames` entra no sidecar `segs/segNNN.json` E na comparação de cache.**
É o risco nº 1 desta spec: com o mesmo corte e outro lead, `src/start/end/zoom/
perfil_video_sha` são idênticos e só a cabeça da imagem muda — sem o campo, o `segs/`
velho é reusado e a trilha do lead NOVO é montada sobre a imagem VELHA, **com todos os
QCs verdes**, porque a trilha se trava nos frames reais e sincroniza com o vídeo errado.
É a classe de bug que deixou o `c-completo` do creator-3 6,25 s mais longo. Sidecar antigo
sem o campo vale 0, que é o que ele de fato renderizou.

O `jcut.json` também carrega `edl_fingerprint`: plano que sobreviveu à EDL que descrevia
é **fatal**, não aviso — mesma defesa da `timeline_real`.

#### O que muda nos QCs

| script | o que muda |
|---|---|
| `qc-ataque.py` | com `audio-takes/` presente, mede a cauda **no wav do próprio take**. No montado a janela de 60 ms antes da fronteira contém os DOIS takes somados e todo J-cut viraria ATAQUE por construção (medido: a inclinação na emenda vai de −0,0 para +4,7 dB/100 ms quando medida no somado) |
| `qc-emendas-asr.py` | a emenda vira **região**, não instante: a janela é centrada no meio da sobreposição e alargada pelo lead |
| `qc-fonemas.py` · `audit-emendas.py` | **não mudam** — medem no bruto |
| legenda | o mapa `Σ durações anteriores` continua certo **desde que use `frames_reais/fps`**; o que muda é a fatia do bruto, e ela sai de `jcut.json.saida[i].src_offset_s` |

#### `qc-jcut.py` — os cinco testes

1 estrutura (sem mídia) · 2 duração · 3 duplicação em junção contígua · 4 sincronia por
take · 5 pico na sobreposição.

Duas decisões de medição que valem para qualquer QC de áudio daqui:

- **o veredito acústico é medido no `audio-exato.wav`, não no `v1-montado.mp4`.** O
  montado carrega AAC; exigir "diferença ≤ −60 dB" contra o bruto ali mede o **codec**.
- **o teste 3 julga por CONTRASTE.** A diferença montado−bruto nunca é zero (o
  round-trip float→int16 já custa ~1 LSB), então a janela da emenda é comparada com uma
  janela de **controle** do mesmo take. Verde medido: emenda −90,3 dBFS contra controle
  −90,3 dBFS (Δ +0,0 dB). Com o defeito plantado (§8d): **Δ +68,1 dB**.

📏 **O teste 3 mede, e reporta, um dado que ninguém tinha**: em junção contígua o take
que sai cobre `frames/fps` de bruto, que quase nunca é igual a `end−start` — sobra ou
falta um pedaço **sub-frame** (medido: +20,0 ms a 25 fps). Isso existe **hoje, sem
J-cut**, e é propriedade do render, não da emenda. O QC imprime o número e só reprova
acima de 1 frame.

#### O que NÃO portamos do ref-A

- **o tail trim** (aparar a cauda do take que sai em até 2 frames): a nossa cauda já é
  decidida no `bordas.py` com `decay_relativo` + `--cap` + `sair_do_ataque`. Somar um
  aparo cego brigaria com a decisão que a EDL já tomou — e com uma constante em frames.
- **o `alimiter` na montagem**: correção de nível por segmento é assunto do `gain_db`.
- **reescrever o `edl.json`**: o plano vive em arquivo próprio. Renderizador que reescreve
  o próprio insumo é fonte de bug (eles tiveram que consertar a não-idempotência que veio
  junto, `render.py:392-398`).

⚠️ **A sobreposição é soma flat, nunca crossfade.** Os micro-fades de 15 ms continuam
sendo anti-click de ponta; fazer o take que sai desvanecer ao longo do lead mataria a
soltura da última palavra e o ataque da primeira — o material que o J-cut existe para
deixar se sobrepor. E o pico da soma é **medido**: o `audio-exato.py` **aborta** com o
índice da junção se passar de 1,0, em vez de deixar o `np.clip` cortar em silêncio
(exercitado: 3 junções acusadas com picos de 1,933 / 1,951 / 1,951).

## 📐 EDL v2 e a timeline real (SPEC-05)

Contrato completo em **`references/contrato-edl.md`**. Aqui só o que muda para
quem opera a ilha.

### O `janelas.json` virou aberto — campo novo ATRAVESSA

O `bordas.py` trabalha por **lista negra**: os oito campos que são insumo do
resolvedor de bordas (`asr_ini`, `asr_fim`, `pre_extra`, `post_extra`,
`limite_pre`, `limite_pos`, `start_fixo`, `end_fixo`) morrem lá; **qualquer** outro
campo escrito no `janelas.json` chega à `edl.json` e, dali, a quem souber lê-lo.
`quem`, `gain_db`, `fadeIn`, `fadeOut`, `lut` — nenhum precisa de código novo aqui.

Duas coisas que isso NÃO significa:

- `src`/`start`/`end` **não** são sobrescritos. Um `start` no `janelas.json` é o
  operador descrevendo o ASR; a borda resolvida vence sempre.
- Passthrough **não é silencioso**. O stderr do `bordas.py` conta em quantos
  segmentos cada campo extra apareceu e nomeia o beat que destoa. Um `gaindb`
  digitado errado aparece como `gaindb(1/23)` em vez de atravessar até um
  consumidor que o ignora.

### 🔴 Posição na saída sai de `timeline_real`, NUNCA de `Σ(end−start)`

O `audio-exato.py` grava, no fim da montagem, a timeline **real** da saída: frames
e amostras inteiros por segmento, medidos dos `segs/` que existem. Quem precisa
saber onde uma emenda cai no montado — legenda, capítulo, overlay, QC — lê dali:

```python
import edl_io
tl = edl_io.timeline(dir, exigir=False) or edl_io.medir_timeline(dir)
fr = edl_io.fronteiras(tl)      # [start_s de cada seg] + [total_s]; a emenda i→i+1 é fr[i+1]
```

📏 **Por que a soma nominal está proibida** — medido em 2026-08-08 nas produções
deste repo: `peca-03` **+353,3 ms**, `peca-01` **+316,7 ms**, `peca-04`
**+298,3 ms** de erro no fim. O erro é monotônico (o nominal é sempre mais curto,
é arredondamento para frame acumulando) e em `peca-03` a última fronteira que o
`qc-emendas-asr.py` amostra andou **+340 ms** ao migrar. É o anti-pattern que o
SKILL do ref-A proíbe na linha 513 e que o código deles comete assim mesmo —
4,433 s de erro num caso de 20 takes.

### A timeline não sobrevive a uma mudança de corte

Editou a EDL depois de montar? A timeline morre, e de duas maneiras: o `bordas.py`
remove o bloco ao reescrever, e o `edl_io.timeline()` **aborta** quando o
`edl_fingerprint` não bate com os segmentos de agora. Se der esse erro, a resposta
é rodar o `montar.sh` — não é para contornar.

### Produção antiga continua funcionando, e continua em v1

EDL em array é lida sem conversão. Quando ela recebe uma timeline, o bloco vai
para o **sidecar** `timeline-real.json` e o `edl.json` fica **byte a byte igual** —
os scripts locais daquelas pastas (`planos.py`, `legendas.py`, `cenas.py`) iteram
o array e continuam iterando. Converter é decisão explícita:
`edl_io.py --migrar <dir>` (grava `edl.v1.bak.json` antes).

### Auditar sem escrever

```bash
python3 .claude/skills/edit-video/scripts/edl_io.py --ver   <dir>   # schema · nº segs · timeline
python3 .claude/skills/edit-video/scripts/edl_io.py --medir <dir>   # o bloco em stdout, sem gravar
```

`--medir` **recusa** produção com segmento órfão (`ovo-de-pascoa`: 22 `.mp4` no
disco contra 21 na EDL). Medir ali gravaria uma timeline coerente com o vídeo
errado — é o bug dos 6,25 s do creator-3 com porta de entrada nova.

### A conferência do `montar.sh` virou DUPLA

| conferência | régua | pega |
|---|---|---|
| **nominal** | Σ da EDL × render, tolerância de 1 frame por segmento | **segmento órfão** — o único detector dele |
| **real** | `timeline_real` × render, **± 2 frames** | frame perdido/inventado no concat ou no mux |

As duas ficam. Um órfão passa na **real** por construção, porque a timeline foi
medida dos próprios segs errados.

### Teste — EDL v2 e timeline real (SPEC-05)

```bash
python3 .claude/skills/edit-video/scripts/tests/test_edl_v2.py            # ~20 s
python3 .claude/skills/edit-video/scripts/tests/test_edl_v2.py --rapido   # sem montar.sh
```

Autocontido (gera o bruto sintético, não toca material de creator) e com **defeito
plantado em cada portão**: timeline corrompida de 5 jeitos, EDL alterada depois do
render, `segments: null`, ordenação lexicográfica. Portão que não acusa o defeito
plantado é indistinguível de portão quebrado.

## Cauda do segmento — `bordas.py --cauda` (SPEC-09)

O `decay` do `bordas.py` pergunta *"qual é a ÚLTIMA janela acima do limiar,
varrendo pra FRENTE?"*. Num bruto de lugar público, uma xícara ou uma risada
300 ms depois do fim da frase cruza qualquer limiar e o `decay` gruda nela. O
`--cap` então **não aperta a cauda: ele só impede a fuga**, e o segmento sai com
o teto colado.

Medido na `peca-01` (23 janelas, café, `--pre 0.02 --post 0.06 --floor
auto --cap 0.15`):

| | `--rel 0` (a produção real) | `--rel 10` ("colado") |
|---|---|---|
| soma da EDL | 70,45 s | 67,25 s |
| cauda mediana | 60 ms *(= o pad `--post`, correto)* | 50 ms |
| cauda **p90** | **338 ms** | **338 ms** |
| cauda **máxima** | **460 ms** | **460 ms** |
| segmentos com cauda > 100 ms | **8 de 23** | **8 de 23** |
| excedente sobre o alvo de 60 ms | **1,82 s** | **1,90 s** |

**`--rel` não resolve.** Ele tira 3,2 s do CORPO das frases e deixa o resíduo de
cauda intacto (p90 idêntico, 338 ms). São dois eixos: `--rel` é ritmo de palavra,
`--cauda` é ar depois dela.

### A flag

```
bordas.py <dir> … [--cauda medir|auto|<segundos>] [--cauda-final]
```

| valor | efeito |
|---|---|
| `--cauda medir` | **default.** Mede, reporta no stderr e grava `cauda_ms` na EDL. **Não muda corte nenhum** |
| `--cauda auto` | alvo = `ritmo.cauda_alvo_s` do perfil de peça; `null` ou sem perfil → alvo = `--post`, e ele diz isso no stderr |
| `--cauda 0.06` | alvo explícito, em segundos |
| `--cauda-final` | permite aparar também o ÚLTIMO segmento (default: não) |

**O default é medir, e é decisão**: ligar o aparo por default mudaria o corte da
próxima produção sem ninguém pedir. O precedente é o FALLBACK do perfil de peça
("produção sem `perfil.json` se comporta exatamente como hoje, byte a byte"). O
operador liga com a flag; o perfil só fornece o número.

### O que ela faz, medido

`--cauda medir` sobre a `peca-01` produz `edl.json` **idêntico ao de hoje
em `src/start/end/fala/beat/zoom/cx/cy` nos 23 de 23 segmentos**, com dois campos
novos. `--cauda 0.06` apara **1,82 s** em **10 de 23** (maior corte 400 ms,
mediana dos cortes > 0 = 175 ms) e a soma da EDL vai de **70,45 s para 68,63 s**.

### As cinco guardas, uma frase cada

| | guarda | por quê |
|---|---|---|
| **G1** | segmento **contíguo** com o próximo no mesmo bruto não é aparado | 🔴 não é opcional: plano contíguo existe para trocar o enquadramento **com o áudio atravessando**; aparar o fim de um deles abre buraco no meio de uma palavra e desfaz a igualdade `soma_audio == soma_video`. Na `peca-01` são **6 pares** |
| **G2** | o **último** segmento não é aparado (salvo `--cauda-final`) | o fim do vídeo não é emenda: o ar ali é respiro de saída |
| **G3** | `end_fixo` no `janelas.json` vence o aparo | é o operador dizendo "eu medi" |
| **G4** | nenhum aparo deixa o segmento abaixo de **100 ms** | guarda de sanidade: segmento não vira frame solto |
| **G5** | guarda **fonética** no trecho exato a remover | rede contra a fricativa: o /ʁ/ e o /s/ podem ficar abaixo do RMS e ainda ser fonema — quem denuncia é a razão (3–9 kHz)/(150–900 Hz). Roda com o classificador do `qc-fonemas.py`, importado e **nunca editado** |

⚠️ **A janela de G5 é EXATAMENTE o trecho a remover**, sem margem para trás:
incluir 20 ms antes puxa o corpo da palavra e o detector acusa em 20 de 23
segmentos, por construção.

📏 **Calibração de G5, medida** — o gate de nível dele é `piso_local + 8 dB`
(o ruído REAL em volta do corte), e não o piso de decisão do `decay`, que é
`piso_local + 10`: com o piso do `decay`, G5 estaria por definição acima de tudo
que existe na janela a remover (o `medir()` só devolve janelas ABAIXO dele) e
**nunca acusaria nada** — portão verde sem dentes. E o que separa fricativa de
chiado de café é o TIPO, não o nível: nas 10 janelas de aparo, 860 quadros
espectrais varridos, **1** bloco passou o gate de nível e foi recusado com 9 dB
de folga. Com o piso GLOBAL de sala (percentil 5 do arquivo, −47,5 dB) o
detector acusaria em **4 dos 10** — chiado lido como fricativa — e o aparo cairia
de 1,82 s para 1,05 s.

### Onde o número mora

`ritmo.cauda_alvo_s` no perfil de peça (`number | null`, `null` em todos os
perfis iniciais = medir e não aparar). É **ritmo, não formato**: o mesmo número
vale em 24, 30 ou 60 fps. O ref-A apara "até 2 frames" (`render.py:522`), que é
valor de formato e erra de fps em fps.

### O que esta peça NÃO faz

- **Não apara na montagem.** Todo o aparo acontece no `bordas.py`, escrevendo
  `end` na EDL. `montar.sh` e `audio-exato.py` não mudam uma linha.
- **Não mexe no `decay`.** O `decay` decide onde a **palavra** acaba; a cauda,
  quanto **ar** fica depois. Fundir os dois faz um número mexer no outro e a
  regressão fica impossível de atribuir.
- **Não re-renderiza produção publicada.**  → RD-2

### Teste — cauda do segmento (SPEC-09)

`python3 scripts/tests/test_cauda.py` — **16 checagens**, sinal 100 % sintético
(fala = ruído 200–1000 Hz a −18 dBFS, sala a −45), cauda **conhecida** em
0/60/200/450 ms, e G5 provado **plantando a fricativa** que ele tem que achar
(o teste confere antes que sem G5 o corte decepava o fonema) e **plantando o
chiado** que ele não pode confundir com fonema.

---

> Núcleo: [`../SKILL.md`](../SKILL.md) — as Regras Duras valem aqui.
