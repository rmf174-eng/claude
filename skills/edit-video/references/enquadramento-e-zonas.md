# Enquadramento, formato e zonas

> O **perfil de peça**, a janela de aspecto, o que mudou em cada script quando o formato saiu do código, e as zonas gráficas que dependem do enquadramento.

---

### 📐 O formato da peça — e a janela de aspecto (SPEC-06)

```
montar.sh <dir> [--perfil <nome|caminho.json>] [--permitir-aspecto-agressivo]
perfil.py resolver <dir> --perfil vsl        # a forma explícita, equivalente
```

`--perfil` materializa `<dir>/perfil.json` **antes** do primeiro render. Trocar
de perfil no meio de uma produção **não** exige apagar `segs/`: o
`perfil_video_sha` do sidecar invalida só o que mudou e o `montar.sh` refaz
sozinho (medido: `reels → quadrado`, 3/3 segmentos refeitos, 0 reusados).

**O bruto passa a ser sondado em TODO segmento que vai ser renderizado**, não só
nos com `zoom > 1`. Sem as dimensões da fonte não há janela de aspecto, e sem
janela de aspecto acontece isto:

> 🐛🔴 **ANAMORFOSE — o defeito que sobreviveu a quatro ondas porque nenhum QC
> olha a geometria do container.** `scale=1080:1920` sobre uma fonte 16:9 **não
> deforma o conteúdo**: o ffmpeg compensa no SAR. Medido em 2026-08-09 com o
> código da onda 4, fonte 1280×720 no perfil `reels` → o arquivo sai
> `width=1080 height=1920 sample_aspect_ratio=256:81 display_aspect_ratio=16:9`.
> Todo o resto da ilha assume pixel quadrado num quadro 1080×1920 (`Root.tsx`,
> `split-broll.py`, as zonas de UI do feed) e **nenhum QC deste repo mede SAR** —
> `qc-cor` mede cor, `qc-ataque` mede A/V, a varredura mede alpha. Verde em tudo,
> imagem espremida. População no repo hoje: **3 das 8 produções com `input/` no
> disco têm fonte 16:9**, e nenhuma delas tem `perfil.json`.

A correção é de construção: a janela do bruto passa a ter o aspecto do **alvo**
antes de qualquer escala, e a cadeia termina sempre em `setsar=1`.

**A guarda de aspecto** — porque *clamp sem guarda transforma medição-lixo em
recorte válido, em silêncio*. A régua é a distância de aspecto
`r = max(a_alvo/a_fonte, a_fonte/a_alvo)`:

| r | o que acontece |
|---|---|
| ≤ 1,15 | silêncio (9:16 → 9:16 é `r = 1,00`) |
| 1,15 – 1,40 | aviso com o % do quadro descartado |
| 1,40 – 2,00 | **aviso alto** + diz se o segmento está no `cx`/`cy` default (9:16 → 1:1 é `r = 1,78`: legítimo, mas `cy = 0.5` num quadro vertical cai no torso) |
| > 2,00 com `ajuste: "crop"` | **ABORTA**, zero segmento renderizado (16:9 ↔ 9:16 é `r = 3,16`) |

O abort propõe as três saídas reais: `"ajuste": "pad"` no perfil (entra inteiro,
com barras), `cx`/`cy` explícitos na EDL + `--permitir-aspecto-agressivo`, ou um
perfil do aspecto da fonte.

⚠️ **Limite declarado**: a janela raciocina em aspecto de **pixel**, não de
exibição. Numa fonte anamórfica (1440×1080 com SAR 4:3, que exibe 16:9) o
recorte sairia plausível e errado. Das 11 fontes em `input/` de produção deste
repo, 11 têm SAR `1:1` ou ausente — por isso é **aviso**, não abort.

**Cadências**: a régua é `sr % fps == 0`, não `fps == 30`. 24, 25, 30, 48, 50, 60
e 120 passam; `30.0` é lido como `30` (o `.0` de digitação não é erro); `29.97` é
**recusado com a fração exata na mensagem** (`30000/1001`) e a razão — 1601,6
amostras por frame não é inteiro, e arredondar por segmento é a deriva
progressiva de 2026-07-25 voltando. Não existe cadência NTSC nesta ilha, por
decisão de projeto: rejeitar, nunca aproximar.

## Zonas gráficas dependem do ENQUADRAMENTO (não copiar o layout da produção anterior)

