# Biblioteca de estilos do usuário — o ritual

> Para o agente que vai editar. O contrato completo e o porquê de cada decisão
> estão em `estilos/README.md`; aqui está **o que fazer, em ordem**.
> Origem: **SPEC-24** · script: `scripts/estilo.py`

---

## A frase operacional

> ### Correção é sobre a **peça** até prova em contrário; o **estilo** só muda com confirmação.

Se você lembrar de uma linha só deste arquivo, que seja essa. As três primeiras
correções de qualquer estilo são sobre a peça, não sobre o gosto — e um sistema
que aprende com a primeira degrada em duas semanas.

---

## 1. Antes de montar: resolver

```bash
E=.claude/skills/edit-video/scripts/estilo.py
python3 $E resolver <dir-producao> --perfil reels --usuario creator-1
```

Sai com **dois** arquivos e nenhum duplica o outro:

| arquivo | o que carrega |
|---|---|
| `<dir>/perfil.json` | forma **inalterada** (`benchmark.perfil-peca/v1`). As camadas 2–5 já estão mergeadas dentro. `_procedencia` ganha `usuario`, `estilo`, `estilo_sha256`, `camadas` |
| `<dir>/estilo-resolvido.json` | o que o schema do perfil não tem slot: `picks`, `grafismo`, `parametros`, `correcoes[]` e o mapa **`_origem`** |

⚠️ **É `estilo-resolvido.json`, na raiz da produção.** Não é `estilo.json`:
`<dir>/.preview/estilo.json` já é o canal de volta da UI (`benchmark.edit-estilo/v1`,
SPEC-16 §3.1). Dois arquivos com o mesmo nome e contratos diferentes é um desfecho
que este repo já teve que consertar uma vez.

Sem `--estilo`, o resolvedor usa o `padrao` do usuário. Se a biblioteca dele
estiver vazia, ele **semeia** `padrao/v001.json` e diz isso no stderr.

**O stderr sempre imprime as camadas que participaram.** Se faltar catálogo, ele
diz que a camada 2 não entrou. Nada muda em silêncio.

---

## 2. Quando o usuário pede em texto

**Não aplique.** Compile:

```bash
python3 $E pedido <dir-producao> "deixa a legenda mais baixa"
# imprime o DIFF (de → para, com o motivo) e grava .preview/pedidos/<carimbo>-pedido.json
python3 $E resolver <dir> --perfil reels --pedido-compilado <o arquivo impresso>
```

Se o pedido cair fora do escopo (*"faz em 16:9"*), o compilador **recusa** e
imprime o comando de perfil correspondente. Formato não se negocia por estilo.

---

## 3. Depois que o usuário corrige na UI

O evento vai para `.preview/aplicados/` (a SPEC-16 §3.12 **move**, não apaga — e é
por isso que esta feature existe: sem histórico da escolha não há sinal).

```bash
python3 $E resolver <dir> --perfil reels --usuario creator-1   # mede as correções
python3 $E sinais   <dir>                                   # → sinais.jsonl
```

🔴 **A correção é medida contra a linha de base (camadas 1–3)**, não contra o
`estilo-resolvido.json` — a camada 4 já está mergeada nele, e comparar contra ele
dá sempre zero. Quem faz essa conta é o `resolver`, e ela fica em `correcoes[]`.

---

## 4. Quando propor uma mudança de estilo

```bash
python3 $E propor creator-1/padrao          # NÃO escreve um byte
```

Ele só propõe um caminho que passe nas guardas de `<estilos>/_escopo.json`:
**`min_producoes` = 1** (SPEC-50 — a biblioteca é de uma pessoa só; esperar três
produções é fazer o produto demorar três semanas para aprender o que ela já
disse), janela de 12 produções, e **saldo ≥ `min_producoes` sem contra-sinal nas
3 mais recentes**. Esta última é a que tem dentes: quando um parâmetro é empurrado
para os dois lados, a saída diz a conclusão certa — **esse parâmetro é decisão por
peça e não pertence ao estilo.** Quem tiver um time editando o mesmo estilo sobe
`min_producoes` no `_escopo.json`, sem tocar em código.

E propor **nunca** promove: `promover` continua exigindo `--confirmar`. O que a
SPEC-50 cortou foi a espera, não a confirmação.

```bash
python3 $E promover creator-1/padrao --confirmar --so legenda.y_pct
```

Sem `--confirmar` sai **2** e imprime o que teria feito. Na UI, a mesma
confirmação é uma tela: *"você corrigiu a legenda para 79% em 3 vídeos. Quer que
'Padrão do creator-1' passe a começar assim? [manter] [atualizar]"*.

---

## 5. Remontar uma peça antiga

```bash
python3 $E resolver <dir> --como-gravado
```

Lê `perfil.json._procedencia.estilo` e resolve com **aquela** versão. Sem a flag,
resolve com o HEAD e **avisa no stderr** listando exatamente os caminhos que
diferem. Nunca em silêncio.

---

## 6. Estilo a partir de referência de terceiro

```bash
python3 $E criar creator-1/plano-alternado-4k --nome "Alternado 4K" --perfis reels \
   --de-receita data/adhoc/modelagem-edicao/edit-recipe.json      # model-edit
python3 $E criar creator-1/vsl-fria --nome "VSL fria" --perfis vsl \
   --de-receita intelligence/estilos/<slug>/estilo.json           # style-extract
```

Os dois contratos entram pela mesma porta. **Campo ausente na receita não vira
default**: fica ausente, e a camada de baixo governa.

O que **não migra automaticamente** e vira linha de `nota` para revisão humana:
`tipografia.*.familia` (identidade), `audio.cadeia_equivalente` (o loudness
canônico de 2 passes é da SPEC-02) e `densidade.*` (é leitura do plano). Da
`style-extract`, `Param` com `conf: baixa` **nunca** vira default — ele sai na
nota dizendo que não migrou.

Slug default vem do **mecanismo**, não da pessoa. E `procedencia.tipo != "proprio"`
exige `ficha` (que tem que existir) ou `corpus`.

---

## 7. O que NÃO fazer

1. **Não deixe o estilo escrever formato**, nem por conveniência. Um estilo com
   `video.largura` é um valor de formato hardcoded, só que em JSON.
2. **Não coloque o estilo no hash do sidecar de segmento.** O sidecar
   (`montar.sh`) grava `src,start,end,zoom,cx,cy` + `perfil_video_sha`. O estilo
   **não influencia o `vf`**: `cor.grade` é aplicado na composição e `ritmo.*` muda
   a EDL (e portanto `start`/`end`, que o sidecar já compara). Incluí-lo
   invalidaria `segs/` inteiros a cada troca de legenda.
   ⚠️ **Se um dia um campo de estilo entrar no `vf`, ele tem que entrar no hash no
   mesmo commit** — senão volta o bug do segmento órfão, que já custou 6,25 s de
   vídeo errado com todos os QCs verdes.
3. **Não promova nada automaticamente.**
4. **Não trate correção de timeline como sinal de estilo.** `notas[]` e
   `operacoes[]` são sobre um `sid`. A classe `peca` é o default.
5. **Não copie hex, tamanho de fonte nem timing do catálogo para dentro do
   estilo.** Referencie o slug.
6. **Não sobrescreva uma versão** "só pra corrigir um typo". Sem git,
   `versoes/vNNN.json` imutável **é** o mecanismo de histórico.
7. **Não escreva em `creators/`.** Ler `perfil-overrides.json` como semente é
   leitura. E não grave caminho nosso (`creators/`, `data/`, `input/`) dentro de
   um estilo: ele deixa de ser portátil na primeira máquina que não os tem.
