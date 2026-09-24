# `qc/bateria.json` — como acrescentar um QC (ou uma sonda) à bateria

> A bateria é **dado**. O `qc.py` executa, adapta e classifica; quem decide *o que
> roda, em que estágio e o que vira falha* é este diretório. Um perfil de peça
> novo (`corte-de-podcast`, `anuncio`) escolhe a bateria dele **sem tocar em
> Python**.

---

## O comando

```bash
qc.py <dir-producao> [--estagio auto|montado|compositado|final]
                     [--so id,id] [--pular id,id] [--jobs 3] [--json] [--completo]
qc.py --autoteste [--desligar-regra <nome>]
qc.py --catalogo
```

`stdout` é o veredito, curto. O despejo vai para o disco:
`<dir>/qc/relatorio.json` (contrato `benchmark.qc-bateria/v1`) e
`<dir>/qc/<id>.log` com stdout e stderr **crus** de cada QC.

| exit | significa |
|---|---|
| `0` | nenhuma FALHA (com ou sem achados) |
| `1` | ao menos uma FALHA — **ou** um sub-QC anormal (veredito `anormal`) |
| `2` | erro de uso |
| `3` | **bateria vazia** — nenhum QC do estágio pôde rodar |

O `3` existe para que *"não verifiquei nada"* nunca seja confundido com *"está
tudo bem"* nem com *"está quebrado"*.

O veredito no `relatorio.json` é mais fino que o exit, e a precedência é esta:

| veredito | quando | exit |
|---|---|---|
| `falha` | algum item classificou FALHA | 1 |
| `anormal` | algum sub-QC morreu ou saiu ≠0 sem se explicar (regra 4) | 1 |
| `vazio` | nenhum item pôde rodar | 3 |
| `achados` | só detector, nada bloqueia | 0 |
| `incompleto` | alguém foi `--pular`ado | 0 |
| `limpo` | varreu e não achou nada | 0 |

---

## As quatro regras que o orquestrador executa

1. **`unidades == 0` nunca vira `ok`.** Vira `NÃO VERIFICADO`. Todo item aprovado
   imprime **quanto varreu** (`qc-ataque(22/28)`). Verde sem contagem é
   indistinguível de portão quebrado — e este repo já teve um QC que mediu uma
   faixa vazia e imprimiu limpo.
2. **Detector ≠ teste de convergência.** Ver abaixo; é o campo `tipo`.
3. **Silêncio não é aprovação.** O bloco `NÃO VERIFICADO` e o exit 3.
4. **Sub-QC que morre não verifica nada.** Traceback, morte por sinal, ou exit ≠0
   que o adaptador não explicou em nenhum item: o item vira `NÃO VERIFICADO` com
   motivo `crash`/`exit-inesperado` (marcado 🔴 na saída), o veredito vira
   `anormal` e o exit vira 1. Medido em campo em 2026-08-12: o `qc-cor.py`
   imprimiu "varreu 17", estourou `TypeError` e o item foi para o relatório como
   **`ok` com `exec.exit=1`**. O guarda só não apaga FALHA — se o QC morreu depois
   de acusar um defeito real, o defeito continua bloqueando. Controle negativo em
   `scripts/tests/test_qc_bateria.py` §9.

---

## `tipo`: a decisão central, e ela não é opinião

> Um QC é **`convergencia`** quando a régua é **independente do critério que
> selecionou o item** medido — os pares, o corpo da palavra vizinha, a fronteira
> de frames, um alvo absoluto do contrato. **Só convergência produz FALHA.**
>
> Um QC é **`detector`** quando o item foi selecionado por estar de um lado de um
> limiar. Ele está do lado errado **por construção**, o número dele nunca converge
> a zero, e o resultado é **ACHADO**: aponta onde ouvir, nunca bloqueia.
>
> **`misto`** é quando o mesmo script emite as duas coisas — aí `promove_falha`
> nomeia o que é convergência.

Se você não consegue escrever, em uma frase, **contra o que** o seu QC compara, ele
é detector. Escreva isso no `nota_classe`: o campo existe para essa frase.

---

## Anatomia de uma entrada

