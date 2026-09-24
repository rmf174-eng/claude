# Áudio e cor — etapas 3 e 4

> O corpo das etapas **3 (áudio)** e **4 (cor)**, mais o nível por segmento, o teto da trilha, a trilha sonora e o transiente do SFX. Aqui mora o motivo de cada número.

`cor.entrada_esperada` aceita `auto`, um perfil (`hlg` ou `sdr`) ou uma lista
com os dois. O resolvedor grava em `cor.json` o valor declarado, o perfil
detectado e a decisão. Compatibilidade nunca relabela metadados: a cadeia de cor
continua sendo escolhida pelo perfil realmente detectado. Divergência bloqueia.

---

### 3. Áudio (PERGUNTAR antes — é regra, não default) · **MEDIR antes de escolher a via**

🔊 🆕 **O `amix` dos SFX levanta o true peak DEPOIS de tudo** (2026-07-27): o loudnorm da voz mira −1,5 dBTP, mas o pico do arquivo entregue vem da soma com os SFX — a peca-03 saiu a −0,88 e a paixão a −0,58 dBTP. Não vale re-normalizar (mexe no corpo): `scripts/loudness.py <arquivo> --teto -1.5 --out <saída>` aplica só o limitador no remux (`-c:v copy`) e traz o pico pro alvo **sem mexer no loudness** (medido: −14,99 LUFS antes e depois, TP −0,58 → −1,48). O `limit` sai de `10**(alvo_tp/20)` — o `0.841` que estava cravado no `peca-09/compor.sh:51` é exatamente esse número para −1,5 dBTP, agora derivado em vez de copiado. ⚠️ **O `alimiter` limita pico de AMOSTRA; o `ebur128` mede TRUE PEAK com oversampling 4×.** Os dois não são o mesmo número: em material com +2 dB de ganho o true peak sobrou **0,2 dB acima do teto**. Por isso o modo `--teto` mede a saída e avisa em vez de dizer "feito".

🔊 **Medir TRUE PEAK sempre, não só o LUFS** (achado nos criativos do creator-3, 2026-07-27): o bruto de iPhone veio a −19,75 LUFS com **true peak em +0,49 dBTP**, ou seja, a fala já chegou CLIPANDO da câmera. Peak acima de 0 distorce no player e piora no transcode da plataforma, e o número de loudness sozinho não denuncia.

🔴 🆕 **LOUDNESS TEM UM SCRIPT CANÔNICO — `scripts/loudness.py`. Normalizar dentro do `filter_complex` da composição é o defeito, não o atalho.** (SPEC-02, medido em 2026-08-08.) O que a skill dizia ("`loudnorm=I=…:TP=-1.5` em 2 passes resolve") e o que os scripts faziam eram coisas diferentes: os `compor.sh` das produções aplicavam **passe único** dentro do mesmo comando que encoda o vídeo — e ali o segundo passe é estruturalmente impossível, porque a medição precisa do mix pronto, que só existe depois desse comando. Passe único não atinge o alvo, ele **estima**, e erra sempre para baixo:

| entregável | alvo | medido (`ebur128=peak=true`) | erro |
|---|---|---|---|
| `creator-3/peca-10-27-07/a-comando/v-final.mp4` | −16,0 | **−17,7** | 1,7 LU |
| `creator-3/peca-10-27-07/b-conselheiro/v-final.mp4` | −16,0 | **−17,5** | 1,5 LU |
| `creator-3/peca-10-27-07/c-16anos/v-final.mp4` | −16,0 | **−18,0** | 2,0 LU |
| `creator-1/peca-11/r1-os-bons/v-final.mp4` | −14,0 | **−15,8** | 1,8 LU |
| `creator-1/peca-11/r5-refem/v-final.mp4` | −14,0 | **−15,6** | 1,6 LU |
| `creator-1/peca-11/L2-os-bons-longo/v-final.mp4` | −14,0 | **−15,9** | 1,9 LU |

**6 de 6 abaixo do alvo, média 1,75 LU, nunca acima.** E o próprio ffmpeg já denunciava: o passe 1 imprime `output_i` (a simulação do que o passe único vai entregar) e `target_offset` (a correção que o segundo passe aplicaria). Medido no `--passes 1` do script novo: previu `output_i −16,53` e entregou **−16,5** — a previsão erra 0,03 LU. A informação para acertar sempre existiu.

**A normalização sai de dentro da composição e vira etapa própria**, a mesma decisão que já provou certa na montagem (`montar.sh` renderiza `-an` e a trilha vem depois do `audio-exato.py`):

```
antes:  [mix] → loudnorm 1 passe DENTRO do filter_complex → v-final.mp4   (erra 1,75 LU)
depois: [mix] → mix.wav (PCM) → loudness.py (medir → aplicar) → mix-norm.wav → mux -c:v copy
```

```bash
python3 scripts/loudness.py mix.wav --normalizar --perfil <reels|vsl|longform|screencast> --out mix-norm.wav
python3 scripts/loudness.py <dir>/v-final.mp4 --verificar --perfil reels     # QC, exit 1 se fora
```