Plano aberto (peca-04: ela de pé na cozinha) → sobra bloco de 420px no topo-esquerda, lettering de 52–64px.
Plano fechado (peca-03: ela sentada, torso ocupando o quadro) → o bloco livre estável é **240px de largura** (x≈680–925, y≈330–900) + um bolso à esquerda (x≈30–250) quando o braço está baixo. Nesse caso: fonte 38–48px, linhas curtas, e o texto longo vai pra **cartão na faixa inferior com a legenda desligada na janela** (`CAPTION_OFF`).
🆕 Plano fechado **com o creator em movimento** (nao-perdeu-a-peca-06: ela se maquiando, braços subindo e descendo o tempo todo) → **não existe bloco lateral**: o maior estável tem **120px**, e a coluna x>924 ainda é UI. Nesse caso a zona gráfica é **a roupa lisa dele** — o suéter azul-escuro dela (y≈1000–1380) é a superfície mais uniforme, escura e grande do quadro, melhor pra tinta branca do que qualquer parede. 7 dos 12 grupos daquela produção viveram ali. Regra: **quando o bolso lateral some, meça a luminância da ROUPA, não da parede.**
Medir sempre: `layout-zones.sh` por sub-janela curta de 1,5–3s (a união de 8s não sobra nada) **e** a luminância do bolso (`PIL`, média do retângulo) — é ela que decide a cor da tinta: bolso a 43–57 aceita branco tranquilo, a 90–130 exige sombra forte, acima de 150 pede tinta escura ou cartão.

# Perfil de peça (SPEC-00)

A ilha sabia fazer **um** formato: vertical Full HD a 30 fps, mono, com os pads da
creator-2, sem alvo de loudness declarado em lugar nenhum — tudo escrito à mão dentro
dos scripts. Foram medidos **54 pontos de acoplamento** (29 de formato, 7 de
áudio, 12 de ritmo/cor/loudness, 6 de configuração que só existia em prosa). A
primeira peça 16:9 do sistema virou um **fork de 175 linhas** do `montar.sh`
porque não havia outro jeito.

> **Desde a SPEC-06 esse fork é DEPRECADO por documento, não por deleção.**
> `creators/creator-1/producao/peca-09/montar-vsl.py` continua no disco
> porque a entrega dele já foi publicada e a regra de ouro é não re-renderizar
> produção publicada. O que mudou é que ele **não precisaria existir**: a mesma
> `edl.json` sai em 9:16, 1:1 e 16:9 com `montar.sh <dir> --perfil <nome>`,
> `SAR 1:1` nos três, `|áudio − vídeo| = 0` nos três. **Se for re-renderizar
> aquela VSL, use o `montar.sh` canônico com `--perfil vsl`, não o fork.**

A regra que fica, e que toda spec seguinte herda:

> **Nenhum script pode conter um valor de formato.** Se um número descreve *como
> a peça é* (dimensão, fps, sample rate, pad, alvo de loudness, zona de UI), ele
> vem do perfil. Se descreve *física* (o RMS é medido em janelas de 10 ms; o piso
> de silêncio é percentil 15 num raio de 0,6 s), pode ficar no script.  → RD-5

## Como se usa

```bash
# uma vez, no começo da produção:
perfil.py resolver <dir-producao> --perfil vsl [--creator creator-1] \
          [--set video.largura=1280 --set video.altura=720]

# depois, nada muda: todo script já recebe <dir-producao> como argumento
bordas.py <dir> ; montar.sh <dir> ; qc-fonemas.py <dir> ; ...
```

O snapshot fica gravado **com a produção**, então remontar em outubro dá o mesmo
resultado mesmo que o catálogo tenha mudado. É a mesma lógica do sidecar de
procedência que o `montar.sh` já tinha, um nível acima.

| comando | o que faz |
|---|---|
| `perfil.py resolver <dir> --perfil <n>` | resolve a cadeia de merge e grava `<dir>/perfil.json` (+ copia para o Remotion) |
| `perfil.py mostrar <dir>` · `mostrar --perfil <n>` | imprime o perfil resolvido de uma produção, ou um do catálogo |
| `perfil.py validar <arquivo.json>` | sai 1 se o schema não bater; imprime quantos nós conferiu |
| `perfil.py patch --arquivo <p.json> --bloco <chave> --de <frag.json>` | acrescenta um bloco a um perfil sob lock, recusando folha que já exista com outro valor |

Cadeia de merge, do genérico ao específico:

```
perfis/_base.json  →  perfis/<nome>.json  →  creators/<c>/perfil-overrides.json  →  --set k=v
                                                    (opcional)                        → <dir>/perfil.json
```

**Herança creator → perfil, e não o contrário.** O perfil manda no formato; o
creator manda no *look e no ritmo dentro daquele formato*. Um
`perfil-overrides.json` só pode escrever em `ritmo.*`, `cor.grade`, `legenda.*` e
`audio.loudness` — escrever em `video.*` é erro de validação. A creator-2 não "tem"
9:16; ela tem um ritmo de corte e um grade, e usa perfis diferentes conforme a
peça.

## Os quatro perfis iniciais

