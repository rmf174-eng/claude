---
name: edit-video
description: Orquestrador da ilha de edição — bruto(s) de vídeo → montagem (takes + corte de respiros) → PLANO DE EDIÇÃO aprovável (cortes, efeitos, SFX, zonas) → implementação Remotion → render com QC. Use quando o creator-1 mandar bruto(s) pra editar ("edita esse vídeo", "faz a edição do vídeo da creator-2"), com arquivos em input/ ou numa pasta de produção. Compõe transcribe, clean-audio e remotion-compositor.
---

# edit-video

**Regra de ouro: PLANEJAR e APROVAR antes de implementar** — o plano de edição é um artefato que o creator-1 revisa; só depois vem o Remotion.

## Local da instalação

A raiz canônica deste produto contém `.codex-plugin/plugin.json`, `skills/` e
`tools/`. Os exemplos históricos abaixo usam `.claude/skills/<skill>` porque
esse é o alias do Claude Code. Em ChatGPT Work ou Codex, resolva o caminho pelo
diretório real desta skill e use `<raiz-ilha>/skills/<skill>`. Nunca deduza a
raiz contando `..` a partir do diretório da produção.

Quando o pacote está aberto pela própria raiz, este bloco cobre as duas formas:

```bash
RAIZ_ILHA="${ILHA_RAIZ:-$PWD}"
S="$RAIZ_ILHA/skills/edit-video"
[ -d "$S" ] || S="$RAIZ_ILHA/.claude/skills/edit-video"
```

## Regras Duras (RD)

O contrato desta ilha. Cada regra nasceu de uma lição medida **aqui**, nenhuma foi
traduzida de fora, e o porquê mora no `references/` da etapa. **Não existe bloco
espelhado de anti-patterns**: o índice é gerado por `doc-check.py --indice`.

| # | regra | evidência — o arquivo, e o marcador `→ RD-N` dentro dele |
|---|---|---|
| **RD-1** | **O portão é real.** Nenhuma camada gráfica antes do OK no corte. | `references/plano-de-edicao.md` → RD-1 |
| **RD-2** | **Nada publicado é re-renderizado.** Trabalhe em cópia. | `references/montagem.md` → RD-2 |
| **RD-3** | **`soma_audio == soma_video`, por construção.** Nunca `-shortest`, nunca pinar duração. | `references/montagem.md` → RD-3 |
| **RD-4** | **Todo segmento carrega procedência**, e o cache compara TODOS os parâmetros que o geraram. | `references/montagem.md` → RD-4 |
| **RD-5** | **Nenhum valor de formato em script.** Resolução, aspecto, cadência e sample rate vêm do perfil. | `references/enquadramento-e-zonas.md` → RD-5 |
| **RD-6** | **Não corte dentro de palavra nem em rampa de ataque.** A borda sai do envelope medido. | `references/montagem.md` → RD-6 |
| **RD-7** | **QC verde sem controle negativo não vale nada.** Imprima quanto varreu, plante o defeito. | `references/qc.md` → RD-7 |
| **RD-8** | **QC tem que ouvir, não só ler.** Transcript perfeito não diz nada sobre nível. | `references/qc.md` → RD-8 |
| **RD-9** | **Detector de achado ≠ teste de convergência.** Régua igual ao critério nunca chega a zero. | `references/qc.md` → RD-9 |
| **RD-10** | **A tag de cor faz parte do entregável.** Nenhum QC por extração de frame pega. | `references/qc.md` → RD-10 |
| **RD-11** | **Texto e overlay são Remotion.** Não queime legenda com ffmpeg nem PIL. | `references/plano-de-edicao.md` → RD-11 |
| **RD-12** | **Entry point isolado por produção.** Confira o `mtime` do `.mov` depois do render. | `.claude/skills/remotion-compositor/SKILL.md` → RD-12 |
| **RD-13** | **Dado de máquina não entra por `Read`.** A lista fechada é a seção Contexto, abaixo. | `scripts/doc-check.py` → RD-13 |
| **RD-14** | **Uma Read por folha.** N frames viram uma folha; a escolha é pelo índice. | `references/montagem.md` → RD-14 |
| **RD-15** | **Amplie a amostra antes de concluir que algo está quebrado.** | `references/audio-e-cor.md` → RD-15 |

