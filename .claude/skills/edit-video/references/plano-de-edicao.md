# Plano de edição — etapas 5 a 7

> O corpo das etapas **5 (retranscrever)**, **6 (o PLANO-EDICAO.md)** e **7 (implementação)**: o arsenal, os momentos dêiticos, a partitura de legenda, o portão de aprovação no artefato, a galeria de estilos e a biblioteca do usuário.

---

### 5. Retranscrever o MONTADO
`transcribe` no v1 final → `final-transcript/`. Timestamps já no tempo do vídeo = zero deriva. É a base de TUDO que vem depois (legendas, overlays, beats).

### 6. ⭐ PLANO DE CORTE (`PLANO-EDICAO.md` na pasta da produção)
É o raciocínio editorial que acompanha a aprovação da Fase 1. Antes de escrever,
rode a análise do transcript para identificar beats, gancho e payoff. Registre o
que entrou no corte, o que ficou de fora e por quê. **O plano abre com o veredito
do check de gancho 0–5s**: a primeira frase do montado é o gancho? Se não, qual
corte foi proposto e por quê.

Não escolha aqui animação, look ou SFX antes de o creator responder ao portão de
estilo. Depois do corte aprovado, a direção escolhida na galeria gera
`plano-visual.json`, que lista por beat:

| Janela | Fala | Visual | Zona | Decisão sonora |
|---|---|---|---|---|
| 0–8.4s | "esse ovo... casamento" | lettering anotado | topo seguro | usar `pencil.wav` em 0,4 s |
| ... | ... | ... | ... | silêncio intencional, com motivo |
**Zonas**: `layout-zones.sh` já desconta o "quadrado proibido" da UI do Instagram (topo <290px = corte 4:5 do feed; fundo >1500px = legenda/perfil; direita >924px = botões). Overlay "muito pra cima" foi feedback real — elemento gráfico vive na faixa y≈290–1500, tipicamente no bloco livre lateral.
**A lista canônica do arsenal é `tools/remotion-compositor/catalogo/catalogo.json`** (SPEC-15) — 47 estilos em 5 grupos (`gramatica` · `gancho` · `legenda` · `grafismo` · `tema`), 39 deles `pronto` com preview renderizado; **no pacote instalado são 46 e 38**, e o `remotion-compositor/SKILL.md` explica por que, cada um com `oQuePinta` em uma frase, os parâmetros com faixa, a `camada` em que age (`edl`/`pixel`/`alpha`), em que perfis é oferecido e um preview renderizado pelo próprio componente. Consulte por `jq -r '.estilos[] | select(.estado=="pronto") | "\(.grupo)\t\(.slug)\t\(.oQuePinta)"' tools/remotion-compositor/catalogo/catalogo.json`. Estilo novo se REGISTRA lá (`npm run catalogo`), nunca se copia de uma produção para outra — a regra e os 5 passos estão em `.claude/skills/remotion-compositor/references/catalogo-de-estilos.md`. O resumo em prosa abaixo continua valendo como orientação rápida, mas quando os dois divergirem, o `catalogo.json` ganha.

Arsenal disponível (detalhes na skill `remotion-compositor`): legendas animadas + modo ênfase · postit/cartão pop-in (com `x`/`width`/`fontSize`) · pilha de cartões · painel-atrás-da-pessoa (recorte por scripts/matte.py, Vision) · write-on manuscrito (sem movimento!) · TypeOn nota digital · seta/sublinhado/círculo mão-livre · marker word · **cenas conceituais custom** (kinetic type que EXEMPLIFICA o conceito — ex.: AhaScene da peca-04, palavra SUBMISSÃO se partindo em SUB|MISSÃO; o Remotion é React, dá pra construir QUALQUER visual/analogia, com SFX próprio — preferir isso a só empilhar texto quando o momento é o coração do vídeo) · SFX (pop/whoosh/pencil/typing + vias de aquisição) · 🆕 **título de gancho type-on** (`HookTitle`: caps condensada digitando com cursor + serif itálica em pop seco) · 🆕 **legenda com estilo por creator** (`CaptionLayer`/`CaptionStyle`, com `highlight: null` pra legenda chapada) · 🆕 **split-screen com b-roll e borda esfumaçada** (`scripts/split-broll.py`, fora do Remotion — mexe nos pixels do vídeo; o b-roll vem da skill `broll-source`). ⚠️ Duas pegadinhas medidas: (1) o b-roll **não precisa cobrir o frame inteiro**, só até o fim da máscara (~51% da altura) — forçar 16:9 a cobrir 9:16 é recorte de 3,2×, cobrir só a faixa é 1,6×, e é por isso que footage landscape de stock serve; (2) **nunca extraia b-roll de um vídeo já COMPOSTO** fora da faixa 100% opaca — o recorte traz a camada de baixo junto e ela reaparece como fantasma semitransparente no feather (aconteceu, o creator-1 viu) · 🆕 **alternância de enquadramento** (`zoom`/`cx`/`cy` na EDL).
**Insert gerado** (skill `omni-insert`, opcional): quando um beat pede uma IMAGEM que o Remotion não faz. Três formas, em ordem de fidelidade ao material real: **`edit`** (mexe NA cena com o creator em quadro — inserir elemento, relight, trocar fundo; janela ≤4s, enviada COM áudio, e o Omni devolve a voz dele preservada com lip sync), **`anim`** (anima o cenário real do creator a partir de um frame sem ninguém em quadro) e **`gen`** (cena nova cobrindo a janela enquanto a fala continua). Entra no plano visual como qualquer efeito — janela, prompt e transição explícitos, sujeito aos mesmos gates — e custa ~$0,10/s, então é pontual, não rotina.
**Apresentar o plano ao creator-1 e esperar OK antes da etapa 7.** (A não ser que ele mande "vai direto".)  → RD-1

🆕 **Se já existe um montado (`v1-montado.mp4` ou melhor), suba o preview junto com o plano** — o markdown descreve o efeito, o preview mostra o corte. É o `preview/README.md` da própria skill, 5 chamadas, sem `sleep`:
`servidor.py sessao --dir <dir-producao>` → `servidor.py servir` (Bash com `run_in_background: true`) → `curl -sf --retry 40 --retry-connrefused` no `api/saude` → `open` da URL **e a URL impressa no chat** → tool `Monitor` no `watch-preview.py`, **no mesmo turno**. Sem o `Monitor`, ele salva, vê o toast e nada acontece — a falha é silenciosa dos dois lados.

