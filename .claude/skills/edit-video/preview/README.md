# preview — servidor local de aprovação

Serve **um diretório de produção** em `127.0.0.1`, com token no caminho: o render
com scrub (Range HTTP), o filmstrip, a waveform, o estado da sessão e uma fila de
saves que volta para o agente. É o portão de aprovação **editorial** — o lugar
onde o creator vê o corte antes de o vídeo existir em versão final.

Entregue pela **SPEC-17** (a spec do servidor de preview). A
interface de verdade é da SPEC-16/18 e mora em `app/` ao lado deste README;
enquanto ela não existir, o servidor serve uma **página de diagnóstico embutida**
que já exercita todas as rotas.

```
preview/
├── servidor.py        o servidor (stdlib pura, sem framework, sem dependência)
├── watch-preview.py   uma linha por save novo — para a tool Monitor
├── README.md          este arquivo
└── app/               ← SPEC-16/18. Não existe ainda; o servidor cai na página de diagnóstico.
```

Tudo que o servidor escreve fica em **`<dir-producao>/.preview/`**. Ele **nunca**
toca `edl.json`, `captions.json` ou qualquer entregável — aplicar uma edição é
decisão do agente, com validação.

---

## Subir: 5 chamadas, nenhuma espera cega

Trocar `<dir-producao>` pelo diretório da peça. O servidor recebe o diretório por
argumento e não conhece creator nenhum: qualquer pasta com um render dentro serve.

**1 — abrir a sessão** (Bash, foreground, instantâneo). Escolhe porta efêmera e
token **antes** de subir, o que elimina a corrida "como descobrir a porta de um
processo em background":

```bash
python3 .claude/skills/edit-video/preview/servidor.py sessao --dir <dir-producao>
# {"url":"http://127.0.0.1:59940/7d15849c0201/","porta":59940,"token":"…","dir":"…","pid":null}
```

O mesmo objeto fica em `<dir-producao>/.preview/servidor.json`. Chamar de novo com
o servidor de pé devolve a **mesma** URL e não sobe nada — é idempotente.

**2 — subir** (Bash com `run_in_background: true`):

```bash
python3 .claude/skills/edit-video/preview/servidor.py servir --dir <dir-producao>
```

**3 — esperar ficar de pé, sem `sleep`** (Bash, foreground) — quem espera é o `curl`:

```bash
U=$(python3 -c "import json;print(json.load(open('<dir-producao>/.preview/servidor.json'))['url'])")
curl -sf --retry 40 --retry-connrefused --retry-delay 0 --max-time 10 "${U}api/saude"
```

**4 — o creator vê a página** (Bash, foreground) — e **imprima a URL no chat também**:
se ele fechar a aba, reabre clicando; e uma sessão futura acha a URL no
`servidor.json` sem reabrir nada.

```bash
open "$U"
```

**5 — fechar o laço** (tool `Monitor`, no **mesmo turno** do passo 2). Sem isto ele
salva, vê o toast e nada acontece:

```
Monitor(command="python3 .claude/skills/edit-video/preview/watch-preview.py '<dir-producao>'",
        description="marcações e escolhas salvas no preview",
        persistent=true)
```

**Encerrar**: `servidor.py parar --dir <dir-producao>`. E o servidor **se mata
sozinho** após `--ocioso 120` minutos sem nenhuma requisição (`--ocioso 0` desliga).

---

## Preview cloud: adaptador, não endpoint embutido

Este pacote não conhece uma API do ChatGPT Work e não inventa rota de publicação.
O backend continua fazendo bind somente em `127.0.0.1`. Quando a plataforma de
hospedagem oferece um proxy HTTPS autenticado para esse loopback, ela pode declarar
o adaptador por ambiente:

```bash
export ILHA_PREVIEW_CLOUD_URL_TEMPLATE='https://preview.exemplo/sessoes/{token}/'
export ILHA_PREVIEW_CLOUD_ALLOWED_HOSTS='preview.exemplo'
export ILHA_PREVIEW_CLOUD_EXPIRES_AT='<RFC3339 futuro, em no máximo 2 horas>'
export ILHA_PREVIEW_CLOUD_AUTHENTICATED='true'
```

