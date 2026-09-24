/**
 * ⚠️ ESTE CABEÇALHO JÁ DECLAROU "obra derivada", E ERA FALSO.
 * A medição de 2026-08-09 contou a coincidência literal com a ferramenta de
 * referência que inspirou o módulo: DUAS linhas, e as duas são a chamada de API
 * do `@remotion/layout-utils` — que só tem uma forma de ser escrita. Isso não é
 * obra derivada, é a mesma biblioteca sendo usada. O mecanismo (medir texto de
 * verdade em vez de estimar por contagem de caractere) foi lido lá; a
 * implementação é nossa.
 */

/**
 * medida.ts — medir texto DE VERDADE, parametrizado (SPEC-13 §3.2).
 *
 * ⚠️ ESTE MÓDULO SÓ RODA NO BROWSER. O `measureText` do `@remotion/layout-utils`
 * lança `'measureText() can only be called in a browser.'` quando
 * `typeof document === 'undefined'`. Fora do Chrome do Remotion (Node, Python,
 * teste) o medidor equivalente é `medidorDeTabela` de `./agrupar`, que soma
 * advance widths do TTF — e é por isso que o algoritmo de agrupamento recebe o
 * medidor por parâmetro em vez de importar este arquivo.
 *
 * O `hlWidth` do ref-A (`Main.tsx:438-441`) NÃO é portável para cá: ele fecha a
 * família na constante de módulo (Poppins) e o `letterSpacing: '-1px'` no corpo
 * da função. O nosso Anton usa `letterSpacing: +1` (`TitleCard.tsx:110`) e o
 * Playfair é ITÁLICO (`:139`) — duas coisas que a função deles não sabe dizer.
 * Por isso tudo entra por `Medida`.
 *
 * TRÊS ARMADILHAS DO `measureText` QUE A ASSINATURA JÁ RESOLVE
 * (conferidas no fonte do pacote, `dist/cjs/layouts/measure-text.js`):
 *
 *   1. `fontStyle` NÃO É PARÂMETRO. O tipo aceito é
 *      `{text, fontFamily, fontSize, fontWeight, letterSpacing,
 *        fontVariantNumeric, textTransform, additionalStyles,
 *        validateFontIsLoaded}` e nada mais. Itálico vai por
 *      `additionalStyles: {fontStyle: "italic"}`, que o pacote aplica com
 *      `node.style[key]` e — importante — INCLUI NA CHAVE DO CACHE. Medir
 *      Playfair itálico como roman devolve largura de outra fonte, calada.
 *   2. `letterSpacing` é STRING COM UNIDADE (`"1px"`), não número. Passar número
 *      faz o `node.style.letterSpacing` receber `1` e o browser ignorar.
 *   3. `caixa: "uppercase"` vai por `textTransform`, nunca por `.toUpperCase()`
 *      no texto — assim o texto ORIGINAL continua disponível para a `key` do
 *      React e para o type-on do `HookTitle`.
 *
 * E a quarta, que a assinatura não resolve sozinha e por isso vira regra:
 * NUNCA CHAME NO ESCOPO DE MÓDULO. O `wordCache` do pacote guarda a primeira
 * medição PARA SEMPRE. Se ela acontecer antes de a fonte carregar, a peça
 * inteira é diagramada com métrica de Arial e nada acusa. Medir dentro do
 * componente (depois do `delayRender` que o `@remotion/google-fonts` instala) e
 * sempre com `validateFontIsLoaded: true`, que faz o pacote comparar com a
 * fonte de fallback e LANÇAR em vez de mentir.
 */
import { measureText } from "@remotion/layout-utils";
import { melhorQuebra } from "./agrupar";

export type Medida = {
  familia: string;
  peso?: number;
  italico?: boolean;
  /** px */
  tamanho: number;
  /** px por caractere, pode ser negativo */
  entreletras?: number;
  caixa?: "uppercase" | null;
};

/**
 * Um medidor de largura. O algoritmo de agrupamento recebe UM DESTES por
 * parâmetro; quem constrói decide se é o Chrome (`larguraDe`, aqui) ou a tabela
 * de advance widths (`medidorDeTabela`, em `./agrupar`).
 */
export type Medidor = (texto: string, m: Medida) => number;

/** Largura em px de `texto` com `m`. SÓ FUNCIONA DENTRO DO BROWSER. */
export const larguraDe: Medidor = (texto, m) =>
  measureText({
    text: texto,
    fontFamily: m.familia,
    fontSize: m.tamanho,
    fontWeight: m.peso,
    // string com unidade, nunca número (armadilha 2)
    letterSpacing: m.entreletras ? `${m.entreletras}px` : undefined,
    textTransform: m.caixa ?? undefined,
    // itálico não tem parâmetro próprio (armadilha 1)
    additionalStyles: m.italico ? { fontStyle: "italic" } : undefined,
    // sem isto, fonte não carregada vira medição silenciosamente errada
    validateFontIsLoaded: true,
  }).width;

/**
 * Maior `fontSize` ≤ `teto` (e ≥ `piso`) em que `texto` cabe em `orcamento` px,
 * em UMA linha.
 *
 * UM passe de refinamento, e o motivo é o que o ref-A documenta em
 * `Main.tsx:463-465`: a largura escala com o tamanho, mas o `letterSpacing` (N px
 * por caractere) NÃO — a primeira estimativa erra alguns px em linha longa. Um
 * passe corrige; iterar não compra nada.
 */
export const ajustarUmaLinha = (
  texto: string,
  m: Medida,
  orcamento: number,
  teto: number,
  piso: number,
  medir: Medidor = larguraDe
): number => {
  if (!texto || orcamento <= 0) return teto;
  const base = 100;
  const w0 = medir(texto, { ...m, tamanho: base });
  if (!(w0 > 0)) return teto;
  const estimativa = Math.max(piso, Math.floor((orcamento / w0) * base));
  const w1 = medir(texto, { ...m, tamanho: estimativa });
  if (!(w1 > 0)) return Math.min(estimativa, teto);
  const refinado = Math.floor((orcamento / w1) * estimativa);
  return Math.max(piso, Math.min(teto, refinado));
};

/**
 * Reparte `texto` em duas linhas equilibradas por largura, com penalidade de
 * órfã. É o `splitTwo` deles (`SimpleCaptions.tsx:130-144`) com a penalidade e a
 * lista de órfãs parametrizadas.
 *
 * ⚠️ NÃO é aplicado ao `HookTitle` (SPEC-13 §3.7): equilibrar largura entre uma
 * grotesca caps e uma serif itálica destrói o degrau assimétrico que dá o ar de
 * assinatura (`TitleCard.tsx:46-49`), e as duas linhas do gancho são
 * semanticamente diferentes — afirmação + assinatura, não uma frase quebrada.
 */
export const duasLinhas = (
  texto: string,
  mA: Medida,
  mB: Medida,
  penalidadeOrfa: number,
  orfas: string[],
  medir: Medidor = larguraDe
): [string, string] => {
  const palavras = texto.split(/\s+/).filter(Boolean);
  if (palavras.length < 2) return [texto, ""];
  const corte = melhorQuebra(
    palavras,
    (p) => medir(p.join(" "), mA),
    (p) => medir(p.join(" "), mB),
    penalidadeOrfa,
    orfas
  );
  return [palavras.slice(0, corte).join(" "), palavras.slice(corte).join(" ")];
};