### 7. Implementação (skill `remotion-compositor`)
captions.json + overlays.json (+ componentes novos se o plano pedir) → stills de validação → render alpha (`Graphics`) → composição ffmpeg sobre o v1-sdr.  → RD-11
Se o plano tiver painel-atrás-da-pessoa, o recorte sai de `scripts/matte.py`
(Vision, 0 B de instalação) e passa OBRIGATORIAMENTE por `scripts/qc-alpha.py`
antes de compor — guard de alpha escrito com `ffprobe` sozinho é cego pra WebM
por construção, e já fez três leituras independentes darem um arquivo correto
como quebrado (SPEC-03 §1.2).
Se o plano tiver insert gerado, ele entra **antes** da camada gráfica: `v1-graded` → `omni-insert/encaixar.py` → composição do `.mov` alpha por cima (senão as legendas somem na janela do insert).

## Quando o beat pede uma FOTO, não um vídeo

Nem todo apoio visual é footage. Um beat que nomeia um **referente único** — "o Cristo
Redentor", "o Neymar", "a capa daquele livro", "o gráfico do Banco Central" — não tem
resposta em stock: pessoa pública e monumento identificável não são material de banco de
imagem comercial. Para esses, o caminho é:

```bash
python3 ../broll-source/scripts/buscar.py "Cristo Redentor" --tipo imagem --n 6 > /tmp/c.json
python3 ../broll-source/scripts/baixar.py --json /tmp/c.json --i 0 --nome cristo
python3 ../broll-source/scripts/imagem-clipe.py <BROLL_DIR>/imagens/cristo.jpg broll/cristo.mp4 \
        --dur 4 --movimento zoom-in --foco centro --dir-producao .
python3 scripts/split-broll.py v1-montado.mp4 broll/cristo.mp4 5.17 9.17 v2-split.mp4 --broll-foco centro
```

O `split-broll.py` **não muda**: ele recebe um `.mp4` e o `imagem-clipe.py` entrega um
`.mp4`. Uma JPEG passada direto ali produziria um stream de **1 frame**.

Três coisas que o plano de edição precisa saber:

- **O formato do plano derivado sai do perfil de peça**, como todo o resto. `--dur`,
  `--movimento` e `--zoom-max` sobrepõem pontualmente; o default por peça está no bloco
  `broll.imagem` do perfil (`reels` 4 s/zoom 1,15 · `vsl`/`longform` 6 s/1,10 ·
  `screencast` **estático** 5 s, porque ali a imagem é evidência de UI e mover atrapalha
  ler).
- **Crédito é a regra em imagem, não a exceção**: ~78% das fotos aprovadas exigem
  atribuição (contra 0 dos clipes de vídeo da biblioteca). `baixar.py --creditos` imprime
  a linha pronta para a legenda, e o clipe derivado carrega um sidecar `<saida>.json` com
  licença, autor e página — senão a licença morre na primeira transformação.
- **Marca e pessoa** são muito mais fáceis de pisar em foto: o Commons é cheio de logo e
  fachada, e a busca por nome de marca funciona. Vale a regra que já está aqui — para "o
  McDonald's vende mais", hambúrguer genérico. E foto de pessoa pública em contexto
  editorial ≠ foto de pessoa pública ao lado da oferta.

### O split não é só "empurrar a base": o enquadramento é MEDIDO (SPEC-28)

`pad`+`crop` é translação pura. Com `--desloca-base` fixo, **onde o rosto
aterrissa é efeito colateral de um número copiado de uma referência** — e o
número estava errado para as duas produções deste repo.

**Medido em 2026-08-09** no `estudos/modelagem-ref-D/v2-split.mp4` **entregue**,
com matte de pessoa (Vision) na base e 35 amostras a 4/s:

| | topo da cabeça na saída | b-roll sobre o cabelo |
|---|---|---|
| entregue (constante 25 %) | 480 px de deslocamento | **mediana 12,20 % · máx 13,48 %** |
| com `split-plano.json` | 620–624 px, medidos por segmento | **mediana 0,00 % · máx 0,00 %** |

O fluxo novo, três comandos:

```bash
python3 scripts/split-plano.py <dir> --janela 5.20 13.20      # mede a cabeça, encaixa a janela
python3 scripts/split-broll.py <base> <broll> <t0> <t1> <saida> --plano <dir>/split-plano.json
python3 scripts/qc-split.py <saida> --plano <dir>/split-plano.json --folha folha-split.png
```

**Sem `--plano` o `split-broll.py` é byte a byte o de hoje** (md5 conferido) e
avisa no stderr. O contrato completo está em `references/contrato-split.md`.

#### Quatro coisas medidas que custaram tempo e valem para além do split

1. 🔴 **O detector de cabeça por massa escura pega o cenário.** A medição
   original desta spec usava "massa escura sustentada na faixa horizontal do
   sujeito" e reportou o topo da cabeça variando **96 px** na janela de 8 s, com
   saltos nas fronteiras de segmento. **Não é a cabeça**: os quatro segmentos têm
   `zoom: 1.0` e nenhum `cx`/`cy`, ou seja o enquadramento é o MESMO nos quatro.
   O que o limiar de luma achava era **uma coluna escura do cenário atrás dele**.
   Com o matte de pessoa, a amplitude na janela inteira é **3,5 px** e não há
   salto nenhum. É a mesma família do `enquadrar.py` do creator-3, que precisa de
   `LIM=92` calibrado *para aquela sala*.
2. 🔴 **Portão ancorado no valor que ele deveria conferir mede a âncora.** A 1ª
   versão do `qc-split.py` procurava o deslocamento em ±8 px do que o plano
   dizia. No arquivo entregue (deslocamento real 480 px, plano 621 px) ela
   devolveu o extremo da janela — 613 px, correlação **0,26** — e a checagem
   seguinte usou esse número como medida boa e **aprovou o arquivo defeituoso**.
   Com busca larga, o mesmo arquivo dá 480 px com correlação 0,9998 e reprova.
