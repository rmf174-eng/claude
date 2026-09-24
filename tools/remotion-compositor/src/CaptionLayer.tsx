import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { createTikTokStyleCaptions, TikTokPage } from "@remotion/captions";
import type { Caption, TikTokToken } from "@remotion/captions";
import { agrupar, type Agrupamento, type Pagina } from "./texto/agrupar";
import { larguraDe } from "./texto/medida";

/**
 * CaptionLayer — legenda de fala PARAMETRIZÁVEL (estilo por creator).
 *
 * Mesmo motor anti-piscada do `Captions.tsx` (ponte entre páginas, fade só em
 * pausa real, fade-in só pós-pausa, pop discreto) — a diferença é que aqui o
 * ESTILO é prop, não constante de módulo. Nasceu da modelagem do
 * ref-D, cujo estilo de legenda é o OPOSTO do nosso default:
 *
 *   nosso default (creator-2/creator-1) : Montserrat 700, 58px, highlight rosé na palavra ativa
 *   ref-D (medido)   : grotesca neutra, 46px, BRANCA CHAPADA (highlight: null),
 *                                2–4 palavras por página, centro em ~79% da altura
 *
 * `highlight: null` desliga a palavra ativa — é o que faz a legenda "sumir" e
 * deixar o ritmo de corte ser o protagonista.
 */

export type CaptionStyle = {
  fontFamily: string;
  fontWeight?: number;
  fontStyle?: "normal" | "italic";
  fontSize: number;
  color?: string;
  /** cor da palavra ativa; `null` = sem highlight (página toda na mesma cor) */
  highlight?: string | null;
  /** centro vertical da legenda em % da altura (referência: 79) */
  yPct?: number;
  maxWidth?: number;
  textShadow?: string;
  letterSpacing?: number;
  lineHeight?: number;
  /**
   * COMO a página se organiza no quadro. `linha` é o default e é exatamente o
   * comportamento de sempre — nenhuma produção existente muda de pixel por causa
   * deste campo.
   *
   *   linha      todas as linhas da página no ar juntas (o de sempre)
   *   empilhado  cada linha entra quando o primeiro token dela começa, e as
   *              anteriores ficam. O bloco não pula, porque as que ainda não
   *              entraram já ocupam o espaço com opacidade 0
   *   disperso   cada token ganha um deslocamento e uma rotação próprios,
   *              determinísticos pelo tempo de início — nunca `Math.random()`,
   *              que faria o mesmo frame sair diferente a cada render
   */
  layout?: "linha" | "empilhado" | "disperso";
};

/** Ruído determinístico em [-1, 1] a partir de um inteiro. Determinístico é
 *  requisito, não preferência: o Remotion renderiza frames em paralelo e em
 *  processos diferentes, então `Math.random()` daria um layout por frame. */
function jitter(semente: number, eixo: number): number {
  const x = Math.sin(semente * 12.9898 + eixo * 78.233) * 43758.5453;
  return (x - Math.floor(x)) * 2 - 1;
}