Para MP4, a normalização não escreve mais diretamente no caminho final. O
script decodifica o áudio para PCM alinhado à duração do vídeo, normaliza esse
PCM, faz o mux com `+faststart` em uma arena temporária e só publica por rename
atômico depois de conferir `moov`, streams, duração, offset A/V, loudness e
decodificação integral. Falha remove o parcial e preserva o último entregável
válido. A rota não usa `-shortest`.

Ganho positivo estritamente maior que 6 dB exige decisão explícita:

```bash
python3 scripts/loudness.py mix.wav --normalizar --perfil reels \
  --autorizar-ganho-alto "aprovado por <nome> após comparação A/B" \
  --out mix-norm.wav
```

A justificativa, o ganho medido e o limiar ficam no sidecar. O comando não
aplica de-esser, denoise ou limpeza automaticamente.

🔒 **O alvo NÃO tem default e o script recusa inventar um**: sem `--perfil`, `--alvo-i` ou `--referencia` ele sai **2** e não escreve nada. Alvo é decisão de destino, e os nossos são incompatíveis entre si: peça orgânica segue o nível do creator (as do creator-1 vivem a **−24,4 LUFS**), **anúncio vai a −16 LUFS / −1,5 dBTP** — 8 LU de distância; e LRA é dinâmica da peça (VSL 11, criativo de 30 s 7), não constante global. O número vem do bloco `audio.loudness` do **perfil de peça** (SPEC-00), que é o único lugar onde ele mora.

⚠️ **O TP a −1,5 é nosso e não é preciosismo**: o padrão que se copia por aí é −1,0 (é o do ref-A, `render.py:829`). Com teto em −1,0, a peca-03 (−0,88 dBTP) e a paixão (−0,58) teriam clipado, porque o `amix` dos SFX sobe o pico DEPOIS da normalização.

📏 **Três medições que decidem como usar o script**:
- **PCM → PCM (o caminho canônico) não move o tempo: Δduração 0,000 ms** em 4 de 4 rodadas. **AAC → qualquer coisa move +16,0 ms** num clipe de 6 s (`duration_ts` 288000 → 288768, +768 amostras), com o stream de vídeo byte a byte idêntico. A causa é o padding do AAC, não o loudnorm. Por isso o script **reprova** o caminho `--midia` por default (`soma_audio == soma_video` é invariante) em vez de disfarçar com `-shortest`; migrar entregável pronto exige subir o limiar à mão (`--deriva-max-ms 25`), e a decisão fica no sidecar.
- **`linear=true` incondicional é bug herdado.** Quando o material chega com TP positivo não existe ganho linear que alcance o alvo sem estourar, e o ffmpeg **desiste de baixar o TP** (medido aqui: saída a +0,04 dBTP onde se pediu −1,5). O script decide pela previsão `input_tp + (alvo_i − input_i)` e só então passa ou omite o flag. Nas rodadas de controle: regime linear fechou em **0,00 LU** de erro, regime dinâmico em **0,20 LU**.
- **O downmix vem ANTES da medição.** O EBU R128 soma a energia dos canais: normalizar em estéreo e só então `-ac 1` entrega mono fora do alvo. Medido no controle sintético: **6,0 LU de erro** (−21,0 contra os −15,0 do caminho certo). O `--canais` do script age antes do passe 1, e o `--verificar` recusa comparar domínios de canais diferentes.
Oferecer limpeza (skill `clean-audio`). Se sim: limpar o áudio DO MONTADO na fonte e remuxar com `-c:v copy` — os SFX do compositor entram por cima, limpos.

⚠️ **A via não é fixa: depende do diagnóstico.** Medir primeiro (`ebur128` + `astats` por banda + piso nas pausas) e só então escolher:
- **sopro/lapela/ruído real** → via D (DeepFilterNet), aprovada no ovo-de-pascoa.
- **sala limpa e voz baixa** (caso peca-03: −29,1 LUFS, piso −66dB, sub-100Hz 18dB abaixo da fala) → **D é a via ERRADA**: medido resíduo (D − só-nível) a **2,7 dB abaixo do sinal** = está reescrevendo a voz, não removendo ruído (e piorou o piso numa das pausas). Via certa: `highpass=80 + deesser + loudnorm I=-14:TP=-1.5` 2-passes.
- **sibilância** aparece depois do loudnorm (o ganho sobe o /s/ junto): medir o pico da banda 5kHz+ e calibrar o `deesser` pela RAZÃO pico/RMS — `i=0.7` tirou 2,7dB dos picos e só 0,8dB do brilho médio; um compressor split-band derrubou 3,9dB do brilho todo (abafa a voz) e foi reprovado.
- Gerar as amostras A/B em `teste-audio/` (13s, mp3) pro creator-1 julgar de ouvido — a medição escolhe o candidato, o ouvido dá o veredito.

🎵 **Trilha sonora (opcional, SPEC-20)** — se o `PLANO-EDICAO.md` pedir música:
`scripts/musica-gerar.py` consegue a faixa (Lyria 3 pela `GEMINI_API_KEY`, US$0,04–0,08)
e `scripts/trilha.py preparar <dir>` prepara com ducking pela voz e nível **relativo à
voz** (Δ do perfil, nunca LUFS absoluto). ⚠️ **O QC de áudio desta etapa roda na versão
SEM trilha** — música esconde defeito (o silêncio digital de −240 dBFS do end card da VSL
só apareceu sem ela). Ver "Trilha sonora" no fim deste arquivo.