3. 🔴 **`ffmpeg -ss <t>` devolve frames DIFERENTES de dois arquivos com GOPs
   diferentes.** Comparando base × saída por `-ss`, a correlação caía para 0,981
   e acusava 4 px de erro inexistente; por `select=eq(n,K)` dá 0,9997. Quando o
   que se compara são dois arquivos, **frame é índice**.
4. ⚠️ **Não dá para achar a cabeça do creator na composição.** O b-roll do
   estudo é um balcão de fast-food *com gente dentro*: o Vision segmenta o
   figurante junto, e o portão devolveu `alpha 100 %` em 35/35 amostras de uma
   composição **certa**. A cabeça é medida na **base**; a transformação, na
   **saída**.

# Momentos dêiticos — onde o roteiro PEDE apoio visual (SPEC-27)

A etapa 6 manda rodar o `layout-zones.sh` "nas janelas candidatas". Até aqui, quais
janelas era leitura livre: `grep -riE "dêit|deitic|olha isso|presta atenção" .claude/`
devolvia **0 linhas**. O `deiticos.py` responde essa pergunta, e só ela.

```bash
S=.claude/skills/edit-video/scripts

# etapa 2 — antes de cortar: existe beat de apoio? em que take?
python3 $S/deiticos.py <dir> --base bruto --por-take

# etapa 6 — a linha "Efeito proposto" do PLANO-EDICAO deixa de nascer de leitura livre
python3 $S/deiticos.py <dir> --gravar
tools/remotion-compositor/scripts/layout-zones.sh <dir>/v1-sdr.mp4 \
    $(python3 $S/deiticos.py <dir> --janelas) --samples 6
```

E, na etapa 1, a companheira dele do outro lado do pipeline:
`timestamped.py <take-N> --silencio` lê os takes em unidade de **4–6 s** em vez do
parágrafo de 18–32 s — que é o que torna a unidade candidata a corte.

## O sinal está no texto, não na imagem

Quando o creator diz *"olha isso"*, *"vou te mostrar"*, *"presta atenção"*, ele está
apontando. É ali que entra b-roll, cartão, zoom ou split. E é ali que **nenhum
detector de imagem acha nada**: a pessoa continua parada falando para a câmera, o
frame anterior é igual ao próximo, `scdet` e o filtro `scene` devolvem zero.

O `deiticos.py` é **puro texto**: lê `transcript.json`, escreve `deiticos.json`
(`benchmark.deiticos/v1`, contrato em `references/contrato-deiticos.md`). Não abre
vídeo, não decodifica áudio, não roda ffmpeg, não escreve `edl.json`,
`janelas.json`, `captions.json` nem `partitura.json`. Sem `--gravar` não escreve
nada (verificado: md5 da pasta idêntico).

## 🔴 Duas coisas que ele NÃO é

**Não é planejador de overlays.** Ele responde *"onde o roteiro pede
EXPLICITAMENTE apoio visual?"*. Zero achados significa "nenhum apoio pedido", não
"nenhum overlay nesta peça". Medido nos **10 brutos da creator-2** (1.031 s):
**3 janelas** no total — `desse jeito`, `aqui está`, `isso aqui` — e **0** nos
3 brutos do creator-3 (447 s). Está certo: o formato dela é frase-na-tela, monólogo
para a câmera, sem prop; **não há nada sendo apontado**. As produções dela têm 12
grupos de overlay cada, e nenhum deles nasce de dêixis — nascem de ênfase e de
estrutura de roteiro. Se o detector acusasse 12 janelas ali, ele estaria errado.
No material em que **há** apontamento ele fala: `peca-11/take-A`
(entrevista, 508 s) → **12** janelas, 11 delas de classe `exemplo`;
`aula-longa-01` (aula com tela, 2 h 16) → **81**.

**Não é QC.** Não reprova, não entra na bateria, não tem limiar de aprovação. É
insumo de decisão. O único exit ≠ 0 é o clamp (abaixo).

## A janela é candidata, não corte

O `deiticos.json` carrega `"fronteira": "candidata"` literalmente. O start/end do
ASR não é verdade acústica — 86 % dos gaps do Deepgram são 0,000 s e o início de
frase cai +98 ms para dentro do silêncio real. Quem acha borda é o `bordas.py`.

## As guardas, e o defeito que cada uma impede

| guarda | o defeito |
|---|---|
| **antipadrão por token** com guarda de pontuação | `olha` é ambíguo: imperativo em *"o problema está aqui, olha"*, 3ª pessoa em *"quando a gente olha esse funil"*. A comparação é **por token** (substring faria `ele` casar dentro de `nele` e matar *"…de funil nele, olha isso aqui"*) e é cancelada por qualquer `,.;:!?` entre o token e o gatilho (senão *"…ia atrás de você, olha, tivemos quatro…"* morria). Medido no corpus: **15 achados mortos de 728** (2,1 %), tokens `você` (8) e `gente` (7) |
| **ancoragem por PALAVRA** | usar a frase como janela é a armadilha do protótipo: `peca-11/take-A` tem uma frase de **69,4 s**. Um mapa `char → índice da palavra` transforma o match de regex em timestamp |
| **longest-match-wins** | `olha só` casa `olha-ostensivo` **e** `olha-solto` e emitiria dois achados no mesmo instante |
| **fusão de janelas** | três `isso aqui` em 10 s não são três beats, é um |
| **teto de densidade** (`apoio_visual.max_por_min`) | um relatório que acende sempre não é informação. Corta por peso e **grava o que cortou** em `descartados[]` |
| **clamp de duração** | é o bug do `grab_cues` do ref-A (`watch_video.py:166,178-180`): lá o cue além do fim **some em silêncio** e o relatório só imprime um `cues=` menor. Aqui a janela é aparada, sai com `"aparada": true`, entra em `resumo.n_aparadas` — e se o clamp **zerar** a janela o script **sai 1** |

