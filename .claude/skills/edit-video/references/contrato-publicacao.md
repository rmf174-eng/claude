# Contrato dos entregáveis de publicação — `benchmark.publicacao/v1`

> Origem: **SPEC-21**. Este arquivo é o contrato versionado que os consumidores
> leem. Quem for escrever ou consumir `.srt`, `.vtt` ou `chapters.txt` desta
> skill lê isto antes.
>
> Implementação: `scripts/palavras.py`, `scripts/srt.py`, `scripts/capitulos.py`
> · teste: `scripts/tests/test_publicacao.py`.

---

## 0. As quatro frases que resumem tudo

1. **As palavras vêm do BRUTO, nunca do montado.** O ASR lê a emenda como fala
   contínua e **inventa palavra** para fazer sentido — a legenda entregue dizia
   *"Você manda as empresas com o seu sócio"* onde o creator-3 fala *"uma das
   empresas que eu sou sócio"*. `fonte_palavras: "transcript-montado"` **não é um
   valor aceito**.
2. **A posição vem da `timeline_real`, nunca de `Σ(end−start)`.** Sem timeline os
   três scripts **abortam**; não existe fallback. Preferimos não entregar o
   arquivo a entregar um arquivo deslocado.
3. **O conjunto de entregáveis é decisão do PERFIL DE PEÇA**, não do script.
   `publicacao.srt.gerar` e `publicacao.capitulos.gerar` — os scripts saem `0`
   sem escrever nada quando estão desligados.
4. **O que reprova é o artefato mentir, não o orador falar rápido.** `cps` e
   `dur_min` são réguas de conforto que o material pode tornar fisicamente
   inalcançáveis; o invariante verificável é o sidecar declarar **exatamente**
   quantos cues estouram cada uma.

---

## 1. Os artefatos

```
<dir>/captions.srt              SAÍDA   texto, UTF-8 SEM BOM, LF, newline final
<dir>/captions.vtt              SAÍDA   opcional (formatos: ["srt","vtt"])
<dir>/chapters.txt              SAÍDA   uma linha "<stamp> <título>", nada mais
<dir>/captions.srt.meta.json    SAÍDA   benchmark.publicacao/v1  (procedência)
<dir>/chapters.txt.meta.json    SAÍDA   benchmark.publicacao/v1
<dir>/capitulos.json            ENTRADA opcional, benchmark.capitulos/v1
<dir>/transcritos.json          ENTRADA opcional, {src: caminho}
<dir>/ortografia.json           ENTRADA opcional, {troca:{}, grupo:[]}
```

`chapters.txt` é para **colar na descrição do YouTube** — nada além das linhas:

```
0:00 Introdução
1:12 O erro que todo mundo comete
4:38 Como a gente resolveu
```

---

## 2. `edl.json` — o campo `capitulo`, aditivo

```json
{"src": "input/a.MOV", "start": 27.61, "end": 30.87, "fala": "…",
 "beat": "gancho", "capitulo": "O que é X"}
```

Aditivo puro: leitor antigo ignora a chave, EDL sem `capitulo` continua válida.
Quem faz o campo sobreviver ao `bordas.py` é a **lista negra** da SPEC-05 — escreva
`capitulo` no `janelas.json` e ele atravessa até a EDL. O capítulo ancora em
`timeline_real.segments[i].start_s`.

Para capítulo que **não** cai em início de segmento (comum em longform, onde um
segmento tem 40 s), use `capitulos.json`:

```jsonc
{"schema": "benchmark.capitulos/v1",
 "capitulos": [{"i_seg": 7, "src_t": 412.30, "titulo": "O erro que todo mundo comete"}]}
```

`src_t` está em tempo **do bruto** e tem que cair dentro do segmento `i_seg`;
a posição sai de `edl_io.t_saida(tl, i_seg, src_t)`. As duas entradas **se somam**.
Dois capítulos no mesmo instante = erro.

---

## 3. O bloco `publicacao` do perfil de peça

```jsonc
"publicacao": {
  "srt": {
    "gerar": false, "arquivo": "captions.srt", "formatos": ["srt"],
    "max_chars_linha": 42, "linhas": 2, "cps_max": 17.0,
    "dur_min_s": 0.833, "dur_max_s": 7.0,
    "gap_quebra_s": 0.7, "gap_entre_cues_frames": 2,
    "caixa": "original",
    "fonte_palavras": "edl-bruto"          // único valor aceito
  },
  "capitulos": {
    "gerar": false, "arquivo": "chapters.txt",
    "minimo": 3, "dur_min_s": 10.0,
    "titulo_abertura": "Introdução", "max_chars_titulo": 100
  }
}
```

