// Estilos de legenda MEDIDOS em VSLs de tráfego pago que estavam no ar em
// 2026-08-01. Não são gosto: cada número saiu de `tipografia.py` sobre o
// arquivo de vídeo. O método é o da skill `style-extract`, e a ficha da
// modelagem (`vsl-rede-ref-E.md`) fica com quem modelou.
//
// Uso:
//   import { vslEstilos } from "./estilos-medidos";
//   <CaptionLayer captions={caps} estilo={vslEstilos.frioAgressivo.estilo}
//                 combinaMs={vslEstilos.frioAgressivo.combinaMs} />
//
// ⚠️ `fontSize` é ESTIMADO: o script mede a altura da CAIXA de texto, não do
// glifo. A conversão usada é fontSize ≈ altura_da_caixa / 1.25 (lineHeight
// típico). Trate como ponto de partida e confirme no primeiro still.

import type { CaptionStyle } from "../CaptionLayer";

export type VslEstilo = {
  /** de onde saiu a medição */
  fonte: string;
  /** temperatura do tráfego que essa peça recebe */
  publico: "frio-total" | "frio" | "morno" | "quente";
  estilo: CaptionStyle;
  /** agrupamento de página que reproduz a cadência medida */
  combinaMs: number;
  /** o que a medição diz sobre esse estilo */
  nota: string;
};

/**
 * ref-G / ref-G — o mais duro dos quatro.
 * Legenda BRANCA CHAPADA: destaque colorido em só 3,1% dos frames, o que é
 * ruído de medição, não design. `highlight: null` é a decisão correta.
 * Usa 41,7% da largura — 1 a 3 palavras por página, nunca frase.
 */
export const frioAgressivo: VslEstilo = {
  fonte: "ref-G var1 (25:31, 12/02/2026) — 27,9 cortes/min",
  publico: "frio-total",
  estilo: {
    fontFamily: "Inter, system-ui, sans-serif", // grotesca neutra
    fontWeight: 700,
    fontSize: 44,
    color: "#FEFEFE",
    highlight: null, // medido: sem palavra ativa
    yPct: 63,
    maxWidth: 450, // 41,7% de 1080
    textShadow: "0 2px 10px rgba(0,0,0,0.9)",
    lineHeight: 1.15,
  },
  combinaMs: 1740, // ~1,74s por página
  nota:
    "Legenda quase invisível de propósito: o protagonista é o ritmo de corte " +
    "(plano médio de 2,2s). Poucas palavras, sem cor, sem competir com o rosto.",
};

/**
 * ref-F — o oposto: a legenda INTEIRA é colorida.
 * Não é branca-com-destaque; é amarelo-dourado #EECD3B em itálico, o tempo todo.
 * Some em blocos inteiros da peça (b-roll de reel de terceiro roda sem legenda).
 */
export const frioColorido: VslEstilo = {
  fonte: "ref-F FCC v2 (37:54, 25/05/2026) — 100% do tráfego pago dela",
  publico: "frio",
  estilo: {
    fontFamily: "Poppins, Nunito, sans-serif", // sans arredondada
    fontWeight: 600,
    fontStyle: "italic", // medido: a legenda dela é itálica
    fontSize: 46,
    color: "#EECD3B", // a legenda toda, não só o destaque
    highlight: null,
    yPct: 59,
    maxWidth: 825, // 76,4% de 1080
    textShadow: "0 0 6px rgba(0,0,0,0.95), 0 3px 10px rgba(0,0,0,0.8)",
    lineHeight: 1.2,
  },
  combinaMs: 2500,
  nota:
    "Presente em 83% dos frames — e os 17% de ausência são intencionais: " +
    "quando entra reel de terceiro em tela cheia, a legenda dela sai. " +
    "Use `off` no CaptionLayer para reproduzir isso.",
};

/**
 * ref-E, home — branca com destaque vermelho na palavra ativa.
 * É o mais próximo do nosso default, e o único dos quatro com highlight de
 * verdade: 42,7% dos frames têm palavra colorida.
 */
export const mornoDestacado: VslEstilo = {
  fonte: "ref-E.com.br home var1 (7:46, 31/07/2026)",
  publico: "morno",
  estilo: {
    fontFamily: "Inter, system-ui, sans-serif",
    fontWeight: 700,
    fontSize: 32,
    color: "#FFFFFF",
    highlight: "#F14418", // medido no núcleo do glifo
    yPct: 56,
    maxWidth: 700, // 64,8% de 1080
    textShadow: "0 3px 12px rgba(0,0,0,0.85)",
    lineHeight: 1.2,
  },
  combinaMs: 1820,
  nota:
    "Destaque em 42,7% dos frames: quase uma palavra colorida por página. " +
    "O vermelho é o mesmo da segunda camada — uma cor de ênfase só na peça.",
};

/**
 * Imersão 7D — peça de evento, público quente.
 * Legenda mais baixa (70%), maior, e com menos destaque (15,6%). A carga
 * gráfica migra para as cartelas full-screen, não para a legenda.
 */
export const quenteEvento: VslEstilo = {
  fonte: "Imersão 7D (6:43, 20/07/2026) — 8,6 cortes/min",
  publico: "quente",
  estilo: {
    fontFamily: "Inter, system-ui, sans-serif",
    fontWeight: 700,
    fontSize: 48,
    color: "#FEFEFE",
    highlight: "#FE5410",
    yPct: 70,
    maxWidth: 680,
    textShadow: "0 3px 12px rgba(0,0,0,0.85)",
    lineHeight: 1.2,
  },
  combinaMs: 2030,
  nota:
    "Plano médio de 7,0s (o mais lento dos quatro) e legenda maior. " +
    "Quem já conhece o vendedor não precisa ser segurado por corte.",
};

export const vslEstilos = {
  frioAgressivo,
  frioColorido,
  mornoDestacado,
  quenteEvento,
} as const;

/**
 * Regra de escolha, derivada da medição cross-peça: os parâmetros escalam com
 * a temperatura do tráfego, não com gosto.
 *
 *   mais frio  → mais corte/min, menos palavra por página, menos cor na legenda
 *   mais quente → plano mais longo, legenda maior, carga gráfica em cartela
 */
export const escolhePorPublico = (
  p: VslEstilo["publico"]
): VslEstilo =>
  ({
    "frio-total": frioAgressivo,
    frio: frioColorido,
    morno: mornoDestacado,
    quente: quenteEvento,
  }[p]);