## Contexto — o que NUNCA entra por `Read`

É a RD-13, com o número de cada caso e o substituto **conferido no disco**. Três dos
oito itens carregam exceção escrita: um "nunca leia dado de máquina" chapado
desligaria o único QC visual que temos.

| # | não leia com `Read` | o número | leia no lugar | veredito |
|---|---|---|---|---|
| **C1** | `transcript.json` do Deepgram, word-level | maior do repo: 4.604.681 B ≈ 1,15 M tokens, sozinho estoura um contexto de 1 M. Na produção, 73.689 B para 1.132 B de fala (65×) | `.claude/skills/transcribe/scripts/timestamped.py` gera o `transcript-ts.md` (99.485 B no mesmo caso, 46× menor) | ✅ regra dura. ⚠️ **Exceção**: o tempo de UMA palavra sai por `jq`, nunca por `Read`. Produção não gera `transcript.md`, então ali o substituto é rodar o script — 1 comando |
| **C2** | `profile.json` de perfil **inteiro** | maior medido: 74.972 B ≈ 18,7k tokens | o ranking resumido que a ferramenta de perfil devolver, ou `jq` para o campo pontual | ⚠️ **Exceção escrita**: no produto o bloco de extração de perfil não embarca, então não há `profile.json` para ler — a regra fica como forma. Onde ele existe, o campo pontual sai por `jq`, nunca por `Read` |
| **C3** | `captions*.json` / `overlays*.json` da produção | maior hoje: 52.105 B ≈ 13k tokens | o `PLANO-EDICAO.md` da produção, indexado em `references/plano-de-edicao.md`, e `jq` para a janela em dúvida | ✅ quando o defeito É a legenda, leia **a janela** por `jq` |
| **C4** | `segs/segNNN.json`, os sidecars de procedência | 29 arquivos só numa produção | um `jq -s` sobre o glob; a procedência já é conferida por `scripts/montar.sh` (RD-4) | ✅ |
| **C5** | `.mp4` `.mov` `.wav` `.mp3` e matte | binário: `Read` não decodifica | `ffprobe` e `ffmpeg` para medir, `scripts/qc-cor.py` para o veredito de cor | 🔴 **Exceção, e é a mais importante**: frame extraído em PNG/JPG **É para ser lido com `Read`** — é o QC de estado final e a escolha na folha de contato. Um "nunca leia binário" chapado desliga o único QC visual que temos |
| **C6** | `ads.json` de anunciante | maior medido: 47.202 B ≈ 11,8k tokens | `jq` para o campo pontual; o arquivo de clusters e a inteligência compilada quando existirem | ⚠️ no produto o eixo de anúncios não embarca, e não há `ads.json` para ler. Onde ele existe, a leitura é por `jq` |
| **C7** | `.tsx` de **outra** produção | 26 tags `Composition` num só entry, 64 composições no bundle | o componente da sua produção (`<dir-producao>/remotion/`) e `tools/remotion-compositor/catalogo/catalogo.json` | ⚠️ é regra de **escopo**, não de tipo: esta ilha é sobre **escrever** TSX |
| **C8** | spec longa que não é a sua | 32 delas somaram 1.763.697 B ≈ 441k tokens na medição | a reference da sua etapa em `references/` — o índice de tudo que esta skill documenta — e `grep` para o trecho | ⚠️ no produto as specs não embarcam (são registro de projeto de quem construiu); o equivalente instalado é `references/`, e a regra vale igual: leia a página da sua etapa, não o acervo |