### 4. Cor
🆕 **A conversão acontece na EXTRAÇÃO, por segmento — não num passe sobre o montado.**
Da fronteira do primeiro `segs/segNNN.mp4` até o entregável existe **um** espaço de
cor: Rec.709; o bruto é o único arquivo HDR da produção. Isso mata uma CLASSE de
defeito, não uma ocorrência: enquanto a conversão era um passe à parte, o segmento e o
montado ficavam HLG e todo re-encode a jusante herdava HLG — foi assim que seis
entregáveis saíram da casa dizendo "eu sou HLG em BT.2020" com pixels já convertidos.
Com o segmento já em `bt709`, a **herança joga a favor**: grade, composição de overlay
em qualquer ordem de entrada e remux saem certos **sem flag de cor nenhuma**.

Quem costura é o `montar.sh`, e a ordem do filtergraph tem três travas medidas
(seg000 da `peca-01`, 2026-08-09): sem `format=yuv420p` antes da conversão a
luminância média sobe **+1,8%**; com a conversão antes do `scale`, **+1,5%**; com a
conversão **depois** do `setparams`, **+0,42%** — porque o yuv→rgb que o ffmpeg insere
sozinho na frente do `lut3d` usa a matriz que o `setparams` acabou de escrever. Na
ordem certa o segmento sai **bit a bit** igual à cadeia calibrada. Contrato completo,
com as duas guardas que abortam em vez de adivinhar:
**`references/contrato-cor.md`**.

🔴 **O portão de cor para a MONTAGEM.** `calibrado: false` (PQ, Apple Log) ou
confiança que não é alta **abortam o `montar.sh` antes do primeiro `ffmpeg`** — zero
segmento renderizado. A saída não é somar uma curva de manual; é medir o `avconvert` e
acrescentar a entrada ao catálogo. Escapes conscientes, que ficam no registro:
`--cor-como <entrada-do-catalogo>` e `--sem-cor`.

⚠️ **O `cor_sha` no sidecar é a quinta porta do segmento órfão.** `gen-hlg2sdr-lut.py`
regrava `luts/hlg2sdr.cube` **no lugar**: sem os BYTES da `.cube` no sha, trocar a
curva deixaria 29 segmentos da curva antiga no disco com sidecar válido e todos os QCs
verdes. Sidecar sem `cor_sha` → refaz.

🆕 **A decisão de perfil não é mais prosa: é `detect-cor.py`.** "Conferir com ffprobe" era instrução para uma pessoa, e nenhum script conferia — o que sustentava o acerto é que todo bruto até hoje foi iPhone HLG. Agora:

    scripts/detect-cor.py resolver <dir-producao> --bruto input/<bruto>   # grava <dir>/cor.json

O `cor.json` (contrato `benchmark.cor/v1.1`) responde **o que o arquivo é** e **qual das NOSSAS curvas se aplica**, em dois tiers: metadado (HLG, PQ, Apple Log, LOG de fabricante, BT.2020 SDR, Rec.709) e, quando o metadado é mudo, estatística de imagem. Ele traz o `vf` pronto. **Códigos de saída**: `0` pode seguir · `3` precisa de humano · `2` diverge do `perfil.json` · `1` erro.
🆕 **Sem `--bruto`, o `resolver` lê os `src` DISTINTOS do `edl.json` e resolve cada
um**, gravando `fontes{}` — uma entrada por fonte, com `fragmento_vf`, `calibrado`,
`confianca` e os segundos somados. Os campos de topo continuam descrevendo a fonte
principal (a de maior tempo), o que mantém o contrato legível por quem já lia
`cor.perfil`. É o que torna possível uma EDL com um take de iPhone HLG e um screencast
BT.709 no mesmo timeline: cada segmento é convertido pela SUA cadeia, e o montado sai
num espaço só. Mais de um perfil na mesma EDL é **aviso com a contagem por perfil**,
não erro — mas mistura não declarada quase sempre é `src` errado na EDL.

🔴 **Dois portões, não um.** Confiança baixa volta para o humano (regra do detector de origem) **e `calibrado: false` também volta, mesmo com confiança alta**. Detectar PQ com certeza absoluta não autoriza converter PQ: não medimos essa conversão contra nada, e a cadeia "de manual" já custou −21% de faixa de contraste no rosto e foi reprovada. Onde não há curva medida, o script **recusa e diz como medir uma** — nunca cai num tone-mapper genérico. O catálogo de perfil→cadeia vive em `tools/remotion-compositor/luts/catalogo-cor.json`.

⚠️ **`bt2020_sdr` NÃO é HDR e NUNCA leva `hlg2sdr.cube`.** É BT.2020 de primárias com curva ordinária; a nossa LUT começa pela inversa da OETF HLG e sobre um sinal já em gamma 709 isso escurece e esmaga as sombras. A cadeia certa é só de gamut (`colorspace=…:itrc=bt2020-10:…`), e o detector já a monta.

