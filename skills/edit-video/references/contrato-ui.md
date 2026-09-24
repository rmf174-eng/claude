# `contrato-ui.md` — o contrato de dados da UI de aprovação

> **Fonte de verdade** dos três schemas que a UI de aprovação lê e escreve.
> Entregue pela **SPEC-16**. Quem consome: a **SPEC-17** (servidor), a **SPEC-18**
> (timeline interativa) e a **SPEC-19** (galeria de estilos).
>
> Implementação: `scripts/estado.py`. Exemplos completos e válidos:
> `scripts/tests/fixtures/{estado,ajustes,estilo}-exemplo.json`.
> Teste: `scripts/tests/test_contrato_ui.py` (71 checagens, 18 defeitos plantados).

---

## 1. Onde os arquivos vivem

Tudo dentro de **`<dir-producao>/.preview/`**. O diretório da produção chega
sempre **por argumento** — nenhum script deste contrato conhece `creators/`,
`data/` ou qualquer caminho da nossa instalação.

```
<dir-producao>/.preview/
├── estado.json          benchmark.edit-estado/v1     ← estado.py escreve, a UI lê
├── estado-agente.json   o que o AGENTE declarou      ← estado.py escreve
├── pendentes/*.json     benchmark.preview-evento/v1  ← o servidor escreve, o agente lê
├── aplicados/*.json     o mesmo arquivo, depois      ← o ACK é o MOVE
├── ajustes.json         benchmark.edit-ajustes/v1    ← caminho SEM servidor
├── estilo.json          benchmark.edit-estilo/v1     ← caminho SEM servidor
├── servidor.json        SPEC-17                      ← estado.py nem lê
└── cache/               SPEC-17                      ← estado.py nem lê
```

Subdiretório oculto, e não a raiz da produção, por três razões: a raiz já tem 20+
arquivos nas produções reais e o ciclo "aparece / é consumido / some" fica
ilegível no meio deles; o watcher observa **um diretório**, não uma lista de
caminhos; e apagar `.preview/` inteiro é um reset limpo da sessão de aprovação
sem tocar em nada de produção.

**Um escritor por arquivo, sempre.** `estado.json` só o `estado.py` escreve. Os
arquivos do canal de volta só a UI (ou o servidor, em nome dela) escreve. Ninguém
edita in-place o arquivo do outro.

### Ciclo de vida

| arquivo | escreve | lê | some quando |
|---|---|---|---|
| `estado.json` | `estado.py` | UI, servidor | nunca (é regravado) |
| `estado-agente.json` | `estado.py` (flags do agente) | `estado.py` | nunca |
| `pendentes/<carimbo>-<tipo>-<n>.json` | servidor (SPEC-17) | `estado.py --consumir` | **move** para `aplicados/` |
| `ajustes.json` · `estilo.json` | agente à mão, teste, fixture | `estado.py --consumir` | **move** para `aplicados/<carimbo>-<tipo>.json` |
| `aplicados/*.json` | `estado.py` (no ACK) | humano, auditoria | nunca |

**Por que move e não delete.** O delete-como-ACK vem do `watch_edits.py:129-130`
do ref-A e existe lá porque não há para onde mover. Mover preserva o que o
usuário pediu, com carimbo, ao lado da produção — e o watcher re-arma do mesmo
jeito, porque o arquivo sumiu de `pendentes/`.

### Escrita atômica

Temporário com sufixo **acrescentado**, no **mesmo diretório**, mais `os.replace`:

```
estado.json.<pid>.parcial   →   os.replace   →   estado.json
```

⚠️ Nunca `Path.with_suffix('.tmp')`: ele **troca** a extensão em vez de
acrescentar. Funciona no ref-A por acidente de nomenclatura e colidiria aqui no
dia em que existir `ajustes.tar` ao lado. **Quem varre o diretório ignora
`*.parcial`.**

Medido: 50 escritas concorrentes com 4 leitores em laço (1.181 leituras) →
**0 falhas de `json.loads`**, **0** `.parcial` sobrando.

---

## 2. `benchmark.edit-estado/v1` — o estado, DERIVADO do disco

O `state.json` do ref-A é **digitado pelo agente**. Aqui o `estado.json` é
**gerado por um script** a partir do que está no disco; o agente só declara o que
o disco não sabe (fase, mensagem, portão, aprovações, quais renders importam), e
isso vive em `estado-agente.json`. Estado escrito à mão descola do disco em
silêncio — é a mesma classe de defeito que o sidecar de procedência existe para
pegar, e este repo já pagou por ela.

