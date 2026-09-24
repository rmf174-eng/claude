# Contrato `benchmark.qc-nivel/v1`

Artefato do `scripts/qc-nivel.py` (SPEC-10). **Novo — não altera nenhum artefato
existente**: `edl.json`, `captions.json`, `overlays.json`, `janelas.json` e os
`segs/segNNN.json` ficam byte a byte iguais.

Gravado só com `--gravar`, em `<dir-producao>/qc-nivel-<modo>.json`. Sem a flag,
o script imprime e **não escreve nada** — é a mesma convenção dos outros QCs.

---

## 1. Os dois modos, e por que são dois

| | `achado` | `balanco` |
|---|---|---|
| roda em | **bruto** (`src` da EDL) | **render** (`v1-montado.mp4`, `v-final.mp4`) |
| referência | mediana das frases do próprio falante | **mediana dos OUTROS ranges** (leave-one-out) |
| seleção | trechos abaixo de `mediana − drop_db` | todos os ranges da EDL |
| exit | **sempre 0** (salvo `--exigir`) | **0 aprovado · 1 reprovado** |
| serve para | achar e dimensionar ganho | **aprovar** |

🔴 **`achado` não aprova, e isso está no código de saída de propósito.** Ele
seleciona o item pelo mesmo delta que depois mede: todo run listado está abaixo
do limiar **por construção**, e perseguir esse número até zero só levanta ruído de
sala. É o erro que fez o `audit-emendas.py` acusar 16 de 20 segmentos na
`peca-03`, todos falso-positivo. Quem quiser um gate a partir dele usa
`--exigir N`, que imprime o aviso antes de reprovar.

`balanco` é o gate porque a referência **independe do critério de seleção**:
ninguém escolheu o range por estar baixo, todo range entra, e um range corrigido
**para** de ser sinalizado.

---

## 2. Onde cada um roda no pipeline

| ponto | comando |
|---|---|
| etapa 2, depois do `bordas.py`, antes do `montar.sh` | `qc-nivel.py achado <dir>` |
| etapa 8, no `v1-montado.mp4`, **antes** dos QCs de cor — **gate canônico** | `qc-nivel.py balanco <dir> --video v1-montado.mp4` |
| etapa 8, no entregável (regressão da mixagem) | `qc-nivel.py balanco <dir> --video v-final.mp4 --mascara palavras --balanco-db 7` |

⚠️ **Com trilha, `--mascara palavras` é obrigatório.** Com música tocando, as
janelas fora da fala deixam de ser ruído de sala, o piso sobe e o critério (b) da
máscara passaria a marcar música como fala, contaminando o P75 de todo range.
Restringindo aos intervalos de palavra, a medida volta a ser da voz — e o limiar
afrouxa para 7 dB porque continua havendo música **por baixo** da voz.

📏 **Trilha esconde defeito**: o silêncio digital de −240 dBFS no end card da VSL
só apareceu na versão **sem** música. Quando existir a versão sem trilha, meça
nela; o passe no entregável é regressão, não substituto.

---

## 3. Envelope `achado`

```jsonc
{
  "schema": "benchmark.qc-nivel/v1",
  "modo": "achado",
  "gerado_em": "2026-08-08T21:40:11-03:00",
  "fonte": "input/take-conteudo.MOV",
  "medicao": {
    "sample_rate": 48000,            // perfil: audio.sr
    "janela_rms_s": 0.02,            // perfil: audio.janela_rms_s
    "mascara": "transcript+piso",    // ou "piso" (sem transcript — AVISA no stderr)
    "piso_db": -43.3, "piso_metodo": "p15",
    "mediana_falante_db": -18.3,
    "mediana_metodo": "mediana-das-frases",   // ou "p50-janelas" (< 5 frases medíveis)
    "n_frases": 15, "drop_db": 5.0,
    "n_janelas": 4499, "n_janelas_mascaradas": 3818,
    "min_janelas_por_span": 20,
    "mediana_por_quem": {"creator-2": -18.9, "amiga": -18.6}
  },
  "frases":    [ /* start, end, texto, nivel_db, delta_db, flag, ganho_sugerido_db */ ],
  "runs":      [ /* start, end, nivel_db, delta_db, texto, ganho_sugerido_db, n_janelas */ ],
  "segmentos": [ {"i": 3, "beat": "vamos", "src": "input/take-conteudo.MOV",
                  "start": 19.59, "end": 20.31, "quem": "creator-2",
                  "nivel_db": -40.0, "delta_db": -21.6, "pior_delta_db": -19.9,
                  "gain_db_atual": 0.0, "ganho_sugerido_db": 12.0,
                  "flag": "LOW", "n_janelas": 33} ],
  "veredito": {"n_low": 1, "aprovado": null,
               "nota": "achado não aprova — ver modo balanco"}
}
```