| campo | `reels` | `vsl` | `longform` | `screencast` |
|---|---|---|---|---|
| resolução | 1080×1920 | 1920×1080 | 1920×1080 | 1920×1080 |
| pads pre/post | 0,12 / 0,20 | 0,15 / 0,25 | 0,25 / 0,40 | 0,15 / 0,25 |
| gap_min | 0,35 s | 0,50 s | **0,80 s** | 0,50 s |
| fade_modo | `por-segmento` | **`so-descontinuidade`** | `so-descontinuidade` | `so-descontinuidade` |
| audio.canais | 1 | **2** | 2 | 2 |
| zonas_ui | Instagram | **nulas** | nulas | nulas |
| legenda | queimada, 3 palavras | queimada, 6 | `.srt`, não queimada | queimada, 6 |

`vsl` **não é reels deitado**, e cada divergência foi medida na produção
`peca-09`: 18 trocas de plano com áudio contínuo contra 1 corte de áudio
real (daí o `so-descontinuidade`); correlação de 0,9989 entre canais mas **4,6 %
de diferença em RMS** (daí `canais: 2`); **2 pausas ≥0,35 s em 189 s** de locução
(daí `gap_min` 0,50).

## O que mudou em cada script

| script | antes | agora |
|---|---|---|
| `montar.sh` | `scale=1080:1920,fps=30` em duas linhas, `-crf 16`, tags bt2020 fixas | `perfil.py sh` + `perfil.py vf` dão o filtro e o encode inteiros |
| `audio-exato.py` | **abortava se `fps != 30`** | aborta só se `sr % fps != 0`; suporta 24/25/30/32/40/48/50/60/75/80/96/100/120, mono ou estéreo, e os dois modos de fade |
| `bordas.py` | pads na flag, lista **branca** de campos | pads do perfil (flag vence), lista **negra** — campo novo do `janelas.json` atravessa para a `edl.json` |
| `qc-fonemas.py` | corte herdado calculado com `/30.0` sobre frames na taxa nativa | `fps_de(src)`, a mesma função de `cortes-do-bruto.py` |
| `qc-cor.py` | região em px e `TS = [2,10,…,70]` s | região em frações e amostras em **% da duração real** |
| `flicker-scan.py` · `cortes-do-bruto.py` · `split-broll.py` · `layout-zones.py` | rasters e zonas em px de um canvas fixo | derivados do perfil |
| `broll-source/{buscar,baixar}.py` | `fps=30`, alvo 1080×1920 | fps e alvo do perfil (`--perfil` ou `$BENCH_PERFIL`) |
| `broll-source/{buscar,baixar}.py` (SPEC-29) | gate de licença por substring de família (`"cc by-sa"` passava no teste de `"cc by"` — 24/24 medidos, 13 `CC BY-SA`); download gravava qualquer HTTP 200 e deixava `.download` órfão | gate único em `licenca.py` (cláusula antes de família, autoteste com controle negativo); validação de bytes nos dois tipos; `--tipo imagem` e `--creditos` |
| `broll-source/imagem-clipe.py` (novo) | — | foto → plano inserível; formato do perfil, look do bloco `broll.imagem`, upscale prévio contra o tremor do `zoompan` |

## 🔴 Três coisas que NÃO se faz

1. **Não aceite fps NTSC fracionário.** 23,976 / 29,97 / 59,94 são **rejeitados na
   resolução**, com mensagem nomeando o vizinho suportado. Interpolar ou
   arredondar `spf` para "suportar 29,97" é o bug de deriva progressiva de
   2026-07-25 voltando pela porta nova. A regra é **rejeitar o fps, nunca
   aproximar**.
2. **Não aplique as tags de cor por `-color_primaries`/`-color_trc`.** Neste build
   2 das 3 são silenciosamente ignoradas. O perfil traz
   `aplicar_tags_por: "setparams"`; o único lugar onde o modo antigo sobrevive é
   o `FALLBACK`, para reproduzir o passado byte a byte.
3. **Não mexa nos `segs/` sem invalidar o cache.** O sidecar de procedência agora
   carrega `perfil_video_sha`, e sidecar **sem** o campo força re-render. Sem
   isso, trocar de perfil reusaria segmento renderizado no formato anterior — o
   bug do segmento órfão (6,25 s de vídeo errado com **todos os QCs verdes**) com
   porta de entrada nova.

## Medições da entrega

| | |
|---|---|
| Literais de formato no caminho canônico | **17 → 0** linhas (15 arquivos, 3.622 linhas varridas) |
| Regressão 9:16@30 pelo FALLBACK | `md5` do vídeo **e** do áudio **idênticos** ao código anterior |
| 16:9 a 25 fps | monta; `spf = 1920`; amostras de áudio `== frames × 1920` **exato** |
| Deriva de A/V a 25 fps, 15 emendas | tendência **+0,0000 ms/emenda** |
| Junção contígua com `vsl` | **bit-idêntica** ao bruto (com `reels`, dip de fade de 15 ms) |
| `qc-fonemas` × `cortes-do-bruto` num bruto de 60 fps | **5 % → 100 %** de acordo (divergência antiga: fator **2,0×**) |

---

---

> Núcleo: [`../SKILL.md`](../SKILL.md) — as Regras Duras valem aqui.