⚠️ **O Tier 2 (estatística) não reconhece HDR — está declarado no contrato, não escondido.** HLG é retrocompatível por desenho: preto no lugar, branco no lugar, saturação normal. Medido nos dois brutos HLG do repo, com as tags raspadas eles saem `rec709` com confiança **alta** (score 0). Por isso o `cor.json` grava `tier` e o `qc-cor.py` não confia no detector sozinho — ele cruza rótulo contra pixel.

Escolha de look entre candidatos (substitui os três dispositivos ad hoc por produção):

    scripts/detect-cor.py candidatos <video> --spec "apple=hlg2sdr.cube;quente35=hlg2sdr.cube+peca-12-quente-35.cube" \
        --em 6,16,47 --regiao 0.16,0.20,0.42,0.40 -o folha-cor.png

Vários instantes (julgar cor num frame só já falhou aqui), **número embaixo de cada tile** (`lum · sat · R/B` da região declarada — a regra do repo é escolher por número), e guarda anti-HDR: tile que ficaria em domínio HLG/PQ é **recusado**, porque folha é sempre SDR contra SDR.  → RD-15

Aplicada a cadeia **na extração**, `v1-montado.mp4` já é o que se chamava `v1-sdr.mp4`
— o nome deixa de ser **produzido** (os arquivos que existem no disco continuam
válidos, e nenhuma produção antiga é remontada). Depois vem **o grade oficial do
creator** (se houver na linha editorial) → `v1-graded.mp4`, que vira a base da
composição; sem grade, a base é o próprio `v1-montado.mp4`.

🔴 **Modo de falha novo: LUT aplicada duas vezes.** Todo script de produção que hoje
converte (`peca-01/cor.py:23,47`, os dois `montar-tudo.sh`) passa a rodar sobre
um montado **já convertido**. Assinatura medida: **−23,7%** de luminância. Antes de
rodar qualquer passe de cor sobre um montado, leia `cor.aplicada_em` no `cor.json`.

⚠️ **QC de cor obrigatório contra o BRUTO** (não só contra o still anterior): medir `p10 / p50 / p90` e a **faixa de contraste (p90−p10)** numa região de rosto no montado HDR e no graded. A perda de faixa deve ser explicada pelo preset do creator e nada mais. Foi assim que se achou, em 2026-07-25, que a LUT v1 comia 21% do contraste e deixava a pele lavada ("ela ficou muito branca" — o cabelo preto virava castanho-avermelhado). Detalhe do bug e do fix na skill `remotion-compositor`. **Ao trocar a LUT, recalibrar o grade do creator** — ele foi ajustado de olho contra a LUT antiga, então erros podem estar se cancelando (no caso da creator-2, a vinheta estava 3× mais forte do que devia e só apareceu depois do fix).
⚠️ **Não julgar cor comparando SCREENSHOT de HDR vs SDR**: o macOS comprime HDR em ~73% do range no screenshot (medido: p99 em 185/255, branco em 154/255), então o lado HDR sai escuro e o SDR parece 15–20% mais claro do que a diferença real. Pro veredito, abrir os dois arquivos no MESMO player ou no celular; pra diagnosticar, medir nos arquivos.
⚠️ **O creator pode preferir SEM o preset**: a conversão HDR→SDR é obrigatória (é troca de formato — se subir HDR, o Instagram converte com a matemática dele), mas o grade é opcional. Se o creator aplica o filtro dele no app de qualquer forma, entregar as duas versões (`v-final.mp4` e `v-final-sem-filtro.mp4`) — a sem-filtro fica a 0,5% da luminância do bruto e preserva o fluxo dele. As duas passam pela composição oficial, cada uma com sua base e manifesto: `compor-final --base v1-graded.mp4 --saida v-final.mp4` e `compor-final --base v1-montado.mp4 --saida v-final-sem-filtro.mp4`. O gate exige proveniência para ambas.
⚠️ **Vinheta em 9:16 bate no rosto, não só nos cantos**: o rosto do creator normalmente fica no terço superior, longe do centro do quadro. Calibrar medindo o rosto (`p50` da caixa do rosto) e a razão cantos/centro — não pelo olho no canto da imagem. A entrega compõe a camada gráfica (render alpha do Remotion) por cima com ffmpeg — cor fiel por construção (arquitetura na skill `remotion-compositor`).
⚠️ **Regra de look (creator-2/creator-1 2026-07-22): sem efeito improvisado** — sem punch-in, sem saturação/grade ad hoc. O que EXISTE é o grade OFICIAL por creator, aprovado e registrado na linha editorial (creator-2: tradução ffmpeg do preset que ela usa no app — destaques −19, sombras +5, iluminação −5, vinheta 20). Efeito criativo pontual (ex.: P&B intencional) só por decisão editorial explícita.
🆕 **"Ficou pálida" tem número — e às vezes a culpa é do preset do próprio creator** (pedido do creator-1, 2026-07-27). Medido no rosto contra a base (LUT Apple), o preset da creator-2 dá **faixa de contraste −6 a −7% e saturação +1%**: ele é um preset de *suavização*, não de *presença*, e sobre cena pouco contrastada (banheiro branco, luz difusa) entrega exatamente essa queixa. Se o creator pedir mais cor, o caminho é **punch por cima do preset**, aprovado como look novo — e a versão sem filtro continua sendo entregue junto.
🔑 **Ao empilhar punch sobre um preset que já escurece, LEVANTE o ponto médio.** A primeira tentativa somou uma curva S normal e a luminância do rosto caiu **−14%** (o punch estava escurecendo junto). Com o mesmo contraste e croma, mas `0.5/0.535` na curva, ficou **lum −8% · faixa +3% · sat +25%** — que é o que "não pálida" quer dizer. Receita validada:
```
curves=master='0/0 0.20/0.185 0.5/0.535 0.80/0.835 1/1',eq=saturation=1.10,
curves=r='0/0 0.5/0.507 1/1':b='0/0 0.5/0.494 1/0.997'
```