Com mais de um `src` na EDL, o topo vira `{"schema", "modo", "fontes": [ ... ]}`,
um objeto por bruto.

**A lista acionável é `segmentos`** — é a que casa com a EDL. `runs` é sub-frase e
over-triggera: o intervalo de palavra do Deepgram é generoso e a pausa **dentro**
dele entra na máscara. Por isso o relatório de texto lista só os 10 piores runs e
diz quantos ficaram de fora; o JSON leva todos.

## 4. Envelope `balanco`

```jsonc
{
  "schema": "benchmark.qc-nivel/v1",
  "modo": "balanco",
  "video": "v-final.mp4",
  "medicao": {
    "referencia": "mediana-dos-outros (leave-one-out)",
    "balanco_db": 5.0,
    "mascara": "transcript+piso",         // auto | palavras | piso
    "palavras_origem": "derivado-do-bruto", // --transcript | final-transcript |
                                            // derivado-do-bruto | nenhuma
    "n_palavras": 199,
    "piso_db": -35.2, "piso_metodo": "p15",
    "n_ranges": 29,
    "fronteiras": "timeline_real",        // ou "ffprobe-segs" (fallback, AVISA)
    "n_janelas": 3539, "n_janelas_mascaradas": 3381,
    "min_janelas_por_range": 20
  },
  "ranges": [ {"i": 3, "beat": "vamos", "quem": "creator-2",
               "inicio_s": 12.567, "fim_s": 13.300,
               "n_janelas": 37, "n_janelas_mascaradas": 33,
               "n_palavras": 1, "dur_palavras_s": 0.63,
               "nivel_db": -34.1, "referencia_db": -13.4, "delta_db": -20.7,
               "flag": "LOW-LEVEL", "ganho_sugerido_db": 12.0} ],
  "veredito": {"flags": 1, "n_low_level": 1, "n_sem_nivel": 0, "aprovado": false}
}
```

---

## 5. Domínio fechado de `flag`

Não invente valor novo sem atualizar **este** arquivo.

| valor | significado | conta no veredito |
|---|---|---|
| `ok` | dentro do balanço | não |
| `LOW` | (só `achado`) `delta_db ≤ −drop_db` | não reprova — `achado` nunca reprova |
| `LOW-LEVEL` | (só `balanco`) `delta_db ≤ −balanco_db` | **sim** |
| `SEM-NIVEL` | tem fala suficiente dentro e **nenhuma** janela mascarada sobreviveu | **sim** |
| `sem-fala` | nenhuma palavra do transcript dentro — payoff mudo, som ambiente | não, e **sai da mediana** |
| `amostra-curta` | span com menos de `min_amostra_s` de fala mascarada | não |

🔴 **`SEM-NIVEL` é reprovação, nunca "pulei".** É a regra que impede o QC de se
auto-neutralizar. Medido: no `v-final.mp4` da `peca-01`, com a máscara
reduzida a um gate de nível, o range 3 fica com **zero** janelas — o defeito
**desaparece** do relatório e o veredito volta verde. Fala suficiente + zero
janela medível é defeito grave, não amostra pequena.

