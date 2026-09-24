# Contrato de cor — quem decide o quê, e onde a conversão acontece

> **schema**: `benchmark.cor/v1.1` — o que `detect-cor.py:65` grava hoje.
> A `v1` (`benchmark.cor/v1`) continua sendo lida: o `1.1` acrescentou campos e
> não removeu nenhum, então consumidor de `v1` lê um arquivo `v1.1` sem mudar
> uma linha. Quem escreve consumidor NOVO implementa contra `v1.1`.
>
> 🔴 Este bloco existe porque a versão viveu só no código até 2026-08-10: a
> docstring do `detectar()` dizia `v1`, a constante dizia `v1.1`, e este arquivo
> não continha a string. Achado A23 da auditoria. O `doc-check.py --contratos`
> passou a conferir isto por máquina — toda `benchmark.*/vN` declarada em código
> tem que existir no `contrato-*.md` da família.


> Origem: **SPEC-25** (a costura), sobre **SPEC-11** (o detector) e **SPEC-00** (o
> perfil de peça). Este arquivo é o que se lê quando a dúvida voltar — e ela volta,
> porque três specs escrevem no mesmo eixo e cada uma está certa isoladamente.
>
> Implementação: `scripts/detect-cor.py` · `scripts/perfil.py :: vf_montagem()` ·
> `scripts/montar.sh` · `scripts/qc-cor.py`.
> Teste: `scripts/tests/test-cor-extracao.sh`.

---

## 0. A frase

> **Da fronteira do primeiro `segs/segNNN.mp4` até o entregável existe UM espaço de
> cor: Rec.709. O bruto é o único arquivo HDR da produção.**

Não é que o rótulo passe a estar certo — é que **não há mais dois candidatos a
rótulo**. Enquanto a conversão era um passe à parte sobre o montado, o segmento e o
montado ficavam HLG e todo re-encode a jusante herdava HLG; foi assim que seis
entregáveis saíram da casa dizendo "eu sou HLG em BT.2020" carregando pixels já
convertidos. Com o segmento já em `bt709`, a **herança joga a favor**: grade,
composição de overlay em qualquer ordem de entrada e remux saem certos **sem flag
nenhuma**.

---

## 1. A tabela de responsabilidade

| responsabilidade | quem | artefato | regra |
|---|---|---|---|
| **decidir o que a fonte é** e qual cadeia se aplica | `detect-cor.py` | `<dir>/cor.json` | nunca lê `edl.json` para decidir **formato**; nunca escreve `perfil.json` |
| **produzir o fragmento de conversão** (só filtros de cor, sem `setparams`, sem geometria) | `detect-cor.py` | `cor.json.fontes[src].fragmento_vf` | string ou `""`; caminho da `.cube` **relativo à raiz que `detect_cor.raiz_repo()` devolve** |
| **decidir o formato** (crop, scale, sar, fps, unsharp, tags) | `perfil.py :: vf_montagem()` | a string `vf` | não decide cor |
| **costurar o fragmento no `vf` do segmento** | `montar.sh` | o `-vf` do ffmpeg do segmento | ver §3 — **é o único lugar do repo que edita uma string `vf` produzida por outro** |
| **gravar a tag** | o `setparams` que o `perfil.py` põe no fim do `vf` | o próprio segmento | **um só lugar**; nunca por `-color_primaries`/`-color_trc` |
| **executar** | `montar.sh` | `segs/segNNN.mp4` | não monta filtro de formato, não passa flag de cor |
| **auditar** | `qc-cor.py` | stdout + exit | lê `cor.json.aplicada_em` para saber o estágio de cada arquivo |

Cada montagem também publica `cor-decisao.json`, preso ao fingerprint atual da
EDL. Ele registra se o caminho usado foi `cor-json`, `cor-como` ou `sem-cor`.
Assim, um escape explícito continua auditável depois que o plano temporário da
montagem é removido.

**Regra de desempate:** a SPEC-11 responde *"o que converter"*; a SPEC-00 responde
*"onde e junto com o quê"*. Se o `cor.json` e o que está no disco divergirem, quem
vale é o disco — e é por isso que o `qc-cor.py` acusa `pixel × declaração em
contradição` em vez de acreditar no arquivo.

---

## 2. 🔴 A fronteira que a execução da SPEC-25 encontrou, e a decisão