```jsonc
{
  "contrato": "benchmark.edit-estado/v1",
  "revisao": 7,                          // inteiro monotônico, +1 a cada escrita
  "gerado_em": "2026-08-08T15:38:04-03:00",
  "gerado_por": "estado.py",

  "producao": {"slug": "…", "dir": ".", "creator": "…"|null, "titulo": "…"|null},
  "fase": 1|null,
  "mensagem": "…"|null,
  "portao": null|"estilo",
  "portao_forcado": null|{"portao": "estilo", "por": "…", "em": "…",
                          "motivo": "…", "aviso": "…"},

  "perfil": { /* snapshot resolvido do perfil.json, SPEC-00 */ }|null,
  "perfil_sha256": "…"|null,
  "formato": {"largura": …, "altura": …, "fps": …, "fonte": "perfil"|"medido"|null},
  "zonas_ui": {"topo_pct": …, "fundo_pct": …, "direita_pct": …}|null,

  "edl_schema": "benchmark.edl/v1"|"benchmark.edl/v2",
  "fingerprint_corte": "sha1:…",         // muda só quando o CORTE muda
  "segmentos": [ /* §2.1 */ ],
  "timeline_real": { /* espelho do bloco da SPEC-05 */ }|null,

  "renders": [
    {"papel": "corte"|"entrega"|"outro", "arquivo": "v1-montado.mp4",
     "fingerprint": "sha1:…", "duracao_s": …, "frames": …,
     "frames_origem": "nb_frames"|"count_frames"|"indisponivel",
     "largura": …, "altura": …, "fps": …, "pix_fmt": "…",
     "tags_cor": {"color_primaries": …, "color_trc": …, "colorspace": …},
     "bytes": …, "mtime": …}
  ],
  "render_corrente": "v1-montado.mp4"|null,
  "fingerprint_render": "sha1:…"|null,

  "legendas": {"arquivo": "captions.json", "palavras": 214}|null,
  "plano": {"arquivo": "PLANO-EDICAO.md", "sha256": "…", "mtime": …}|null,
  "aprovacoes": [ /* §2.3 */ ],
  "estilo_vigente": { /* §2.5 */ }|null,
  "integridade": { /* §2.2 */ },
  "ultimo_ajuste_aplicado": { /* §3.3 */ }|null,
  "qc": [],                              // RESERVADO. Vazio nesta versão.
  "avisos": []
}
```

🔴 **`tags_cor` viaja CRU e não é veredito.** Neste build o rótulo mente
(`-pix_fmt gray` sai `yuvj420p`; `-color_primaries` de saída é ignorado). Quem
decide se a cor está certa é o `detect-cor.py`/`qc-cor.py` da SPEC-11, cruzando
rótulo × pixel. A UI pode **mostrar** as três tags; não pode concluir nada delas.

⚠️ **`qc: []` é reservado.** Popular exigiria uma convenção de saída que nenhum
dos nossos QCs escreve hoje (todos imprimem em stderr/stdout). Inventar o formato
aqui, sem consumidor, é a definição de dívida.

### 2.1 Um segmento

```jsonc
{"sid": "reveal#1", "i": 7, "src": "input/IMG_6700.MOV", "start": 41.57, "end": 45.33,
 "fala": "…", "beat": "reveal", "zoom": 1.0, "cx": 0.5, "cy": 0.5,
 "extras": {"quem": "creator-2"},              // TODO campo da EDL que não é conhecido
 "arquivo": "segs/seg007.mp4"|null,
 "rascunho": {"ini_s": 41.220, "dur_s": 3.760}|null,   // 🔴 régua do RASCUNHO
 "medido":   {"frames": 113, "frames_origem": "nb_frames", "fps": 30.0,
              "largura": …, "altura": …, "bytes": …}|null,
 "saida":    {"ini_s": 41.573, "dur_s": 3.767,
              "ini_frame": 1247, "frames": 113}|null,   // só com timeline_real
 "procedencia": {"estado": "ok"|"ausente"|"divergente"|"orfao"|"nao_renderizado",
                 "campos": […], "sidecar": {…}, "edl": {…},
                 "extras_sidecar": […]}}
```

🔴 **`rascunho` × `saida` — a distinção que este contrato existe para manter.**

| | `rascunho` | `saida` |
|---|---|---|
| como é calculado | Σ(`end`−`start`) dos anteriores | `timeline_real`: Σ frames / fps |
| o que descreve | a timeline **virtual** que a UI compõe | o **arquivo que existe** |
| quando é `null` | EDL sem `start/end` nem `f0/f1` | sempre que `timeline_real` é `null` |
| pode virar coordenada de render? | **NUNCA** | é a única que pode |

`Σ(end−start)` é MENOR que a saída, sempre, porque o render arredonda para frame
e o erro acumula no mesmo sentido. Medido neste repo: **353,3 ms** no fim de
`peca-03` (20 segs), **316,7 ms** em `peca-01` (29) e **351,7 ms** em
`c-completo` (16). Marcar por essa régua manda o agente editar o take vizinho, e
nada acusa.

`extras_sidecar` lista campos do sidecar que **não têm contraparte na EDL** —
decisões de render, como `perfil_video_sha` e `video_skip_frames`. Não são
divergência (a regra é estrutural, não uma lista de nomes: `video_skip_frames`
nasceu no `montar.sh` depois deste contrato), mas aparecem, porque campo que some
em silêncio é o defeito que a SPEC-05 acabou de matar na EDL.

