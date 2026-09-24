# Contrato do SFX — inventário, sidecar e a ordem das operações

> SPEC-26 §3.6, §4.2 e §4.3. Uma página. Quem prepara um SFX lê isto; quem só
> quer saber se a biblioteca está boa roda `qc-sfx.py`.

---

## 1. A ordem das operações, e o número que a obriga

```
1. aparar o LEAD-IN   → transiente em t = 0 (com 3 ms de guarda antes do onset)
2. aparar a CAUDA     → fim acústico + 250 ms de release
3. declick / fade     → pela CLASSE MEDIDA, sem atravessar o corpo
4. MEDIR o integrado  → ebur128 com -stream_loop 15 (16 passagens)
5. NORMALIZAR e RE-MEDIR
```

🔴 **Medir antes de aparar é o erro, e ele tem número.** `pop.wav` mede
**−22,5 LUFS** como está e **−17,5 LUFS** sem a cauda muda: **5,0 LU vindos de
silêncio dentro do arquivo** (medido 2026-08-09, reprodutível com o comando de
§4 abaixo). Um `loudnorm` rodado antes do corte normaliza o padding junto e
entrega um efeito 5 dB mais alto do que o alvo pedia.

O mesmo vale menor no `whoosh.wav`: −20,0 como está, −18,5 sem os 46 ms de
lead-in — **1,5 LU**.

### Duas emendas medidas à receita genérica (`remotion-compositor/SKILL.md:236`)

A receita antiga é `afade in 30ms + afade out 200-300ms + loudnorm`. Duas
correções, as duas com número:

| emenda | por quê |
|---|---|
| **o fade-in vira DECLICK** (≤ 5 ms, limitado à guarda antes do onset) | o `afade in 30ms` genérico é **parte do problema**: é ele que explica `shutter` a 7 ms e `scratch` a 17 ms de onset. Reaplicá-lo depois de aparar o lead-in para t=0 desfaria o conserto |
| **o fade-out começa no FIM ACÚSTICO**, e dura só o silêncio disponível depois dele | um `afade out 250ms` cego atenua som de verdade: medido, muda o corpo do `pencil` em **212 ms** e o do `typing` em **56 ms**, e os dois seriam recusados pela guarda de §7.9 — com razão, porque estariam sendo comidos |

### Guarda que recusa

Se o aparo mudar `corpo_ms` em mais de **5 ms**, ou se o `onset` depois ficar
acima de **3 ms**, o arquivo **não é escrito**. O achado registrado vale mais que
um arquivo estragado.

Se o ganho necessário para o alvo estourar o teto de pico (**−1,0 dBFS**), ele é
**limitado** e o motivo entra no sidecar (`ganho_limitado_por`). O arquivo sai
mais baixo que o alvo e o `qc-sfx.py` **acusa** — que é o certo. Medido: `typing`
sai a −27,9 LUFS porque o pico dele não deixa subir 9 dB sem clipar.

---

## 2. `classe` — medida, não declarada

`acento` quando `corpo_ms ≤ perfil.sfx.corpo_acento_max_ms` (400), senão
`textura`. Na biblioteca real o corte separa limpo — 36 a 348 ms de um lado,
1.715 a 2.070 ms do outro, ninguém perto da linha.

A classe decide o fade **e** decide a severidade: acento atrasado é **FALHA**
(`TRANSIENTE-ATRASADO`), textura atrasada é **ACHADO**
(`TRANSIENTE-ATRASADO-TEXTURA`). São duas tags porque quem classifica é o
catálogo da bateria, que só enxerga a string.

---

## 3. Os dois contratos

### `<biblioteca>/_inventario.json` — `benchmark.sfx-inventario/v1`

Escrito pelo `qc-sfx.py` a cada execução. Campos por arquivo: `nome`, `dur_s`,
`onset_ms`, `pico_ms`, `corpo_ms`, `fim_ms`, `atraso_frames`, `classe`, `lufs`,
`pico_dbfs`, `estado`, `tags`, `sidecar`. O `resumo` traz
`medidos · ok · achados · falhas · loudness_fora · sem_procedencia`.

### `<biblioteca>/<nome>.json` — `benchmark.sfx/v1`