A §3.2 da SPEC-25 diz: *"a costura mora no `plano-render.py`"*, e a §3.5 manda
editá-lo. **`plano-render.py` não existe.** A SPEC-00 já havia entregue a mesma
função com outro nome — `perfil.py :: vf_montagem()` — e a §5 da SPEC-25 declara
`perfil.py` como **não tocado** (*"usamos o `patch`, não editamos o script"*).

Criar `plano-render.py` seria um **segundo dono da matemática de formato**, que é
exatamente o que a SPEC-00 existe para impedir. Editar `perfil.py` fura a §5.

**A costura ficou no `montar.sh`, e o preço está medido:** ele passa a ser o
**segundo autor** da string `vf`. Isso é uma dívida real, e não é escondida — é por
isso que ele **confere** o que recebe antes de mexer (§3) e **aborta** em vez de
adivinhar.

**Quando alguém for consolidar isto**, o lugar certo é `vf_montagem()` receber o
fragmento por parâmetro e devolver a string inteira. Aí a tabela do §1 fica com um
autor só e as duas guardas do §3 viram asserções internas.

---

## 3. A ordem do filtergraph — e por que ela não é preferência

O `perfil.py vf` devolve:

```
crop=…  scale=…  [unsharp=…]  setsar=1  fps=…  setparams=…
```

O `montar.sh` insere, **imediatamente antes do `setparams`**:

```
format=yuv420p , <fragmento_vf da fonte>
```

Resultado (`peca-01`, perfil `reels`):

```
scale=1080:1920,setsar=1,fps=30,format=yuv420p,lut3d=/abs/…/hlg2sdr.cube,setparams=…bt709
```

### As três travas, com o número de cada uma

Medidas em 2026-08-09 no `seg000` da `peca-01`
(`input/take-inicio.MOV`, HLG, `-ss 1.66 -t 4.13`), luminância média do frame:

| o que se mexe | efeito na luminância média | por quê |
|---|---|---|
| tirar `format=yuv420p` antes da conversão | **+1,8%** | a LUT recebe o frame em 10 bits |
| pôr a conversão **antes** do `scale` | **+1,5%** | o `scale` opera sobre frame ainda tagueado BT.2020/HLG |
| pôr a conversão **depois** do `setparams` | **+0,42%** (\|d\| médio 1,62/255, máx 35) | o yuv→rgb que o ffmpeg insere sozinho na frente do `lut3d` usa a matriz que o `setparams` acabou de escrever |
| aplicar a LUT **duas vezes** | **−23,7%** | (é o controle negativo, não uma variante) |

E a prova de que a costura está certa: o `seg000` produzido pelo `montar.sh` é
**bit a bit idêntico** (`md5` do rawvideo rgb24) à cadeia calibrada montada à mão
com o `setparams` no fim. `+1,8%`, `+1,5%` e `+0,42%` são md5 diferentes.

### As duas guardas do `montar.sh`

| situação | o que acontece |
|---|---|
| o `vf` do perfil **não termina** em `setparams=` e há fragmento | **aborta**, imprimindo o `vf` recebido. Colar no fim custaria os 0,42% em silêncio |
| o `vf` contém `unsharp` **antes** do ponto de inserção e há fragmento | **aborta**. Medido: unsharp antes da conversão dá **−1,53%** contra unsharp depois (\|d\| médio 2,1/255). Escape consciente: `--permitir-unsharp-antes-da-cor` |

⚠️ O caso do `unsharp` hoje tem **zero ocorrências** neste repo: só `vsl` e
`screencast` têm `unsharp`, e as fontes das duas já são SDR (fragmento vazio). Ele é
alcançável por uma fonte HLG num perfil com unsharp, e o `unsharp` do
`vf_montagem()` só aparece quando há **ampliação real** — a fixture do teste usa uma
fonte HLG 540×960 num alvo 1080×1920.

---

## 4. Quando a conversão **não** entra na extração

`montar.sh` **não converte** — e diz o motivo em voz alta — em cinco casos:

| caso | o que sai no `cor.json` | por quê |
|---|---|---|
| `perfil.cor.aplicar_em: "nunca"` | `aplicada_em: null` | a peça é entregue no espaço da fonte |
| `perfil.cor.aplicar_em: "passe"` | `aplicada_em: "passe"` | a conversão é um passe separado sobre o montado (o comportamento da SPEC-11), e é o caminho para reprocessar um montado que já existe sem remontar |
| `--sem-cor` | `aplicada_em: null` | bisseção |
| `perfil.cor.aplicar_tags_por != "setparams"` | `aplicada_em: null` | 🔒 **é o que congela o FALLBACK.** Com `opcoes-de-saida` a tag iria por flags que este build ignora: pixels Rec.709 com rótulo da fonte. Produção **sem `perfil.json` remonta byte a byte igual** porque aqui ela não converte |
| sem `cor.json` | o montador executa `detect-cor.py resolver` antes do primeiro segmento | produção nova nunca segue sem contrato; baixa confiança, divergência ou perfil não calibrado abortam. Só `--sem-cor`/`--cor-como` escapam de forma explícita |
| `cor.json` anterior à SPEC-25 (sem `fragmento_vf`) | `aplicada_em` intocado | compatibilidade legada: não converte e pede nova resolução de forma explícita |

🔴 **Em qualquer um desses casos, se alguma fonte for HDR e o perfil escrever
`color_trc=bt709`, o `montar.sh` grita**: os segmentos vão sair com pixels da fonte e
rótulo de saída, que é literalmente o defeito de 2026-08-06 em que 13 arquivos deste
repo ainda estão. Custa um `ffprobe` por fonte e é a diferença entre um defeito que
nasce em silêncio e um que nasce com o nome do arquivo na tela.

---

## 5. O portão: `calibrado: false` e confiança baixa **param a montagem**

A SPEC-11 deixou o portão duplo como exit code do detector. Aqui ele governa a
montagem, que é onde a decisão vira pixel.

| situação da fonte | `montar.sh` |
|---|---|
| `calibrado: true` e `confianca: alta` | costura e segue |
| `confianca` ≠ alta | **aborta**, com a linha do `detect-cor.py candidatos` |
| `calibrado: false` (PQ, Apple Log) | **aborta**, com a `acao_humana` do catálogo |
| `src` da EDL sem entrada em `cor.json.fontes` | **aborta** — a EDL mudou depois do `resolver`, e montar assim converteria um segmento pela cadeia de outro arquivo |
| qualquer `src` da EDL fora de `cor.entrada_esperada` | **aborta**: a expectativa vale para todas as fontes usadas, não apenas para a principal |
| expectativa persistida/hash ≠ `perfil.json` atual | **aborta**: o perfil mudou depois do `resolver`; reresolva antes de montar |

O detector grava `perfil_esperado`, seu `perfil_esperado_sha256` canônico e o
resultado de cada fonte em `expectativa_cor.por_fonte`. O `montar.sh` confere o
valor, o hash e todas as fontes novamente. Esse portão é global e acontece antes de
`--sem-cor`, `aplicar_em: nunca`, `aplicar_em: passe` e da guarda de tags: esses
modos mudam **onde** a cor é tratada, não quais entradas a peça aceita. O único
override é `--cor-como`, que fica registrado como decisão do operador.
Em `cor.json` legado sem valor/hash, o montador reavalia os perfis SDR/HLG salvos
em `fontes` contra a expectativa atual; assim um upgrade antigo também não ganha
um falso verde.

O abort acontece **antes do primeiro `ffmpeg`**: zero segmento renderizado, medido.

A saída **não** é somar uma curva de manual (hable/reinhard/mobius). A cadeia
derivada do standard já foi percorrida aqui: −21% de faixa de contraste no rosto,
reprovada; a segunda tentativa saiu +38% mais clara. A saída é **medir o avconvert**
(receita em `gen-hlg2sdr-lut.py:32-36`) e acrescentar a entrada ao catálogo.

Escape consciente, para "eu sei o que é este arquivo e o detector não":
`montar.sh --cor-como <entrada-do-catalogo>`, que grava
`origem: "forcado_por_operador"` no plano e imprime aviso. Ele **não** dispensa o
`calibrado` — não convertemos o que não medimos, nem sob ordem.

---

## 6. Cache: `cor_sha` no sidecar

`segs/segNNN.json` ganha `cor_sha` = `sha256(fragmento_vf relativo + bytes de cada
.cube referenciada)`, truncado em 16 hex.

**Os bytes, não o nome** — `gen-hlg2sdr-lut.py` regrava `luts/hlg2sdr.cube` **no
lugar**. Sem os bytes no sha, trocar a curva deixaria 29 segmentos da curva antiga no
disco com sidecar válido e todos os QCs verdes: é a **quinta porta** da família do
segmento órfão, que já custou 6,25 s de vídeo errado nos criativos do creator-3.

**Sidecar sem `cor_sha` = cor desconhecida → refaz.** Custa CPU; a alternativa custa
entrega errada.

---

## 7. `v1-sdr.mp4`