### 2.2 `integridade` — o que nenhum QC nosso mostra

```jsonc
{"veredito": "ok"|"suspeito"|"quebrado",
 "soma_nominal_s": 65.880,        // Σ(end−start) — DIAGNÓSTICO, nunca posição
 "timeline_real_s": 66.233,       // null sem SPEC-05
 "render_s": 66.233,              // frames/fps do render corrente
 "delta_nominal_ms": 353.3,       // esperado: o arredondamento para frame
 "delta_real_ms": 0.0,            // ≠ 0 significativo = segmento de outra geração
 "segs_no_disco": 22, "segs_na_edl": 21,
 "orfaos": ["segs/seg21.mp4"],
 "sem_sidecar": ["segs/seg00.mp4", "…"],
 "divergentes": [{"seg": …, "sid": …, "campos": ["start"], "sidecar": {…}, "edl": {…}}]}
```

| veredito | quando |
|---|---|
| `quebrado` | há órfão, há divergente, ou `\|delta_real_ms\|` > 1 frame |
| `suspeito` | falta sidecar, falta `timeline_real`, ou não há render de montagem |
| `ok` | nada disso |

⚠️ **`sem_sidecar` ≠ `orfao`.** No `montar.sh` os dois se resolvem igual (refazer
o segmento), mas no relatório são coisas diferentes: `peca-03` e `peca-04` têm
37 segmentos sem sidecar e **nenhum órfão** — são produções da era anterior ao
fix, já publicadas, e marcá-las como quebradas é falso positivo em massa. `orfao`
é `.mp4` **sem entrada correspondente na EDL**; `ausente` é entrada da EDL cujo
`.mp4` existe sem sidecar.

🔴 **`estado.py` REPORTA, NUNCA CONSERTA.** Apagar órfão é trabalho do
`montar.sh`. Um gerador de estado que conserta apaga a evidência que ele existe
para mostrar — e é o que permite rodá-lo, sem medo, sobre as produções já
publicadas. Medido: em `ovo-de-pascoa` (22 `.mp4` × 21 na EDL), `ls segs/*.mp4 |
wc -l` continua **22** depois de rodar, e o script sai **0**.

### 2.3 `aprovacoes` — confrontável com o disco

```jsonc
{"alvo": "fase-1", "render": "v1-montado.mp4", "render_fingerprint": "sha1:…",
 "plano_sha256": "…", "em": "2026-08-08T15:41:02-03:00", "por": "creator-1",
 "valida": true, "motivo": null}
```

**Uma aprovação só vale se `plano_sha256` e `render_fingerprint` baterem com o
que está no disco.** Editar o plano depois de aprovado invalida a aprovação, com
mensagem explícita (`"motivo": "plano_sha256 divergente"`). Medido: **1 byte** no
`PLANO-EDICAO.md` derruba `valida` para `false`.

A origem `ui-save` exige também `sessao.nonce_aprovacao`, emitido numa resposta
200 de `api/estado` somente depois que o servidor entregou o documento da UI e
abriu sua sessão privada de browser. Ele vive na memória do servidor por até 10
minutos, fica preso à sessão, ao token e aos cinco campos do snapshot da tela, e
é consumido na primeira tentativa. O nonce não participa do ETag nem dos
fingerprints e é retirado do payload antes de o envelope entrar em `pendentes/`.

Isto bloqueia POST direto, replay e aprovação de um snapshot diferente. Não
prova criptograficamente um clique humano contra um processo local deliberado:
quem controlar a sessão completa do browser consegue automatizar o protocolo.
Por isso o contrato do agente continua explícito: ele nunca busca, copia ou
envia o nonce fora do código da própria UI.

O `PLANO-EDICAO.md` deixa de ser o portão e passa a ser o **documento de
decisões** que acompanha o render aprovado. O que ele tem e uma timeline nunca vai
ter é o **raciocínio**.

### 2.5 `estilo_vigente` — o campo que faz a aba ESTILO ter volta

```jsonc
{"aplicado_em": "2026-08-11T01:12:44-03:00", "revisao_aplicada": 7,
 "arquivo": ".preview/estilo-vigente.json",
 "origem": ".preview/aplicados/20260811T011203-estilo.json",
 "legenda": "legenda-quente-evento", "headline": "headline-card",
 "acento": "palavra-acento", "gramatica_plano": "punch-pontual",
 "elementos": ["punch", "tracking"]}
```

`null` enquanto nenhum estilo foi aplicado. Preenchido pelo gerador a partir de
`.preview/estilo-vigente.json`, que é escrito **só** por
`escolha-estilo.py --aplicar` — nunca pela tela, nunca pelo servidor.