### Nível E posição do SFX (SPEC-26)

```bash
python3 .claude/skills/edit-video/scripts/qc-sfx.py --perfil reels
python3 .claude/skills/edit-video/scripts/sfx-preparar.py --migrar [--confirmar]
```

O agendamento do SFX é cego para o **conteúdo** do arquivo: o `<Sequence>` põe o
**arquivo** no frame do beat, então lead-in de 180 ms é batida 180 ms atrasada.
Medido na biblioteca real: **4 de 9** passavam de um frame, e `whoosh-soft`
gastava **41 % do próprio corpo** em silêncio. Derivar por pitch/stretch
multiplica o lead junto (46 ms → 75 ms).

E as duas medições não são independentes: **`pop.wav` mede −22,5 LUFS como está e
−17,5 sem a cauda muda — 5,0 LU de padding**. Daí a ordem obrigatória
**aparar → medir → normalizar** (contrato em `references/contrato-sfx.md`).

Depois do `--migrar --confirmar`: os 4 arquivos foram para `onset ≤ 3 ms` com
`corpo` preservado (Δ máximo **1,0 ms**), os originais estão em
`public/sfx/_historico/` e cada `.wav` ganhou sidecar com `sha256`. O
`qc-sfx.py` passou de **2 falhas** para **0**.

`LOUDNESS-FORA-DO-ALVO` é **achado**, nunca falha — parte do desvio é padding, e
o `pico_min_dbfs` impede que a normalização clipe para alcançar o alvo.

# Trilha sonora (SPEC-20)

A trilha deixou de ser "o creator-1 arruma um mp3". Dois scripts, e todo número de
comportamento vem do bloco `trilha` do perfil de peça.

```bash
S=.claude/skills/edit-video/scripts
# 1. conseguir a música (US$ 0,04 clip / US$ 0,08 pro; 2ª chamada idêntica = US$ 0)
python3 $S/musica-gerar.py --vibe "<gênero + instrumentos + BPM + humor>" --dur 190 \
        --tags vsl,cinematico --out <dir>/trilha/musica.mp3
# 2. escolher entre candidatas (a medição elimina; o ouvido escolhe)
python3 $S/musica-gerar.py --avaliar a.mp3 b.mp3 --voz <dir>/v1-graded.mp4 --dir <dir>
# 3. preparar (ducking + nível) e verificar
python3 $S/trilha.py preparar  <dir>
python3 $S/trilha.py verificar <dir> --controle-negativo
```

## A regra de uma linha

> **O nível da trilha é Δ EM RELAÇÃO À VOZ, nunca LUFS absoluto.**

As VSLs vivem por volta de −14 LUFS e as peças orgânicas do creator-1 a −24,4. Um
"−27" cravado deixa a trilha 13 LU abaixo numa e 2,6 LU **acima** do pretendido na
outra. O passo 0 do `preparar` **mede** a voz; o alvo é `I_voz − delta_voz_lu`.

## O que muda por perfil (§3.9 da spec)

| campo | `reels` | `vsl` | `longform` | `screencast` |
|---|---|---|---|---|
| `ativa` | **false** | **false** | **false** | **false** |
| `delta_voz_lu` | 13,0 | 13,0 | 14,0 | 15,0 |
| `duck_db` | 9,0 | 5,0 | 7,0 | 7,0 |
| `fade_in_s` / `fade_out_s` | 1,0 / 2,0 | 2,5 / 4,0 | 2,5 / 4,0 | 1,5 / 3,0 |

🔴 **`reels.ativa = false` tem motivo editorial, não só cautela**: áudio trend do
Instagram só conta para o algoritmo se aplicado **no app** na hora de postar, e
trilha queimada compete com o trend. Onde a trilha ganha sem disputa é onde não
existe trend: VSL, anúncio, screencast, YouTube. Ligar trilha num reel orgânico é
decisão explícita do creator, registrada no `PLANO-EDICAO.md`.

## Os três defeitos que vieram do script de origem, e o quarto que ninguém tinha visto