const CaptionPage: React.FC<{
  page: TikTokPage & { linhas?: TikTokToken[][] };
  st: CaptionStyle;
  fadeOut: boolean;
  fadeIn: boolean;
}> = ({ page, st, fadeOut, fadeIn }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, height } = useVideoConfig();
  const absMs = page.startMs + (frame / fps) * 1000;

  const pop = spring({ frame, fps, config: { damping: 20, stiffness: 300 } });
  const scale = 0.985 + 0.015 * pop;
  const inOp = fadeIn
    ? interpolate(frame, [0, 2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
    : 1;
  const outOp = fadeOut
    ? interpolate(frame, [durationInFrames - 5, durationInFrames], [1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;

  const base = st.color ?? "white";
  const pinta = (tk: TikTokToken) => {
    const ativo = st.highlight != null && tk.fromMs <= absMs && tk.toMs > absMs;
    return (
      <span key={tk.fromMs} style={{ color: ativo ? st.highlight! : base }}>
        {tk.text}
      </span>
    );
  };
  const pintaDisperso = (tk: TikTokToken) => {
    const ativo = st.highlight != null && tk.fromMs <= absMs && tk.toMs > absMs;
    const s = Math.round(tk.fromMs / 10);
    return (
      <span
        key={tk.fromMs}
        style={{
          color: ativo ? st.highlight! : base,
          display: "inline-block",
          transform:
            `translate(${(jitter(s, 1) * st.fontSize) / 9}px, ` +
            `${(jitter(s, 2) * st.fontSize) / 7}px) ` +
            `rotate(${jitter(s, 3) * 4}deg)`,
        }}
      >
        {tk.text}
      </span>
    );
  };
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          top: (height * (st.yPct ?? 79)) / 100,
          left: 0,
          width: "100%",
          transform: `translateY(-50%) scale(${scale})`,
          textAlign: "center",
          opacity: inOp * outOp,
        }}
      >
        <div
          style={{
            display: "inline-block",
            maxWidth: st.maxWidth ?? 900,
            fontFamily: st.fontFamily,
            fontWeight: st.fontWeight ?? 700,
            fontStyle: st.fontStyle ?? "normal",
            fontSize: st.fontSize,
            letterSpacing: st.letterSpacing ?? 0,
            lineHeight: st.lineHeight ?? 1.2,
            color: base,
            // ⚠️ `pre-wrap` = O NAVEGADOR decide onde quebra, e ele pode cortar
            // depois de "de", "a", "que". Só sobrevive no caminho LEGADO (sem
            // `linhas`), onde mudar isso reescreveria entrega publicada. Quando a
            // página vem do agrupamento por largura, a quebra é NOSSA e cada
            // linha é uma <div> — `pre`, nunca `pre-wrap`.
            whiteSpace: page.linhas ? "pre" : "pre-wrap",
            textShadow: st.textShadow ?? "0 3px 12px rgba(0,0,0,0.85)",
          }}
        >
          {/* 🔴 NUNCA "\n" para separar linha: em atributo JSX o escape é literal
              e o `\n` cru vai para a tela (defeito medido, EDICAO-CAPACIDADES.md:190-194).
              Linha é <div> num array, ponto. */}
          {page.linhas
            ? page.linhas.map((ln, i) => (
                <div
                  key={i}
                  style={
                    st.layout === "empilhado"
                      ? {
                          // a linha existe desde o começo (o espaço é reservado)
                          // e só ACENDE quando o primeiro token dela começa.
                          opacity: ln.length && ln[0].fromMs <= absMs ? 1 : 0,
                          transition: "none",
                        }
                      : undefined
                  }
                >
                  {ln.map(st.layout === "disperso" ? pintaDisperso : pinta)}
                </div>
              ))
            : page.tokens.map(st.layout === "disperso" ? pintaDisperso : pinta)}
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const CaptionLayer: React.FC<{
  captions: Caption[];
  estilo: CaptionStyle;
  /** ms de agrupamento por página (1100 = default histórico; menor = menos palavras por página) */
  combinaMs?: number;
  /**
   * SPEC-13 — agrupamento por LARGURA MEDIDA. OPT-IN: quando presente vence o
   * `combinaMs`, que passa a ser ignorado. É opt-in porque as produções
   * entregues chamam sem ele e têm que sair byte a byte iguais (a skill proíbe
   * remontar entrega publicada, edit-video/SKILL.md:62) — mesma disciplina do
   * FALLBACK_REELS da SPEC-00.
   */
  agrupamento?: Agrupamento;
  /**
   * SPEC-14 — as páginas JÁ DECIDIDAS pelo diretor (`partitura.paginas`).
   * Quando presente vence tudo, inclusive `agrupamento`.
   *
   * 🔴 A PRECEDÊNCIA NÃO É ESTILO, É CORREÇÃO DE DEFEITO. A partitura ancora
   * `legenda_off[]` nas fronteiras de página QUE ELA MESMA GEROU. Se o
   * componente recalcular as páginas por outro critério, as janelas de
   * supressão deixam de cair na fronteira e volta exatamente o defeito que a
   * partitura existe para consertar — e ele é SILENCIOSO: o vídeo sai bonito,
   * com segundos a mais sem legenda num beat qualquer (foi assim que nasceram
   * os buracos de 3,9 s e 2,1 s). Por isso, receber as duas props emite
   * `console.warn`: o canário tem que aparecer no log antes de alguém aceitar o
   * silêncio como aprovação.
   */
  paginas?: Pagina[];
  /** janelas [ini,fim] em segundos onde a legenda NÃO aparece */
  off?: [number, number][];
  /** segundos antes dos quais nada aparece (ex.: enquanto o título de gancho está no ar) */
  aPartirDeS?: number;
}> = ({
  captions,
  estilo,
  combinaMs = 1100,
  agrupamento,
  paginas,
  off = [],
  aPartirDeS = 0,
}) => {
  const { fps, durationInFrames } = useVideoConfig();
  const fimMs = (durationInFrames / fps) * 1000;

  /**
   * ⚠️ DENTRO DO useMemo, nunca no corpo do componente nem no topo do módulo.
   * Duas razões, as duas medidas:
   *   1. sem memo, `agrupar` roda A CADA FRAME (o `SimpleCaptions` do ref-A faz
   *      isso em `:150` e `:163` — 1.800 reexecuções em 60 s a 30 fps);
   *   2. o `wordCache` do `measureText` guarda a PRIMEIRA medição para sempre.
   *      Medir aqui é medir depois do `delayRender` que o `@remotion/google-fonts`
   *      instala; medir no topo do módulo é arriscar diagramar a peça inteira com
   *      métrica da fonte de fallback, calado.
   */
  const pages = useMemo<(TikTokPage & { linhas?: TikTokToken[][] })[]>(() => {
    if (paginas) {
      if (agrupamento) {
        // canário obrigatório (SPEC-14 §4.7): sem ele a precedência fica
        // implícita no código e alguém a inverte sem nada acusar.
        // eslint-disable-next-line no-console
        console.warn(
          "[LEGENDA] agrupamento ignorado: paginas tem precedência " +
            `(${paginas.length} páginas vindas da partitura)`
        );
      }
      return paginas;
    }
    if (agrupamento) return agrupar(captions, agrupamento, larguraDe, fimMs);
    return createTikTokStyleCaptions({
      captions,
      combineTokensWithinMilliseconds: combinaMs,
    }).pages;
  }, [captions, combinaMs, agrupamento, paginas, fimMs]);

  /**
   * ⚠️ Suprimir pelo START da página não basta: uma página que COMEÇA antes da
   * janela e se estende para dentro dela continuava na tela por cima da cena
   * conceitual (pegado no QC de varredura da VSL — "100% na nuvem" aparecia como
   * legenda sobre a cena que dizia a mesma coisa). O teste certo é INTERSEÇÃO.
   */
  const suprimida = (page: TikTokPage) => {
    const ini = page.startMs;
    const fim = Math.max(...page.tokens.map((t) => t.toMs));
    if (ini < aPartirDeS * 1000) return true;
    return off.some(([a, b]) => ini < b * 1000 && fim > a * 1000);
  };

  return (
    <AbsoluteFill>
      {pages.map((page, i) => {
        if (suprimida(page)) return null;
        const bruta = pages[i + 1] ?? null;
        const prox = bruta && suprimida(bruta) ? null : bruta;
        const ultimoFim = Math.max(...page.tokens.map((t) => t.toMs));
        let fim: number;
        let fadeOut = false;
        if (prox && prox.startMs - ultimoFim < 500) {
          fim = prox.startMs;
        } else {
          fim = Math.min(ultimoFim + 280, fimMs);
          fadeOut = true;
        }
        const ant = pages[i - 1] ?? null;
        const antFim = ant ? Math.max(...ant.tokens.map((t) => t.toMs)) : null;
        const emendada =
          ant !== null && !suprimida(ant) && page.startMs - (antFim as number) < 500;
        const from = (page.startMs / 1000) * fps;
        const dur = (fim / 1000) * fps - from;
        if (dur <= 0) return null;
        return (
          <Sequence key={i} from={from} durationInFrames={dur}>
            <CaptionPage page={page} st={estilo} fadeOut={fadeOut} fadeIn={!emendada} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

/**
 * SPEC-13 — `legenda.estilo` do perfil de peça → `CaptionStyle` em px.
 *
 * Companheiro de `agrupamentoDoPerfil` (`texto/agrupar.ts`): lá sai o
 * agrupamento, aqui sai a tipografia. Tudo no perfil é FRAÇÃO DA LARGURA; a
 * conversão para px acontece no render, com a largura real do canvas.
 *
 * É por aqui que o `perfil-overrides.json` do creator entra: o rosé da creator-2
 * (`legenda.estilo.destaque`) e o contorno reforçado dela são LOOK de creator,
 * não formato de peça — `video.*` continua proibido para o creator.
 */
export const estiloDoPerfil = (
  p: {
    legenda?: {
      y_pct?: number;
      estilo?: {
        familia: string;
        peso?: number;
        italico?: boolean;
        tamanho_pct: number;
        entreletras_pct?: number;
        altura_linha?: number;
        cor?: string;
        destaque?: string | null;
        sombra?: string;
      };
      agrupamento?: { largura_max_pct: number } | null;
    } | null;
  },
  larguraCanvas: number
): CaptionStyle | null => {
  const est = p.legenda?.estilo;
  if (!est) return null;
  return {
    fontFamily: est.familia,
    fontWeight: est.peso,
    fontStyle: est.italico ? "italic" : "normal",
    fontSize: est.tamanho_pct * larguraCanvas,
    color: est.cor,
    highlight: est.destaque,
    yPct: p.legenda?.y_pct === undefined ? undefined : p.legenda.y_pct * 100,
    maxWidth: p.legenda?.agrupamento
      ? p.legenda.agrupamento.largura_max_pct * larguraCanvas
      : undefined,
    letterSpacing: est.entreletras_pct === undefined
      ? undefined
      : est.entreletras_pct * larguraCanvas,
    lineHeight: est.altura_linha,
    textShadow: est.sombra,
  };
};

/**
 * Estilo medido no ref-D: branca chapada, PEQUENA, centro em 79%.
 * ⚠️ O tamanho surpreende: "Ele não vende" ocupa só 31% da largura do frame (≈345px em 1080). Medir por ALTURA DE CAIXA engana (a caixa inclui acento e ascendente, e deu
 * 42px = quase o dobro do que a largura implica) — calibre pela LARGURA de uma frase
 * conhecida. Legenda pequena é decisão de estilo: ela não disputa com o rosto nem com
 * o ritmo de corte, que é o protagonista aqui.
 */
export const ESTILO_LEGENDA_CHAPADA = (fontFamily: string): CaptionStyle => ({
  fontFamily,
  fontWeight: 600,
  fontSize: 46,
  color: "#ffffff",
  highlight: null,
  yPct: 79,
  maxWidth: 860,
  textShadow: "0 3px 10px rgba(0,0,0,0.8)",
});