Densidade no corpus inteiro (200 transcripts, 17,78 h, 188 peças com ≥10 s):
**p50 0,45 · p75 0,91 · p90 1,42 · máx 4,96 por minuto**, e **44 % das peças saem
com 0 janelas**. Se a p90 passar de 2,5, alguma entrada do léxico está larga demais.

## O léxico é DADO, e cada entrada tem número na frente

`references/lexico-deitico-pt.json` (`benchmark.lexico-deitico/v1`): 13 entradas,
**11 ativas e 2 candidatas**, todas levantadas do corpus deste repo (200
transcripts, 183.052 palavras) e não inventadas. Quatro expressões estão em
`descartadas[]` **com o motivo**: `repare` (0 ocorrências — em pt-BR falado o
Deepgram escreve `repara`), `como você pode ver` (0 — é a expressão da docstring do
ref-A, inglês traduzido), `presta bem atenção` (0 — coberta) e `nota (só|bem|…)`
(2 de 2 eram o substantivo: *"minha nota só dava pra cursar estatística"*).

Expressão nova entra **medida**, nunca por gosto:

```bash
python3 $S/deiticos.py --frequencia "\bo teu ponto\b" --corpus data creators
# ≥5 ocorrências em ≥3 arquivos E uso ostensivo em ≥10 dos 15 contextos.
# Abaixo disso entra como "status": "candidata" e NÃO produz janela.
```

Três portas de extensão que não tocam o arquivo canônico: `--lexico <arquivo>`
(mescla por slug, o de fora vence), `<creators>/<nome>/lexico-deitico.json` via
`--creator <nome>`, e `apoio_visual.classes_off` no perfil de peça.

## Onde os números moram: `perfil.apoio_visual`

Bloco novo no perfil de peça, gravado por `perfil.py patch --bloco apoio_visual`.
Nenhum limiar é constante no script (`grep -nE "1080|1920|fps=30|48000|0\.5\b"` no
`deiticos.py` → **0 linhas**); sem perfil, o script cai no `FALLBACK` e diz isso no
JSON (`origem_gap_min`, `origem_apoio_visual`).

| perfil | `janela_s` | `max_por_min` | `classes_off` | por quê |
|---|---|---|---|---|
| `reels` | 2,0 | 2,0 | — | 1,5–3 s é a janela em que o `layout-zones` sobra zona |
| `vsl` | 3,0 | 1,5 | — | peça argumentativa: apoio dura mais e aparece menos |
| `longform` | 4,0 | 1,0 | `["enumeracao"]` | em aula longa `primeiro/segundo` é estrutura de fala o tempo todo (medido: 85 ocorrências em só 7 arquivos) |
| `screencast` | 4,0 | 3,0 | — | é o formato em que a dêixis é o conteúdo |

O limiar de frase é o **mesmo `ritmo.gap_min` do corte** — não inventamos um
segundo número. A régua da leitura passa a ser a régua do corte.

**Teste**: `python3 $S/tests/test_deiticos.py` — 23 checagens, material 100 %
sintético, e as guardas são testadas **plantando o defeito** que cada uma tem que
acusar (substring no antipadrão, guarda de pontuação removida, clamp desligado).

## Etapa 6b — a partitura acompanha o plano visual (SPEC-14)

Depois da montagem e antes de escrever TSX, roda o **diretor de legenda**. Ele
transforma o `captions.json` numa **partitura**: quais palavras viram tipografia, com
que componente, em que canal e por quê — com o número medido no áudio ao lado de cada
escolha.

```bash
S=.claude/skills/remotion-compositor/scripts
D=creators/<n>/producao/<slug>
python3 $S/diretor-legenda.py $D --audio $D/v1-graded.mp4 --tema <tema> \
        --perfil .claude/skills/edit-video/perfis/<perfil>.json
python3 $S/diretor-legenda.py md $D/partitura.json
python3 .claude/skills/remotion-compositor/scripts/compilar-plano-visual.py \
        $D preparar
python3 .claude/skills/remotion-compositor/scripts/compilar-plano-visual.py \
        $D renderizar --saida graphics-alpha.mov
python3 .claude/skills/remotion-compositor/scripts/compilar-plano-visual.py \
        $D compor-final --base v1-montado.mp4 --saida v-final.mp4
```

O compilado e os assets SFX ficam somente em `$D/remotion/`. O render oficial
passa `partitura-compilada.json` em `--props` e `remotion/public` em
`--public-dir`; nenhum estado da peça é copiado para `tools/.../src/data/`.
Na composição final, o gráfico passa por `unpremultiply + overlay`; quando o
plano usa SFX, o áudio do MOV é somado ao áudio base com `amix normalize=0`.

O `PARTITURA.md` entra na Fase 2, depois da escolha de acabamento: é onde o creator vê
o que entrou **e o que quase entrou** (`descartados[]` com motivo). O que ele mudar
volta marcado `"travado": true` e sobrevive byte a byte à próxima execução; o que ele
cortar volta `"removido": true` e não é reocupado.

**Áudio**: use o **pré-limiter** (`v1-graded`/`v1-montado`). Medido na
`peca-02`: o realce p90 cai de **+2,83 dB** no áudio do bruto para **+1,92 dB**
no `v1-graded`. Se só houver o entregável, o `_procedencia` grava
`audio_e_entregavel: true` e o script avisa no stderr.
⚠️ `peca-05/v1-graded-pele.mp4` **não tem faixa de áudio nenhuma** — ali o áudio
é `audio-tratado.wav`, e o `--audio` é obrigatório.

### 🔴 O resultado que não se confirmou, e que vale mais que um verde

A spec apostava que **prosódia medida** escolheria melhor que texto puro (é o que o
diretor do ref-A não tem). Contra o único ground truth aprovado do repo — os 19 beats
falados da `peca-02`, extraídos do `peca-02.tsx` publicado — a aposta **não se
confirmou**:

| | recall |
|---|---|
| acaso (21 sorteios, 4000 réplicas) | **19,9 % ± 7,8** · p95 **31,6 %** |
| eixo prosódia sozinho | **10,5 %** ← abaixo do acaso |
| eixo léxico sozinho | 15,8 % |
| eixo posição sozinho | 31,6 % |
| eixo repetição sozinho | **36,8 %** ← único acima do p95 do acaso |
| **pesos da spec** (prosódia 0,45): prosódia × só-texto | **26,3 % × 31,6 % = −5,3 pp** |
| pesos medidos (prosódia 0,20): prosódia × só-texto | 36,8 % × 26,3 % = +10,5 pp |