- 🐛 **`duck_db` abaixo de 10 não fazia nada.** `ratio = max(2.0, 20/(20−duck))` —
  o piso de 2,0 engolia todo pedido ≤10 dB e o stderr anunciava metade do que
  aplicava. Medido depois do conserto, na mesma peça: duck 5 → ratio 1,33, LRA da
  trilha **6,5 LU**; duck 9 → 1,82, **8,4 LU**; duck 15 → 4,00, **13,4 LU**. Com
  o piso os três primeiros eram o **mesmo arquivo**. O integrado final não muda
  (o ganho de compensação corrige) — o que `duck_db` controla é a **textura**.
- 🐛 **Alvo absoluto e nível da voz cravado no fonte.** Sumiram: o alvo é Δ e a voz
  é medida.
- 🐛 **`os.listdir(".")` apagando todo `_m*.wav`** do diretório corrente. Os
  temporários agora vivem em `<dir>/trilha/_tmp/`, criado e removido pelo script.
- 🐛 🆕 **O `sidechaincompress` deste build (ffmpeg 8.0.1) NÃO ESVAZIA A CAUDA no
  EOF.** Medido: 0,405 s a menos numa peça real de 70,784 s, 0,805 s num sintético
  de 2,000 s. **Não é latência** — um impulso posto na amostra 0 sai na amostra 0.
  Nem pré-decodificar a voz para PCM nem `apad` só na voz resolvem (ainda faltaram
  0,384 s e 0,533 s). O conserto é `apad` nos **dois** lados e trim exato depois.
  ⚠️ Isto estava no script de origem: aquela trilha sairia ~1 s mais curta que a
  voz, emudecendo antes do fim, e o `amix=duration=first` não acusa — ele só para
  de somar. Hoje o `preparar` **aborta** se a saída não bater com a voz em 1 ms.

## O QC mede o EFEITO, não o alvo

`trilha.py verificar` classifica as janelas de 400 ms da voz e mede quanto a
trilha soma em cada classe: **mascaramento** na fala densa (teto 0,5 dB) e
**presença** nas pausas (piso 3,0 dB). O alvo em LUFS é o **detector**; ele nunca
pode ser o teste de convergência.

🔴 **O piso de pausa é `integrado − 10 dB`, e isso foi medido — a spec propunha 25
e com 25 o QC não pega o defeito que existe para pegar.** Plantando a trilha 22 LU
abaixo da voz (que reproduz os −36,4 LUFS históricos; a VSL saiu medindo −36,3):

| piso | VSL (473 jan.): n / boa / morta | reels (176 jan.): n / boa / morta |
|---|---|---|
| −10 dB | 33 / **+5,03** / **+1,07** ✅ | 16 / **+8,18** / **+2,30** ✅ |
| −12 dB | 27 / +6,29 / +1,49 | 11 / +11,19 / **+4,04** ❌ passa |
| −25 dB | 8 / +14,61 / **+6,56** ❌ | **1** / +21,84 / **+13,04** ❌ |

A −25 dB a população some (1 janela em 176 num reel) e a morta sobe junto com a
boa. De onde vinha o 25: a spec colocou o limiar entre "+4,2 dB na pausa" e "+0,1
dB", mas o +0,1 foi medido na **fala densa** — limiar posto com número do outro
eixo.

🔒 **Prova de dentes**: o `verificar` imprime **quantas** janelas varreu, e
`--controle-negativo` refaz a conta com a trilha atenuada em 30 dB — que **tem
que** reprovar. Se não reprovar, o veredito vira `CEGO` e o script sai 1.

📏 **A premissa que não se sustentou**: a spec supunha que reel tem pausas e VSL
não. Medido nas nossas peças, é o contrário — o corte tira o respiro do reel, e a
VSL tem mais janelas de pausa (33) que o reel (16) e que a `peca-02` (1 em
197, em qualquer piso de −20 a −30). Talking-head cortado quase não tem silêncio,
**por construção**. Quando a peça tem menos de 3 janelas de pausa o QC diz isso e
manda ouvir, em vez de imprimir verde.

## Licença: persistida, não impressa

Toda faixa entra em `tools/music-library/INDEX.json` com `licenca`, `synthid` e
`custo_usd`. `exige_atribuicao: true` faz o `preparar` escrever
`<dir>/trilha/CREDITO.txt` e **sair 5** se não puder escrever um crédito honesto;
o `verificar` **sai 5** se o arquivo sumiu.

⚠️ A saída do Lyria carrega marca d'água **SynthID** e vale sob os Termos da API do
fornecedor. **Não afirmar que a trilha é "livre de royalties"** — é pergunta
jurídica em aberto.

## O que NÃO herdar do ref-A nesta área

1. **`volume=0.10` cru** (`shortform.md:472`): ganho cego sobre um mp3 nunca
   medido. Medido aqui, o gerador entrega quente e **já clipando**: a faixa que
   geramos saiu a **−12,6 LUFS / −0,1 dBFS**. Com `volume=0.10` ela viraria −32,6;
   uma próxima geração a −18 viraria −38, 5 LU de diferença sem nada mudar no
   comando.
2. **Calibrar o nível de ouvido porque não se mediu.** Ouvir é o veredito; não
   pode ser o instrumento.
3. **Trilha igual para short e long** — reel de feed disputa com o áudio trend do
   app; VSL não.
4. **Deixar a trilha passar pelo Remotion** — eles mesmos mediram +0,66 s de deriva
   aos 78 s. Trilha é áudio, e áudio é ffmpeg.

