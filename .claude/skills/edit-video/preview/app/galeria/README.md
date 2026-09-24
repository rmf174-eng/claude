# Galeria de estilos — o módulo

Tela do **portão de estilo**, entre a Fase 1 e a Fase 2 (SPEC-19). Lê **um**
arquivo (`benchmark.galeria-estilos/v1`) e devolve a escolha como
`benchmark.edit-estilo/v3`.

Produção nova começa sem direção implícita. Antes dos ajustes de look, a tela
exige uma escolha explícita entre **Essencial**, **Com animações** e **Me
surpreenda**. A escolha viaja em `direcao_edicao` e alimenta o
`plano-visual.json` da Fase 2. V1 e v2 continuam legíveis para histórico, mas não
liberam uma produção nova sem a decisão v3.

```
galeria.html          página autônoma
galeria.js            módulo ES: export function montarGaleria(host, opcoes)
galeria.css           escopado em .galeria-*, zero seletor de elemento global
interruptores.json    benchmark.galeria-interruptores/v1 — dado do APP, não da sessão
```

## Embutir (a SPEC-18 aplica; a SPEC-19 não)

```js
import { montarGaleria } from './galeria/galeria.js';
const g = montarGaleria(document.getElementById('stage'), { base: `/${token}` });
// g.destruir() ao trocar de aba
```

`opcoes`: `base` (prefixo `/<token>`), `galeria` (URL do JSON), `estado`,
`salvar`, `fixture`.

## 🔴 Onde a tela busca o `galeria.json` — e por que não é o que a spec dizia

A §3.4 da spec previa **um** fetch relativo para
`../../media/.preview/estilos/galeria.json`. **Medido em 2026-08-08 contra o
servidor da SPEC-17 já entregue: não funciona.** A rota `/media/` recusa tudo o
que está sob `.preview/`:

```python
# preview/servidor.py:872-874
if dir_preview(raiz) in p.parents:
    self._json({"erro": "fora da raiz"}, 403, so_cabecalho=so_cabecalho)
    return
```

Medição, com controle:

| requisição | resposta |
|---|---|
| `GET /<token>/media/.preview/estilos/galeria.json` | **403** `{"erro":"fora da raiz"}` |
| `GET /<token>/media/.preview/estilos/peca/<slug>.png` | **403** |
| `GET /<token>/media/PLANO-EDICAO.md` (controle, fora do `.preview/`) | **200** |
| `GET /<token>/app/galeria/interruptores.json` | **200** |

Por isso o default é `./galeria.json` — o vizinho — e existe um modo que monta
esse vizinho:

```bash
previews-peca.py <dir-producao> --pacote /caminho/do/pacote
servidor.py servir --dir <dir-producao> --app /caminho/do/pacote
# abre em  <url>app/galeria/galeria.html
```

O pacote é **descartável** e contém a tela + o `galeria.json` + as mídias
(hardlink). Os artefatos canônicos continuam em `<dir-producao>/.preview/estilos/`,
como a §4.1 manda.

Para restaurar o desenho original da §3.4 bastaria **uma** linha em
`servidor.py` — abrir uma exceção nomeada para `.preview/estilos/` na rota
`/media/`. Esse arquivo é da **SPEC-17** e está fora da §5 desta spec: não foi
tocado.

## Sem servidor nenhum

```bash
previews-peca.py --fixture /tmp/galeria-fixture
cd /tmp/galeria-fixture && python3 -m http.server 8765
# http://127.0.0.1:8765/galeria.html?fixture=1
```

O modo fixture desliga o POST e mostra o payload numa caixa de texto. É como a
tela é testada antes de o servidor existir.

## As regras que a tela honra

| regra | de onde vem |
|---|---|
| o portão **substitui o palco** — a escolha não é pulável | `ref-A/assets/preview/app.js:28-32` |
| acento **antes** dos estilos de texto ("é com ele que eles pintam") | `ref-A/SKILL.md:180-181` |
| cor que ninguém pinta **não é instrução** | `ref-A/SKILL.md:183-186` |
| caixa desmarcada é um **NÃO explícito** (vai no payload como `false`) | `ref-A/helpers/watch_edits.py:93-95` |
| cartão-fantasma "mais estilos em breve" | `app.js:1191` |
| rótulo do botão muda com `rerender` | `app.js:1162-1164` |
| sem glow, ícones SVG em vez de emoji | `app.js:14-33`, `:50-58` |

E as três que são **nossas**, e que o desenho deles não alcança:

1. **o preview é o componente renderizado**, não uma imitação em DOM (eles
   admitem o problema em `app.js:182-188`);
2. **`acento` mora no catálogo**, apontando o parâmetro — em vez da lista
   espelhada `ACCENT_USERS` (`app.js:1051`);
3. **grupo vazio aparece** com o fantasma em vez de fazer o portão sumir
   (`ref-A/SKILL.md:210-212` manda pular o portão).

## Acabamento e som

- **Essencial**: cortes e legenda, sem eventos gráficos e sem SFX.
- **Com animações**: o agente planeja os movimentos por beat e registra a
  decisão sonora de cada evento.
- **Me surpreenda**: delegação criativa explícita. A direção resolvida continua
  registrada no plano, não fica implícita no chat.

Nem toda animação precisa de som. Toda animação precisa dizer se usa SFX, se o
silêncio é intencional, ou se som não se aplica. O gate de entrega rejeita asset
ausente e rejeita captions como única prova de uma direção Animada ou Surpresa.
