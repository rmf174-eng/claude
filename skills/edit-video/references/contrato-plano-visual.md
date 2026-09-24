# Contrato do plano visual, `benchmark.plano-visual/v1`

O `plano-visual.json` é o elo executável entre a decisão da aba Estilo, o plano
editorial aprovado e o que a Fase 2 realmente entregou. Ele não substitui o
`PLANO-EDICAO.md`: o Markdown guarda o raciocínio; este contrato guarda eventos,
tempos e referências que um gate consegue conferir.

## 1. Autoridades e ordem

1. O corte é aprovado.
2. A aba Estilo grava e aplica `.preview/estilo-vigente.json`.
3. `plano-visual.py <dir> --iniciar` cria o esqueleto.
4. O agente preenche os eventos e valida `planejamento`.
5. A Fase 2 implementa o plano.
6. O gate `entrega` prova artefatos e SFX antes de finalizar.

O estilo aplicado precisa conter um payload `benchmark.edit-estilo/v3` com:

```json
{
  "direcao_edicao": {
    "modo": "essencial|animada|surpresa",
    "densidade": "leve|equilibrada|alta",
    "sfx": "automatico|sem-sfx"
  }
}
```

V1 e v2 continuam legíveis pela UI, mas não autorizam este plano. O validador não
infere uma direção que o usuário não escolheu.

## 2. Forma do arquivo

```json
{
  "contrato": "benchmark.plano-visual/v1",
  "criado_em": "2026-08-16T12:00:00-03:00",
  "vinculos": {
    "estilo_vigente": {
      "arquivo": ".preview/estilo-vigente.json",
      "sha256": "sha256:..."
    },
    "plano_edicao": {
      "arquivo": "PLANO-EDICAO.md",
      "sha256": "sha256:..."
    },
    "render_corte": {
      "arquivo": "v1-montado.mp4",
      "fingerprint": "sha1:..."
    },
    "timeline_real": {
      "arquivo": "edl.json",
      "sha256": "sha256:...",
      "edl_fingerprint": "sha1:...",
      "total_s": 73.166667
    }
  },
  "direcao_edicao": {
    "modo": "animada",
    "densidade": "equilibrada",
    "sfx": "automatico"
  },
  "eventos": [
    {
      "id": "gancho-ovo",
      "inicio_s": 0.4,
      "fim_s": 2.1,
      "beat": "gancho",
      "visual": {
        "tipo": "hook-title",
        "descricao": "a tese entra na palavra-chave"
      },
      "zona": "topo-seguro",
      "som": {
        "decisao": "usar",
        "asset": "pop-hi.wav",
        "at_s": 0.53,
        "ganho_db": -8.0
      },
      "implementacao": {
        "artefato": "partitura.json",
        "ref": {"tipo": "json-pointer", "valor": "/itens/0"}
      }
    }
  ]
}
```

### Vínculos

Os vínculos são calculados no `--iniciar` e nunca são atualizados silenciosamente:

- `estilo_vigente.sha256`: bytes exatos de `.preview/estilo-vigente.json`;
- `plano_edicao.sha256`: bytes exatos de `PLANO-EDICAO.md`;
- `render_corte.fingerprint`: a mesma identidade do estado da UI,
  `sha1(nome|bytes|mtime_inteiro)`;
- `timeline_real.sha256`: JSON canônico do bloco `timeline_real`, mais o
  `edl_fingerprint` do corte e a duração real.

Se qualquer autoridade muda, os gates retornam `STALE-*`. Alterar um arquivo que
não participa desses vínculos não invalida o plano.

## 3. Regras por modo

| Modo | Eventos | SFX |
|---|---:|---|
| `essencial` | exatamente zero | densidade `leve` e `direcao_edicao.sfx` igual a `sem-sfx` |
| `animada` | um ou mais | decisão explícita por evento |
| `surpresa` | um ou mais | decisão explícita por evento e `direcao_resolvida` |

`surpresa` é delegação, não ausência de decisão. Antes do gate de planejamento, o
agente persiste o que resolveu:

```json
{
  "direcao_resolvida": {
    "resumo": "tipografia editorial com dois cartões nos argumentos centrais",
    "resolvido_por": "agente-editor",
    "resolvido_em": "2026-08-16T12:03:00-03:00"
  }
}
```

## 4. Evento e decisão sonora

Cada evento animado exige:

- `id` único;
- `inicio_s` e `fim_s` absolutos na saída, dentro de `timeline_real.total_s`;
- `beat` editorial;
- `visual.tipo` e `visual.descricao`;
- `zona`;
- `som.decisao`.

As decisões sonoras são:

| Decisão | Campos |
|---|---|
| `usar` | `asset`, `at_s` absoluto dentro do evento e `ganho_db` |
| `silencio-intencional` | `motivo`; não aceita asset, tempo ou ganho |
| `nao-se-aplica` | não aceita asset, tempo ou ganho |

Uma direção `sem-sfx` proíbe `usar`. Nem toda animação precisa emitir som, mas
nenhuma animação pode deixar a decisão sonora em branco.

No gate `entrega`, um asset pode ser um caminho relativo dentro da produção ou um
slug/nome da biblioteca `tools/remotion-compositor/public/sfx`. O arquivo precisa
existir. Este gate prova existência, não substitui o `qc-sfx.py` da biblioteca.

## 5. Prova de implementação

No gate `planejamento`, `implementacao` ainda pode estar ausente. O compilador
oficial transforma os eventos planejados em dado consumido pelo compositor:

```bash
python3 skills/remotion-compositor/scripts/compilar-plano-visual.py \
  "$D" preparar
```