```jsonc
{
  "schema": "benchmark.sfx/v1",
  "nome": "whoosh", "classe": "acento",
  "origem": {"tipo": "arquivo|sintetizado|desconhecida",
             "caminho": "_historico/whoosh-d98f010f.wav",
             "sha256": "…", "licenca": null, "fonte": "…", "seed": null},
  "antes":  {"onset_ms": 46.0, "corpo_ms": 102.0, "lufs": -20.0, "pico_dbfs": -3.1},
  "depois": {"onset_ms": 3.0,  "corpo_ms": 102.0, "lufs": -20.0, "pico_dbfs": -4.6},
  "sha256_wav": "…", "ganho_db": -1.5, "corte_s": [0.043, 0.154],
  "reprocessado": true,
  "gerado_em": "…", "gerado_por": "sfx-preparar.py"
}
```

Três regras duras:

1. **`sha256_wav` divergente do `.wav` é FALHA** (`SIDECAR-DIVERGENTE`). É o que
   impede que alguém troque o áudio por baixo do nome — a família exata do
   segmento órfão: quem re-renderizar uma peça antiga recebe outro som sem aviso.
2. **`origem.seed` é obrigatório e não-nulo quando `origem.tipo == "sintetizado"`.**
   O `generate_sfx.py` do ref-A usa `np.random.randn` sobre o RNG **global**, sem
   seed: duas execuções produzem arquivos diferentes com o mesmo nome. Se um dia
   sintetizarmos, é `np.random.default_rng(seed)` com a seed aqui, e
   `qc-sfx.py --verificar` reprova sidecar de sintetizado sem seed.
3. **Sidecar ausente não é erro** (a biblioteca é anterior a esta spec): vira
   `sidecar: null` e o arquivo conta em `sem_procedencia`.

---

## 4. Reproduzir as medições

```bash
S=.claude/skills/edit-video/scripts
S9=tools/remotion-compositor/public/sfx

python3 $S/qc-sfx.py --perfil reels                 # inventário + veredito
python3 $S/sfx-preparar.py --migrar                 # dry-run: só imprime o diff
python3 $S/sfx-preparar.py --migrar --confirmar     # escreve, com _historico/
python3 $S/sfx-preparar.py --selar --confirmar      # sidecar sem reprocessar

# a ordem das operações, em 4 comandos
L() { ffmpeg -nostdin -hide_banner -stream_loop 15 -i "$1" -af ebur128=peak=true \
      -f null - 2>&1 | grep -A6 Summary | grep "  I:" | awk '{print $2}'; }
L $S9/pop.wav                                                   # -22.5
ffmpeg -v error -y -i $S9/pop.wav -af "atrim=end=0.10,asetpts=N/SR/TB" /tmp/p.wav
L /tmp/p.wav                                                    # -17.5 → Δ 5,0 LU
```

⚠️ `--migrar` **sem** `--confirmar` não escreve nada. O `.wav` anterior vai para
`_historico/<nome>-<sha8>.wav` e **nunca** é apagado.

---

## 4b. 🔶 Dois arquivos não vêm no pacote

`whoosh.wav` e `whoosh-soft.wav` (que deriva dele) têm a licença marcada **não
conferida** no `MANIFESTO.ativos` — catálogo de terceiro, e ninguém verificou os
termos. Redistribuir arquivo nessa situação não é decisão de quem empacota, então
eles ficam fora do `git clone` e continuam declarados como ativo, com sha256.
As medições deste documento que os citam **continuam válidas** (foram feitas na
biblioteca completa); o que falta no pacote é o áudio, não o número.
`chaves.py --ativos` os reporta ausentes sem reprovar.

## 5. O que esta camada NÃO faz

Compensar o `onset` residual em runtime dentro do `<Sfx>`
(`from = round(atS×fps) − round(onset_ms×fps/1000)`) exigiria `MotionKit.tsx`,
que a SPEC-15 protege por baseline `md5`. Consequência aceita e declarada: um SFX
de terceiro colocado em `public/sfx/` na mão, sem passar pelo `sfx-preparar.py`,
continua caindo atrasado. O `qc-sfx.py` acusa; o render não conserta sozinho.
É melhor que hoje (onde nem acusa) e é honesto.