🔴 **Por que este campo existe, e por que ele é um RESUMO.** A aba ESTILO decide
se fica habilitada por `estado.estilo_vigente` (`preview/app/js/estilos.js:69`),
e a galeria decide se a próxima escolha é uma TROCA (`rerender: true`, que o
watcher anuncia como `🔁 REFAÇA`) por `galeria.json.vigente`
(`galeria.js:148-149`). Até 2026-08-11 os dois campos existiam só no leitor: um
grep por escritor devolvia zero, e o efeito medido na tela era um beco — estilo
aplicado, portão fechado, aba **desabilitada**, sem caminho de volta para trocar.
É resumo e não o payload inteiro porque o estado é lido por poll a cada 2 s; quem
precisa do payload abre o arquivo nomeado em `arquivo`.

`elementos` traz só os interruptores LIGADOS, em ordem — é o que a tela mostra, e
uma lista de `false` não informa nada.

### 2.4 Modo degradado — o gerador nunca inventa o que não pode medir

| falta | o que o estado faz | o que **não** faz |
|---|---|---|
| `perfil.json` (SPEC-00) | `perfil: null`; `formato` **medido** dos `segs/` por ffprobe; `zonas_ui: null`; aviso nomeando o motivo | não assume vertical, não assume 30 fps, não assume zona de feed |
| `timeline_real` (SPEC-05) | `timeline_real: null`; `saida: null` em 100% dos segmentos; `notas[].render` obrigatoriamente `null`; aviso | **não** calcula por Σ(end−start) |
| `timeline_real` velha | tratada como ausente, com o aviso dizendo que ela não descreve este corte | não usa os números velhos |
| EDL v1 (array) | lê normal; `edl_schema: "benchmark.edl/v1"` | não converte o arquivo |

Medido em `peca-09` (16:9, sem `perfil.json`): `formato.fonte ==
"medido"`, **1280×720@30**, `zonas_ui: null`. A UI simplesmente não desenha guias
de feed num vídeo de player web — o layout segue a **saída**, nunca a fonte (o
bruto do creator-3 é 4K landscape e a entrega é 9:16 recortada).

---

## 3. O canal de volta

### 3.0 A regra que mata o bug do ref-A

> **Índice posicional não aparece em nenhum dos arquivos de volta. Toda
> referência a um segmento é por `sid`. O canal de volta transporta
> OPERAÇÕES, nunca um array reconstruído.**

O ref-A manda de volta `edl.ranges` (a lista inteira, já filtrada), `edl.changes`
e `edl.removed` — três representações da mesma coisa, e é a discordância entre
elas que o `app.js:1826` produz: remover um take desalinha `draft` e `rendered`
para sempre, e toda nota salva depois aponta para o take errado. Aqui há uma
representação só.

**`sid`** = `<slug do beat, ou do basename do src>#<ordinal da ocorrência>`.
Derivado, nunca persistido — `bordas.py` pode reescrever a EDL inteira e os `sid`
saem iguais. Medido em material real:

- `peca-01`: mover `start`/`end` de 5 segmentos em ±0,30 s → **29/29**
  `sid` preservados; renomear 1 `beat` → **exatamente 1** `sid` muda.
- `peca-03`: remover o **8º de 20** → os **19/19** restantes mantêm o `sid`, e uma
  nota gravada sobre o segmento 15 continua resolvendo para o mesmo
  `src/start/end`. No ref-A isso falha por construção.

### 3.1 `benchmark.edit-ajustes/v1`

```jsonc
{
  "contrato": "benchmark.edit-ajustes/v1",
  "salvo_em": "2026-08-08T15:41:19-03:00",   // ISO-8601 COM offset
  "revisao_base": 7,                          // a revisão que o usuário estava vendo
  "fingerprint_corte": "sha1:…",
  "fingerprint_render": "sha1:…",
  "render_alvo": "v1-montado.mp4",

  "notas": [
    {"sid": "reveal#1"|null,                  // null = nota livre
     "rascunho": {"ini": 41.220, "fim": 44.980},
     "render":   {"ini": 41.573, "fim": 45.333}|null,
     "fase": 1, "texto": "o corte come o começo do 'porque'"}
  ],
  "operacoes": [
    {"sid": "dor-2#1", "op": "ajustar",
     "de":   {"start": 22.310, "end": 25.980},   // o que a UI ACREDITA ser o atual
     "para": {"start": 22.410, "end": 25.980}},
    {"sid": "muleta#1", "op": "remover", "de": {"start": 51.02, "end": 52.44}}
  ],
  "elementos": [
    {"ref": "cartao-3", "op": "mover", "para": {"ini": 12.30, "fim": 15.10}}
  ]
}
```

`op ∈ {ajustar, remover, restaurar}`. `de` é sempre o valor que a UI acredita ser
o atual — o agente compara e recusa se não bater (mesma ideia do
`confere_procedencia` do `audio-exato.py`).

🔴 **`notas[].render` é `null` sempre que `timeline_real` for `null`. Sem exceção
e sem "só como fallback".** A SPEC-17 §4.2 expõe `"timeline_real_ausente": true`;
o **flag é bom e deve ser consumido**, a soma não. Nesse caso a UI desenha a régua
como aproximada e **não grava número nenhum** no canal de volta. Uma aproximação
que só existe na tela é um desenho; a mesma aproximação gravada num arquivo que o
agente vai aplicar é um defeito. `validar()` **reprova** um `render` preenchido
sem `timeline_real`.