```jsonc
{
  "id": "audit-emendas",
  "titulo": "energia de fala nas bordas do corte",
  "classe": "qc",                      // "qc" | "sonda"
  "tipo": "detector",                  // detector | convergencia | misto
  "estagios": ["montado"],
  "exec": {"script": "audit-emendas.py", "argv": ["{dir}"]},
  "requer": ["edl.json", "take-*/transcript.json", "{srcs}"],
  "requer_perfil": null,               // predicado declarativo, ver abaixo
  "unidade": "segmento",               // o que ele varre — é o que aparece no OK
  "adaptador": "audit_emendas",
  "promove_falha": ["SEM-PALAVRAS-COM-ENERGIA"],
  "rebaixa_achado": [],
  "depois_de": ["integridade-edl"],
  "prova_de_dentes": false,
  "nota_classe": "por que a classificação é essa, com o número medido",
  "custo_s": 15                        // timeout = max(120, custo_s × 20)
}
```

### `exec` — três formas, e só três

| forma | quando |
|---|---|
| `{"script": "x.py", "argv": [...]}` | script da própria skill `edit-video` |
| `{"script": "x.py", "skill": "omni-insert", "argv": [...]}` | script de outra skill |
| `{"cmd": ["ffmpeg", ...]}` | comando literal (o `preto` é assim) |
| `{"sem_script": "por quê"}` | o QC é **prescrito e não existe** — vira `NÃO VERIFICADO / sem-script`, com a causa nomeada. É como a bateria expõe um buraco em vez de escondê-lo |

Há ainda `argv_se: [["<predicado>", ["--flag", "valor"]]]`, para argumento que só
entra quando o perfil pede.

### Placeholders

`{dir}` · `{video}` / `{artefato}` (o artefato primário do estágio) · `{srcs}` (os
`src` distintos da EDL, expandido em N argumentos) · `{scripts}` · `{python}` ·
`{perfil.<caminho.no.perfil>}` · `{insert.base}` / `{insert.editado}` (dos pares
declarados em `qc/local.json`).

### `requer` — e o que cada forma checa

- `"edl.json"`, `"segs/"`, `"trilha.json"` — glob relativo ao `<dir>`;
- `"{srcs}"` — todos os brutos citados pela EDL têm que existir;
- `"{video}"` / `"{artefato}"` — o artefato primário do estágio;
- `"env:DEEPGRAM_API_KEY"` — variável de ambiente (motivo `ambiente`);
- `"local:inserts"` — bloco declarado em `<dir>/qc/local.json`.

### `requer_perfil` — o predicado declarativo

`"video.largura == 1080 && video.fps == 30"`. Sem `eval`, sem parênteses, e `&&`
não se mistura com `||`. Quando o predicado é falso o item sai em
`NÃO VERIFICADO / perfil` **com a causa nomeada** (`video.largura=1920, pedia ==
1080`) — é assim que um QC acoplado a um formato expõe o acoplamento em vez de
reprovar peça correta.

---

## 🔴 Nunca ponha valor de formato aqui

Resolução, fps, aspecto, zona: **nada disso entra no `qc.py` nem no
`bateria.json`**, exceto dentro de `requer_perfil`, onde é declarativo. O gate é
um `grep` e ele lê **0** hoje:

```bash
grep -nE "1080|1920|:30\b|9:16|fps=30" scripts/qc.py qc/bateria.json
```

---

## Registrar uma SONDA sem editar este arquivo — `qc/bateria.d/`

Todo `.json` em `qc/bateria.d/` é mesclado sobre o `bateria.json`, **por `id`,
campo a campo**, na ordem alfabética do nome do arquivo. Um `id` novo entra no
fim; um `id` existente tem só os campos declarados sobrescritos.

```jsonc
// qc/bateria.d/26-sonda-densidade.json
{"itens": [
  {"id": "sonda-densidade", "titulo": "densidade de apoio visual por minuto",
   "classe": "sonda", "tipo": "detector", "estagios": ["compositado"],
   "unidade": "beat", "adaptador": "generico",
   "exec": {"script": "densidade.py", "argv": ["{dir}", "--json"]},
   "requer": ["edl.json"], "nota_classe": "sonda: mede, não reprova",
   "custo_s": 5}
]}
```

