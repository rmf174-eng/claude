---
name: style-extract
description: >-
  Extrai o ESTILO DE EDIÇÃO comum a N vídeos de referência e devolve um
  artefato aplicável (estilo.json + ESTILO.md) em que todo número carrega
  quantas referências o sustentam, a dispersão e a confiança. Use quando o
  creator-1 mandar vários vídeos dizendo "extrai o estilo de edição disso",
  "quero editar assim", "modela essas VSLs", ou quando um estilo precisar ser
  recalculado com referências novas. Diferente da model-edit, que responde
  "como ELE fez ESTE vídeo", esta responde "qual é o estilo DESTAS N peças, e
  o que nelas é estilo e o que é peculiaridade de uma".
---

# style-extract — o estilo de N referências, com o N sempre à vista

## Quando usar

| o creator-1 diz | você faz |
|---|---|
| manda 2+ vídeos: "extrai o estilo de edição disso" · "quero editar assim" | o fluxo inteiro desta skill |
| manda **um** vídeo: "como ele fez esse efeito?" · "modela isso" | skill `model-edit` (uma peça, prosa, gap analysis) |
| "esse estilo aqui, mas mais enxuto" | `variantes.enxuta` de um estilo já extraído — não é conversa, é campo |
| "por que meu vídeo não ficou como a referência?" | `ESTILO.md` → seção "o que VARIA": provavelmente você aplicou um `conf: baixa` |

`model-edit` é o dono dos medidores e da modelagem unitária. Esta skill é
**consumidora** deles: chama `ritmo.py`, `tipografia.py` e `deep-edit-analysis.py`
por subprocess e **não edita nenhum**.

---

## A ideia em uma frase

> **Um número sem `n` e sem dispersão é a armadilha mais cara deste repo,
> automatizada.**

As 4 VSLs de `data/advertisers/_ritmo/` cortam a 27,9 · 18,4 · 14,7 · 8,6 por
minuto. A mediana é **16,55** — um número que **não descreve nenhuma das quatro**
e que, entregue como "o ritmo do estilo", é pior que não entregar nada. O que
separa as quatro não é gosto: é a **temperatura do tráfego**. Média sem
estratificação é desinformação com cara de medição.

Por isso todo valor do estilo é um `Param` (`{v, agg, n, n_total, disp, conf,
fonte, metodo, por_ref, faltou, qualidade, nota}`) e **`conf: baixa` nunca vira
default**.

---

## O fluxo

```bash
S=.claude/skills/style-extract/scripts
C=/tmp/corpus-x          # o corpus é descartável; o que importa é o estilo

# 1. medir cada referência (idempotente — medição existente é pulada)
python3 $S/medir-ref.py <url|arquivo> --id <id> --objetivo venda --temperatura frio \
   --perfil vsl --marcos 0:00-1:22=abertura 1:22-20:45=corpo 20:45-25:31=oferta --dir $C

# 2. "vale a pena agregar isso?" — de graça, sem gravar nada
python3 $S/coerencia.py $C

# 3. agregar
python3 $S/agregar.py $C --slug <slug> --perfil vsl --nome "..."

# 4. a ficha legível
python3 $S/estilo-md.py <caminho impresso pelo passo 3>
```

Sempre **rode o passo 2 antes do 3**. Ele custa zero e responde a única pergunta
que importa antes de agregar: essas referências compartilham estilo?

### Onde a saída é gravada

`$BENCH_ESTILOS_EXTRAIDOS` → senão `intelligence/estilos/` **se `intelligence/`
existir** → senão `$ILHA_HOME/estilos-extraidos/` (default `~/.ilha`).
Nunca `intelligence/` cravado: a **skill é produto**, a **saída não** — e a
ausência de `intelligence/` é silêncio, não aviso.

---

## Os cinco scripts

| script | faz |
|---|---|
| `medir-ref.py` | 1 referência → `<corpus>/medicoes/<id>.json` (`benchmark.medicao-ref/v1`). Ingestão, ritmo, tipografia, som, semântica, guardas. `--refazer` força |
| `coerencia.py` | score, estado, clusters, denominador comum. **Não grava nada** |
| `complexidade.py` | o índice de complexidade (IC) e os 5 componentes. Roda sozinho (é como se audita a escala) |
| `agregar.py` | N medições → `estilo.json` (`benchmark.estilo-edicao/v1`), validado antes de gravar. `--validar <arquivo>` valida um estilo existente |
| `estilo-md.py` | `estilo.json` → `ESTILO.md` ao lado |

Contrato de I/O do repo: **caminho do artefato final no stdout, logs no stderr**;
tudo idempotente; refresh = apagar o artefato.

---

## 🔴 As três guardas herdadas — são código, não aviso