### 3.2 `benchmark.edit-estilo/v1`

```jsonc
{
  "contrato": "benchmark.edit-estilo/v1",
  "salvo_em": "2026-08-08T15:52:03-03:00",
  "revisao_base": 8,
  "rerender": false,                    // true quando chega depois de a fase 2 existir
  "legenda": "karaoke",
  "headline": "realce",
  "acento": "#D14E72",
  "acento_usado": true,                 // false = os estilos escolhidos não pintam acento
  "elementos": {"punch_alternado": true, "split_broll": false, "sfx": true,
                "trilha": false, "flash_no_corte": false},
  "gramatica_plano": "alternada",
  "observacao": "…"
}
```

- **`acento_usado: false`** — nomear uma cor que nenhum estilo pinta lê como
  instrução para inventar onde usá-la. O resumo diz explicitamente para não
  inventar.
- **Caixa desmarcada é um NÃO explícito, não silêncio.** O resumo imprime a linha
  `fora:` com os desmarcados, nominalmente.
- ⚠️ **`gramatica_plano` afeta o CORTE** (`zoom`/`cx`/`cy` na EDL), não a camada
  gráfica. Está aqui porque a escolha é do mesmo momento e da mesma tela; quem
  consome tem que saber que aceitar isso implica **remontar**, não só
  re-renderizar o alpha. O resumo avisa.

**Por que dois arquivos e não um.** Aplicar `ajustes` significa reeditar a EDL e
remontar (`bordas.py` → `montar.sh` → `audio-exato.py`, minutos de render).
Aplicar `estilo` significa regerar a camada alpha do Remotion — outro pipeline,
outro artefato. Num arquivo só, uma escolha de estilo salva enquanto a remontagem
roda seria consumida pelo lado errado do fluxo. O envelope carimbado já mata o
clobber por construção; o que sobrevive, e é o que importa, é o **roteamento por
`tipo`**.

### 3.3 Os dois caminhos de entrada, um só consumidor

`consumir()` aceita:

1. **Envelope** `benchmark.preview-evento/v1` em `.preview/pendentes/` (SPEC-17):
   ```jsonc
   {"schema": "benchmark.preview-evento/v1", "tipo": "ajustes"|"estilo",
    "salvo_em": "…", "origem": {"ua": "…", "token": "…"}, "payload": { /* §3.1 ou §3.2 */ }}
   ```
2. **Objeto cru** em `.preview/ajustes.json` / `.preview/estilo.json` — o caminho
   de quando **não há servidor**: agente escrevendo à mão, teste, fixture.

Medido: os dois produzem `resumo()` **byte a byte idêntico** (414 bytes no caso de
teste) e o mesmo `ultimo_ajuste_aplicado` (menos `arquivo` e `aplicado_em`).

**Ordem**: por `salvo_em`, do mais antigo para o mais novo, **um por vez**. Com
dois pendentes do mesmo `tipo` na fila, o **mais novo vence** e o mais antigo vai
para `aplicados/` com `"ignorado": "superado por <arquivo>"` — **1** aplicação,
nunca 2, e nunca aplicado em cima.

**Conflito**: se `fingerprint_corte` ou `fingerprint_render` do payload não
baterem com o estado atual, `consumir()` **sai 2, não move nada** e diz o quê
mudou. `--mesmo-com-conflito` aplica assim mesmo e registra o conflito em
`ultimo_ajuste_aplicado.conflito` (medido: aplica de verdade, não é no-op).

`ultimo_ajuste_aplicado`:

```jsonc
{"tipo": "ajustes", "salvo_em": "…", "revisao_base": 5, "aplicado_em": "…",
 "arquivo": ".preview/aplicados/20260808T154119-ajustes.json",
 "conflito": null, "superados": 0, "notas": 3, "operacoes": 1, "elementos": 0}
```

---

## 4. Revisão e invalidação — o fim do toast preso

Três campos, e é o **contrato** que resolve, não a UI:

| campo | muda quando |
|---|---|
| `revisao` | **toda** escrita de `estado.json` (+1, monotônico) |
| `fingerprint_corte` | só quando o **corte** muda (sha1 canônico dos segmentos) |
| `fingerprint_render` | só quando o **render corrente** muda (caminho + bytes + mtime) |

1. Ajustes pendentes são invalidados **se e somente se** `fingerprint_corte` ou
   `fingerprint_render` mudarem. Mudança em `mensagem`, `fase`, `avisos` ou
   `plano` **não** invalida nada — o usuário continua editando. Medido: duas
   escritas mudando só `mensagem` deixam os dois fingerprints idênticos e a
   `revisao` cresce.
2. O aviso "novo estado disponível" é emitido **uma vez por `revisao`**, e a
   revisão vista é registrada **incondicionalmente** — não só no ramo limpo, que é
   o defeito do `app.js:726` (com ajustes sujos, cada poll cai no `else`, chama
   `toast()`, o `clearTimeout` reprograma o timer e o aviso **nunca some**).
