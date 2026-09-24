# Contrato da trilha — `benchmark.trilha/v1` e `benchmark.music-library/v1`

> SPEC-20. Dois artefatos, um por script: `musica-gerar.py` escreve o índice da
> biblioteca; `trilha.py` escreve o sidecar da produção. Nenhum artefato existente
> (`edl.json`, `janelas.json`, `captions.json`, `cenas.json`, sidecar de `segs/`)
> ganha ou perde campo.

---

## A regra que governa tudo

> **O nível da trilha é Δ EM RELAÇÃO À VOZ, nunca LUFS absoluto.**

Um alvo absoluto vale para uma peça e mente em todas as outras: as VSLs vivem por
volta de −14 LUFS e as peças orgânicas do creator-1 a −24,4. O mesmo "−27" que deixa a
trilha 13 LU abaixo numa deixa 2,6 LU **acima** do pretendido na outra. Por isso o
passo 0 do `preparar` **mede** o integrado da voz e o alvo sai de
`I_voz − delta_voz_lu`.

E o corolário, que é o que o QC existe para checar:

> **O alvo em LUFS é o DETECTOR. Ele nunca pode ser o teste de convergência.**
> Quem seleciona por um limiar não converge por ele. A referência independente é
> o EFEITO medido sobre a voz.

---

## 1. `<dir-producao>/trilha.json` — `benchmark.trilha/v1`

Escrito pelo `preparar`; o campo `verificacao` é preenchido pelo `verificar`.

```json
{
 "contrato": "benchmark.trilha/v1",
 "musica": "trilha/musica.mp3",
 "saida": "trilha-pronta.wav",
 "voz_referencia": "v1-graded.mp4",
 "voz_i_lufs": -14.2,
 "voz_dur_s": 189.461333,
 "perfil_trilha_ativa": true,
 "alvo": {"delta_voz_lu": 13.0, "i_lufs": -27.2},
 "ducking": {"duck_db": 5.0, "ratio": 1.3333, "threshold": 0.0195,
             "attack_ms": 25, "release_ms": 450,
             "derivacao": "threshold = 10^((I_voz−20)/20); ratio = 20/(20−duck_db), sem piso"},
 "loop": {"copias": 7, "crossfade_s": 1.5, "dur_musica_s": 30.772},
 "audio": {"sr": 48000, "canais": 2, "highpass_hz": 60},
 "fades": {"in_s": 2.5, "out_s": 4.0},
 "medido": {"pos_ducking_i": -29.1, "compensacao_db": 1.9,
            "final_i": -27.3, "final_tp": -10.7,
            "dur_s": 189.461, "deriva_ms": 0.0},
 "licenca": {"na_biblioteca": true, "faixa": "reels-intimista-65cec8c6",
             "texto": "Gemini API (tier pago) — …", "exige_atribuicao": false,
             "synthid": true, "credito": null},
 "verificacao": { … ver §3 … }
}
```

**Campos que não são decoração:**

| campo | por que existe |
|---|---|
| `voz_i_lufs` | é a origem do alvo e do `threshold`. Sem ele o número não é reproduzível |
| `medido.deriva_ms` | `soma_audio == soma_video` é invariante do pipeline. `preparar` ABORTA acima de 1 ms |
| `medido.pos_ducking_i` e `compensacao_db` | o passo que o ref-A não tem. Sem ele, fala contínua entrega trilha morta |
| `licenca.*` | a licença é **persistida**, não impressa. Impressa some com a sessão |
| `perfil_trilha_ativa` | `ativa=false` no perfil e o comando rodado à mão: fica registrado que a decisão foi explícita |

---

## 2. `tools/music-library/INDEX.json` — `benchmark.music-library/v1`

Array; um objeto por faixa. Espelha `tools/broll-library/INDEX.json`, mesma
disciplina: **a licença é do item, não da biblioteca.**

