# Contrato — `benchmark.deiticos/v1` e `benchmark.lexico-deitico/v1`

> Schemas dos dois artefatos da SPEC-27. `classe` e `sugestao` têm **domínio
> fechado**: valor novo exige editar **este** arquivo, não um `deiticos.json`
> individual. Consistência é o que torna a base agregável — é a mesma regra de
> schema do resto do repo.

---

## 1. O que estes artefatos são, e o que não são

| | |
|---|---|
| **É** | uma lista de **janelas candidatas** de apoio visual, lidas do TEXTO, no formato posicional que o `layout-zones.sh` já aceita |
| **NÃO é** | ponto de corte. A fronteira de frase vem do ASR, e o ASR **não é verdade acústica**: 86 % dos gaps entre palavras do Deepgram são exatamente 0,000 s porque ele estica a última palavra para dentro do silêncio; contra o envelope RMS o recall é de **70 %** e o início da frase cai em média **+98 ms** para dentro do silêncio real. Quem acha borda de corte é o `bordas.py` |
| **NÃO é** | um planejador de overlays. Zero janelas quer dizer "nenhum apoio **pedido explicitamente**", não "nenhum overlay nesta peça" |
| **NÃO é** | QC. Não reprova, não entra em bateria, não tem limiar de aprovação. O único exit ≠ 0 é o clamp (§4) |

---

## 2. `deiticos.json` — `benchmark.deiticos/v1`

```jsonc
{
  "schema": "benchmark.deiticos/v1",
  "gerado_em": "2026-08-08T21:10:03-03:00",
  "fonte": "…/final-transcript/transcript.json",   // ou "N takes em <dir>"
  "base": "montado",                  // montado | bruto
  "duracao_s": 66.312,
  "fronteira": "candidata",           // LITERAL, sempre. Ver §1
  "medicao": {
    "gap_min_s": 0.35,
    "origem_gap_min": "perfil:reels",        // perfil:<nome> | FALLBACK
    "pontuacao": true,
    "n_frases": 16,
    "lexico": "lexico-deitico-pt.json",
    "lexico_versao": "v1",
    "n_padroes": 11,                          // só os `status: ativo`
    "lexico_merges": [],                      // caminhos que sobrescreveram por slug
    "janela_s": 2.0, "pre_s": 0.15, "max_por_min": 2.0,
    "classes_off": [], "antes_nao_k": 3,
    "origem_apoio_visual": "perfil:reels"     // perfil:<nome> | FALLBACK | flag
  },
  "janelas": [
    {
      "ini": 38.79, "fim": 41.29,
      "gatilho": "desse jeito",       // o texto NORMALIZADO que casou
      "slug": "desse-jeito",          // slugs fundidos vêm com "+"
      "classe": "ostensivo",
      "peso": 2,
      "sugestao": "broll",            // domínio fechado, §3
      "dica_zona": "pleno",           // DERIVADO da sugestao, §3 — não é medição
      "frase": [37.9, 42.4],          // a unidade de leitura que contém o gatilho
      "texto": "É desse jeito que ela vira o jogo.",
      "aparada": false,               // true = o clamp encurtou o fim
      "take": "take-A"                // só em --por-take
    }
  ],
  "descartados": [
    {"ini": 31.0, "fim": 33.0, "slug": "por-exemplo", "motivo": "teto-densidade"}
  ],
  "antipadrao": [
    {"ini": 44.2, "slug": "olha-solto", "token": "gente", "trecho": "quando a gente olha"}
  ],
  "resumo": {"n_janelas": 1, "n_descartados": 0, "n_antipadrao": 0,
             "n_aparadas": 1, "densidade_por_min": 0.905}
}
```

### Domínios fechados

| campo | valores |
|---|---|
| `base` | `montado` · `bruto` |
| `fronteira` | `candidata` (não há outro; o campo existe para o consumidor não precisar saber a versão) |
| `classe` | `ostensivo` · `exemplo` · `anuncio` · `enfase` · `projecao` · `enumeracao` |
| `sugestao` | `broll` · `cartao` · `zoom` · `split` |
| `dica_zona` | `topo` · `lateral` · `faixa-legenda` · `pleno` |
| `motivo` (em `descartados`) | `teto-densidade` |

---

## 3. `sugestao → dica_zona` — derivação fixa, não medição

Medir zona é do `layout-zones.py`; a SPEC-14 é explícita sobre **não chutar
posição**. Esta tabela existe só para a partitura ter uma dica e não para
substituir a medição.

| `sugestao` | `dica_zona` | motivo |
|---|---|---|
| `broll` | `pleno` | o b-roll ocupa o quadro (ou a faixa do split) |
| `cartao` | `lateral` | é o bloco livre que o `layout-zones` procura |
| `zoom` | `pleno` | punch-in não tem zona, tem enquadramento |
| `split` | `faixa-legenda` | a máscara do `split-broll.py` cobre ~51 % da altura |

---

## 4. As cinco guardas de saída, e o que cada uma existe para impedir

| guarda | regra | o defeito que ela impede |
|---|---|---|
| **longest-match-wins** | spans sobrepostos na mesma frase: o maior vence | `olha só` casa `olha-ostensivo` **e** `olha-solto` e emitiria dois achados no mesmo instante |
| **fusão de janelas** | janelas que se tocam viram uma, `slug` composto, maior `peso` manda | três `isso aqui` em 10 s não são três beats, é um |
| **teto de densidade** | `max_por_min × duração`; acima disso ranqueia por `peso` e corta — mas **grava os cortados** em `descartados[]` | um relatório que acende sempre não é informação |
| **clamp de duração** | nenhuma janela passa da duração; a aparada sai com `"aparada": true` e entra em `resumo.n_aparadas`. Se o clamp **zerar** a janela, o script **sai 1** | é o bug do `grab_cues` do ref-A (`watch_video.py:166,178-180`): lá o cue além do fim **some em silêncio** e o relatório só imprime um `cues=` menor |
| **amostra mínima** | frase com < 3 palavras não recebe o teste de `posicao` | `Olha` dentro de fragmento de 2 palavras é ruído de ASR |