3. `revisao_base` no canal de volta é a revisão que o usuário estava vendo. O
   ref-A não tem esse campo; sem ele não há como distinguir "chegou atrasado" de
   "chegou agora".

Medido: 50 escritas → `revisao` estritamente crescente em **50/50**.

---

## 5. CLI

```
estado.py <dir> [--fase N] [--mensagem "…"] [--portao estilo|nenhum]
                [--render v1-montado.mp4] [--entregavel v-final.mp4]
                [--creator …] [--titulo …] [--aprovar <alvo> [--por <nome>]]
                [--medir-timeline]                   → grava .preview/estado.json
estado.py <dir> --pendentes                          → a fila do canal de volta (JSON)
estado.py <dir> --consumir <arquivo|ajustes|estilo> [--mesmo-com-conflito]
estado.py <dir> --validar <arquivo.json>             → sai 1 se violar o contrato
estado.py <dir> --mostrar                            → imprime o estado (stdout)
```

As flags do primeiro modo **persistem** em `.preview/estado-agente.json`, então
`estado.py <dir>` sem flag nenhuma regenera preservando o que o agente já
declarou.

`--medir-timeline` mede a `timeline_real` offline a partir dos `segs/` quando ela
não está no disco (é `edl_io.medir_timeline`, o mesmo código da SPEC-05) e
**não grava nada na produção**. É opt-in porque o padrão tem que ser a
degradação honesta: um gerador que supre em silêncio o que a SPEC-05 não gravou
esconde exatamente o que a §2.4 existe para mostrar.

Como biblioteca:

```python
sid_de(segments)                      -> list[str]
gerar(dir, medir_timeline=False)      -> dict          # lê o disco, não grava
escrever(dir, est)                    -> str           # tmp + os.replace, revisao +1
coordenada_render(est, sid, ini, fim) -> dict|None     # None sem timeline_real
validar(obj, contrato=None, est=None) -> list[str]     # vazia = ok
pendentes(dir)                        -> list[dict]
consumir(dir, alvo, mesmo_com_conflito=False) -> dict|None
resumo(obj)                           -> str
```

`resumo()` mora **aqui**, e não no watcher da SPEC-17, porque quem conhece o
schema é quem o define — no ref-A, 55% do `watch_edits.py` é digest amarrado ao
schema, e qualquer campo novo obriga a editar dois arquivos. O watcher só imprime
o que este módulo devolve.

---

## 6. O que a SPEC-18/19 não pode fazer

- 🔴 **Não somar `Σ(end−start)` para achar posição no render.** Nem "só como
  fallback". Sem `timeline_real`, a marcação por instante de render fica
  **desabilitada**.
- 🔴 **Não reconstruir um array de segmentos no canal de volta.** Se você se pegar
  escrevendo `segmentos[i]`, pare: é o `app.js:1826` voltando.
- ⚠️ **Não sondar `ffprobe` por requisição.** O `preview_server.py:271` do ref-A
  chama `probe_duration()` em **toda** requisição de `/api/state`, com poll de
  2 s: ~1.200 subprocessos numa sessão de 40 min. Aqui o ffprobe roda na
  **geração** e o número fica gravado. Precisa de frescor? Regenere o estado.
- ⚠️ **Não escrever valor de formato.** `formato.largura/altura/fps` e
  `zonas_ui` (em **fração**, convertidas para pixel por quem desenha) são a única
  fonte. Portão do lado de cá: o grep das dimensões conhecidas em `estado.py`
  devolve **0** linhas.
- ⚠️ **Não tratar `creator` como chave.** É string **opaca**, informativa, e vem
  só do que o agente declarou. Nenhum campo do contrato tem semântica que dependa
  do valor, e todos os caminhos são relativos a `<dir-producao>`.

---

## 6b. `benchmark.edit-estilo/v2` — o estilo com vocabulário de catálogo (SPEC-19)

O **v1** acima nomeia estilo com palavra solta (`"legenda": "karaoke"`), herdada
do ref-A. O **v2** nomeia com **slug do catálogo de estilos** (SPEC-15), que é o
que permite validar a escolha contra o que a peça realmente oferece.

**É mudança de versão, não adição solta.** Um leitor de v1 quebra num v2 em dois
pontos: `headline` virou `gancho`, e os *valores* de `legenda` passaram a ser
slugs. **O v1 continua válido** — `escolha-estilo.py` aceita os dois e traduz
`headline → gancho` ao ler o antigo. Nenhum arquivo foi migrado: nenhum
`estilo.json` v1 chegou a ser escrito.