`_schema.json` recebe o bloco como **opcional**, com `additionalProperties: false`
dentro dele: um `cps_maximo` digitado errado falha no `perfil.py validar` em vez de
virar default silencioso. `cps_max` **não tem teto** no schema — 99 desliga o passe
de CPS na prática, e isso é escolha do operador, não erro.

| perfil | `srt.gerar` | `capitulos.gerar` |
|---|---|---|
| `reels` | false | false |
| `vsl` | **true** | false (ver `_motivo` no arquivo) |
| `longform` | **true** | **true** |
| `screencast` | **true** | false |

⚠️ `publicacao` **não** está em `CREATOR_PODE` (`perfil.py`): um
`creators/<n>/perfil-overrides.json` **não pode** ligar/desligar o bloco. Quem liga
é o perfil de peça ou `perfil.py resolver … --set publicacao.capitulos.gerar=true`.

**Sem `perfil.json`** (produção histórica, ou anterior à SPEC-00): default embutido
`palavras.PADRAO_PUBLICACAO`, com `srt.gerar = true` e `capitulos.gerar = null`
(AUTO: liga se houver ao menos um capítulo declarado). Roda; só não dá para
desligar por perfil.

⚠️ Os nomes em `publicacao.*.arquivo` têm de aparecer em `entregaveis` quando
`gerar: true`. O `longform` do catálogo já lista `captions.srt` e `chapters.txt` —
os defaults foram escolhidos para bater com aquela linha.

---

## 4. O sidecar de procedência

```jsonc
{"schema": "benchmark.publicacao/v1", "gerado_por": "srt.py", "gerado_em": "…",
 "edl_fingerprint": "sha1:…", "perfil": "longform", "fonte_palavras": "edl-bruto",
 "fonte_tempo": "asr", "transcritos": {"input/a.MOV": "take-A/transcript.json"},
 "ortografia": {"arquivo": null, "trocas_aplicadas": 0, "grupos_aplicados": 0},
 "regra": { /* o bloco publicacao.srt efetivamente usado */ },
 "cues": 38, "palavras": 403, "cps_p50": 16.7, "cps_p95": 25.55,
 "cps_excedidos": 17, "dur_min_violada": 4, "sobreposicoes_clampadas": 21,
 "sobreposicao_max_ms": 66.7, "cauda_clampada": 6, "total_s": 127.266667, "fps": 30.0}
```

O `edl_fingerprint` é o que permite dizer, meses depois, se o `.srt` na pasta
descreve o corte que está lá. `.srt` e `chapters.txt` **desatualizados são piores
que ausentes**, porque parecem prontos.

**Idempotência**: artefato existente com `edl_fingerprint` **e** `regra` iguais →
pula e imprime o caminho. Mudou `ortografia.json` ou o transcript? Apague o
artefato antes (é a regra do projeto: *refresh = apagar o artefato*).

---

## 5. Como o tempo é calculado

```
tl  = edl_io.timeline(d, exigir=True)     # ABORTA se ausente ou stale
seg = tl["segments"][i]

a_off_s   = seg.get("audio_offset_samples", seg["start_sample"]) / tl["sample_rate"]
src_ini_a = seg["src_start"]              # o `start` da EDL É a cabeça do ÁUDIO
t_saida(w) = a_off_s + (w.start − src_ini_a)
```

**Pelo ÁUDIO e não pelo vídeo.** Legenda acompanha fala. Sem J-cut,
`audio_offset == video_offset` e a distinção não aparece; com J-cut (SPEC-07) o
áudio de um take entra **antes** da imagem, e indexar pelo vídeo poria todo cue
daquele take `lead` atrasado — até 165 ms, o suficiente para a legenda entrar
depois da palavra. O `.get()` funciona nos dois mundos sem `if`.

**Quais palavras entram no segmento `i`**: as do transcript de `seg.src` com
`seg.src_start <= w.start < seg.src_end` — *começa dentro da janela*. **Não é
sobreposição**: uma palavra partida por um corte pertenceria aos dois lados e
apareceria **duas vezes**.

---

## 6. De onde vem o transcript de cada `src` — 6 passos, nenhum silencioso

1. `--transcript "<src>=<caminho>"` (repetível) — explícito, vence tudo.
2. `<dir>/transcritos.json` — `{"input/take-a.MOV": "take-A/transcript.json"}`.
3. `<dir>/spec.json` com as chaves `src` e `transcript` (precedente em uso).
4. `<dir>/<stem(src)>/transcript.json` — `input/take-conteudo.MOV` →
   `take-conteudo/transcript.json`.
5. Um único `src` na EDL **e** um único **`take*/`**`transcript.json` → casamento
   por eliminação.
6. Não achou: **erro fatal**, listando o que foi tentado e imprimindo a linha
   `--transcript "<src>=<caminho>"` pronta para colar.