### (a) `cortes.py` mede a PÓS, não a montagem
No vídeo de oferta da ref-C ele achou **27 eventos e só 6 eram corte**
(`intelligence/edicao/ref-C-oferta.md:63-66`): numa edição onde a variedade
vem 100% de overlay, cada troca de camada acende o detector.

`frac_camada = tipos["troca de camada"] / cortes >= 0,40` marca a montagem como
`qualidade: suspeita` ⇒ `conf: baixa`. **Limiar validado nos dois lados**: ref-C
dá 21/27 = **0,78** (dispara, correto) e as 4 VSLs dão 0,027 · 0,011 · 0,009 ·
0,086 (não dispara, correto).

### (b) `reframe.py` NÃO roda no automático
Correlação 0,55–0,65 em talking-head de mão solta, e ele inventa uma trajetória de
zoom que não existe (`:67-69`). O extrator **nunca** emite trajetória de zoom.
`plano.gramatica` sai `null` com `conf: baixa`, e só vira medida com
`--override <arquivo>` contendo `{"plano": {"gramatica": "...", "correlacoes":
[...]}}` com **≥3 correlações, todas ≥0,75** — medidas à mão com fiducial fixo da
cena. Override que não passa nesse portão é recusado e vira aviso.

`punch_ins_por_min` vem do `deep-edit.punch_ins[]` (contagem), que é uma pergunta
diferente e não depende de casamento de imagem.

### (c) O objetivo governa, não a pessoa
Mesma creator, medida três vezes: **6 punch-ins em 96 s e 13 em 125 s** nos vídeos
educativos, **0 em 70 s** no de oferta; densidade 5–6 contra 7,4 elem/10s
(`intelligence/edicao/ref-C-oferta.md:34-45`). Agregar os três dela produz um
estilo que não é nenhum dos três.

Então: `agregar.py` **recusa** (exit **2**) corpus com `objetivo` misturado,
nomeando as refs de cada grupo. Com `temperatura` misturada ele agrega mas
**rebaixa toda a família ritmo/densidade** para `qualidade: suspeita`.

---

## Custo, e onde ele mora

Os passos de pixel (ritmo, tipografia, som) são ffmpeg local: rodam sempre na
**peça inteira**, custo zero. O único passo que custa dinheiro é o `deep-edit`
(Gemini).

```
dur <= 360 s   → deep-edit na peça inteira
dur >  360 s   → UMA janela de 90 s por bloco declarado (-ss … -t 90 -c copy)
```

Todo `Param` derivado de peça amostrada carrega a cobertura em segundos na `nota`
— **o `n` nunca mente sobre o que foi visto**.

Três formas de não gastar:

- `--sem-semantico` — pula o Gemini. Útil para iterar de graça no agregador.
- **`deep-edit.json` que já existe ao lado do vídeo é reusado**, sem chamar a API.
- `--deep-edit <bloco>=<arquivo.json>` — anexa semântica já calculada, um arquivo
  por bloco. É como o corpus de VSL longa deste repo foi montado sem gastar nada.

⚠️ O `deep-edit-analysis.py` usa `gemini-2.5-pro` por default e **não temos esse
número medido**. A única referência do repo é `docs/CUSTOS.md:34` (11 min ≈ $0,30
com Flash). Não invente um: rode com `BENCH_DEEP_MODEL` explícito e anote o custo
real no `NOTAS.md` do primeiro corpus.

E `--transcrever` é **opt-in**: o Deepgram custa dinheiro e nenhum campo
obrigatório do contrato depende dele. Ligue quando quiser `fala.palavras_por_min`
e `fala.chars_por_segundo` (que é o que converte `s_por_pagina` em palavras por
página). Acima de 3600 s ele usa `transcribe-longo.sh` — o Deepgram trunca >1h e
responde 200.

---

## As regras em texto — quem escreve e quem confere

O modelo escreve a regra; **o script confere o suporte**. O modelo não é a
autoridade sobre o próprio suporte.

1. Rode `agregar.py` sem `--regras`. As `sistema_composicao.regras_observadas` de
   cada medição saem em `regras_candidatas[]`, cruas, com `suporte: 1` e sem
   evidência timestampada — nunca em `regras[]`.
2. Leia as candidatas + as medições e escreva `regras-propostas.json`:

```jsonc
{"regras": [{
  "id": "destaque-cai-em-numero", "tipo": "o-que-destacar",
  "texto": "A segunda camada tipográfica só aparece sobre número, valor em reais ou contagem — nunca sobre adjetivo.",
  "aplicavel_por": "plano",
  "evidencia": [{"ref": "home-var1", "t_s": 412.5, "citacao": "+R$200 MIL"},
                {"ref": "ref-F-var2", "t_s": 96.0, "citacao": "100 MIL SEGUIDORES"}]
}]}
```