```jsonc
{
  "contrato": "benchmark.edit-estilo/v2",
  "salvo_em": "…", "revisao_base": 8,
  "fonte": "galeria",                  // "galeria" | "chat" — procedência da escolha
  "rerender": false,                   // true = restilizar peça que já tem Fase 2

  "gramatica": "plano-alternado",      // SLUG (grupo gramatica)
  "gramatica_plano": "alternada",      // DERIVADO de aplica.valor — o que vai pro perfil
  "tema": "tema-creator-2",
  "gancho": "hook-titulo-typeon",      // era "headline"
  "legenda": "legenda-morno-destacado",// era "karaoke"

  "acento": "#d14e72",
  "acento_usado": true,                // DERIVADO: algum escolhido tem `acento`
  "acento_onde": ["legenda"],          // [] quando acento_usado = false

  "grafismos": ["postit"],
  "grafismos_fora": ["marca-texto", "…"],   // o COMPLEMENTO, nomeado
  "elementos": {"sfx": true, "trilha": true, "split_broll": false,
                "flash_no_corte": false, "legenda_ativa": true,
                "tracking": false},                              // mapa COMPLETO
  "parametros": {"legenda-morno-destacado": {"fontSize": 40}},    // DIFF
  "observacao": "…", "perfil": "reels", "catalogo_gerado_em": "…"
}
```

**As duas regras que o validador cobra, e por quê:**

1. **`elementos` traz o mapa COMPLETO**, com os `false` explícitos, e
   `grafismos_fora` traz o complemento. Mandar só os `true` transforma ausência
   em silêncio, e o agente lê silêncio como "tanto faz". O digest imprime a linha
   `· fora:` com os desligados **nomeados** (`ref-A/helpers/watch_edits.py:93-95`).
   Os ids vivem em `preview/app/galeria/interruptores.json` e o validador cobra o
   mapa **completo** contra aquele arquivo: id que falta reprova, e id que sobra
   reprova também. Foi por aí que o `tracking` ficou pendurado por um dia —
   `previews-peca.py` já mandava o card ligá-lo e o id não existia no arquivo, de
   modo que `elementos.tracking` era recusado como "id fora de
   interruptores.json". **O que liga o `tracking` na prática**: rodar
   `rastrear-rosto.py <dir>` (grava `track-rosto.json`, contrato
   `benchmark.track-rosto/v1`) e passar o track ao punch por
   `MotionKit.CameraSegue track=`. Ele só é oferecido com a gramática
   `punch-pontual`, porque `CameraSegue` com `z = 1` tem deslocamento máximo 0 e
   não move nada.
2. **`acento_usado`/`acento_onde` são DERIVADOS** de `estilo.acento` no catálogo,
   nunca declarados. Declarar reabre a lista paralela que o ref-A mantém à mão
   (`app.js:1051`, *"Mirrors the template — update both together"*). O validador
   recusa um payload cujo `acento_usado` não bate com o catálogo.

## 6c. `benchmark.edit-estilo/v3` - direção de acabamento explícita

O v3 mantém todo o vocabulário visual do v2 e acrescenta uma decisão que antes
ficava implícita: quanto de edição visual esta peça deve receber. O campo é
obrigatório em saves novos e não é inferido em eventos antigos.

```jsonc
{
  "contrato": "benchmark.edit-estilo/v3",
  "direcao_edicao": {
    "modo": "essencial",        // essencial | animada | surpresa
    "densidade": "leve",        // leve | equilibrada | alta
    "sfx": "sem-sfx"            // automatico | sem-sfx
  },
  // ...os mesmos campos do v2
}
```

- **Essencial** significa corte e legenda, sem motion e sem SFX. É uma escolha,
  não o resultado de o agente ter esquecido a Fase 2.
- **Animada** exige um plano visual por beat antes da implementação.
- **Surpresa** registra a delegação criativa. O agente resolve a direção no
  plano, em vez de escolher silenciosamente e deixar a decisão fora do disco.

`direcao_edicao.sfx` e `elementos.sfx` precisam concordar. O primeiro descreve
a política editorial; o segundo liga ou desliga o pipeline. O v3 não obriga som
em todo movimento. Ele obriga uma decisão sonora explícita por movimento, que
pode ser usar SFX, silêncio intencional ou não aplicável.

V1 e v2 continuam legíveis para histórico e restilização, mas não liberam uma
Fase 2 nova sem uma escolha v3. O gate dessa transição está no contrato
`benchmark.plano-visual/v1`.

### Tradução `gramatica` (slug) → pipeline

| slug | efeito |
|---|---|
| `plano-fixo` | `perfil.ritmo.gramatica_plano = "fixa"` |
| `plano-alternado` | `= "alternada"`, com `zoomB` do parâmetro |
| `punch-pontual` | `= "punch-pontual"` |
| `split-screen-esfumacado` | **não** é gramática de plano: liga o `split-broll.py`; `gramatica_plano` fica no default do perfil e **o digest diz isso** |

`gramatica_plano` é mantido de propósito: quem remonta não precisa conhecer o
catálogo.

### `benchmark.galeria-estilos/v1` — a entrada da tela

`<dir-producao>/.preview/estilos/galeria.json`, **gerado** por
`previews-peca.py`, nunca editado à mão. É o **único** arquivo que a tela lê:
consolida catálogo + perfil + texto da peça + interruptores, com todo caminho
**relativo a `.preview/estilos/`**.