**Teste**: `python3 $S/tests/test_trilha.py` — 45 checagens, material 100 %
sintético e nenhuma chamada de rede. Cada mecanismo é testado duas vezes: o caso
bom com o número medido, e o defeito plantado que ele **tem** que acusar (o piso
de 2,0 de volta, a trilha 22 LU abaixo, o `sidechaincompress` sem padding, a
resposta da API sem a chave `content`, a trilha atenuada em 30 dB).

## Nível por segmento (`gain_db`) — SPEC-08

O take sussurrado é o defeito que **nenhum outro QC deste repo enxerga**.
`qc-ataque`, `qc-emendas-asr`, `qc-fonemas`, `audit-emendas`, `flicker-scan` e
`qc-cor` medem borda, fonema, palavra, flicker e cor. Um take baixo tem
transcript perfeito, emenda limpa, cor certa — e o espectador não ouve. A régua
de "casar por ganho antes do concat" já estava escrita nesta SKILL; o que faltava
era a ferramenta.

### As duas coisas, e por que são duas

```
ganho    é do SEGMENTO.  campo `gain_db` na EDL, resgata UM take.
teto     é da TRILHA.    perfil.audio.limiter, entra uma vez depois da soma.
```

🔴 **Ganho global é proibido.** Resgatar um take baixo com compressor ou ganho na
trilha inteira bombeia os takes que já estavam certos. É o único ponto em que
este pipeline e o ref-A concordam sem ressalva (`ref-A/SKILL.md:501`).

### Como se usa, na prática

1. `qc-nivel.py achado <dir>` mede o **bruto** e imprime `ganho_sugerido_db` por
   segmento. **Ele sugere; ele nunca escreve.**
2. O operador/agente escreve `"gain_db": 3.5` no **`janelas.json`** — nunca na
   `edl.json`, que o `bordas.py` reescreve inteira a cada passada.
3. `bordas.py` faz o campo atravessar (lista NEGRA) e `audio-exato.py` aplica.
4. `qc-nivel.py balanco <dir> --video v1-montado.mp4` **aprova** — a referência
   dele é a mediana dos *outros* ranges, independente do critério que selecionou.

⚠️ **Não persiga o número do `achado` até zero.** Ele seleciona o trecho pelo
mesmo delta que depois mede: todo run listado está abaixo do limiar por
construção, e reexecutá-lo no material já corrigido continua listando as caudas
de decaimento e as consoantes surdas da passagem que acabou de ser consertada.
Achado ≠ aprovação.

🎯 **Ajustar nível não re-renderiza nada.** O sidecar de procedência do
`montar.sh` grava `src,start,end,zoom,cx,cy`, e `gain_db` não toca um pixel:
o ciclo é *editar o `janelas.json` → rodar só o `audio-exato.py` → ouvir*, de
segundos. **Não** adicione `gain_db` ao sidecar para "consertar" isso.

### O contrato do campo

`[−24, +12] dB`, **absoluto** (substitui, nunca acumula), ausente = `0.0`.
Fora da faixa, não-numérico, ou chave parecida (`gaindb`, `ganho`, `gain_dB`) →
**`sys.exit` nomeando o beat**, e nenhum WAV é escrito. Detalhes em
`references/contrato-edl.md`.

O teto de +12 é do ref-A (`voice_levels.py:252-260`): passando disso o ruído de
sala sobe junto com a voz e "soa como outro microfone". O piso de −24 é a
fronteira em que abaixar deixa de ser nivelar e vira mutar — se o take é para
sumir, corte-o da EDL.

### O limitador: por que numpy e não `alimiter`

**Medido nesta máquina, 2026-08-08** (senoide com cliques de 10 ms, 5 s, 48 kHz):

| cadeia | amostras | deslocamento | pico 0,5 → |
|---|---|---|---|
| `alimiter=level_in=1:level_out=1:limit=0.95` (attack default 5) | 240000 → 240000 | **+239 (4,979 ms)** | **0,52631** |
| o mesmo com `:level=disabled` | 240000 → 240000 | **+239 (4,979 ms)** | 0,5 |
| `alimiter=limit=0.841:attack=4:release=60:level=disabled` (a receita da §remux) | 240000 → 240000 | **+191 (3,979 ms)** | 0,5 |

🔴 **Nunca aplique `alimiter` (nem nenhum filtro do ffmpeg com ataque) como passe
sobre o `audio-exato.wav`.** Ele atrasa o sinal em ~`attack` ms **preservando a
contagem de amostras** — desloca a trilha inteira e trunca a cauda. É deriva
constante de A/V, a mesma categoria do bug de 2026-07-25 (0,28 s em 20 emendas).
O teste de tendência **não pegaria** (a tendência é zero); a régua de ±3 ms sim.

🔴 **E `level_in=1:level_out=1` sem `level=disabled` não é transparente**: aplica
ganho de `1/limit` no sinal inteiro. Um "limitador" que **sobe** o nível de
material que não precisava de nada. O ref-A faz isso em três lugares
(`render.py:320`, `:640`, `:886`); a nossa receita de remux já usa
`level=disabled` — mantenha.

