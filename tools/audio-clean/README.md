# audio-clean — o binário que NÃO está neste repositório

`clean-audio` usa o **DeepFilterNet3** para tirar sopro de microfone e ruído de
fundo (a "via D" da skill, a única que o creator-1 aprovou de ouvido para sopro de
lapela). O binário nativo que faz isso, `deep-filter`, **não está versionado**.

```
tools/audio-clean/
├── deep-filter          ← 27.877.081 bytes, Mach-O 64-bit arm64 — IGNORADO pelo git
├── models/bd.rnnn       ← 299.693 bytes — versionado, é o modelo do rnnoise
└── README.md            ← este arquivo
```

## ⚠️ A dívida consciente (SPEC-000 §3.9)

**Um clone novo deste repositório não roda `clean-audio` enquanto o binário não
for baixado.** Isso é decisão, não esquecimento:

- `.gitignore` da ilha tem a linha `tools/audio-clean/deep-filter`;
- a SPEC-22 §3.3 (item B2) já havia decidido que ele **sai do pacote** do produto
  e vira download por plataforma no primeiro uso, porque é `arm64`-only: não roda
  em Intel, nem Linux, nem Windows;
- 27,9 MB de binário de plataforma única em todo clone, para um recurso opcional,
  não paga.

O que quebra sem ele: só a **via D**. As vias `highpass+afftdn` e `arnndn`
(rnnoise, que usa `models/bd.rnnn`, este sim versionado) continuam funcionando —
e para o caso "sala limpa, voz baixa" a via D é **rejeitada por medição** de
qualquer forma (`clean-audio/SKILL.md:25`).

## Identidade do binário — medido nesta máquina em 2026-08-08

| | |
|---|---|
| caminho | `tools/audio-clean/deep-filter` (via symlink: `ilha/tools/audio-clean/deep-filter`) |
| tamanho | 27.877.081 bytes |
| tipo | `Mach-O 64-bit executable arm64` |
| **sha256** | `4601e7f4e4c03e59a4c5b5000216ef3add3e808799cfccd95e14e83ea4611081` |

```bash
shasum -a 256 tools/audio-clean/deep-filter
# 4601e7f4e4c03e59a4c5b5000216ef3add3e808799cfccd95e14e83ea4611081
```

**O sha256 acima é a referência autoritativa.** Confira contra ele qualquer
binário que você baixar, e não confie no nome do arquivo.

## Origem

**Projeto**: DeepFilterNet — `https://github.com/Rikorose/DeepFilterNet`
**Versão declarada**: **v0.5.6**, registrada em `clean-audio/SKILL.md:51`
(*"Binário nativo arm64 em `tools/audio-clean/deep-filter` (v0.5.6, de
Rikorose/DeepFilterNet)"*).
**Releases**: `https://github.com/Rikorose/DeepFilterNet/releases`

🔶 **O que NÃO consta em lugar nenhum desta árvore**: a **URL exata do asset**
baixado (o nome do arquivo dentro do release) e a data do download. Foram
procurados em toda a árvore em 2026-08-08 — `grep` por `deep-filter`,
`DeepFilterNet` e `Rikorose` em `.md`, `.sh` e `.py` — e não existem. O binário
tem mtime de **2026-07-22 21:04**, que é o dia em que a via D foi validada
(`clean-audio/SKILL.md`), e é o melhor que dá para afirmar sobre quando ele
chegou aqui.

Quem for reobter: baixe o asset macOS/aarch64 do release **v0.5.6**, confira o
sha256 contra o valor acima, e **anote a URL exata aqui** — foi a falta dessa
anotação que produziu este parágrafo.

## Como usar (o contrato que a skill assume)

```bash
tools/audio-clean/deep-filter -o <OUTDIR> in.wav    # depois: highpass + loudnorm
```

⚠️ Duas armadilhas medidas, ambas em `clean-audio/SKILL.md:51`:

- a saída é `<OUTDIR>/<mesmo-basename>`, **sem sufixo** — se o `OUTDIR` contiver
  o input, ele é **sobrescrito em silêncio**. Use sempre um outdir separado;
- rodar duas vezes processa o áudio **duas vezes**, e o artefato "eletrônico"
  dobra.

O binário trabalha em **48 kHz** (extraia com `ffmpeg -ac 1 -ar 48000`), não usa
torch — é tract/Rust, portanto imune ao torch quebrado desta máquina — e tem
RTF ~0,013 (20 s de áudio em 0,26 s).
