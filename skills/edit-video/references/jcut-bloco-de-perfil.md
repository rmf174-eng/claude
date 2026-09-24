# SPEC-07 → o bloco `jcut` dos perfis de peça — **NÃO ESCRITO, e por quê**

🔴 **Isto é uma FRONTEIRA, não uma pendência de execução.**

A §3.6 da SPEC-07 diz *"o perfil da SPEC-00 ganha um bloco"* e traz a tabela de valores
por tipo de peça, mas a **§5 da SPEC-07 não declara `perfis/*.json`** — e a própria §3.6
registra que *"a SPEC-00 é dona da tabela"*. Executei sem tocar nos perfis. O código foi
escrito para ler o bloco quando ele existir (o `_schema.json` é `additionalProperties:
true`, então nada precisa mudar lá) e, enquanto não existe, o comportamento é:

> **sem bloco `jcut` no perfil e sem flag → modo `off`, plano com lead 0 em toda junção,
> e um aviso no stderr dizendo exatamente isso e como ligar.**

Nenhum valor de teto tem default no código — é valor de formato, e o gate §7.9 da spec
proíbe explicitamente o literal `165` em `jcut.py`. Ligar J-cut com um teto inventado
pelo código seria o "sucesso silencioso" que esta spec passou a tarde inteira fechando.

Operacionalmente, hoje, o J-cut se liga assim:

```bash
jcut.py <dir> --modo medido --lead-max-ms 165
```

---

## Quando a SPEC-00 (ou quem for dono dos perfis) inscrever, é isto

Um `perfil.py patch` por perfil. O fragmento é o **conteúdo do bloco**:

```bash
S=.claude/skills/edit-video/scripts
P=.claude/skills/edit-video/perfis

echo '{"modo":"medido","lead_max_ms":165}' > /tmp/jcut-165.json
echo '{"modo":"medido","lead_max_ms":100}' > /tmp/jcut-100.json
echo '{"modo":"off","lead_max_ms":0}'      > /tmp/jcut-off.json

python3 $S/perfil.py patch --arquivo $P/reels.json     --bloco jcut --de /tmp/jcut-165.json
python3 $S/perfil.py patch --arquivo $P/vsl.json       --bloco jcut --de /tmp/jcut-100.json
python3 $S/perfil.py patch --arquivo $P/longform.json  --bloco jcut --de /tmp/jcut-100.json
python3 $S/perfil.py patch --arquivo $P/screencast.json --bloco jcut --de /tmp/jcut-off.json
```

### A tabela, e o motivo de cada linha

| perfil | `modo` | `lead_max_ms` | por quê |
|---|---|---|---|
| `reels` | medido | **165** | fala rápida; interlock é o ritmo da plataforma |
| `vsl` | medido | **100** | argumentativa: imagem entrando na fala pesa mais em peça longa |
| `longform` | medido | **100** | idem |
| `screencast` | **off** | 0 | a imagem é UI, não rosto. Antecipá-la **desalinha a demonstração da narração** — é o defeito já registrado em `docs/EDICAO-CAPACIDADES.md`, que aqui seria induzido de propósito |

A spec também prevê `corte-de-podcast` (medido/165) e `anuncio` (medido/130). **Esses
dois perfis não existem no catálogo hoje** (`perfis/` tem `_base`, `_ritmos`, `_schema`,
`longform`, `reels`, `screencast`, `vsl`): quando nascerem, herdam essas linhas.

### 📏 O que o teto em ms de fato produz, medido

O teto é resolvido contra o fps da peça, e é aí que ele se separa do
`JCUT_LEAD_FRAMES = 5` fixo do ref-A:

| teto | 24 fps | 25 fps | 30 fps |
|---|---|---|---|
| 165 ms | 3 frames (125,0 ms) | 4 frames (160,0 ms) | **4 frames (133,3 ms)** |
| 100 ms | 2 frames (83,3 ms) | 2 frames (80,0 ms) | 3 frames (100,0 ms) |

`lead_frames = floor(lead_ms × fps / 1000)` — **floor**, para nunca remover mais ar do
que existe. ⚠️ A §3.6 da spec afirma que 165 ms *"a 30 fps e a 24 fps recebem 4 e 4
frames"*: a 24 fps o floor dá **3**, não 4 (`floor(0.165×24) = floor(3.96)`). É erro de
aritmética da spec, não do código — a regra escrita na própria §3.4 é `floor`.

### O que **não** precisa mudar

- **`perfis/_schema.json`** — ele é `additionalProperties: true` de propósito, e o
  próprio texto dele já antecipa blocos de topo novos vindos por `patch`. Além disso, o
  `perfil.py patch` **recusa** escrever em `_schema.json` (valida-o como perfil completo).
  Se alguém quiser documentar o bloco no schema, é edição à mão, e é decisão da SPEC-00.
- **`creators/*/perfil-overrides.json`** — J-cut é decisão de FORMATO da peça, não look de
  creator. Um creator que queira desligar numa produção específica usa
  `jcut-override.json` na pasta da produção, que é por junção e carrega o motivo escrito.

---

## 🔶 Decisão do creator-1 — 2026-08-08, no fecho da onda 3

**Não ligar agora. Testar depois.**

O J-cut está entregue e medido em plano (19 de 22 junções descontínuas recebem lead,
2.100 ms de respiro removidos, maior lead 133,3 ms contra os 166,7 ms que o lead fixo
de 5 frames do ref-A daria), mas os critérios `[verif]` da SPEC-07 sobre material real
— o render dos 29 segmentos da `peca-01` — ainda não rodaram.

Inscrever o bloco `jcut` nos perfis ligaria o J-cut por default em toda produção
resolvida daqui em diante, ativando um caminho ainda não verificado em render. Fica
para depois da passada de verificação (`docs/specs/FILA-DE-VERIFICACAO.md`).

**Enquanto isso, o J-cut liga por flag explícita**, sem tocar em perfil nenhum:

```bash
jcut.py <dir> --modo medido --lead-max-ms 165
```

Quem for inscrever o bloco: use os comandos da seção acima, e rode os `[verif]` da
SPEC-07 antes, não depois.

---

## ✅ LIGADO em 2026-08-09, por decisão do creator-1

> *"pode deixar ligado ou como opcional para o cliente, vamos testando"*

O bloco `jcut` foi inscrito nos quatro perfis do catálogo com os valores medidos
pela SPEC-07. Produção resolvida daqui em diante nasce com J-cut ativo:

| perfil | `modo` | `lead_max_ms` |
|---|---|---|
| `reels` | medido | 165 |
| `vsl` | medido | 100 |
| `longform` | medido | 100 |
| `screencast` | off | 0 |

**Continua opcional em três níveis**, que é o que atende "ou como opcional para o cliente":

1. **Por produção**: `jcut.py <dir> --modo off` ignora o perfil.
2. **Por perfil**: `perfil.py patch --bloco jcut --de '{"modo":"off"}' --forcar`.
3. **Por ausência**: produção sem `perfil.json` cai no `FALLBACK_REELS`, que não tem
   bloco `jcut`. Toda produção antiga remontada continua se comportando byte a byte
   como antes, sem J-cut. Isso não mudou.

⚠️ **Um resíduo medido, que segue aberto.** A passada de verificação achou um
deslocamento de ±2 amostras (±0,042 ms) no lado de saída de 4 das 6 junções
contíguas da `peca-01`. Compensado o lag por correlação, as seis medem
−90,3 dB, trinta dB abaixo do limite do critério, então não é audível e não é
deriva acumulada. Fica registrado porque "vamos testando" quer dizer que o próximo
render em material real deve ser ouvido, não só medido.