Isto existe por um motivo concreto e medido: **specs paralelas que precisam
registrar uma sonda não deveriam ter que editar o mesmo JSON ao mesmo tempo.** Dois
patches no mesmo arquivo é como se perde trabalho num merge. Um arquivo por
registro resolve.

Uma `sonda` (`"classe": "sonda"`) é uma medição que **reporta um número e nunca
reprova**. Se ela pode reprovar, ela não é sonda: é QC de convergência, e aí
`classe` é `qc`.

---

## QC que só a produção conhece — `<dir>/qc/local.json`

```jsonc
{
  "schema": "benchmark.qc-local/v1",
  "extras": [
    {"id": "varredura-alpha", "script": "qc-varredura.py",
     "argv": ["--alpha", "graphics-alpha.mov"],
     "tipo": "convergencia", "unidade": "frame", "prova_de_dentes": true}
  ],
  "inserts": [
    {"base": "v1-graded.mp4", "editado": "v1-com-insert.mp4", "janela": [12.0, 16.0]}
  ]
}
```

- **`extras`** — script que mora na PRODUÇÃO. Um extra com o mesmo `id` de um item
  do catálogo **substitui** o item: é assim que a `varredura-alpha`, que não tem
  script canônico, sai de `NÃO VERIFICADO` numa produção que tem o seu.
- **`prova_de_dentes: true`** exige que a saída traga um número de unidades. Sem
  esse número, **resultado limpo é rejeitado** e o item vira
  `NÃO VERIFICADO / sem-prova-de-dentes`.
- **`inserts`** é o que permite rodar o `qc-fala.py` do `omni-insert`: o par
  original/editado não se adivinha, e adivinhar errado seria pior.

Ausência de `qc/local.json` é o caso normal e não gera erro.

---

## Escrever um adaptador

Um adaptador é uma **função pura sobre string** — sem ffmpeg, sem disco — em
`qc.py`, seção `ADAPTADORES`:

```python
def ad_meu_qc(stdout, stderr, exit_code, ctx):
    return {"unidades": n,          # quantas linhas de MEDIÇÃO foram lidas
            "esperadas": m,         # quantas deveriam ser (ou None)
            "itens": [{"onde": "seg08 fim 37.450", "tag": "SILABA-TRUNCADA",
                       "detalhe": "≤ 120 chars"}],
            "resumo": "…",          # ≤ 90 chars, é o que vai pro stdout
            "estado_forcado": None, # p.ex. "nao_verificado" quando o script já disse
            "motivo": None}
```

O adaptador **não classifica**: ele devolve `itens` com `tag`, e quem separa
achado de falha é o catálogo. Registre a função em `ADAPTADORES`.

> **Por que parsear stdout em vez de dar `--json` a cada QC**: (1) vários deles são
> editados por outras specs, e uma terceira mexendo nos mesmos arquivos é o jeito
> mais rápido de perder trabalho num merge; (2) cada um é um **documento** — o
> docstring do `qc-fonemas.py` carrega a fonética que custou um defeito entregue;
> (3) o orquestrador tem que sobreviver a QC que ele não escreveu, incluindo
> script local de produção e, um dia, de cliente. O preço do parse frágil é pago
> pela regra `unidades == 0` nunca vira `ok`.

Quando o QC **já** tem `--json` (é o caso de `qc-nivel`, `qc-alpha` e
`qc-avsync`), use: o adaptador vira `json.loads` e o parse deixa de ser frágil.

---

## Depois de mexer, rode o autoteste

```bash
python3 scripts/qc.py --autoteste                              # tem que sair 0
python3 scripts/qc.py --autoteste --desligar-regra promove-falha   # tem que sair 1
python3 scripts/tests/test_qc_bateria.py                       # TUDO PASSOU
```

O `--desligar-regra` é o **controle negativo**: se desligar uma regra de
classificação e o autoteste continuar verde, a regra não está implementada. As
quatro regras são `convergencia-falha`, `promove-falha`, `rebaixa-achado` e
`unidade-zero`.

Se você acrescentou um QC, acrescente **uma fixture** em
`scripts/tests/fixtures/qc/` e o caso correspondente em `esperado.json`, com o
campo `porque`. Fixture **nunca** sai de material de creator: gere de `testsrc2` +
áudio sintético, como as que estão lá.