O valor de `ILHA_PREVIEW_CLOUD_URL_TEMPLATE` vem da plataforma e precisa conter
`{token}` como um segmento do caminho. `{porta}` é opcional quando o proxy precisa
dele. O servidor aceita o endereço remoto somente quando todas estas garantias
forem verdadeiras:

- URL `https://`, sem credencial embutida e sem fragmento;
- host exato presente em `ILHA_PREVIEW_CLOUD_ALLOWED_HOSTS`, sem wildcard;
- proxy declarado como autenticado;
- token único da sessão mantido no caminho;
- expiração RFC 3339 futura, com fuso e no máximo duas horas.

Se qualquer campo faltar ou for inválido, `preview.modo` fica `local` e `url`
continua sendo a URL de loopback. Nenhuma porta pública é aberta como atalho. Em
modo cloud, o Host remoto exato entra na defesa contra DNS rebinding, o cookie da
UI recebe `Secure`, e o servidor encerra quando a validade declarada expira.

`servidor.json` mantém `url_local` para a sonda interna e grava `url_preferida`
mais o objeto `preview` para o orquestrador. A plataforma ainda precisa fornecer
e operar o proxy autenticado. Esta integração apenas valida o contrato recebido.

---

## Medido nesta máquina (2026-08-08), não presumido

| pergunta | resposta medida |
|---|---|
| `run_in_background` mantém o processo vivo **entre turnos**? | **sim.** O servidor subiu num turno e respondeu em vários turnos seguintes. Ao ser encerrado, o harness devolveu a notificação de saída (exit 0) — *servidor caiu ⇒ o agente fica sabendo*. **É este o mecanismo válido**; o `nohup … &` continua servindo para testes dentro de uma única chamada |
| `curl --retry-connrefused` sem `sleep` | exit 0 em **0,015 s** |
| filmstrip da peça de 70,784 s | **3,33 s**, `n=35`, intervalo 2,0224 s |
| `/api/estado` **durante** a geração | mediana **2,2 ms**, máximo 9,0 ms — a geração roda em thread e não segura requisição nenhuma |
| 30 polls com `If-None-Match`, peça parada | **30/30 → 304**, `sondas` sobe **0**, mediana **0,40 ms** |
| o mesmo servidor com o cache de sonda desligado (defeito plantado) | `sondas` sobe **29** ⇒ o critério reprova. O portão tem dentes |
| `pgrep -f 'servidor.py servir' \| wc -l` | devolve **2** com um servidor só de pé. O segundo é o **shell wrapper** que o `run_in_background` cria, cujo comando contém a string. Contar processo Python de verdade: `pgrep -f 'servidor.py servir' \| xargs -I{} ps -o comm= -p {} \| grep -ci python` → **1** |

---

## Rotas — `benchmark.preview-api/v1`

Tudo sob `/<token>/`. Fora do prefixo, ou com token errado: **404** (não confirma
que existe algo ali). `Host` que não seja loopback ou o host HTTPS exato aceito
pelo adaptador: **403** (defesa contra DNS rebinding).

| método | rota | resposta |
|---|---|---|
| GET | `/<token>/` | `app/index.html`, ou a página de diagnóstico embutida |
| GET/HEAD | `/<token>/app/<caminho>` | arquivo da app (`no-store`) |
| GET/HEAD | `/<token>/media/<caminho>` | arquivo sob a produção, com Range/206/416 (`no-cache` + ETag) |
| GET | `/<token>/gen/<chave>/thumbs/<NNNN>.jpg` | thumb (`immutable`); **404** enquanto não está pronto |
| GET | `/<token>/gen/<chave>/thumbs/meta.json` | `benchmark.preview-strip/v1` |
| GET | `/<token>/gen/<chave>/waveform.json` | `benchmark.preview-waveform/v1` |
| GET | `/<token>/api/estado` | `benchmark.preview-estado/v1`, com `ETag`; no 200 de uma sessão criada por `GET /<token>/` emite `sessao.nonce_aprovacao`; **304** com `If-None-Match` |
| GET | `/<token>/api/saude` | `{ok, dir, pid, versao, desde, sondas, req}` |
| POST | `/<token>/api/salvar` | `{ok, arquivo}`; 400 / 413 (>1 MiB) / 415 (não-JSON) |

CLI:

```
servidor.py sessao --dir D [--porta N] [--altura-thumb 90]
servidor.py servir --dir D [--porta N] [--token T] [--app DIR] [--ocioso 120] [--altura-thumb 90]
servidor.py parar  --dir D
servidor.py status --dir D
```

---

## O que a app pode contar (contrato para SPEC-18/19)

`GET api/estado` devolve `benchmark.preview-estado/v1`. O schema completo está na
**SPEC-17 §4.2**; o que mais importa para quem consome:

- **`estado`** — o `<dir-producao>/.preview/estado.json` **cru**, escrito pelo
  `estado.py` da SPEC-16. O servidor repassa e **não valida**. Sem o arquivo,
  vem `{}`.
- **`midia`** — `rel`, `chave`, `dur`, `width`, `height`, `fps`, `aspecto`, `rot`,
  `bytes`, `mtime_ns`, mais `strip` e `waveform`. Todos saem de `ffprobe` **do
  arquivo que está tocando**. Nenhum número de formato é escrito no código: quem
  decide layout é a app, a partir de `midia.aspecto`. `midia: null` = ainda não há
  render.
  - `strip`: `{estado: "gerando"|"pronto"|"ausente"|"erro", n, intervalo, altura, feito}`.
    O instante do thumb `k` (1-based) é `t0 + (k-1)*intervalo`, com
    `t0 = intervalo/2` — a amostragem é no **meio** do balde, não na borda; é o que
    evita o filmstrip defasar.
  - `waveform`: `{estado, picosPorS}`. `picosPorS` é **float** e cai numa peça
    longa (teto de 20.000 baldes). **Leia o campo, nunca uma constante.**
  - **`servivel`** (adendo desta implementação ao schema da §4.2, aditivo): `false`
    quando o render é um symlink que resolve para **fora** da produção. Nesse caso
    o filmstrip e a waveform são gerados normalmente (leitura local e deliberada,
    vinda do `estado.json`), mas `GET media/<rel>` devolve **403** — a validação de
    caminho não abre exceção. É o caso real de `input/<bruto>` symlinkado para o
    banco de dados do repo. A app deve olhar `servivel` antes de montar o `<video>`.
- **`perfil`** — o `perfil.json` da produção, **cru** (SPEC-00) ou `null`. O
  servidor não interpreta.
- **`edl`** — `edl.json` cru: array (v1) **ou** objeto (v2). Sem conversão.
- **`timeline_real`** / **`timeline_real_ausente`** — 🔴 quando
  `timeline_real_ausente` é `true`, **não existe coordenada de render**. A
  `SPEC-16 §3.12` é a autoridade: a UI **desabilita** a marcação por instante de
  render. **Somar `Σ(end−start)` da EDL é proibido** — foi exatamente aí que o
  ref-A acumulou 4,433 s de erro em 20 takes.
- **`arquivos`** — `{nome: [mtime_ns, bytes]}` dos observados; é o que gera o
  `ETag`. Fazer poll **com `If-None-Match`**: com a peça parada a resposta é 304,
  sem corpo e sem subprocess.
- **`pendentes`** — quantos saves ainda não foram aplicados.

### Salvar

```jsonc
POST api/salvar   Content-Type: application/json   (≤ 1 MiB)
{"tipo": "ajustes" | "estilo", "payload": { /* ajuste v1 ou estilo v1/v2/v3, cru */ }}
```

Saves novos da aba Look usam `benchmark.edit-estilo/v3` e exigem
`direcao_edicao`: Essencial, Animada ou Surpresa. O servidor continua sem
inventar default; validação e aplicação pertencem a `escolha-estilo.py`. Sem a
escolha explícita, a UI não habilita o envio e a Fase 2 não deve começar.

O servidor **não valida o payload**: carimba, envelopa e grava. Cada save vira
**um arquivo novo** em `<dir-producao>/.preview/pendentes/`, com nome ordenável
cronologicamente — nada é sobrescrito, nunca. Salvar 5 vezes gera 5 eventos.

A exceção é `tipo: "aprovacao"`: além do snapshot completo de contexto, o
POST precisa carregar o `nonce_aprovacao` efêmero recebido pela UI. O servidor
o confere contra o token e o contexto que o emitiram, consome uma vez e o remove
antes de persistir o envelope. POST sem nonce, com nonce repetido ou com contexto
divergente não registra aprovação nem cria pendência.

