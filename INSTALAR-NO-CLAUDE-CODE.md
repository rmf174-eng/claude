# Instalar a Ilha no Claude Code

A Ilha v0.17 está instalada neste repositório. As skills vivem em `.claude/skills/`
— caminho que o Claude Code descobre sozinho ao abrir o projeto — e o projeto de
render em `tools/remotion-compositor/`.

Skills disponíveis: `edit-video` (orquestra tudo), `transcribe`, `clean-audio`,
`remotion-compositor`, `broll-source`, `model-edit`, `omni-insert`,
`style-extract`, `video-download`.

---

## Caminho A — sua máquina (é onde a Ilha funciona inteira)

A Ilha roda onde estão os brutos, o `ffmpeg` e o navegador que abre a tela de
aprovação. macOS ou Linux; **Windows só via WSL2**, com os arquivos dentro do WSL.

```bash
git clone https://github.com/rmf174-eng/claude.git ilha
cd ilha
./tools/pacote/instalar.sh --deps      # ffmpeg, ffprobe, jq, node 22+, python 3.11+, numpy, Pillow, npm install, navegador do Remotion
python3 tools/pacote/chaves.py --pedir DEEPGRAM_API_KEY
```

Sem `--deps` o script não instala nada de sistema: ele confere e te diz o comando.
A chave da Deepgram é a única credencial bloqueante — sem ela não há transcrição,
e sem transcrição não há corte por fala, legenda nem QC de emendas. Ela fica em
`~/.config/ilha-de-edicao/.env`, fora da instalação.

Conferir:

```bash
python3 tools/pacote/chaves.py --status
cd tools/remotion-compositor && npx remotion compositions      # o cd é obrigatório
npm run catalogo -- --check
```

Primeiro vídeo — abra o Claude Code na pasta da peça e peça em português:

```bash
mkdir -p minha-peca/input && cp ~/Downloads/take*.mov minha-peca/input/
claude
```
> *edita isso num Reels*

A tela de aprovação sobe antes de qualquer corte. Sem o clique em **✓ Aprovar o
corte**, a camada gráfica não entra — o portão é executável.

Se quiser as skills em **qualquer** pasta, e não só neste projeto:
`cp -r .claude/skills/* ~/.claude/skills/`.

---

## Caminho B — Claude Code na nuvem (sessões web)

Já configurado: o hook `.claude/hooks/session-start.sh` instala `ffmpeg`, `numpy`,
`Pillow` e as dependências do Remotion a cada sessão remota (nas seguintes o
container já vem com cache, e o hook termina em menos de um segundo).

**O que funciona aqui:** ler e escrever os arquivos da produção, transcrever
(com a chave), montar com `ffmpeg` + `jq`, rodar as baterias de QC que não
precisam de render.

**O que não funciona aqui, e o porquê medido nesta sessão:**

| Bloqueio | Motivo |
|---|---|
| `npx remotion compositions` / qualquer render | O download do `chrome-headless-shell` bate em `remotion.media`, que a política de egresso do ambiente nega (HTTP 403). |
| Render com o Chromium do próprio container | Ele sobe, mas as fontes do Google (`fonts.gstatic.com`) falham com `ERR_CERT_AUTHORITY_INVALID`: o Chromium não confia na CA do proxy. |
| Tela de aprovação | O servidor de preview nasce em `127.0.0.1` e o navegador da nuvem não alcança o sandbox. O pacote não publica porta, por decisão dele. |

Para liberar o primeiro item: no menu do ambiente de nuvem, na barra de título da
sessão, em **Edit → Network access**, adicione `remotion.media` aos domínios
permitidos (ou use um nível de acesso mais amplo). Os outros dois não têm conserto
do lado do pacote — a aprovação e o render são para a máquina local.

Para a chave da Deepgram em sessões web: adicione `DEEPGRAM_API_KEY` nas
configurações do ambiente (**Edit → API credentials**, ou como variável de
ambiente). Uma sessão nova já nasce com ela. Não cole chave no chat.

---

## O que foi verificado nesta instalação

- `ffmpeg 6.1.1`, `jq 1.7`, `node 22.22`, `python 3.11.15`, `numpy 2.4.6`, `Pillow 12.3.0` ✅
- `npm ci` em `tools/remotion-compositor` ✅
- As 4 baterias de fumaça que o `RELEASE.json` declara: `test_timeline_zoom`,
  `test_aprovacao_nonce`, `test_galeria_estilos`, `test_contrato_ui` — todas passaram ✅
- `chaves.py --status`: 4 de 6 recursos de pé; `transcricao` bloqueado (falta a
  chave) e `insert-gerado` indisponível (falta `GEMINI_API_KEY`, que tem alternativa) ⚠️

## Duas coisas que ficaram deliberadamente de fora do git

`public/sfx/whoosh.wav` e `whoosh-soft.wav` estão no `.gitignore` do próprio
pacote: licença não conferida (catálogo remotion.media), e o autor decidiu não
redistribuir. Nenhuma das 4 composições do produto usa whoosh, então nada quebra —
o `chaves.py --ativos` só os reporta ausentes num clone novo. Eles vieram no ZIP,
se você precisar deles.

O `RELEASE.json` descreve o pacote original; este repositório acrescenta o
instalador, o hook e este guia, então o `tree_sha256` de lá não bate mais com a
árvore daqui. Isso é esperado.