Com `aplicada_em: "extracao"`, o `v1-montado.mp4` **já é** o que se chamava
`v1-sdr.mp4`. O nome deixa de ser **produzido**; os arquivos que existem no disco
continuam válidos e o `qc-cor.py` continua sabendo lê-los.

🔴 **O modo de falha novo que isso cria:** todo script de produção que hoje converte
(`peca-01/cor.py:23,47`, os dois `montar-tudo.sh`) passa a rodar sobre um
montado **já convertido**. Assinatura medida: **−23,7%** de luminância. Três defesas,
e as três são exigidas: o detector do `qc-cor.py` §5, o campo `cor.aplicada_em` que
esses scripts podem ler, e o controle negativo no `test-cor-extracao.sh`.

---

## 8. O detector de LUT dupla — e a régua da spec que **não se sustentou**

A SPEC-25 §3.10 pedia: acusar quando um alvo pós-conversão ficasse **mais de 15%
abaixo** da luminância da referência avconvert, *"calibrado no número medido de
−23,7%, com folga de 1,6×"*.

Medido em 2026-08-09 na `peca-01`, região rodapé, contra a referência
avconvert do próprio bruto:

| arquivo | lum vs referência | o que é |
|---|---|---|
| `v1-sdr.mp4` | **+0,6%** | convertido, **sem** look |
| `v1-montado.mp4` | +34,8% | ainda HLG |
| `v1-graded.mp4` | **−20,6%** | convertido, **com** o preset da creator-2 |
| `v-final.mp4` | −20,5% | idem, com a camada gráfica |

**O preset do creator escurece −20,6% de forma legítima, e a LUT dupla assina
−23,7%. As duas populações se sobrepõem.** O limiar de −15% reprovaria
`v1-graded.mp4` e `v-final.mp4` — dois arquivos aprovados e publicados. Um QC que
acusa a peça entregue é pior que um que não acusa nada, porque ensina a ignorar o
vermelho.

**O que entrou no lugar:** o detector roda **só nos alvos sem look** (`v1-montado*`,
`v1-sdr*`). Neles o esperado é ≈0% (medido +0,6%) e a LUT dupla os leva a ≈−23%
(0,6% × 0,763). Limiar −15%: 1,5× de folga abaixo da assinatura, 25× acima do ruído
do caso bom. Confirmado com defeito plantado: `v1-sdr-dupla.mp4` mediu **−24,6%** e
foi acusado; `v1-montado` e `v1-sdr` corretos mediram **−1,9%** e passaram.

Nos arquivos com look o número é impresso como informação, com o motivo — em vez de
virar um vermelho que ninguém pode consertar.

---

## 9. `_schema.json`: por que `cor.aplicar_em` **não** entrou lá

A §5 da SPEC-25 pedia `_schema.json (patch: enum de cor.aplicar_em)`. Medido:

1. `perfil.py patch --arquivo _schema.json` **recusa** (exit 1): o `patch` valida o
   alvo como perfil COMPLETO e o schema não tem `contrato`, `nome`, `video`,
   `audio`, `ritmo`. É a terceira spec a bater nisso.
2. `properties.cor.additionalProperties` já é **`true`**, então `aplicar_em` valida
   sem nenhuma mudança — e os quatro perfis passaram no `validar` do próprio
   `patch`.
3. O enum no schema **não teria dentes onde importa**: medido, um perfil com
   `cor.aplicar_em: "bananinha"` passa em `perfil.py validar` com **exit 0** (194
   nós conferidos), porque `additionalProperties: true` não olha o valor.

**Decisão: o schema fica intocado e os dentes ficam no consumidor.** O `montar.sh`
recusa qualquer valor fora de `{extracao, passe, nunca}` com exit 1 e a lista dos
válidos — antes de renderizar. É onde o campo vira pixel, e é o único ponto por onde
todo perfil passa.

---

## 10. Os quatro perfis

`reels`, `vsl`, `longform` e `screencast` receberam `cor.aplicar_em: "extracao"` por
`perfil.py patch --bloco cor` (aditivo, idempotente — rodar duas vezes não muda
nada).

`quadrado.json` **não** foi patchado (a §5 nomeia quatro) e não precisa: a ausência
do campo resolve para `"extracao"`, que é o mesmo valor. O FALLBACK também resolve
para `"extracao"` e cai na trava do §4 (`aplicar_tags_por: "opcoes-de-saida"`) — que
é como remontagem antiga continua byte a byte igual.
