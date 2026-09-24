# `benchmark.edit-marcacoes/v1` — a marcação IN/OUT com instrução

> **Fonte de verdade** do que a timeline interativa grava e do que o
> `digest-marcacoes.py` lê. Entregue pela **SPEC-18**.
> Contrato irmão: `references/contrato-ui.md` (SPEC-16), que define
> `benchmark.edit-estado/v1` e `benchmark.edit-ajustes/v1`.
>
> Exemplo válido: `preview/tests/fixtures/marcacoes-exemplo.json`.
> Bateria: `preview/tests/test_digest.py`.

---

## 1. Para que existe

O canal de volta de hoje é prosa sem coordenada — *"lá pelo meio, quando ela
fala do ovo"*. Os quatro defeitos entregues em 2026-07-27 foram achados pelo
creator-1 **assistindo**, e voltaram como texto na conversa. Esta marcação carrega o
pedido **com o instante exato no arquivo que existe** e, do nosso lado, com o
take, a coordenada no BRUTO e a fala literal — que é o que o agente precisa,
porque a EDL é escrita em tempo de **fonte**, não de saída.

---

## 2. Onde vive

```
<dir-producao>/.preview/pendentes/<AAAAMMDD>T<HHMMSS>-marcacoes-<n>.json
```

Escrito pelo **servidor** (SPEC-17), a pedido da app, dentro do envelope
`benchmark.preview-evento/v1` com `tipo: "marcacoes"`. O ACK é o **move** para
`.preview/aplicados/` — feito por `digest-marcacoes.py --ack`, nunca pela
leitura.

A app **não escreve arquivo nenhum**: ela faz `POST api/salvar` e para. Uma UI
que editasse `edl.json` direto furaria todos os QCs de emenda desta skill
(`qc-fonemas.py`, `qc-emendas-asr.py`, `audit-emendas.py`) — que são justamente
os que pegaram aqueles quatro defeitos.

---

## 3. O documento

```jsonc
{
  "contrato": "benchmark.edit-marcacoes/v1",
  "salvo_em": "2026-08-08T17:41:09-03:00",   // ISO-8601 COM offset
  "revisao_base": 7,                          // a revisão que o usuário via
  "fingerprint_corte": "sha1:…"|null,
  "fingerprint_render": "sha1:…"|null,
  "render_alvo": "v-final.mp4"|null,
  "formato": {"largura": …|null, "altura": …|null, "fps": …|null,
              "fonte": "perfil"|"estado"|"medido"|"decodificado"|"desconhecido"},
  "timeline_real_ausente": true|false,
  "app": "preview/app v1",
  "notas": [ /* §3.1 */ ]
}
```

### 3.1 Uma nota

```jsonc
{
  "id": "m1754680869123-1",
  "tipo": "intervalo"|"ponto",
  "fase": 1|2,
  "trilha": "legenda"|null,                  // null = "o que houver ali"; enum §4
  "ref": null|{"tipo":"segmento","sid":"…"}|{"tipo":"overlay","id":"…"},

  "rascunho": {"ini": 41.573, "fim": 45.333},
  "render":   {"ini": 41.573, "fim": 45.333},
  "render_frames": [1247, 1360]|null,

  "sid": "faz-de-novo#1"|null,
  "sid_confianca": "exata"|"aproximada"|"indisponivel",
  "marcado_invertido": false,

  "texto": "essa legenda tá cobrindo o rosto dela, sobe",

  "contexto": {
    "palavras": [{"t": 41.62, "w": "e"}],    // máx. 40, da captions.json
    "trilhas_com_conteudo": ["corte", "audio", "legenda"]
  }
}
```

**Compatibilidade com a SPEC-16.** `sid`, `rascunho`, `render`, `fase` e `texto`
têm **os mesmos nomes e a mesma semântica** do `notas[]` de
`benchmark.edit-ajustes/v1`. Um consumidor daquele contrato lê este subconjunto
sem adaptador. O resto é acréscimo, e nenhum campo acrescentado é obrigatório
para agir.

**Por que contrato próprio e não extensão.** `scripts/estado.py` e
`references/contrato-ui.md` são arquivos da SPEC-16; editá-los aqui criaria a
única colisão de arquivo da fase. O `tipo: "marcacoes"` já é previsto pela
SPEC-17 §4.3 e o roteamento por `payload.contrato` é o que a SPEC-16 §3.12
especifica. Zero arquivo em comum, zero divergência de campo.

---

## 4. Enum de `trilha`

```
corte · audio · legenda · enquadramento · falante · grafico · broll · insert ·
sfx · trilha-sonora · geral
```

Espelhado em `app/js/trilhas.js` (`TRILHAS`) e em `digest-marcacoes.py`
(`TRILHAS`). **Atualizar os dois juntos** — é a lição do `ACCENT_USERS` do ref-A
(`app.js:1047-1051`: *"Mirrors the template — update both together"*).

---

## 5. Invariantes