🔴 **O prefixo `take` do passo 5 não é cosmético.** `creator-2/peca-03` tem TRÊS
diretórios com `transcript.json`: `take-A/` (o bruto, correto), `final-transcript/`
e `final-transcript-derivado/` — os dois últimos são transcrições **do montado**.
Aceitar "qualquer diretório" faria o resolvedor sortear entre eles, e no dia em que
sorteasse o do montado o `.srt` sairia com a palavra inventada na emenda.

Comportamento medido nas 4 produções do repo:

| produção | resolve por | resultado |
|---|---|---|
| `peca-10-27-07/c-completo` | passo 3 (`spec.json`) | ✅ |
| `creator-2/peca-01` | passo 4 (`<stem>/`) | ✅ 2 takes |
| `creator-2/peca-03` | passo 5 (único `take*/`) | ✅ |
| `creator-2/peca-04` | — | ❌ erro com as 2 linhas prontas (nomes não casam) |

---

## 7. As regras de cue (`srt.py`)

**Agrupamento** — fecha o cue no **primeiro** gatilho:

1. **Fronteira de descontinuidade real** — troca de `src` ou `end_k != start_{k+1}`.
   É o mesmo predicado de `fade_modo: so-descontinuidade`. Segmentos **contíguos**
   (a divisão em planos do `dividir-planos.py`) **não** quebram cue: são a mesma
   frase com dois enquadramentos.
2. Pontuação de fim de frase no `punctuated_word` (`.!?…`).
3. Gap de silêncio ≥ `gap_quebra_s`.
4. Orçamento de caracteres (`linhas × max_chars_linha`), medido **no texto já
   quebrado**.
5. Duração > `dur_max_s`.

**Três passes, nesta ordem:**

- **CPS** — primeiro **estica** o fim para dentro do silêncio até
  `próximo.ini − gap`; se ainda estoura, **parte** o cue no maior gap interno (ou
  numa vírgula) e estica de novo; se ainda estoura, **não mente**: mantém o tempo
  real e conta em `cps_excedidos`. Partir só é aceito se **medidamente melhorar** —
  partir sem gap interno deixa as duas metades piores que o original.
- **Duração mínima** — estende o **fim** até `dur_min_s`. 🔴 **Nunca antecipa o
  início**: texto na tela antes da palavra ser dita é erro de sincronia; cue curto
  é só desconforto.
- **Sobreposição** — `cue[i].fim <= cue[i+1].ini − gap_entre_cues`, com
  `gap_entre_cues = gap_entre_cues_frames / fps` (frames do `timeline_real`, nunca
  um valor de ms fixo). **Sem piso mágico de 0,4 s**: a violação é contada e
  reportada, não escondida.

**Grade de 1 ms.** Depois dos três passes os tempos são levados para a grade do
formato `HH:MM:SS,mmm` e o clamp é refeito **lá**. Sem isso, `gap = 2/30 s` (que
não cai na grade) fazia 16 cues do `c-completo` saírem 0,7 ms sobrepostos **no
arquivo** enquanto a memória estava certa — é por isso que `--verificar` relê o
disco, não o objeto.

**Quebra de linha**: o **menor** número de linhas que cabe, e só então equilíbrio
pelo caractere do meio. Minimizar a linha mais longa sem esse teto quebra
"e na verdade" em duas linhas de 4 e 7 caracteres.

**Formato**: UTF-8 **sem BOM**, `LF`, newline final, caixa **preservada** do
`punctuated_word`. `.vtt` sai do mesmo objeto de cue.

---

## 8. As regras de capítulo (`capitulos.py`)

Todas **duras** (exit 1), medidas **nos stamps floored** — é o que a plataforma
enxerga:

| regra | valor |
|---|---|
| primeiro stamp | `0:00` |
| quantidade | ≥ `minimo` (3) |
| duração de cada um | ≥ `dur_min_s` (10 s), o último contra `total_s` |
| ordem | estritamente crescente |
| título | 1–`max_chars_titulo`, sem `\n`, espaços colapsados |

**Arredondamento: `floor`, sempre.** Um stamp arredondado para cima cai **dentro**
da seção e o espectador perde a primeira palavra. Com `floor` o erro é sempre ≤ 1 s
**para trás** e cai dentro do pad `pre` que o `bordas.py` já deixa antes da fala. E
`floor` dá `0:00` de graça para `t < 1`.

**Abertura ausente**: se o primeiro capítulo está em `t ≥ 1 s`, insere um em `0:00`
com `titulo_abertura` e **avisa**. 🔴 **Nunca duplicar o título do primeiro** — um
índice com duas entradas idênticas é pior do que não ter índice.

**Formato do stamp**: `H:MM:SS` se `total_s ≥ 3600`, senão `M:SS`.
**stdout = caminho do artefato; o bloco vai para stderr.**

