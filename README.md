# Ilha de edição

Você joga os brutos numa pasta, abre seu agente ali dentro e diz *edita isso num
Reels*. Ele transcreve, escolhe os takes, corta os respiros, monta, e te chama
numa tela para você aprovar o corte antes de qualquer camada gráfica entrar.

Depois que o corte está aprovado, você escolhe o acabamento e o look numa
galeria onde cada estilo aparece **em vídeo**, com o texto da sua peça dentro.
Há três direções explícitas: **Essencial**, **Com animações** e **Me
surpreenda**. Nada de o agente encerrar só com legenda porque ninguém lembrou de
pedir motion.

Quando a direção inclui animações, a Ilha registra antes do render cada beat,
janela, visual e zona. Cada movimento também recebe uma decisão sonora:
usar SFX, ficar deliberadamente em silêncio ou não se aplicar. Assim o som não
vira um pedido posterior, e uma animação silenciosa por escolha continua válida.

O que sai: o vídeo final, legenda queimada ou `.srt`, capítulos, e um relatório
de QC que mediu o que entregou.

## Escolha onde vai usar

A Ilha roda na máquina que tem os brutos, `ffmpeg` e o projeto de render. O
mesmo pacote atende às duas superfícies:

- **Claude Code com painel lateral:** usa as skills pela pasta `.claude/` e o
  `launch.json` incluído no pacote abre a aprovação ao lado da conversa.
- **ChatGPT Work:** o pacote já é um plugin de skills válido, declarado em
  `.codex-plugin/plugin.json`. Para editar e aprovar na interface, use **Work
  locally** no app desktop, com acesso à pasta e ao navegador desta máquina. Um
  ambiente cloud também pode fornecer um proxy HTTPS autenticado pelo contrato
  documentado em `skills/edit-video/preview/README.md`.

O Work em nuvem consegue executar o pipeline headless a partir do ZIP, mas o
navegador da nuvem não alcança sozinho o servidor `127.0.0.1` do sandbox. O
pacote não contem endpoint do Work nem publica porta. Sem um proxy autenticado
fornecido pela plataforma, o preview cai de forma explícita no loopback e a
aprovação deve acontecer em Work locally.

## Instalar

Rode da raiz deste pacote. As skills já vêm em `.claude/skills/`, caminho que o
Claude Code descobre no projeto. O pacote também traz a cópia gerada em
`skills/`, declarada pelo manifesto do ChatGPT e do Codex.

```bash
# macOS / Linux
cp -n .claude/skills/edit-video/preview/launch.exemplo.json .claude/launch.json
python3 -m pip install -r requirements.txt
cd tools/remotion-compositor && npm ci
```

No Claude Code, ajuste `<DIR-DA-PRODUCAO>` em `.claude/launch.json` se abrir o
painel manualmente. Quando a sessão de preview nasce pelo fluxo normal, o
servidor aponta esse campo para a produção corrente.

No ChatGPT Work desktop, selecione **Work locally**, abra esta pasta e invoque
`@Ilha de edição` se o plugin estiver instalado pela sua fonte local. Sem uma
fonte local habilitada, a pasta ainda pode ser usada diretamente: peça para o
agente seguir `skills/edit-video/SKILL.md`. O manifesto deixa o pacote pronto
para instalação e submissão, mas não afirma que ele já está publicado no
diretório universal.

Precisa de: **Node 22+**, **Python 3.11+**, **ffmpeg**, **ffprobe** e **jq** no
PATH, mais os dois pacotes Python do `requirements.txt` (**numpy** e
**Pillow**). O `jq` não é conveniência: o `montar.sh` o chama 15 vezes para ler
o EDL e o perfil, e sem ele a montagem para na primeira leitura de JSON.

Uma chave da Deepgram para transcrever (`DEEPGRAM_API_KEY`) — sem ela a
montagem não roda, e a mensagem diz isso em vez de falhar de lado. É a única
credencial bloqueante; todas as outras têm alternativa nomeada.

Configure uma vez pela ferramenta oficial. A entrada é oculta e o valor fica em
`$ILHA_HOME/.env` (por padrão,
`~/.config/ilha-de-edicao/.env`), fora da instalação:

```bash
python3 tools/pacote/chaves.py --pedir DEEPGRAM_API_KEY
```

O ambiente do processo continua tendo precedência. O modelo manual está em
`tools/pacote/.env.example`; não copie esse arquivo para a raiz do repositório.

**O primeiro render baixa um navegador.** O Remotion busca o
`chrome-headless-shell` (~193 MB) na hora do primeiro render, não na
instalação. Se você vai rodar isto num sandbox cuja rede é cortada depois do
setup, puxe o navegador enquanto ainda há rede:

```bash
cd tools/remotion-compositor && npx remotion browser ensure
```

## Conferir que instalou certo

Quatro comandos, e os quatro existem neste pacote:

```bash
python3 tools/pacote/chaves.py --status          # quais credenciais estão de pé
python3 tools/pacote/chaves.py --contrato-cloud  # nomes/origens/booleanos, sem valor
cd tools/remotion-compositor && npx remotion compositions
cd tools/remotion-compositor && npm run catalogo -- --check
```

O terceiro lista as composições de mecanismo do produto. O `cd` é obrigatório: o
Remotion resolve `public/` e a config pelo diretório corrente, e rodar de fora
falha de um jeito que parece problema de instalação.

O quarto confere que os previews do catálogo de estilos batem com o catálogo —
é a galeria que você vai usar para escolher o look.

Antes de distribuir um pacote ou anexar logs, procure o valor Deepgram resolvido
sem mostrá-lo na saída:

```bash
python3 tools/pacote/chaves.py --scan-segredos --scan-dir . --scan-dir ./logs
```

O scanner também abre ZIPs. Um vazamento ou erro de leitura sai `1`; chave não
resolvida sai `2`, para que ausência de medição nunca pareça verde.

## O primeiro vídeo

```bash
mkdir -p minha-peca/input && cp ~/Downloads/take*.mov minha-peca/input/
```

Aí, no seu agente, dentro dessa pasta: *edita isso num Reels*.

A UI de aprovação sobe antes de qualquer coisa ser cortada, e é lá que você
acompanha a peça nascer. Quando o corte estiver pronto, o botão **✓ Aprovar o
corte** libera a fase gráfica. Sem esse clique a camada gráfica não entra — o
portão é executável, não uma recomendação.

## O que ele faz bem, e o que ele não faz

O formato da peça (resolução, cadência, sample rate, zonas de UI, alvo de
loudness) vem de um arquivo de perfil, nunca de um número escrito dentro de um
script. Peça de formato novo é um JSON novo em `perfis/`. Reels, VSL, longform e
screencast já vêm prontos.

Todo QC imprime quanto varreu. Vários trazem defeito plantado de propósito, para
que verde signifique alguma coisa.

O que ele **não** faz hoje: não roda em Windows, não instala as dependências com
um comando e não fornece por conta própria o proxy exigido pelo preview cloud.
O recorte de pessoa por Vision e a limpeza de áudio com DeepFilterNet dependem
de binários que só existem em macOS ARM. As outras vias de limpeza de áudio
funcionam em qualquer lugar.

## Onde está o resto

- `.claude/skills/edit-video/SKILL.md` — as etapas, na ordem, com a régua de cada uma
- `.claude/skills/edit-video/instalacao.md` — a verificação bloco a bloco e o diagnóstico dos erros conhecidos
- `.claude/skills/edit-video/references/` — o porquê de cada regra, um arquivo por etapa
- `AVISOS-DE-TERCEIROS.md` e `LICENSES/` — a procedência do que não nasceu aqui
