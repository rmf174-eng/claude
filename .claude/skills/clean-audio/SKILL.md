---
name: clean-audio
description: Limpeza de voz local — remove sopro no microfone (plosivas/vento), ruído de fundo e normaliza loudness, sem depender de Adobe Podcast. Use quando o áudio de um bruto tiver sopro, chiado, ruído ambiente, ou antes da montagem final de qualquer vídeo falado. Equivalente local do "Enhance Speech" (ffmpeg + rnnoise + DeepFilterNet).
---

# clean-audio

Bloco de pré-processamento de áudio: **bruto com sopro/ruído → voz limpa e normalizada**. Validado numa produção real com sopro em microfone de lapela, por teste A/B ouvido.

## ⚠️ REGRA: SEMPRE PERGUNTAR antes de limpar

Veredito do teste A/B, ouvido: **só a via D (DeepFilterNet) removeu o sopro de verdade**, com leve artefato "eletrônico" em alguns momentos. A via D foi **aprovada em produção real**, limpando na fonte e pondo os SFX por cima. Mesmo assim: **nunca limpar automaticamente — sempre oferecer e perguntar.** Limpeza é decisão de quem aparece no vídeo, e o artefato é audível para quem conhece a própria voz. Melhoria a testar se ele incomodar: mixar wet/dry (~80/20, `amix` do enhanced com o original) ou pós-EQ suave.

## ⚠️ MEDIR antes de escolher a via

A via D não é a resposta default — ela é a resposta pra **ruído/sopro real**. Diagnóstico primeiro:

```bash
ffmpeg -i in.wav -af ebur128=peak=true -f null -                      # nível: <-20 LUFS = falta ganho
ffmpeg -i in.wav -af "lowpass=f=100,astats" -f null -                 # sub-100Hz: rumble/plosiva?
ffmpeg -i in.wav -af "highpass=f=5000,astats" -f null -               # sibilância (pico vs RMS)
# piso de ruído: RMS das janelas mais silenciosas (numpy) — sala boa fica <= -60 dB
```

**Caso "sala limpa, voz baixa"** (medido num bruto real: −29,1 LUFS, piso −66 dB, sub-100Hz 18 dB abaixo da fala): o problema é **nível, não ruído**. A via D nesse material foi **rejeitada por medição** — o resíduo (D − só-nível) ficou a **2,7 dB abaixo do sinal**, ou seja o DeepFilterNet estava reescrevendo a própria voz; e o piso PIOROU numa das pausas (−51,8 vs −55,1 dB). Via certa: `highpass=80 + deesser + loudnorm` 2-passes.

**Métrica pra decidir**: gerar as vias, medir (a) piso nas pausas e (b) energia do resíduo `via − referência` dentro da fala. Resíduo >20 dB abaixo do sinal = a via só limpou o entorno; resíduo perto do sinal = ela mexeu na voz.

**Sibilância** aparece DEPOIS do loudnorm (o ganho sobe o /s/ junto). Calibrar o `deesser` pela razão pico/RMS da banda 5kHz+: `deesser=i=0.7:m=0.5:f=0.4` tirou 2,7 dB dos picos e só 0,8 dB do brilho médio. Um compressor split-band (crossover 5,5kHz) derrubou 3,9 dB do brilho todo — abafa a voz, reprovado.

⚠️ **`loudnorm` só aceita 192 kHz internamente**: o ffmpeg insere um resampler e o wav de saída sai em 192 kHz. Inofensivo (o mux final volta pra 48 kHz), mas não se assuste ao ler o header — e não calcule duração assumindo 48 kHz.

## As 3 vias (da mais leve pra mais forte)

🔊 🔴 **NÍVEL NÃO É ASSUNTO DESTA SKILL — as vias abaixo LIMPAM e param aí.** (SPEC-02.) Até 2026-08-08 as receitas B e C terminavam em `loudnorm=I=-16:TP=-1.5`, e isso estava errado por dois motivos independentes. Primeiro: é **passe único**, que contradiz o que este mesmo arquivo manda na seção acima ("2-passes") e que, medido em 6 entregáveis do repo, erra **1,75 LU em média, sempre para baixo** (nunca acima). Segundo: **−16 é o alvo de anúncio**, não um default de limpeza — peça orgânica segue o nível de quem fala, e as que medimos vivem a **−24,4 LUFS**. Uma receita de limpeza que crava um alvo de destino leva o número errado para toda peça que a copiar.

O caminho é: **limpar aqui, normalizar no `loudness.py`.**