Três coisas que a lista **não** faz: não proíbe `edl.json` (é decisão editorial, é
pequeno e é insumo de quase tudo), não proíbe `analysis.json` (cabe), e **não vira
gate automático** — um hook que bloqueasse `Read` quebraria exatamente as exceções
acima, que são as que importam.

## Input (o que o creator-1 faz)

1. Joga o(s) bruto(s) em `<dir-producao>/input/`.
2. Diz o que quer: o que é o vídeo, e qualquer direção ("só corte e legenda",
   "usa o roteiro X", "estilo mais seco").

O diretório da produção é onde tudo desta peça mora: o bruto, os artefatos
intermediários, o `PLANO-EDICAO.md`, o `remotion/` com a peça e os entregáveis.

## 🖥 ETAPA 0 · A UI SOBE ANTES DE TUDO — não é a etapa 6

**Assim que o diretório da produção existir, e ANTES de transcrever ou montar:**

```bash
RAIZ_ILHA="${ILHA_RAIZ:-$PWD}"
S="$RAIZ_ILHA/skills/edit-video" ; D=<dir-producao>
python3 $S/preview/servidor.py sessao --dir "$D"     # imprime a URL com token
python3 $S/preview/servidor.py servir --dir "$D"     # em background; --abrir põe a janela na tela
```

Numa produção **vazia** isso funciona e é o estado normal: a UI abre com as três
abas (ESTILO e FASE 2 cinzas, é assim mesmo), *"ainda não há render nesta
produção"* e a timeline com as trilhas declarando o que ainda não existe. Medido
na tela em 2026-08-10 num diretório recém-criado. **O creator vê a peça nascer**,
em vez de receber um `.mp4` no fim.

🔴 **Um `.mp4` proxy no chat NÃO é a UI.** Sem `<D>/.preview/` no disco, esta
etapa não aconteceu — e ela não falha com erro, ela simplesmente não acontece.
Medido numa produção real: ela foi do bruto a 4 entregáveis **sem** `.preview/`
nenhum, com a escolha de estilo virando pergunta no chat e o portão assinado pelo
próprio agente. Todos os QCs verdes.

**Escolha o caminho pela superfície, procurando a ferramenta antes de usá-la**
(`references/qc.md` § "Onde a UI aparece" tem os três com o porquê):

| superfície | como | o agente |
|---|---|---|
| tem `preview_start` | `.claude/launch.json` com o `--dir` **desta** produção → `preview_start` | vê a UI ao lado da conversa |
| tem browser MCP | navega na URL | **enxerga a tela** e confere sozinho |
| qualquer uma | `servir --abrir` em background | tem a URL no log |

🔴 **E todo save do creator tem que virar ação visível pra você.** Onde existe
`Monitor`, arme o watcher **no mesmo turno** em que o servidor sobe:

```
Monitor(command="python3 <skill>/preview/watch-preview.py '<D>'",
        description="escolhas e marcações salvas no preview", persistent=true)
```