```json
{
 "nome": "reels-intimista-65cec8c6",
 "chave": "65cec8c68f6c8468",
 "arquivo": "tracks/reels-intimista-65cec8c6.mp3",
 "provedor": "lyria-3-clip-preview",
 "licenca": "Gemini API (tier pago) — … contém marca d'água SynthID inaudível",
 "exige_atribuicao": false, "synthid": true, "autor": null,
 "prompt": "<o prompt final, já moldado>", "vibe": "<a vibe crua>",
 "estrutura_declarada": "<instrumental>",
 "custo_usd": 0.04, "tentativas": 1, "filtradas": 0,
 "gerado_em": "2026-08-08T22:21:57-0300",
 "sha256": "e1ccedc64988…", "bytes": 744610,
 "dur": 30.77, "sr": 44100, "canais": 2,
 "i_lufs": -12.6, "tp_dbfs": -0.1,
 "mascara_pct": 0.1935, "dinamica_db": 23.0, "crest_db": 14.3,
 "tags": ["reels", "intimista"]
}
```

- **`chave`** = `sha256(prompt_canônico + modelo)[:16]`. É a idempotência: a
  segunda chamada idêntica faz **zero** requisição HTTP. Isso é dinheiro.
- **`sha256`/`bytes`** = identidade por CONTEÚDO. A faixa é copiada para
  `<dir>/trilha/musica.mp3` e perde o nome — casar por nome erraria exatamente no
  caso em que alguém precisa saber a licença.
- **`exige_atribuicao: true`** tem consequência mecânica: o `preparar` escreve
  `<dir>/trilha/CREDITO.txt` e **sai 5** se não puder escrever um crédito honesto
  (registro sem texto de licença); o `verificar` **sai 5** se o arquivo sumiu.
- **`filtradas`** existe para medirmos a taxa real do filtro de copyright depois
  de algumas produções — e para responder se geração filtrada é cobrada.

---

## 3. O bloco `verificacao` — medir o EFEITO, não o alvo

```json
"verificacao": {
 "janelas_total": 473, "janela_ms": 400,
 "janelas_densas": 110, "janelas_pausa": 33, "janelas_fala": 440,
 "voz_integrado_dbfs": -13.8, "piso_pausa_dbfs": -23.8, "limiar_densa_dbfs": -12.2,
 "mascaramento_db": 0.09, "presenca_db": 5.03, "adicao_total_db": 0.1234,
 "limiares": {"mascara_max_db": 0.5, "presenca_min_db": 3.0},
 "controle": {"atenuacao_db": 30.0, "presenca_db": 0.01,
              "queda_energia_db": 31.5, "veredito": "reprovou (esperado)"},
 "controle_negativo": "reprovou (esperado)",
 "veredito": "ok"
}
```

**Como as janelas são classificadas** (tudo em dBFS RMS, os dois lados no mesmo
domínio — comparar janela em dBFS com integrado em LUFS mistura K-ponderado com
não-ponderado e desloca o piso alguns dB):

- **densa** = RMS ≥ percentil 75 do envelope das janelas de fala;
- **pausa** = RMS ≤ integrado da peça **− 10 dB**.

> 🔴 **O piso é −10 dB, e isso foi MEDIDO — não é o −25 que a spec propunha.**
> Com −25 este QC **não pega** o defeito que ele existe para pegar. Plantando a
> trilha 22 LU abaixo da voz (que reproduz os −36,4 LUFS históricos; a peça de
> VSL saiu medindo −36,3):
>
> | piso | VSL: n / boa / morta | reels: n / boa / morta | limiar 3,0 |
> |---|---|---|---|
> | −8 dB | 45 / +3,51 / +0,64 | 18 / +7,05 / +1,79 | separa, margem 0,5 |
> | **−10 dB** | **33 / +5,03 / +1,07** | **16 / +8,18 / +2,30** | **separa, margem ~2 ✅** |
> | −12 dB | 27 / +6,29 / +1,49 | 11 / +11,19 / +4,04 | morta PASSA ❌ |
> | −25 dB | 8 / +14,61 / +6,56 | **1** / +21,84 / +13,04 | morta PASSA ❌ |
>
> A −25 dB a população some (1 janela em 176 num reel: veredito de uma janela não
> é veredito) e a trilha morta sobe junto com a boa, porque numa janela quase muda
> qualquer coisa parece presente.