A spec pedia **≥ 15 pp** de ganho e **≥ 50 %** absoluto. Nenhum dos dois.

**A causa, medida**: o realce das 52 palavras que o editor humano escolheu é
**−0,46 dB** contra −0,21 dB das outras 205 (t de Welch −0,90); no áudio do bruto,
−0,13 × −0,09 (t **−0,10**). **Nesta creator, a palavra que vira tipografia não é a
palavra dita com mais força** — "cansaço" sai a −3,5 dB e "metade" a −3,1 dB. A
premissa "ela gritou aquela palavra" não descreve esta fala.

O peso de prosódia caiu de 0,45 para **0,20** nos perfis, e a justificativa é a medição
**por eixo** (10,5 % contra um acaso de 19,9 %), não o número composto. ⚠️ A segunda
linha da tabela é **pós-hoc na mesma amostra, sem holdout**: não é evidência de que a
prosódia ajuda, só o registro de que um peso pequeno não atrapalha e um peso grande
atrapalha. Para virar evidência faltam 2–3 peças com ground truth aprovado.

**O que sobrevive intacto** (e é o entregável): a partitura como **dado auditável**, a
paginação decidida fora do componente, o `legenda_off` ancorado, o `por_que` com o
número medido em cada item, e a doação de fronteira que zerou os 5 solos curtos da
SPEC-13.

### A janela de supressão deixa de ser escrita à mão

Medido nos dois lados, sem render, sobre o `peca-05`:

| | janela declarada | buraco real | excesso |
|---|---|---|---|
| janela **escrita à mão** `[42,92 → 46,54]` sobre a paginação por tempo | 3,620 s | **4,217 s** | **+0,597 s** |
| janelas **ancoradas** pelo diretor (3) | — | — | **+0,113 s** (pior) |

O limite do critério é +0,120 s. (O registro em `edit-video/SKILL.md:155` fala em 2,1 s
de tela sem legenda; não consegui reconstruir esse número exato a partir da janela
citada — o que medi com o modelo é o excesso de +0,597 s acima. Fica declarado assim
em vez de forçado a bater.)

🔴 **Não amplie a janela "para garantir".** Se a fronteira não couber, mova o elemento
gráfico: nas duas produções aprovadas o conflito era **geométrico**, e as duas
terminaram com `CAPTION_OFF: []`.

## Portão de aprovação no artefato — o contrato da UI

A partir da SPEC-16 existe um **contrato de dados** entre a ilha e a UI de
aprovação, e ele muda o papel do `PLANO-EDICAO.md`.

| | antes | depois |
|---|---|---|
| o que o creator-1 aprova | o texto do plano | **o render**, com o plano ao lado |
| o que o plano de corte carrega | tudo, inclusive o pedido de OK | as **decisões do corte e o porquê**: veredito do gancho 0–5 s, o que ficou de fora e transições editoriais |
| onde a aprovação fica | numa mensagem de chat | em `estado.aprovacoes[]`, confrontável com o disco |

Look, animações, zonas gráficas e SFX ficam no `plano-visual.json`, criado depois
do estilo. Essa separação impede o plano de corte de prometer uma animação que o
creator ainda não escolheu e mantém a aprovação da Fase 1 independente da
implementação visual.

O que o plano tem e uma timeline nunca vai ter é o **raciocínio**: *"este gancho
abre no `vem cá, deixa eu te contar` e por isso propus cortar 3 s"* é prosa, não é
um bloco na tela.

### Os arquivos

Tudo dentro de **`<dir-producao>/.preview/`** — o diretório da produção chega por
argumento, e nenhum script daqui conhece `creators/`.

```
<dir-producao>/.preview/
├── estado.json          o estado, DERIVADO do disco por `estado.py`
├── estado-agente.json   o que o agente declarou (fase, mensagem, portão, aprovações)
├── pendentes/*.json     o que o usuário salvou na UI      (servidor, SPEC-17)
├── aplicados/*.json     o mesmo arquivo depois do ACK — o ACK é o MOVE, não o delete
├── ajustes.json         canal de volta SEM servidor (agente à mão, teste)
└── estilo.json          idem, para o portão de estilo
```

### Comandos

```bash
S=.claude/skills/edit-video/scripts

# gerar/atualizar o estado (as flags do agente PERSISTEM entre chamadas)
python3 $S/estado.py <dir-producao> --fase 1 --mensagem "corte montado, aguardando OK" \
                                    --render v1-montado.mp4

# registrar a aprovação (fica presa ao sha256 do plano e ao fingerprint do render)
python3 $S/estado.py <dir-producao> --aprovar fase-1 --por creator-1

# o que o usuário mandou de volta, e aplicar um por vez
python3 $S/estado.py <dir-producao> --pendentes
python3 $S/estado.py <dir-producao> --consumir ajustes     # ou estilo, ou o caminho do arquivo
```

`--consumir` imprime o **resumo** no stdout, move o arquivo para `aplicados/` e
registra `ultimo_ajuste_aplicado` no estado. Se o corte ou o render mudaram desde
que o usuário salvou, ele **sai 2 e não move nada** — não aplica às cegas.

### O que o estado mostra e nenhum QC nosso mostrava

`integridade` põe na tela os dois defeitos que ficam **verdes em todos os QCs**:

- **segmento órfão** — `.mp4` no disco sem entrada na EDL. É o que deixou o
  `c-completo` do creator-3 **6,25 s** mais longo com tudo verde. Medido hoje:
  `ovo-de-pascoa` tem **22** `.mp4` contra **21** na EDL e sai `veredito:
  "quebrado"`.
- **procedência por sidecar** — `ok` / `ausente` / `divergente` / `orfao` /
  `nao_renderizado`, por segmento, em vez de um `sys.exit` dentro de um script.