O limitador do `nivel.py` constrói um **envelope de ganho** por blocos de 1 ms e
multiplica ponto a ponto: latência **zero por construção** (medido: lag 0 na
correlação cruzada), sem look-ahead bufferizado, sem soft-knee, sem makeup.
O teto é garantido pela construção do envelope, não por medição — **não existe
`np.clip` em lugar nenhum do caminho**.

📏 **O número que justifica tudo isto**: senoide de 1 kHz 3 dB acima do teto —
`np.clip` produz **13,47 % de THD**, `nivel.limitar` produz **0,0000 %**, e os
dois saem com pico **1,000000**. Nenhum QC deste repo distingue esses dois
arquivos, e é por isso que o clipper duro tinha que sair.

Sobrou **um** `np.clip` no `audio-exato.py`, em `escreve_takes()`, e ele é da
representação (s16 não guarda `|x| > 1`), não uma escolha. Ele foi tornado
alcançável quando a SPEC-08 removeu o clipper pós-soma. Medido em 2026-08-09 com
controle plantado: `gain_db +6` num take cujo pico está longe de qualquer junção
→ `confere_picos` mede **0,000** na janela de sobreposição e deixa passar, e
4.000 de 48.000 amostras (**8,3 %**) eram ceifadas sem uma linha de aviso.
A trilha entregue não é afetada (o limitador cuida do teto depois da soma); quem
lê `audio-takes/segNNN.wav` é o `qc-ataque.py`, e sobre um take ceifado **ele
mede o clipper, não a cauda**. Desde a SPEC-06 ele diz quantas amostras ceifou,
em qual take e com qual `gain_db`. A saída em bytes é idêntica, sempre.

### O sidecar `nivel-aplicado.json`

`benchmark.nivel-aplicado/v1`, escrito pelo `audio-exato.py` **em toda execução**
(inclusive quando nada aconteceu), junto com o WAV que descreve. É o que o
`qc-nivel.py balanco` lê e o que responde "o que exatamente foi aplicado nesta
trilha".

```jsonc
{
  "schema": "benchmark.nivel-aplicado/v1",
  "gerado_por": "audio-exato.py",
  "gerado_em": "2026-08-08T23:19:50-03:00",
  "limitador": {
    "teto_dbfs": 0.0, "lookahead_ms": 5.0, "release_ms": 60.0, "bloco_ms": 1.0,
    "origem": "fallback",          // "perfil" quando veio de perfil.audio.limiter
    "atuou": true,
    "pico_entrada": 1.8711, "pico_saida": 1.0000,
    "reducao_max_db": 5.44, "blocos_reduzidos": 1305, "blocos_total": 9500
  },
  "segmentos": [
    {"i": 0, "beat": "gancho", "gain_db": 0.0, "pico_pos_ganho": 0.299988},
    {"i": 3, "beat": "cta",    "gain_db": 12.0, "pico_pos_ganho": 1.871109}
  ]
}
```

⚠️ `reducao_max_db` é a redução aplicada **ao sinal pós-ganho**, não o `gain_db`.
Um take com pico 1,0 recebendo `+3 dB` sai com `reducao_max_db ≈ 3,0`; recebendo
`+12 dB` sobre pico 0,47, sai com 5,44.

### O teto default é 0 dBFS, e é decisão

O `audio-exato.wav` é **intermediário PCM**, não entregável. O teto de entrega é
*true peak* e quem o define é o `loudnorm=…:TP=-1.5` de dois passes, depois do
mix com SFX. Pôr −1 dBFS aqui roubaria 1 dB de um estágio que vai renormalizar de
qualquer jeito, e mudaria o md5 de toda produção existente sem nenhum ganho.

⚠️ **Isto é pico de amostra, não true peak.** Um sinal a 0 dBFS de pico de
amostra pode ter pico inter-amostra acima de 0 dBTP. Esta ferramenta **não**
resolve clipping de entrega.

Com teto 0 dBFS e material que não passa do fundo de escala o limitador é
**inerte** e devolve o mesmo array: produção sem `gain_db` sai **bit a bit** como
antes. Medido em produção sintética de 4 segmentos: md5 idêntico antes e depois
da SPEC-08.

⚠️ **O look-ahead atravessa a emenda.** Um transiente logo depois de um corte
abaixa o ganho até 5 ms **antes** dele, ou seja na cauda do segmento anterior. É
comportamento correto de limitador e é inaudível nessa escala — mas **não amplie
`lookahead_ms`** "para ficar mais suave": acima de ~10 ms vira ducking audível na
costura, justamente onde este pipeline não pode ter artefato.

**Teste**: `python3 $S/tests/test_nivel.py` — 37 checagens, material 100 %
sintético, sem ffmpeg e sem creator, ~0,3 s. Três delas são **defeito plantado**:
um "limitador" que só clipa (passa no teste de teto e reprova no de THD, que é
por que os dois testes existem), a interpolação **sem** a trava anti-overshoot
(fura o teto em 1,040460) e a medição de lag que o `alimiter` reprovaria.

---

> Núcleo: [`../SKILL.md`](../SKILL.md) — as Regras Duras valem aqui.