```jsonc
{"schema":"benchmark.preview-evento/v1","tipo":"ajustes",
 "salvo_em":"2026-08-08T20:11:15-03:00",
 "origem":{"ua":"…","token":"…"},"payload":{ … }}
```

**O ACK é o move**: o agente aplica e **move** o arquivo para
`<dir-producao>/.preview/aplicados/` — não apaga. O histórico do que foi pedido
fica na produção, ao lado do `NOTAS.md`, e o `watch-preview.py` re-arma sem
depender de ninguém apagar nada.

---

## Dentro de `<dir-producao>/.preview/`

```
servidor.json          sessão viva (url, porta, token, pid) — apagado ao encerrar
cache/<chave>/thumbs/  filmstrip + meta.json     ← endereçado por conteúdo, immutable
cache/<chave>/waveform.json
pendentes/*.json       saves ainda não aplicados  ← o servidor grava
aplicados/*.json       saves já aplicados         ← o agente move
estado.json            escrito pelo estado.py da SPEC-16 — aqui só é LIDO
```

`<chave> = sha1(caminho|mtime_ns|bytes|n|altura)[:12]`. O render mudou ⇒ a chave
muda ⇒ a URL muda ⇒ o browser busca de novo, sem revalidação. Cache velho é
coletado **no fim** de uma geração (guarda as 3 chaves mais recentes), **nunca**
durante o uso. A geração acontece em `<chave>.thumbs-parcial/` e só vira
`<chave>/thumbs/` por `os.replace` no fim: um `kill` no meio não deixa cache pela
metade.

---

## Decisões que não se mexem sem medir de novo

- **Contagem de thumbs limitada, intervalo derivado** (24 ≤ n ≤ 200, alvo 2 s).
  O custo do filmstrip fica **independente da duração da peça**: uma VSL de 30 min
  gera 200 thumbs, não 918. O oposto — intervalo fixo — cresce linear e sem teto.
- **Geração por seek pontual em pool**, não por decode completo. Na peça curta os
  dois métodos empatam; o que muda é o teto.
- **`ffprobe` cacheado por `(caminho, mtime_ns, bytes)`** + ETag/304 + piso de
  reavaliação de 250 ms. Um `/api/estado` caro nunca quebra nada — só faz a
  máquina rodar ffprobe o dia inteiro com uma aba aberta. O contador `sondas` em
  `/api/saude` existe para essa recaída ser conferível por comando.
- **Nada de framework.** Stdlib pura, `python3` que já está na máquina.
- **Só `127.0.0.1`**, nunca `0.0.0.0`. Porta efêmera do SO, nunca porta fixa.
- **Cloud não muda o bind.** O adaptador aceita apenas um proxy autenticado que a
  plataforma declarou por ambiente. Sem esse recurso externo, o fallback local
  permanece a unica superficie funcional.
- **Nenhum valor de formato no código** — largura/altura/fps/aspecto vêm sempre do
  `ffprobe`; a largura do thumb sai de `scale=-2:<altura>`.
  Portão: `grep -nE '1080|1920|\b30\b|9:16|16:9' servidor.py` tem que voltar vazio.
- **`sleep` em foreground é bloqueado neste harness.** Quem espera é o
  `curl --retry-connrefused` ou um laço `until`.
- **`preview_start` é uma capacidade da superfície, não do servidor.** Este
  pacote inclui `launch.exemplo.json`; a instalação o copia para
  `.claude/launch.json` para o Claude Code que oferece painel lateral. Onde essa
  capacidade não existe, o arquivo é ignorado e o mesmo servidor abre no
  navegador local. O fluxo nunca depende do painel para salvar ou aprovar.

---

## A UI não substitui os QCs medidos

Ela é portão de aprovação **editorial**. Não substitui `qc-fonemas.py`,
`qc-cor.py`, `qc-emendas-asr.py` nem a varredura de frames. O olho acha o que os
QCs não acham — e os QCs acham, em 70 s de vídeo, o que o olho não acha.

---

Desenho derivado de o servidor de preview de uma ferramenta de edição de terceiro de uma ferramenta de edição de terceiro, sem cópia literal. O que é nosso e o que é
deles está discriminado na **SPEC-17 §10**.