O destino canônico é `$D/remotion/partitura-compilada.json` e os assets resolvidos
ficam em `$D/remotion/public/`. Caminhos relativos passados em `--destino` ou
`--public-dir` são resolvidos contra `$D` e não podem escapar da produção. O
compilador nunca grava dado da peça em `tools/remotion-compositor/src/data`.
O preparo também publica a árvore exata `benchmark.remotion-public-tree/v1`,
com caminho relativo, bytes e SHA-256 de cada arquivo, totais e hash canônico do
conjunto. Symlinks e entradas não regulares são proibidos. Alterar, adicionar ou
remover qualquer asset depois de `preparar` bloqueia o Remotion; uma mutação
durante a execução descarta o parcial e preserva a saída anterior. O manifesto de
render repete o mesmo inventário para o gate comparar preparo, execução e árvore
presente no disco.

O mesmo compilador executa o Remotion com esses props e public-dir. O vídeo nasce
como parcial dentro da produção, é validado e só então substitui a saída anterior:

```bash
python3 skills/remotion-compositor/scripts/compilar-plano-visual.py \
  "$D" renderizar --saida graphics-alpha.mov
python3 skills/remotion-compositor/scripts/compilar-plano-visual.py \
  "$D" compor-final --base v1-montado.mp4 --saida v-final.mp4
```

`renderizar` chama `src/index-partitura.tsx`, composição `Graphics`, com
`--props=$D/remotion/partitura-compilada.json` e
`--public-dir=$D/remotion/public`. Não existe subcomando para registrar um MP4
externo: sucesso publica `remotion/plano-visual-render.json`, preso aos hashes do
plano, compilado e render. Não se escreve recibo à mão. No gate `entrega`, cada evento precisa apontar por
JSON Pointer para seu objeto compilado, que passa a carregar esta prova:

`compor-final` é a única via oficial do gráfico para o entregável. Ela aplica
`unpremultiply` e `overlay`; quando existe `som.decisao: usar`, exige áudio no
MOV e mistura base + gráfico com `amix`, `duration=first` e `normalize=0`. Sem
SFX, mantém somente o áudio da base. O resultado atômico fica vinculado em
`remotion/plano-visual-finais/<saida>.<id>.json`; mapear apenas `0:a` num MP4
externo não gera essa prova. Se o perfil pedir as versões com grade e sem filtro,
rode `compor-final` uma vez para cada base e saída. O gate valida todos os
`v-final*.mp4` e `v2-final*.mp4`: dois entregáveis oficiais coexistem, mas uma
terceira cópia externa sem manifesto próprio reprova. A descoberta é
case-insensitive para nome e extensão (`v-final-COPIA.MP4` também entra), mas o
nome oficial precisa ser ASCII literal e casar com
`^(?:v-final|v2-final).*\.mp4$`. A saída fica diretamente na raiz da produção:
subdiretório, nome genérico e truque fullwidth são recusados. Nomes ou manifestos
que colidem após NFKC + `casefold` também são recusados. `remotion/`,
`plano-visual-finais/` e seus pais não podem ser symlinks nem escapar da produção.
A raiz precisa ser listável: erro de inventário é falha, nunca “nenhum final”.
Diretório, FIFO, socket ou qualquer entrada não regular com nome de final também
bloqueia o gate.

```json
{
  "contrato": "benchmark.evento-visual-aplicado/v1",
  "evento_id": "gancho-ovo",
  "inicio_s": 0.4,
  "fim_s": 2.1,
  "visual_tipo": "hook-title",
  "camada": "grafismo",
  "plano_sha256": "sha256:...",
  "render": {
    "arquivo": "graphics-alpha.mov",
    "sha256": "sha256:..."
  }
}
```

O recibo precisa repetir exatamente id, janela e tipo do evento. Também guarda o
SHA-256 de `plano-visual.json`, para uma mudança posterior de animação ou SFX
invalidar a entrega. O render deve estar dentro da produção, ser diferente do
corte-base, corresponder ao SHA-256 e ter manifesto de execução Remotion com
`exit: 0`.
O gate também usa `ffprobe`: extensão e bytes quaisquer não bastam, é obrigatório
haver stream de vídeo com dimensões e duração ou frames positivos.

Para `animada` e `surpresa`, o gate também exige
`remotion/plano-visual-preparado.json`, confere o hash da partitura compilada e
prova que cada JSON Pointer foi materializado nela. Portanto, fabricar só o
recibo depois do render não passa. `essencial` preserva zero eventos e não exige
compilação nem recibo.

`captions.json`, `caps.json`, SRT, VTT e caminhos nomeados apenas como
caption/legenda não contam. Renomear captions também não funciona: o conteúdo
apontado continua sem o contrato de evento aplicado e sem vínculo verificável ao
render. `marcador-texto` continua legível como referência histórica, mas não
prova entrega. Um mesmo par artefato/referência não pode comprovar dois eventos.

## 6. CLI e códigos de saída

```bash
S=skills/edit-video/scripts
D=/caminho/da/producao

python3 $S/plano-visual.py $D --iniciar
python3 $S/plano-visual.py $D --validar planejamento
python3 $S/plano-visual.py $D --validar entrega --json
```

- `0`: esqueleto criado ou gate aprovado;
- `1`: fonte ausente, contrato inválido, vínculo stale ou gate reprovado;
- `2`: erro de uso do `argparse`.

`--iniciar` nunca sobrescreve `plano-visual.json`. Ele grava e sincroniza um
parcial no mesmo diretório, publica por link atômico exclusivo e remove o parcial.
Se dois processos disputarem o nome, um vence e o outro recebe
`PLANO-JA-EXISTE`; nenhum plano completo é substituído.

O esqueleto `essencial` já pode passar. Os esqueletos `animada` e `surpresa`
nascem deliberadamente pendentes: só passam depois que os eventos forem
planejados; `surpresa` também exige a direção resolvida.