Regras: `preview.nivel ∈ {0,1}`; `preview: null` exige `estado: "candidato"` com
`bloqueio` não-vazio; no máximo **um** `padrao: true` por grupo de seleção única;
`acento` é `null` ou `{param}`, nunca booleano; nenhum caminho absoluto nem com
`..`; `grupos[].id` presente **mesmo com `estilos: []`** — grupo vazio não some,
senão o vocabulário faltante de um perfil novo nunca é notado.

Dois campos merecem leitura atenta:

- **`perfil.nome` × `perfil.vocabulario`.** O primeiro é o perfil resolvido (a
  verdade); o segundo é o nome que filtrou o catálogo. Diferem no fallback — o
  `FALLBACK_REELS` da SPEC-00 se chama `reels-fallback` e o catálogo diz `reels`.
  Filtrar pelo nome cru devolve **0 estilos** com o JSON válido e a tela vazia.
- **`avisos[]`.** Perfil vindo do fallback, texto vindo da amostra, nível 1
  suspenso por canvas divergente e tema sem cor de destaque declarada aparecem
  aqui **nomeados**. A tela os mostra; nada degrada em silêncio.

### `benchmark.edit-estilo-vigente/v1`

`<dir-producao>/.preview/estilo-vigente.json` — o objeto v2 ou v3 **aplicado**, mais
`aplicado_em`, `revisao_aplicada` e `origem`. Escrito **só** por
`escolha-estilo.py --aplicar`; nunca pela tela, nunca pelo servidor. É ele que
faz o portão continuar aberto depois da Fase 2 existir (`rerender`) **sem
acrescentar campo nenhum** ao `benchmark.edit-estado/v1`.

### `galeria.json.semente` — a pré-seleção, que NÃO é escolha (SPEC-41)

Campo **aditivo** no `benchmark.galeria-estilos/v1`, escrito por
`previews-peca.py --estilo <u>/<slug>`:

```json
"semente": {"origem": "<usuario>/<slug>", "versao": "vNNN",
            "estilo": {"gramatica": "…", "tema": "…", "grafismos": ["…"]}}
```

É por aqui que um estilo da biblioteca do usuário (SPEC-24) — inclusive um
**extraído de N referências** pela `style-extract` — chega à tela como cards já
marcados, em vez de morrer no artefato.

🔴 **A galeria lê `vigente` primeiro e `semente` só na ausência dele**, e
`rerender()` olha **só** para `vigente`. A distinção é o contrato:

| campo | quem escreveu | o que significa | botão |
|---|---|---|---|
| `vigente` | `escolha-estilo.py --aplicar`, de um evento da UI | **escolheram** para esta peça | âmbar, "Salvar e refazer a Fase 2" |
| `semente` | `previews-peca.py --estilo`, da biblioteca | **sugerem**; ninguém escolheu ainda | verde, "Confirmar e iniciar a Fase 2" |

Semear em `vigente` faria toda peça nova nascer dizendo "trocando um estilo já
aplicado" e mandaria refazer uma Fase 2 que nunca foi feita.

⚠️ **Os três contratos de escolha valem na leitura.** A galeria grava
`benchmark.edit-estilo/v3`; `estilo.py` já chegou a ler só `v1`, e o efeito era silencioso e
caro: a **camada 4** da precedência ("escolha pontual da UI") nunca se aplicava, e
o colhedor de sinais imprimia "0 evento(s) lidos" com exit 0 numa produção cheia
de eventos. Quem lê evento da UI aceita `v1`, `v2` **e** `v3`, sempre.

### Quem roteia e quem executa

`estado.py` **roteia** por `tipo`; `escolha-estilo.py` **executa** quando
`tipo == "estilo"`. Consumo duplo do mesmo pendente vira corrida de ACK — há um
dono só por tipo. `escolha-estilo.py` funciona **standalone**: sem as duas
edições no `estado.py`, a degradação é de ergonomia, não de função.

---

## 7. Procedência

O desenho de três arquivos (estado do agente / ajustes da UI / estilo da UI), a
escrita atômica com temporário, o carimbo de salvamento, o par de coordenadas
rascunho↔render, o consumo destrutivo como ACK, "caixa desmarcada é NÃO
explícito" e `accentUsed` são **mecanismo** observado em **uma ferramenta de edição de terceiro**: `helpers/preview_server.py:5-12,227-236`,
`assets/preview/app.js:1810-1817`, `helpers/watch_edits.py:69-95,129-130`.
**Nenhuma linha foi portada.** Detalhe item a item na **SPEC-16 §10**.

Nosso, sem equivalente lá: o `sid` derivado e estável, o bloco `integridade` com
órfão e procedência visíveis, o `estado.json` derivado do disco em vez de
digitado, `revisao_base` no canal de volta, a aprovação confrontável por
`plano_sha256` + `render_fingerprint`, e o layout seguindo a **saída** e não a
fonte.
