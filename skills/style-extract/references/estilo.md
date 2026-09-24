# O schema do estilo, comentado

`_schema.json` é o contrato executável (`benchmark.estilo-edicao/v1`), validado
pelo `agregar.py`. Este arquivo é a leitura humana dele: o que cada campo
significa e **por que ele existe**.

> `jsonschema` **não** é dependência desta skill. O validador é o do `agregar.py`
> (`validar()`), que cobre o subconjunto de JSON Schema que o `_schema.json` usa
> — mesma decisão do `perfil.py` da SPEC-00. Dependência nova por causa de
> validação não paga o custo de portabilidade.

---

## 1. `Param` — o único tipo do estilo

Todo valor é um `Param`. Sem exceção. **Não existe `"cortes_por_min": 16.55`** no
artefato; existe `"cortes_por_min": {Param}`.

```jsonc
{
  "v": 14.7,                       // o valor a aplicar (número, enum, hex, lista, null)
  "agg": "mediana",                // mediana | faixa | moda | uniao | regra
  "n": 4,                          // refs que contribuíram COM MEDIÇÃO VÁLIDA
  "n_total": 5,                    // refs no corpus (n < n_total ⇒ ver `faltou`)
  "disp": {"p25": 13.18, "p75": 20.78, "iqr": 7.60, "cv": 0.459},
  "conf": "baixa",                 // alta | media | baixa
  "fonte": "medido",               // medido | semantico | derivado
  "metodo": "ritmo.py --fps 8",
  "por_ref": {"ref-B-var1": 27.9, "ref-F-var2": 18.4,
              "home-var1": 14.7, "ref-C3": 8.6},
  "faltou": [{"ref": "x", "motivo": "campo ausente na medição"}],
  "qualidade": "ok",               // ok | suspeita
  "nota": null
}
```