**Onde `Monitor` não existe** (e é por isso que a regra é essa, e não "arme o
watcher"): diga ao creator que salve e responda no chat, e **no início de cada
turno seguinte, antes de qualquer outra coisa**, leia `<D>/.preview/pendentes/`.
O contrato é *nenhum save morre em silêncio* — o watcher é só o meio numa
superfície. Sem isso ele salva, vê a confirmação, e espera trabalho que ninguém
disparou.

## Etapas (nesta ordem)

As oito etapas em forma de checklist: **o que rodar · a régua · onde está o porquê**.
Um agente que só executa o caminho feliz nunca precisa abrir um `references/`; um
agente que bateu num alerta abre exatamente um.

| # | etapa | o que rodar | a régua | o porquê |
|---|---|---|---|---|
| **0** | o bruto é mesmo um take? | `scripts/cortes-do-bruto.py <arquivo.mp4>` | corte seu a menos de ~8 frames de um corte dele lê como flash | `references/montagem.md` |
| **1** | ingestão | `transcribe` cada bruto; pedir o ROTEIRO | energia sem palavra no transcript é palavra não reconhecida, não ruído | `references/montagem.md` |
| **2** | montagem | `scripts/bordas.py <dir>` → `scripts/montar.sh <dir>`. Com punch-in na gramática, `scripts/rastrear-rosto.py <bruto>` antes: o `track-rosto.json` é o que faz `MotionKit.CameraSegue` manter a linha dos olhos no lugar em vez de deixar a pessoa passear pela borda | RD-3, RD-4, RD-6; check de gancho 0–5 s antes de montar · o tracking recusa cobertura <35%, e sem zoom ele não move nada (de propósito) | `references/montagem.md` |
| **2b** | J-cut — **a decisão é obrigatória, o J-cut não** | `scripts/jcut.py <dir>` → `scripts/qc-jcut.py <dir>`. Ele **grava `jcut.json`, e o `montar.sh` lê**. A decisão NEGATIVA também é arquivo: `scripts/jcut.py <dir> --nao-aplicar --motivo "…"` grava `aplicar: false` com quem, quando e por quê. 🔴 **`rm jcut.json` não é mais uma opção** — sem o arquivo o `qc-jcut` REPROVA, porque apagar deixa 'decidiu não' e 'não pensou no assunto' idênticos no disco. E a escolha **não** vai escrita no PLANO: o `.md` está preso pelo `plano_sha256` da aprovação, e editá-lo depois invalidaria o portão (exit 2) | 🔴 **pular calado é o defeito** — "opcional" virou "nunca aconteceu" numa produção real (15 emendas butt-join, e quem aparece no vídeo só soube porque perguntou). Junção contígua nunca sobrepõe | `references/montagem.md` |
| **3** | áudio | `scripts/loudness.py` (medir antes de escolher a via) | alvo não tem default: vem do perfil, ou o script recusa | `references/audio-e-cor.md` |
| **4** | cor | `scripts/detect-cor.py resolver <dir>` | `calibrado: false` aborta a montagem; RD-10 na entrega | `references/audio-e-cor.md` |
| **5** | retranscrever o montado | `transcribe` no v1 final | timestamps já no tempo do vídeo, zero deriva | `references/plano-de-edicao.md` |
| **6** | ⭐ DIREÇÃO E PLANO VISUAL | escrever `PLANO-EDICAO.md` para o corte. **A UI já está de pé desde a etapa 0**: gere a galeria com `scripts/previews-peca.py <dir> --somente-defaults` e abra `scripts/estado.py <dir> --portao estilo --fase 1 --mensagem "…"`. A aba começa por uma decisão obrigatória: **Essencial**, **Com animações** ou **Me surpreenda**. Depois de consumir e aplicar o estilo v3, rode `scripts/plano-visual.py <dir> --iniciar`, preencha os beats e valide com `--validar planejamento` | a escolha acontece NA ABA, nunca no chat. Animada/Surpresa não avançam sem evento; Essencial exige zero eventos. Cada animação decide `usar`, `silencio-intencional` ou `nao-se-aplica` para o som | `references/plano-de-edicao.md` · `references/contrato-plano-visual.md` |
| **7** | implementação | `scripts/qc-portao.py <dir>` **tem que sair 0**, e só então `scripts/estado.py <dir> --portao nenhum --fase 2`. Rode `skills/remotion-compositor/scripts/compilar-plano-visual.py <dir> preparar`, depois `... renderizar --saida graphics-alpha.mov` e `... compor-final --base <base> --saida <entregavel>`, uma vez para cada saída pedida pelo perfil. O compilador chama Remotion com os props/SFX do plano e mistura o áudio gráfico no final; cada entregável recebe manifesto próprio em `remotion/plano-visual-finais/`. Dados e assets da peça ficam em **`<dir-producao>/remotion/`** (RD-12), NUNCA em `tools/remotion-compositor/src/data/` | aprovação do corte e plano visual são gates separados. Mudar estilo, corte, timeline ou `PLANO-EDICAO.md` deixa o plano visual stale. `Me surpreenda` autoriza a direção criativa, mas ela ainda fica persistida em `direcao_resolvida` | `references/plano-de-edicao.md` |
| **8** | QC e entrega | depois do render e composição oficiais, `scripts/plano-visual.py <dir> --validar entrega` e `scripts/qc.py <dir>` | recibos ligam plano, render gráfico e MP4 final. Com SFX, o manifesto final exige `audio_grafico_misturado:true`; captions sozinhas não provam animação; asset ausente reprova; silêncio deliberado com motivo passa. RD-7 em todo QC: quanto varreu, e o defeito plantado | `references/qc.md` |

🔴 **A etapa 6→7 tem dois gates executáveis.** `qc-portao.py` prova que o corte
visto continua sendo o corte atual. `plano-visual.py --validar planejamento`
prova que a direção escolhida virou um plano de Fase 2 preso ao estilo, ao corte,
à timeline real e ao `PLANO-EDICAO.md`. O primeiro não é invalidado só porque o
acabamento foi detalhado; o segundo é refeito quando o acabamento muda. Produção
Animada ou Surpresa com apenas legenda não chega à entrega.

## `references/` — onde está o porquê

O núcleo diz o que fazer e qual é a régua. Estes arquivos dizem **por que a régua é
essa e o que já deu errado** — abra o da sua etapa, não todos.

| arquivo | o que carrega |
|---|---|
| `references/montagem.md` | etapas 0–2, J-cut, EDL v2 e `timeline_real`, cauda do segmento |
| `references/audio-e-cor.md` | etapas 3–4, nível por segmento, trilha, transiente do SFX |
| `references/plano-de-edicao.md` | etapas 5–7, arsenal, dêiticos, partitura, portão no artefato, galeria e biblioteca de estilos |
| `references/contrato-plano-visual.md` | contrato da Fase 2 por beat, decisão sonora, vínculos stale e gates de planejamento/entrega |
| `references/qc.md` | etapa 8, bateria orquestrada, prova pela imagem, preview |
| `references/duas-pessoas.md` | duas pessoas em quadro |
| `references/enquadramento-e-zonas.md` | perfil de peça, janela de aspecto, zonas por enquadramento |
| `references/contrato-edl.md` · `contrato-cor.md` · `contrato-ui.md` · `contrato-qc-nivel.md` · `contrato-trilha.md` · `contrato-publicacao.md` · `contrato-sfx.md` · `contrato-split.md` · `contrato-deiticos.md` | os contratos de dado, um por schema |
| `references/biblioteca-de-estilos.md` · `jcut-bloco-de-perfil.md` · `lexico-deitico-pt.json` | ritual, decisão datada e léxico |

## Referências

Cada produção deixa o próprio diário: escreva `NOTAS.md` no diretório dela com as
decisões e o que deu errado. É o material que faz a segunda peça custar menos que
a primeira, e é o único lugar onde o histórico desta peça faz sentido.


## A fronteira: o que é mecanismo e o que é a sua instalação

O `tools/pacote/MANIFESTO.json` é o corte declarado — o que é produto, o que
nunca sai, quais ativos existem fora do git e quais credenciais cada etapa pede.
O `tools/pacote/chaves.py` resolve credencial na ordem `env` → `$ILHA_HOME/.env`
→ `None`, e nunca imprime valor.

### A régua de uma frase

> **O mecanismo é produto; a instância é sua.** E: **nenhum mecanismo pode
> falhar quando a instância não existe.**

Uma instalação nova não tem produção nenhuma no disco. Se um script exige que
um diretório de trabalho já exista para funcionar, ele não é mecanismo — é uma
instalação disfarçada. O teste é literal: mova o diretório de produções para
fora, rode o comando, e traga de volta.

### Antes de mexer em script da ilha, rode

```bash
S=.claude/skills/edit-video
python3 $S/scripts/qc.py --autoteste
python3 $S/scripts/doc-check.py --indice $S/SKILL.md $S/references/*.md --contexto $S/SKILL.md
python3 $S/scripts/doc-check.py --contratos $S/scripts/*.py $S/preview/*.py --docs $S/references/contrato-*.md
```

O primeiro roda a bateria de QC contra fixtures com defeito plantado; o segundo
confere que toda Regra Dura tem evidência que resolve e que o contrato de
contexto aponta para substituto que existe; o terceiro confere que toda string
`benchmark.*/vN` declarada em CÓDIGO existe no `contrato-*.md` da família — o
drift que é silencioso e plausível, porque o dado continua batendo enquanto a
VERSÃO divergiu. Verde nos três é o piso.

⚠️ **O terceiro precisa dos dois lados na linha de comando**, e é por isso que a
invocação canônica está escrita aqui: sem `--docs` ele recusa, e com uma lista de
código VAZIA ele reprova com exit 2 em vez de imprimir "0 conferidas · OK" — um
verificador que varre zero e sai zero é indistinguível de um quebrado. Hoje ele
lê 52 strings, confere 10 contra 9 docs e nomeia 41 famílias sem `contrato-*.md`
(contrato sem doc é decisão de outra spec, não reprovação).

### As quatro coisas que mordem quem edita a ilha sem saber disto

1. **`os.path.join(…, "..","..","..","..")` é classe A.** Subir quatro níveis é
   uma afirmação sobre onde a skill mora. Instalada em `~/.claude/skills/`, a
   mesma expressão resolve para um caminho que não existe, e o script falha em
   *silêncio de configuração*, não em erro de código. O jeito certo está escrito e
   testado em `auditar-acoplamento.py:achar_raiz()`: sobe até achar um marcador,
   nunca conta níveis.
2. **`os.environ["X_API_KEY"]` cru é classe D.** Use
   `chaves.resolver(nome, recurso=…)`, e declare o recurso em
   `MANIFESTO.chaves.recursos` com um `fallback`. **Nenhuma etapa do caminho
   bruto → entregue pode ter `fallback: null`** — o auditor checa.
3. **JSON com fala transcrita é classe E, e classe E não se aceita.** Emenda 3 da
   SPEC-000: qualquer achado de classe E reprova, mesmo listado em
   `aceitos.json`. O detector lê a **forma** (lista de objetos com texto + tempo),
   não o tamanho — um arquivo de legenda com 257 palavras de fala real tem 25 KB e
   passava num limiar de "mídia > 1 MB".
4. **Binário nativo dentro de `scripts/` embarca no produto.** `matte-vision`
   (89.184 B, Mach-O arm64) e `deep-filter` (27,9 MB) não rodam em Intel, Linux
   nem Windows. O padrão é `MANIFESTO.ativos`: sha256 declarado, mídia fora do
   git, materializada e conferida no primeiro uso.

### Os SFX não estão no git, e é decisão

Os 9 `public/sfx/*.wav` (515 KB) são **ativos**, não arquivos versionados. O
`MANIFESTO.ativos.sfx` guarda nome, bytes, duração, **sha256**, origem, licença e
— nos três derivados — a receita. O auditor confere o hash a cada execução:
ausência é silêncio (é o clone novo), divergência é exit 1 com o hash do disco.

⚠️ **A camada de som quebra sem eles**, e não em silêncio teórico: são **12
chamadas** a `staticFile("sfx/…")` dentro de componentes que **são** o produto
(`MotionKit.tsx:108`, `Overlays.tsx:388,399`, `HookLettering.tsx`, `SfxDemo.tsx`).

### O que ainda NÃO é verdade, e não pode ser dito

Quatro afirmações que tentam escapar toda vez, e as quatro são falsas:
*"nenhuma chave de API"* (`transcribe.sh:24` aborta sem ela), *"instala com um
comando"* (o instalador não existe — a instalação é a cópia do README),
*"roda em Windows/Linux"* (`avconvert` e dois binários arm64) e *"vídeos
ilimitados"* (não medido, e é consumo de assinatura de terceiro).