```bash
# 1. limpar (esta skill)     2. normalizar (canônico, 2 passes, alvo pelo perfil de peça)
python3 .claude/skills/edit-video/scripts/loudness.py limpo.wav \
    --normalizar --perfil <reels|vsl|longform|screencast> --out limpo-norm.wav
```

Sem `--perfil`, `--alvo-i` ou `--referencia` o script sai **2** e não escreve nada: alvo de loudness não tem default. E o `--pre` dele aceita a cadeia de limpeza (`--pre "highpass=f=80,deesser=i=0.45"`) para quem quiser limpar e normalizar numa passada só — a cadeia entra **antes** do loudnorm, como em `montar-vsl.py:159`.

⚠️ **Ordem importa em duas pontas.** A sibilância (nota acima, sobre o `deesser`) aparece **depois** do ganho: o `loudness.py` avisa no stderr quando o ganho passa de 6 dB, justamente para você voltar aqui — mas ele **não** aplica de-esser por conta própria, porque a regra desta skill é perguntar antes de limpar. E o resample interno de 192 kHz do `loudnorm` (nota abaixo) já vem resolvido lá: a saída sai sempre com o `-ar` do perfil.

**B — ffmpeg clássico** (zero dependência):
```bash
ffmpeg -i in.wav -af "highpass=f=90,afftdn=nr=12:nf=-32,deesser" out.wav
# nível: loudness.py --normalizar --perfil <n> --out out-norm.wav   (2 passes, alvo do perfil)
```
Bom pra ruído estacionário leve (ar-condicionado, hiss). O `highpass=90` sozinho já mata a maior parte do THUMP de sopro/plosiva (energia <100Hz).

**C — ffmpeg + rnnoise** (`arnndn`, rede neural leve, CPU):
```bash
ffmpeg -i in.wav -af "highpass=f=90,arnndn=m=tools/audio-clean/models/bd.rnnn:mix=0.85" out.wav
# nível: loudness.py --normalizar --perfil <n> --out out-norm.wav   (2 passes, alvo do perfil)
```
Modelo em `tools/audio-clean/models/bd.rnnn` (beguiling-drafter, de GregorR/rnnoise-models). `mix<1` preserva naturalidade.

**D — DeepFilterNet3** (o "Adobe Podcast local", melhor qualidade):
```bash
tools/audio-clean/deep-filter -o <OUTDIR> in.wav   # depois: highpass+loudnorm
```
Binário nativo arm64 em `tools/audio-clean/deep-filter` (v0.5.6, de Rikorose/DeepFilterNet). Ultra-rápido (RTF ~0.013 = 20s de áudio em 0.26s). ⚠️ O output é `<outdir>/<mesmo-basename>` — **SEM sufixo**; se o outdir contém o input, sobrescreve em silêncio (e rodar de novo processa DUAS vezes = mais artefato eletrônico). Sempre outdir separado. Não usa torch (é tract/Rust) — imune ao torch quebrado da máquina.

**Ordem no pipeline com Remotion:** limpar o áudio NA FONTE (trocar a trilha do input em `public/` com `-c:v copy`, preservando as tags de cor!) e só então renderizar — assim os SFX do compositor entram POR CIMA do áudio limpo e não passam pelo denoise.

## Fluxo recomendado num vídeo

1. Extrair áudio: `ffmpeg -i video.mp4 -ac 1 -ar 48000 audio.wav` (48k: o deep-filter trabalha em 48k).
2. Limpar (D pra sopro/ruído sério; B pra retoque leve).
3. Recolocar no vídeo sem re-encode de imagem: `ffmpeg -i video.mp4 -i limpo.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k out.mp4`.
4. **Limpar ANTES de transcrever** (Deepgram rende melhor) e antes da ilha de edição.
5. A/B de ouvido é obrigatório — denoise forte demais deixa a voz "debaixo d'água"; se acontecer, reduzir `mix` (arnndn) ou misturar dry/wet.

## Sopro/plosiva especificamente

- A energia do sopro é <100Hz + rajada: `highpass=f=90` resolve 80%; o DeepFilterNet limpa o resto.
- Estouro pontual forte (P/B colado no mic): `adeclick` ajuda; caso extremo, atenuar só a janela da palavra (temos timestamps por palavra do transcript).
- Prevenção na gravação (direcional pra creator): lapela 10–15cm da boca, fora da linha do ar, ou espuma/deadcat.

## Adobe Podcast (status 2026-07)

Enhance Speech NÃO tem API pública — vive no Premiere e no Firefly Video Editor (beta; GA "later in 2026" via Firefly Services, foco enterprise). O drag-and-drop do site continua manual. DeepFilterNet local cobre o caso na prática; reavaliar quando a Firefly Services API abrir.