**Por que `n`, `cv` e `por_ref` são obrigatórios.** É a lição mais cara e mais
repetida deste repo, e ela está registrada três vezes:
`docs/EDICAO-CAPACIDADES.md:39` (o `edit` do Omni "não existia" — existia),
`:65-67` (duas conclusões erradas seguidas por amostra insuficiente e insumo
capado) e `:168-171` (*"é a terceira vez que o projeto registra a mesma lição:
ampliar a amostra antes de concluir que algo está quebrado"*). Um extrator que
devolve número sem `n` é essa armadilha automatizada em escala industrial.

**Por que `por_ref` é sempre completo.** É o que permite auditar um estilo depois
sem re-medir, e o que torna a agregação **reversível**: se amanhã descobrirmos que
uma referência não pertencia ao corpus, dá para recalcular sem tocar nos vídeos.

## 2. Regra de agregação, por classe

Decidido no contrato. Quem executa não escolhe.

| classe | `agg` | dispersão |
|---|---|---|
| escalar contínuo | **mediana** | `p25`, `p75`, `iqr`, `cv = iqr/|mediana|` |
| escalar-envelope (é um limite, não um alvo) | **faixa** `[p10,p90]`, `v = p90` | a própria faixa |
| categórico / enum | **moda** | `{votos, fracao_moda}` |
| cor | **mediana em CIELab** → hex | `deltaE_mediano_ao_centro` (CIE76) |
| conjunto | **união com frequência** | cada item com `presente_em = k/N` |
| regra em texto | **regra com suporte** | `suporte: k/N` + evidência por ref |

Três decisões que resolvem ambiguidade:

- **Mediana, nunca média.** Com N entre 2 e 6, uma peça fora da curva sequestra a
  média.
- **Cor agrega em Lab.** Média de hex entre `#F14418` e `#EECD3B` dá um marrom que
  não é nenhuma das duas; em Lab a mediana por canal fica na região perceptual do
  conjunto, e o `deltaE_mediano` denuncia conjunto bimodal.
- **Percentis com `np.percentile` método `linear`** (o default), para os números
  serem reproduzíveis — é o que torna os critérios de aceite verificáveis.

**Empate de moda** não está na fórmula de §3.4 e não muda a `conf`; ele vai
escrito na `nota` (`"empate na moda entre A, B (2 voto(s) cada): v é o desempate
alfabético, não um vencedor"`), para o consumidor ver que o vencedor não venceu.

## 3. Confiança — e o que o consumidor faz com ela

A fórmula vive em dados, no bloco `x_conf` do `_schema.json`. Antes de qualquer
limiar: `qualidade == "suspeita"` ⇒ **baixa**, e `n <= 1` ⇒ **baixa**, sempre.

| `conf` | destino — **parte do contrato, não sugestão** |
|---|---|
| **alta** | vira default aplicado: entra em `overlay_perfil` e é escrito direto no plano/EDL |
| **media** | é aplicado, mas o plano tem que **imprimir o número, o `n` e o `cv`** na linha em que aparece |
| **baixa** | **nunca vira default.** Fora do `overlay_perfil`; entra em `sugestoes[]` do plano |

> **Regra dura**: um parâmetro `baixa` jamais aparece num artefato executável
> (EDL, `perfil.json`, `captions.json`, `overlays.json`) sem decisão humana
> explícita registrada no `PLANO-EDICAO.md`.

O desenho vem do `detect_color.py` do ref-A (`helpers/detect_color.py:20-21`):
*"reports a confidence, rather than pretending to be certain. At `low` confidence
the caller should ask."* Lá os sinais que precisam concordar são canais da imagem;
aqui são **as referências**.

## 4. A fronteira pixel × semântico

| grandeza | fonte única permitida |
|---|---|
| posição, tamanho, largura, cadência, % de tempo na tela, cor (hex) | **pixel** (`tipografia.py`) |
| ritmo de corte, duração de plano, tipos de corte | **pixel** (`ritmo.py`/`cortes.py`) |
| loudness, piso, dinâmica | **áudio** (ffmpeg `ebur128` + RMS 100 ms) |
| inventário de recursos, animação, `max_simultaneos`, sync com a fala, trilha, SFX | **`deep-edit.json`** |
| quando cortar, o que destacar, humor, gestão de espaço | **`deep-edit.sistema_composicao` + leitura do modelo** → `regras[]` |

O schema **proíbe** `fonte: "semantico"` nas chaves de posição e cor
(`y_centro_pct`, `cor_base`, `cor_destaque`, `altura_glifo_pct`, `paleta`; o
`altura_glifo_px_1920` é o nome legado do mesmo número — ver SPEC-41).
O motivo está medido: o Gemini reportou legenda a **85%** da altura onde o pixel
mediu **56%**, e destaque `#FFFF00` onde o pixel mediu `#F14418`
(`remotion-compositor/references/sistema-vsl-trafego-pago.md:27-31`).

Consequência prática: **`cor.paleta` sai como não-medido**, mesmo com a paleta do
Gemini disponível. Ela fica registrada na medição
(`semantico.paleta_gemini`) e não vira `Param` de estilo. Campo faltando fica
faltando.

## 5. As proibições que o validador impõe

1. Todo nó folha sob `eixos` / `por_bloco` / `denominador_comum` /
   `variantes.*.overrides` é um `Param` completo. `"cortes_por_min": 14.7` é
   inválido.
2. `Param.n <= n_refs`, `n == len(por_ref)` e `set(por_ref) ⊆ {ids do corpus}`.
3. `Param.conf == "alta"` exige `n >= 3`. Sempre.
4. `Param.fonte == "semantico"` proíbe as chaves de posição e cor.
5. Chaves de formato (`largura`, `altura`, `fps`, `aspecto`, `sr`, `pix_fmt`,
   `crf`) são proibidas em **qualquer** nível, exceto dentro de
   `aplica_a.formato_das_refs`, que é **descritivo**.
6. `estado == "incoerente"` exige `overlay_perfil == {}` **e** `variantes == {}`.
7. `overlay_perfil` só contém `ritmo.*`, `legenda.*`, `audio.loudness` e
   `cor.grade` — o subconjunto que a SPEC-00 §3.2 autoriza a um override — e só a
   partir de `Param` com `conf ∈ {alta, media}`.

**Gravar inválido é bug, não aviso**: `agregar.py` sai 1 sem escrever o arquivo.

## 6. O que o estilo NUNCA carrega

Valor de formato. `largura`, `altura`, `fps`, `aspecto`, `sr`, `pix_fmt`, `crf`
são do **perfil de peça** (SPEC-00), e a regra de ouro de lá vale aqui inteira:
*"Nenhum script pode conter um valor de formato."*

`aplica_a.formato_das_refs` é a exceção nomeada e é **descritiva**: serve para o
consumidor recusar aplicar um estilo de VSL 16:9 num reel 9:16. Ela descreve as
referências; não configura nada.

## 7. `estado` — e o que o consumidor faz com cada um

`coerencia.score` = fração dos **12 parâmetros-núcleo** (`x_nucleo` no
`_schema.json`) que atingem `conf >= media`.

| score | `estado` | o extrator |
|---|---|---|
| ≥ 0,60 | `pronto` | emite o estilo completo, com `overlay_perfil` preenchido |
| 0,30–0,60 | `parcial` | emite o estilo, `overlay_perfil` só com o que fechou, e `avisos[]` nomeia o resto |
| < 0,30 | `incoerente` | **`overlay_perfil` vazio, `variantes` vazias** — o artefato vira diagnóstico |

**A SPEC-24 recusa aplicar estilo com `estado: "incoerente"`**, e ao aplicar um
`parcial` usa só o que está em `overlay_perfil`.

N referências podem simplesmente **não compartilhar estilo**, e esse é o resultado
certo — não um erro a mascarar numa média. Foi o que a análise manual das 3 peças
da rede do ref-E achou: cenário, figurino, enquadramento, paleta, densidade de
b-roll e ritmo mudam por completo, e *"a única constante visual é a legenda
queimada palavra a palavra"* (`intelligence/edicao/vsl-rede-ref-E.md:13-33`).
É isso que `denominador_comum` guarda.

## 8. `benchmark.medicao-ref/v1` — o insumo

Uma referência medida, em `<corpus>/medicoes/<id>.json`. É o **cache**: remedir
custa Gemini, agregar não custa nada.

Campos que o agregador lê:
`medido.{montagem,legenda,grafismo,som,plano,fala}` · `por_bloco.<rotulo>.*` ·
`declarado.{objetivo,temperatura,perfil_sugerido}` · `amostragem.*` ·
`semantico.regras_observadas` · `fonte.{caminho,url,dur_s,aspecto}`.

`edit-recipe.json` (`benchmark.edit-recipe/v1`) **não** vira entrada do agregador,
e isso é decisão: as duas receitas do repo têm schemas diferentes na prática,
porque a convenção da skill `model-edit` é *"campo ausente = não medido"*. Agregar
sobre schema variável esconde ausência dentro de mediana. Uma receita antiga pode
ser convertida **à mão** numa medição, com `n` e `qualidade` refletindo o que de
fato foi medido — nunca automaticamente.