---

## 9. CLI e exit codes

```
palavras.py  <dir> [--transcript "src=path"]... [--transcritos map.json]
             [--ortografia f.json] [--alinhamento alignment.json] [--json]

srt.py       <dir> [-o captions.srt] [--formatos srt,vtt] [--perfil-off]
             [--max-chars N --linhas N --cps N --dur-min S --dur-max S --gap S]
             [--verificar] [--verificar-audio [--amostras N] [--offset-teste S]
                            [--janelas-json]]

capitulos.py <dir> [-o chapters.txt] [--forcar] [--json] [--perfil-off]
```

| exit | significa |
|---|---|
| `0` | ok (inclusive "o perfil desligou este entregável") |
| `1` | regra violada — `.srt` inconsistente, capítulo fora das regras do YouTube |
| `2` | **declarado e não produzido** — `gerar: true` e faltou transcript, ou não há capítulo nenhum declarado |

O `2` existe para a bateria de QC (SPEC-12) tratar "entregável declarado e ausente"
como falha **sem precisar saber o que cada script faz**.

Flags de CLI **vencem** o perfil. `--forcar` grava o `chapters.txt` mesmo com regra
violada, mantendo exit 1 — para o operador ver o bloco e decidir onde mover o
capítulo.

---

## 10. A régua independente (`--verificar-audio`)

`--verificar` relê o **arquivo** e afirma os invariantes; ele confirma o critério
que o gerador usou. **Não basta.** `--verificar-audio` amostra N cues, corta a
janela `[ini, fim]` do `v1-montado.mp4`, transcreve só aquilo (Deepgram
`nova-3/multi` — **nunca `nova-2` pt-BR**, que devolveu transcrição vazia em 3 de 16
janelas curtas) e compara os tokens.

Régua: **sobreposição de tokens ≥ 80 %**, não igualdade — a quantização de 80 ms do
Deepgram e a palavra de borda que o ASR completa sozinho **não são erro**.

🔴 **O controle negativo é obrigatório para o verde valer alguma coisa.** Com
`--offset-teste 0.5` a sobreposição tem de **cair**; se não cair, o teste não está
medindo nada. A parte barata roda sem API: `--janelas-json` imprime as janelas que
seriam transcritas, e comparar as duas rodadas prova que o offset desloca 500 ms de
verdade.

Sem `v1-montado.mp4` ou sem `DEEPGRAM_API_KEY`, `--verificar-audio` sai **2** com
aviso e **não finge** ter verificado.

---

## 11. O que NÃO herdamos do ref-A (e por quê)

| bug deles | onde | o que fazemos |
|---|---|---|
| posição por `Σ(end−start)` | `chapters.py:44-49`, `render.py:762,798-799,809` | ler `timeline_real`; abortar se ausente |
| transcript de fonte ausente pulado em silêncio | `render.py:770-773` | erro fatal com a linha pronta para colar |
| palavra selecionada por **sobreposição** → duplica no corte | `render.py:736-748` | "começa dentro da janela" |
| `min_dur` prometido e violado com piso de 0,4 s | `captions_srt.py:58` vs `:77-80` | clamp que **reporta**; sem piso mágico |
| nenhum controle de CPS | `captions_srt.py` inteiro | `cps_max` no perfil, com passe próprio |
| `upper()` na legenda | `render.py:806` | `caixa: "original"` |
| validação do YouTube só como warning | `chapters.py:69-81` | exit 1; `--forcar` grava e mantém o código |
| título duplicado ao forçar o `0:00` | `chapters.py:58-61` | `titulo_abertura` do perfil |
| `round` no stamp | `chapters.py:26` | `floor`, sempre |
| leitor de palavras no formato Whisper | `captions_srt.py:31-33` | leitor Deepgram (`punctuated_word`) |

**Nenhum arquivo desta spec porta código do ref-A** — mecanismo sim, código não.

---

## 12. Uma medição que muda como se lê o `cps_p95`

Em `peca-10-27-07/c-completo` (16 segmentos, 127,267 s, 403 palavras) a fala tem
**17,2 caracteres por segundo de média global** e **23,2 no p95 de janelas de 5 s**.
O `.srt` gerado dá `cps_p95 25,55`. **Nenhum agrupamento chega ao teto de 17 nesse
material** sem apagar texto ou mentir no tempo — o teto é convenção de mercado de
legendagem em pt-BR adotada como default revisável, **não** medição nossa, e a peça
é um anúncio com as pausas cortadas.

Por isso o que reprova no `--verificar` é o **sidecar não declarar** os cues que
estouram, não os cues existirem. Um `cps_p95` acima do teto é **informação para
quem revisa** (baixar o ritmo, cortar palavra, aceitar) — não um bug do gerador.