3. `agregar.py … --regras regras-propostas.json`. O verificador determinístico
   confere que **cada `ref` está no corpus** e **cada `t_s` cai dentro da duração
   daquela ref**, recomputa o `suporte` como o número de refs DISTINTAS com
   evidência válida, e **derruba** para `regras_candidatas[]` com o motivo tudo que
   não fecha ≥2.

Tipos: `quando-cortar` · `o-que-destacar` · `composicao` · `humor` ·
`ritmo-de-fala`. `aplicavel_por`: `plano` (vira restrição no prompt do
PLANO-EDICAO) · `prompt` · `codigo` (vira condição verificável, ex.: "legenda
desliga quando entra reel de terceiro em tela cheia" → `CAPTION_OFF` por janela).

> **O contra-exemplo que não se herda**: o ref-A resolve a camada semântica com um
> **léxico fixo escrito à mão** (`helpers/caption_style.py:25-53` — `EMPH` com
> ~80 palavras do nicho dele, `PAUSE_MS = 400`, `MAX_WORDS = 4`). Funciona e é
> honesto no comentário, mas **não aprende com referência nenhuma**. O nosso
> equivalente é gerado a partir do corpus e carrega o suporte.

---

## O estilo diz X → quem executa é Y

| o estilo diz | quem executa |
|---|---|
| `overlay_perfil` | `perfil.py resolver --set` / o `perfil-overrides.json` do creator (SPEC-00) |
| `legenda.y_centro_pct`, `s_por_pagina`, `cor_base/destaque` | `CaptionLayer` + `CaptionStyle` (`src/CaptionLayer.tsx`) |
| `montagem.cortes_por_min`, `plano_mediano_s` | leitura do plano de edição — **não** vira parâmetro de corte automático |
| `grafismo.recursos`, `elementos_por_10s` | inventário de overlays do `PLANO-EDICAO.md` — e, com `conf >= media`, viram **picks do catálogo** por `estilo.py criar --de-receita` (tabela `edit-video/references/recurso-para-slug.json`), que a galeria pré-seleciona |
| `som.lufs_integrado`, `dinamica_db` | cadeia `acompressor,loudnorm` do `montar.sh` via `audio.loudness` |
| `regras[]` com `conf >= media` | restrições **textuais** no `PLANO-EDICAO.md`, com o suporte em cada linha — saem colável por `estilo-md.py <estilo.json> --restricoes` |
| `variantes.enxuta/densa` | o "mesmo estilo, versão X" — recursos e densidade já resolvidos |
| `complexidade.ic` | conversa com o humano. **Nunca** "esta edição é 44% complexa" |

`aplica_a.formato_das_refs` é **descritivo**: serve para recusar aplicar estilo de
VSL 16:9 num reel 9:16. **O estilo nunca carrega valor de formato** — dimensão,
fps, sample rate, crf vêm do perfil de peça, e o `_schema.json` recusa gravá-los.

---

## O que NÃO fazer

1. **Não simplifique o `Param` "porque polui o JSON".** O `n`, o `cv` e o
   `por_ref` **são** a spec.
2. **Não use média, e não agregue sem estratificar.** Objetivos diferentes: dois
   estilos. Temperaturas diferentes: agrega, mas o ritmo cai para `baixa`.
3. **Não "melhore" o `cortes.py`** aqui — ele é do `model-edit`.
4. **Não rode `reframe.py` no automático**, e não emita trajetória de zoom. Nunca.
5. **Não aceite posição nem cor do Gemini.** Campo faltando fica faltando, com
   `faltou[]`. É por isso que `cor.paleta` sai como não-medido mesmo com a paleta
   do Gemini no disco.
6. **Não use `silencedetect`** para medir pausa em peça com trilha: dá "zero
   pausas". RMS em janelas de 100 ms.
7. **Não rode `ritmo.py` no default de 30 fps** em peça longa: estoura memória.
8. **Não fabrique autoridade na escala de complexidade.** As âncoras são
   convenção; grave `versao_escala` e não compare IC entre versões.
9. **Não escreva valor de formato no estilo** — nem "porque a SPEC-24 vai
   precisar". Ela vai pedir ao perfil.
10. **Não acople a creator nem a caminho absoluto.** Estilo e perfil são conceitos
    do produto; creator não é.

---

## Referências

- `references/estilo.md` — o schema comentado, campo a campo, com o porquê
- `references/_schema.json` — o contrato executável (+ `x_nucleo`, `x_conf`,
  `x_limiares`, `x_escala_complexidade`: os números moram aqui, uma vez só)
- `references/blocos.md` — a taxonomia de bloco por objetivo e o critério de
  entrada em `por_bloco`
- `references/escala-complexidade.md` — âncoras, pesos e o que o IC não é