**Veredito:**

| condição | resultado |
|---|---|
| `mascaramento_db > mascara_max_db` | FALHA — a trilha está cobrindo a voz |
| `presenca_db < presenca_min_db` | FALHA — a trilha é inaudível |
| `janelas_densas == 0` | FALHA — o classificador não mediu nada |
| `janelas_pausa < 3` | AVISO — `presenca` vira informação, régua passa a ser só mascaramento, e o QC **manda ouvir** |

🔒 **Prova de dentes, obrigatória.** O modo `verificar` imprime **quantas** janelas
densas e de pausa varreu, e `--controle-negativo` refaz a conta com a trilha
atenuada em 30 dB. O controle **tem que** reprovar; se não reprovar, o veredito
vira `CEGO` e o `verificar` sai 1 dizendo que o verificador está cego.

⚠️ A atenuação do controle é feita **em memória** (multiplicação do vetor), não com
um `ffmpeg volume=-30dB`: um encoder no meio faria o portão medir o encoder.

⚠️ `queda_energia_db` compara **energia acrescentada** (`Pm/Pv`), não `adicao_db`.
São unidades diferentes: atenuar a trilha 30 dB divide `Pm/Pv` por 1000, mas move
o `adicao_db` de 0,05 para 0,00005 — comparar esses 0,05 com um limiar de 20
reprovaria um verificador que está funcionando.

---

## 4. Exit codes

| | `trilha.py` | `musica-gerar.py` |
|---|---|---|
| 0 | ok | ok |
| 1 | QC reprovou | — |
| 2 | uso inválido / perfil sem bloco `trilha` completo | uso inválido |
| 3 | falha de ffmpeg, ou deriva de duração acima de 1 ms | falha de ffmpeg |
| 4 | (repassado do gerador) | geração filtrada em todas as tentativas |
| 5 | licença exige crédito e o `CREDITO.txt` não está lá | — |

stdout = caminho do artefato final; logs em stderr.

---

## 5. Onde a trilha entra na cadeia

```
v1-graded (voz) ─┐
graphics.mov ────┤ overlay (vídeo)                   → [v]
   (SFX) ────────┤ amix inputs=3 normalize=0         → mix.wav (PCM 48k)
trilha-pronta ───┘        ▲
                          └── trilha.py preparar (ducking e nível já resolvidos AQUI)
                                    │
                    loudness.py --normalizar  (2 passes, alvo do perfil)
                                    │
                    loudness.py --teto        (alimiter, se necessário)
                                    │
                    mux -c:v copy + aac → v-final.mp4
```

**A trilha entra ANTES do loudnorm final, e isso não é indiferente**: o alvo dela é
relativo à voz, e o loudnorm aplica ganho ao programa inteiro — a relação se
preserva. Entrar depois somaria energia num sinal já no alvo e estouraria o alvo.

- ⚠️ `normalize=0` no `amix` é obrigatório: sem ele o `amix` divide por N e derruba a voz.
- ⚠️ `duration=first`, e **nada de `-shortest`**: trilha curta é para APARECER, não para truncar o vídeo.
- ⚠️ Somar a trilha muda o true peak. O instrumento é o `--teto` do `loudness.py`; re-normalizar mexeria na dinâmica que o ducking acabou de criar.
- ⚠️ **O QC de áudio roda na versão SEM trilha.** Medido: o silêncio digital de −240 dBFS no end card de uma VSL só apareceu na versão sem música. Trilha **esconde** defeito.