---

## 5. `lexico-deitico-pt.json` — `benchmark.lexico-deitico/v1`

Campos por entrada de `padroes[]`:

| campo | |
|---|---|
| `slug` | identidade. É por ele que os merges (`--lexico`, `--creator`) sobrescrevem |
| `padrao` | regex contra o **texto normalizado** (minúsculo, sem acento, pontuação → espaço). **Acento no padrão nunca casa** |
| `posicao` | `qualquer` · `inicio` · `fim` · `borda` (≤ 10 caracteres de cada ponta da frase) |
| `classe` | domínio fechado, §2 |
| `peso` | 1–3. Só é usado no ranking do teto de densidade e na fusão |
| `sugestao` | domínio fechado, §2 |
| `antes_nao` | tokens que, nas K palavras anteriores **sem pontuação no meio**, matam o achado. Comparação **por token**, nunca substring |
| `ocorrencias_corpus` / `arquivos_corpus` | contagem **crua** do `padrao`, medida por `--frequencia`. Não aplica `posicao` nem `antes_nao` |
| `status` | `ativo` · `candidata`. `candidata` **não** produz janela — aparece só no léxico, com o número que a reprovou |

`descartadas[]` guarda o que **não** entrou, com `ocorrencias_corpus` e `motivo`.
É o que permite discordar de uma entrada com número na frente em vez de opinião.

---

## 5b. 🔶 O bloco `apoio_visual` no `perfis/_schema.json` — PENDENTE, e por quê

Os 5 arquivos de perfil (`_base`, `reels`, `vsl`, `longform`, `screencast`)
receberam `apoio_visual` por `perfil.py patch --bloco apoio_visual` e validam. O
**`_schema.json` não recebeu**, e não é esquecimento:

```
$ python3 perfil.py patch --arquivo perfis/_schema.json --bloco properties \
      --de /tmp/frag-schema.json
ERRO: patch deixaria perfis/_schema.json inválido:
  (raiz): falta a chave obrigatória 'contrato'
  (raiz): falta a chave obrigatória 'nome'
  (raiz): falta a chave obrigatória 'video' / 'audio' / 'ritmo'
exit=1        # o arquivo fica INTACTO
```

**Causa medida**: `perfil.py:633` (`patch`) chama `validar_arquivo` no fim, e
`validar_arquivo:770-777` manda o `_schema.json` para `validar(p)` — que valida o
**documento de schema contra ele mesmo**, exigindo dele as chaves obrigatórias de
um *perfil*. Nenhum bloco pode ser patcheado em `_schema.json` por esta via; a
correção é de quem é dono do `perfil.py` (SPEC-00/20/24), não desta spec.

**Nada quebra por isso.** A própria `description` do `_schema.json` diz que blocos
de topo desconhecidos são **aceitos de propósito** (`additionalProperties: true`),
justamente para specs seguintes acrescentarem blocos sem editar o arquivo em 7
frentes concorrentes. Os 5 perfis com `apoio_visual` validam **OK** hoje.

Bloco pronto para colar em `_schema.json`, dentro de `properties`, quando o
`perfil.py` aceitar:

```jsonc
"apoio_visual": {
  "description": "Parâmetros do detector de momentos dêiticos (deiticos.py). Não são valores de formato: são propriedades DO TIPO DE PEÇA — screencast pede apoio visual o tempo todo, reels quase nunca.",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "lexico":      {"type": "string", "description": "nome do arquivo em edit-video/references/, ou caminho absoluto"},
    "janela_s":    {"type": "number", "minimum": 0.5, "maximum": 15,
                    "description": "duração da janela candidata. A faixa útil para o layout-zones é 1,5–3 s: a união de 8 s não sobra zona nenhuma."},
    "pre_s":       {"type": "number", "minimum": 0, "maximum": 2,
                    "description": "o apoio visual entra JUNTO com a palavra, não depois dela"},
    "max_por_min": {"type": "number", "minimum": 0, "maximum": 20,
                    "description": "teto de densidade; acima disso ranqueia por peso e corta, gravando os cortados em descartados[]"},
    "classes_off": {"type": "array", "items": {"type": "string"},
                    "description": "classes desligadas neste tipo de peça"},
    "antes_nao_k": {"type": "integer", "minimum": 0, "maximum": 10,
                    "description": "quantas palavras antes o antipadrão olha"}
  }
}
```

---

## 6. Como o número entra: a régua de extensão

1. `deiticos.py --frequencia "<regex>" --corpus data creators`
2. Critério: **≥ 5 ocorrências em ≥ 3 arquivos distintos** e uso ostensivo em
   **≥ 10 dos 15 contextos** impressos. Abaixo disso → `"status": "candidata"`.
3. Rodar a varredura de corpus e comparar densidade. Se a **p90 passar de
   2,5/min**, a entrada é ruído: reverter ou apertar o `padrao`.

Três portas de extensão que **não** tocam o arquivo canônico:
`--lexico <arquivo.json>` (mescla por slug, o de fora vence) ·
`<creators>/<nome>/lexico-deitico.json` via `--creator <nome>` ·
`perfil.apoio_visual.classes_off` (desliga uma classe inteira por tipo de peça).