Como o script separa os dois: `SEM-NIVEL` exige que a **duração das palavras
dentro do range** alcance `min_amostra_s`. Um range longo com uma única palavra
de 0,2 s é `amostra-curta`; um range com 0,63 s de palavra e zero janela é
`SEM-NIVEL`. Sem transcript nenhum, um range com duração suficiente e zero janela
medível é `SEM-NIVEL` — não dá para provar que o silêncio é intencional, e um QC
não aprova o que não conseguiu medir.

---

## 6. Os parâmetros vêm do perfil de peça

Bloco `audio` do perfil (SPEC-00). O que **já existe hoje** e é lido sempre:
`audio.sr`. O que o `qc-nivel.py` consome **quando o catálogo passar a ter**, com
fallback nomeado no topo do script (`# perfil: audio.nivel.<campo>`):

```jsonc
"audio": {
  "sample_rate": 48000,
  "janela_rms_s": 0.020,
  "nivel": {
    "drop_db": 5.0,           // achado, no bruto
    "balanco_db": 5.0,        // convergência, no render
    "min_run_s": 0.25,
    "min_amostra_s": 0.40,
    "margem_mascara_db": 6.0,
    "piso_percentil": 15,
    "headroom_db": 1.5,
    "ganho_max_db": 12.0
  }
}
```

Defaults sugeridos por tipo de peça:

| perfil | `drop_db` | `balanco_db` | motivo |
|---|---|---|---|
| `reels` | 5,0 | 5,0 | calibrado nos 52 ranges entregues deste repo |
| `vsl` | 4,0 | 4,0 | locução contínua, dinâmica menor; e um trecho inaudível numa peça de venda custa mais |
| `corte-de-podcast` | 6,0 | 6,0 | dois microfones e dois falantes: variação legítima maior |
| `longform` | 5,0 | 5,0 | igual reels |
| `screencast` | — | — | sem fala contínua de um falante único; rodar só se houver locução |

🔴 **O `balanco_db` é 5,0 e não 4,0, e a calibração é nossa.** Medido em
2026-08-08 nas três produções entregues: `peca-01` −20,7 dB (o defeito),
`peca-03` **−4,1 dB** e `nao-perdeu-a-peca-06` −0,5 dB. Com 4,0 o gate reprovaria
uma entrega aprovada por 0,1 dB — falso positivo no primeiro dia de uso, que é
como um QC perde a confiança do operador. Com 5,0 sobra ~1 dB de margem sobre o
pior material limpo e ainda restam 16,6 dB de separação para o defeito real.

---

## 7. Duas regras que o consumidor não pode quebrar

1. **A fronteira do range na saída vem da timeline real**, nunca de
   `Σ(end−start)` da EDL. A soma nominal é sempre menor (353 ms no fim da
   `peca-03`, 317 ms na `peca-01`) e o range 3 da `peca-01`, que
   dura 0,73 s, seria medido meio segmento fora. O script usa
   `edl_io.timeline()` e cai em `edl_io.medir_timeline()` avisando no stderr.
2. **A máscara de fala vem do transcript, nunca do nível.** Definir fala por
   nível é circular — a fala baixa demais deixa de ser fala e some do relatório.
   Quando não há transcript, o script **avisa** e grava `"mascara": "piso"`, para
   que o relatório diga que naquele modo ele tem o teto de detecção do detector
   que a SPEC-10 rejeitou.

## 8. Autoteste

```bash
python3 tests/test_qc_nivel.py          # 29 checagens, 100 % sintético, ~5 s
python3 tests/test_qc_nivel.py --real   # + 6 checagens nas 3 produções entregues
```

O autoteste **não depende de fixture nenhuma** — gera áudio, transcript, EDL,
`segs/` e montado em `/tmp`. Sem `creators/` na máquina, os casos `--real` são
pulados com uma linha e o resto continua verde: quem depende de fixture é o
teste, não a ferramenta. Toda guarda é provada por **defeito plantado**.