🔴 **`estado.py` REPORTA, NUNCA CONSERTA.** Não apaga órfão, não regrava sidecar,
não recorta segmento. É o que permite rodá-lo, sem medo, sobre as produções já
publicadas — que a linha 62 deste arquivo proíbe remontar.

### As três regras que valem para quem for consumir o contrato

1. **Referência a segmento é por `sid`, nunca por índice.** `sid` é derivado
   (`<beat ou basename do src>#<ordinal>`), estável sob reajuste de borda e não
   persistido em lugar nenhum. Medido: mover 5 segmentos de `peca-01` em
   ±0,30 s preserva **29/29**; remover o 8º de 20 em `peca-03` preserva os
   **19/19** restantes.
2. **Coordenada de render só com `timeline_real` (SPEC-05).** Sem ela,
   `notas[].render` é `null` — nunca `Σ(end−start)`. A soma nominal erra
   **353,3 ms** em `peca-03`, **316,7 ms** em `peca-01` e **351,7 ms** em
   `c-completo`, sempre para menos.
3. **Nenhum valor de formato.** Largura, altura, fps e zonas saem do
   `perfil.json`; sem perfil, são **medidos** por ffprobe e o campo
   `formato.fonte` diz `"medido"`.

O contrato inteiro, com os três schemas e o ciclo de vida de cada arquivo, está em
**`references/contrato-ui.md`** — é a fonte de verdade para a SPEC-17 (servidor),
a SPEC-18 (timeline) e a SPEC-19 (galeria).

**Teste**: `python3 $S/tests/test_contrato_ui.py` — 79 checagens, material 100 %
sintético, com **18 defeitos plantados** que o mecanismo tem que acusar (órfão,
sidecar divergente, índice posicional no canal de volta, coordenada de render
forjada sem timeline, `revisao_base` no futuro, plano editado depois de aprovado,
dois saves do mesmo tipo na fila). `--rapido` pula o que chama o `montar.sh`.

### A timeline interativa, e a marcação IN/OUT com instrução (SPEC-18)

O contrato acima é o que a UI lê. A **app** que o consome vive em
`preview/app/` e é servida pelo `--app` do `servidor.py` (SPEC-17) — nenhuma
linha do servidor muda para ligá-la.

```bash
S=.claude/skills/edit-video
D=<dir-producao>
python3 $S/scripts/estado.py "$D"                       # o estado, derivado do disco
python3 $S/preview/servidor.py sessao --dir "$D"        # imprime a URL com token
python3 $S/preview/servidor.py servir --dir "$D"        # em background
python3 $S/preview/digest-marcacoes.py "$D"             # o que o creator-1 pediu, acionável
python3 $S/preview/digest-marcacoes.py "$D" --ack       # move para .preview/aplicados/
```