Conferidas na escrita pela app e na leitura pelo digest
(`conferir_nota()`; `--verificar` sai **1** se alguma cair):

| invariante | por quê |
|---|---|
| `render.ini ≤ render.fim` | quem marcou de trás pra frente sabe o que quis dizer: as pontas são trocadas e `marcado_invertido` registra |
| `tipo == "ponto"` ⟺ `render.ini == render.fim` | duração abaixo de 1 frame é pedido legítimo ("aqui falta um cartão"), não erro. O ref-A **recusa** abaixo de 0,05 s e perde a intenção |
| `render_frames[i] == round(render[i] × fps)` | a montagem pensa em frames (`EDICAO-CAPACIDADES.md:22`) |
| `render` sempre presente | ela vem do `video.currentTime`, não do desenho — ver §6 |
| `sid == null` ⟹ `sid_confianca == "indisponivel"` | não inventar identidade |
| `texto` não vazio | marcação sem pedido não é dado |

⚠️ **`render_frames` pode passar do último frame do stream de vídeo.** Medido:
`v-final.mp4` da `peca-01` tem **2123 frames** (70,766667 s) e duração de
container **70,784 s** — a cauda de áudio. Uma marcação no fim do player produz
`round(70,784 × 30) = 2124`. A invariante continua valendo; quem consome trata o
excedente como "no último take", e o digest avisa quando a coordenada de fonte
sai da janela cortada.

---

## 6. 🔴 A regra que governa o contrato inteiro

> **A coordenada vem do `video.currentTime`, nunca da geometria da timeline.**

A agulha é um desenho; o tempo é do player. Três consequências:

1. **O erro de desenho não contamina o dado.** Sem `timeline_real` (SPEC-05) os
   blocos são posicionados por `Σ(end−start)`, que erra **316,7 ms** no fim da
   `peca-01` — e a marcação continua exata.
2. **Nenhum número derivado de `Σ(end−start)` é gravado**, nem "só como
   fallback" (SPEC-16 §9). A soma existe como pixel, e é desenhada **hachurada**,
   com o rótulo dizendo que é aproximada.
3. **`sid` é a única coisa que a régua aproximada influencia** — e aí ela vem
   marcada `sid_confianca: "aproximada"`. O digest **recalcula** o take por régua
   medida e **diverge em voz alta** quando não bate. Medido em material real: uma
   marcação em 52,300 s da `peca-01` sai `de-novo-ai#1` pela régua somada
   e `e-se#1` pela medida; o digest imprime as duas.

**`rascunho == render`** enquanto não houver operação de corte (o MVP não edita
corte). A distinção passa a valer no incremento B2, e aí vem da `timeline_real`
— nunca de soma.

---

## 7. `benchmark.marcacoes-digest/v1` — a saída do digest

```
digest-marcacoes.py <dir> [--json] [--ack] [--arquivo X] [--verificar]
                          [--componente src/Foo.tsx]
```

Markdown no stdout, logs no stderr. `--json` devolve `{contrato, dir, render,
timeline, eventos, ffprobe_invocado, ffmpeg_invocado, avisos, marcacoes[]}`.

Regras da saída, cada uma com um motivo:

- **Só o que foi medido.** A régua é `timeline_real`, `medida` (de `segs/` por
  `ffprobe -count_frames`) ou `indisponivel` — e o cabeçalho diz qual. Sem régua,
  a linha do take sai `indisponível`, **nunca chutada**.
- **Camada sem dado sai `sem dado`, não `nenhum`.** "Nenhum" é uma medição de
  zero. `b-roll` e `insert` nascem sem sidecar (são CLI), então é `sem dado`.
- **`em código` só com `--componente`.** Medido em 2026-08-08: **nada** dentro de
  `<dir-producao>` aponta para o `.tsx` da peça — o vínculo vive no projeto
  Remotion (`src/index-*.tsx`), fora da produção. Adivinhar acoplaria o digest à
  nossa instalação.
- **Fingerprint que não bate vira alarme no topo**, não rodapé.
- **`--ack` é separado da leitura.** Ler não consome.
- **Sem ffmpeg, e sem ffprobe quando há `timeline_real`.** É a forma operacional
  de dizer *"o agente age sem reabrir o vídeo"*: com a timeline no disco, o
  digest roda com `PATH=/usr/bin:/bin` e sai 0.

---

## 8. Procedência

Marcar IN/OUT e escrever a instrução, a caixa centrada e clampada, e descartar a
marcação nova sem texto são **mecanismo** observado em **uma ferramenta de edição de terceiro**: `assets/preview/app.js:981-1035` · `SKILL.md:162-166`. **Nenhuma linha
foi portada.** Detalhe item a item na SPEC-18 §10.

Nosso, sem equivalente lá: a coordenada vinda do player, a tradução para tempo de
FONTE, o `sid` com confiança declarada, o contexto congelado e confrontável, a
marcação de ponto aceita, e o enum de trilha versionado dos dois lados.