**O que a app resolve.** O canal de volta era prosa sem coordenada. Agora o
creator-1 para a agulha, aperta **M** (ou **I**/**O**), navega, aperta **M** de novo
e escreve o pedido em português. A nota sai com o instante exato **no arquivo que
existe** — e o digest traduz aquilo para o que o agente vai editar: o **take**, a
coordenada no **BRUTO**, a fala literal da `captions.json` e as camadas presentes.

🔴 **A coordenada vem do `video.currentTime`, nunca da geometria da timeline.**
A agulha é desenho; o tempo é do player. É por isso que a marcação sai exata
mesmo sem `timeline_real`, quando a régua desenhada erra 316,7 ms no fim da
numa das peças medidas — e é por isso que **nenhum número derivado de `Σ(end−start)`
entra em arquivo**, nem como fallback.

O que a régua aproximada afeta é só o `sid`, e ele viaja com
`sid_confianca: "aproximada"`. O digest recalcula o take por régua **medida** e
**diverge em voz alta** quando não bate. Medido em material real: a marcação em
52,300 s da `peca-01` sai `de-novo-ai#1` pela régua somada e `e-se#1` pela
medida — o digest imprime as duas.

**O que a app NÃO faz**: editar o corte. Trim e remoção são incremento B2, e a
razão é o bug do ref-A (`app.js:752-753`, `:1826`): remover um take desalinha
`draft`/`rendered` **para sempre** e toda nota salva depois aponta para o take
errado. Quando B2 entrar, o canal de volta leva **operações por `sid`**, nunca um
array reconstruído.

**Trilha sem dado desenha faixa hachurada com o que falta**, não faixa vazia:
hoje gráficos (57 `OverlayGroup` em 5 `.tsx`, tempo na prop), b-roll, insert e
SFX aparecem declarando a ausência. Faixa vazia mente; a hachurada é o argumento
a favor de mover aquilo para dado.

**Medido na entrega** (`peca-01` e `peca-09`, 2026-08-09):

| o quê | número |
|---|---|
| atribuição de take, varredura dos 29 | **29/29**, com `src_ini/src_fim` dentro de 1 frame |
| a régua proibida (`Σ end−start`), controle negativo | **118 de 2123 frames (5,6 %)** caem no take errado, afetando **25 dos 29** takes |
| filmstrip: defasagem imagem × posição | **0,000006 s** em 91 thumbs (teto por construção: `intervalo/2`) |
| o mesmo cálculo pelo algoritmo do ref-A | **1,976 s** — o bug não foi herdado |
| digest com `timeline_real`, `PATH=/usr/bin:/bin` | exit **0**, `ffprobe_invocado: false` |
| `seek → seeked` no render, 20 buscas | mediana **41,4 ms** (gatilho do proxy é 300 ms → **B3 não entra**) |

**Teste**: `python3 $S/preview/tests/test_digest.py` — 27 checagens sobre material
real, sandbox em `/tmp` (nada é escrito na produção), com **6 defeitos plantados**
que as invariantes têm que acusar e o **controle negativo** da régua somada.
`--rapido` pula a medição dos `segs/`.

O contrato do que a marcação carrega está em **`preview/app/CONTRATO-MARCACOES.md`**.

## ⭐ Portão de estilo — a galeria (SPEC-19)

**Entre a Fase 1 e a Fase 2 existe um portão, e ele é uma TELA, não uma
pergunta.** O corte já está aprovado e nada sobre o *look* da Fase 2 foi
decidido. A resposta certa nesse momento é abrir a galeria.

### 🔴 NÃO pergunte estilo no chat

Enquanto `estado.portao == "estilo"`, a resposta do agente para *"que legenda
você quer?"*, *"qual cor de destaque?"*, *"quer post-it?"* é **abrir a galeria** —
nunca listar opções em texto. O arsenal de dispositivos em prosa (a linha do
"arsenal" na etapa 6) descreve o que existe; ele não é o menu de escolha.

O motivo é medido do lado de fora: **a pergunta "que legenda você quer?" se
responde vendo, não lendo.** É a mesma lição do teardown — *"portão de aprovação
no artefato, não no documento; 'ver o plano' e 'aprovar o plano' são a mesma
coisa"*.

### O ciclo, com dois gates separados

```bash
S=.claude/skills/edit-video/scripts
D=<dir-producao>

# 1 · gera a galeria (nível 0 na hora; nível 1 com o texto da peça em background)
python3 $S/previews-peca.py $D --somente-defaults    # ~18 s, os 2 defaults
python3 $S/previews-peca.py $D                       # o resto

# 2 · abre o portão
python3 $S/estado.py $D --portao estilo

# 3 · serve a tela  (ver a NOTA sobre a rota, abaixo)
python3 $S/previews-peca.py $D --pacote /tmp/galeria-$(basename $D)
python3 .claude/skills/edit-video/preview/servidor.py servir --dir $D \
        --app /tmp/galeria-$(basename $D)
#   → <url>app/galeria/galeria.html

# 4 · consome a escolha v3 e aplica
python3 $S/escolha-estilo.py $D --consumir estilo    # valida, digere, move
python3 $S/escolha-estilo.py $D --aplicar $D/.preview/aplicados/<...>-estilo-1.json

# 5 · cria o plano visual da Fase 2 e preenche os eventos por beat
python3 $S/plano-visual.py $D --iniciar
# editar $D/plano-visual.json conforme references/contrato-plano-visual.md
python3 $S/plano-visual.py $D --validar planejamento

# 6 · só depois libera a implementação
python3 $S/qc-portao.py $D
python3 $S/estado.py $D --portao nenhum --fase 2
python3 $S/previews-peca.py $D                       # nível 1 já com o acento escolhido

# 7 · antes de entregar, prova que o plano foi executado
python3 $S/plano-visual.py $D --validar entrega
```

`PLANO-EDICAO.md` continua descrevendo e fingerprintando o corte aprovado.
`plano-visual.json` nasce só depois da escolha de acabamento e descreve a Fase
2. Isso evita a circularidade antiga: não é preciso adivinhar animações antes de
o creator escolher o estilo, nem invalidar a aprovação do corte só por detalhar
o acabamento.

### O que a galeria pergunta, e o que ela nunca pergunta

O primeiro bloco é obrigatório: **Essencial**, **Com animações** ou **Me
surpreenda**. Só depois vêm **gramática de plano** (o que muda o corte vem antes
da tinta) · **tema + cor de destaque** · **gancho** · **legenda** · **grafismos
liberados** · **interruptores** de pipeline · **observação livre**.

O modo Essencial significa cortes e legenda, sem eventos gráficos nem SFX. Os
modos Animada e Surpresa exigem pelo menos um evento no plano visual. Surpresa
registra a delegação e também a direção que o agente resolveu aplicar.

Cada evento declara uma decisão sonora. `usar` exige asset, instante e ganho;
`silencio-intencional` exige motivo; `nao-se-aplica` deixa explícito que aquele
movimento não pede som. O objetivo não é sonorizar tudo, e sim impedir que o som
seja esquecido.

E ela **não pergunta nada que o disco responda**: perfil, formato, zonas de UI,
duração e tema default chegam resolvidos no `galeria.json`.

### Três coisas que o agente precisa saber ao ler o digest

1. **Caixa desmarcada é um NÃO explícito.** O digest imprime a linha `· fora:`
   com os interruptores desligados **nomeados**, e `· grafismos FORA:` com o
   complemento. Isso é instrução, não sobra: é o que tem que ficar de fora.
2. **Cor que ninguém pinta não é instrução.** Quando nenhum estilo escolhido
   declara `acento`, o digest diz *"não se aplica (os estilos escolhidos não usam
   destaque)"*. **Não invente um lugar para a cor.**
3. **`gramática de plano` implica REMONTAR.** Ela mexe no corte (zoom/cx/cy na
   EDL), não na camada gráfica: aceitar a escolha é rodar `bordas.py → montar.sh
   → audio-exato.py`, não só re-renderizar o alpha. O digest marca a linha com
   `→ remontagem:`.

### Restilizar é edição normal

O portão **continua disponível depois de a Fase 2 existir**. Com
`.preview/estilo-vigente.json` no disco e o portão fechado, a galeria abre em
modo troca: o botão vira *"Salvar e refazer a Fase 2"*, o payload chega com
`rerender: true` e o digest abre com **TROCA DE ESTILO**.

### ⚠️ NOTA sobre onde a tela é servida

A rota `/media/` do servidor de preview **recusa tudo que está sob `.preview/`**
(403 `{"erro":"fora da raiz"}`, medido em 2026-08-08 com controle: o mesmo tipo
de arquivo fora do `.preview/` responde 200). Por isso o `--pacote` do passo 3:
ele monta um diretório descartável, servível por `--app`, com a tela + o
`galeria.json` + as mídias por hardlink. Os artefatos canônicos continuam em
`<dir-producao>/.preview/estilos/`.

### O que o preview NÃO é

O card **não** é uma imitação em DOM/CSS do estilo: é um `.webm` de 3 s
renderizado **pelo próprio componente Remotion**. Fiel por construção, impossível
de dessincronizar. Dois níveis:

| nível | o que mostra | custo |
|---|---|---|
| **0** | frase de amostra, placa sintética — versionado no repo | 0 |
| **1** | o mesmo componente com o **texto real da peça**, na página de **pior caso** (a mais longa) | ~9 s por preview, em `legenda` e `gancho` só |

**Nenhum render é síncrono com clique.** Todo card abre no nível 0 e troca
sozinho quando o nível 1 existe.

E a janela do nível 1 é a do **pior caso de propósito**: é onde o estilo estoura,
quebra linha errado ou invade a zona de UI. Medido na primeira execução — o
gancho real de `peca-02` (74 caracteres) **estoura o quadro** no
`hook-titulo-typeon`, e é exatamente isso que o card mostra. Um preview com a
frase curta e bonita seria um preview que mente por seleção de amostra.

## Biblioteca de estilos do usuário (SPEC-24)

Um **perfil de peça** descreve o TIPO DE PEÇA e é do produto. Um **estilo**
descreve *como este usuário quer que a peça fique*, dentro do que o perfil
permite, e é dele: privado, nomeado, versionado, exportável.

```
perfil  (SPEC-00)  = FORMATO        1080×1920, 30 fps, 48 kHz, zonas de UI
estilo  (SPEC-24)  = LOOK E RITMO   dentro daquele formato
```

> **Um estilo nunca escreve formato.** `perfil_overrides` é *allowlist*
> (`estilos/_escopo.json`), não denylist: caminho fora dela é **erro** com o path
> na mensagem e o comando `perfil.py … --set` pronto — nunca campo ignorado em
> silêncio. Se o usuário quer mesmo 25 fps, isso é escolha de **perfil**.

### As seis camadas — a de cima vence campo a campo

| # | camada | escreve |
|---|---|---|
| 0 | invariantes físicos | são condições (`48000 % fps == 0`), não valores |
| 1 | perfil de peça | **tudo** — e só ela escreve `video.*`, `audio.{sr,canais,codec}`, `zonas_ui`, `qc.*`, `legenda.fonte_palavras` |
| 2 | defaults do catálogo (`defaultDe`, SPEC-15) | os `picks`, só onde a 3 for silenciosa |
| 3 | estilo do usuário | `picks`, `grafismo`, `parametros` + os prefixos do escopo |
| 4 | escolha pontual na UI (`benchmark.edit-estilo/v1`) | o mesmo escopo, só nesta produção |
| 5 | pedido em texto | o mesmo escopo, **depois de compilado num diff** |

Camada ausente **não existe**: não vira `null`, não zera nada. Grupo com `null`
**explícito** em `picks` *desliga* o grupo — diferente de ausente.

### No fluxo

```bash
E=$S/estilo.py
python3 $E resolver <dir-producao> --perfil reels --usuario creator-1
#   → <dir>/perfil.json           (forma inalterada; camadas já mergeadas)
#   → <dir>/estilo-resolvido.json (picks, grafismo, parametros, correcoes[], _origem)
```

Roda **antes** do `bordas.py`, no lugar do `perfil.py resolver`. Sem `--estilo`,
usa o `padrao` do usuário; se a biblioteca dele estiver vazia, semeia
`padrao/v001.json` e diz isso no stderr. **O stderr sempre imprime as camadas que
participaram** — sem catálogo, ele avisa que a camada 2 não entrou.

⚠️ O arquivo é `estilo-resolvido.json`, na **raiz** da produção.
`<dir>/.preview/estilo.json` já é o canal de volta da UI, com outro contrato.

### `_origem`: por que essa peça saiu assim

Uma entrada por **folha**, produzida pelo próprio merge:

```
ritmo.pads.pre       estilo:creator-1/reels-verde@v003
picks.gancho         catalogo:defaultDe[reels]
legenda.y_pct        ui:.preview/aplicados/20260808T154119-estilo-1.json
audio.loudness.I     pedido:"deixa mais alto" → -14.0→-12.0
```

Medido na entrega: **141 folhas, 141 entradas, diferença 0**, com controle
negativo (tirar 1 folha do mapa faz o censo acusar).

### Evolução: nada é promovido automaticamente

```bash
python3 $E sinais   <dir>          # .preview/aplicados/ + correcoes[] → sinais.jsonl
python3 $E propor   creator-1/padrao   # imprime. NÃO ESCREVE UM BYTE
python3 $E promover creator-1/padrao --confirmar --so legenda.y_pct
```

Quatro guardas: 3 produções **distintas**, janela de 12, saldo ≥ 3 sem
contra-sinal nas 3 mais recentes, e nunca a partir de uma peça só. Quando o mesmo
parâmetro é empurrado para os dois lados, a saída diz a conclusão certa —
**"esse parâmetro é decisão por peça e não pertence ao estilo"**.

🔴 **A correção é medida contra a linha de base (camadas 1–3)**, nunca contra o
`estilo-resolvido.json`: a camada 4 já está mergeada nele, e o diff contra ele dá
sempre zero. Foi um sucesso silencioso encontrado durante a própria execução —
o colhedor dizia "1 evento lido", gravava nada e saía 0.

### Remontar peça antiga

```bash
python3 $E resolver <dir> --como-gravado    # resolve com a versão do _procedencia
```

Sem a flag, resolve com o HEAD e **avisa no stderr** listando exatamente os
caminhos que diferem. Nunca em silêncio.

### O que NÃO fazer

- **Não coloque o estilo no hash do sidecar de segmento.** O estilo não influencia
  o `vf` (`cor.grade` é da composição; `ritmo.*` muda a EDL, e `start`/`end` o
  sidecar já compara). Incluí-lo invalidaria `segs/` inteiros a cada troca de
  legenda. ⚠️ Se um dia um campo de estilo entrar no `vf`, ele entra no hash **no
  mesmo commit** — senão volta o bug do segmento órfão.
- **Não trate correção de timeline como sinal de estilo.** `notas[]`/`operacoes[]`
  são sobre um `sid`: a classe `peca` é o default e nunca conta para promoção.
- **Não copie hex nem número do catálogo para dentro do estilo** — referencie o slug.
- **Não sobrescreva uma versão.** `versoes/vNNN.json` imutável é o mecanismo.

Ritual completo: `references/biblioteca-de-estilos.md`. Contrato e a linha do
material de terceiro: `estilos/README.md`. Bateria: `scripts/tests/test_estilo.py`
(**36 asserções, 0 falhas** em 2026-08-08).

---

> Núcleo: [`../SKILL.md`](../SKILL.md) — as Regras Duras valem aqui.
