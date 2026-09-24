import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Sequence,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  spring,
} from "remotion";
import { createTikTokStyleCaptions, TikTokPage } from "@remotion/captions";
import type { Caption } from "@remotion/captions";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { loadFont as loadPlayfair } from "@remotion/google-fonts/PlayfairDisplay";
import captionsData from "./data/captions.json";
import overlays from "./data/overlays.json";

const montserrat = loadMontserrat("normal", {
  weights: ["600", "700"],
  subsets: ["latin"],
});
const playfair = loadPlayfair("italic", {
  weights: ["600"],
  subsets: ["latin"],
});

const SWITCH_CAPTIONS_EVERY_MS = 1100;
// Highlight por creator: creator-2 = "#FF8FA3" (rosé) · creator-1 = "#4ADE80" (verde
// operador/terminal — 1ª produção dele, peca-08). Trocar por produção.
const HIGHLIGHT = "#FF8FA3"; // creator-2/nao-perdeu-a-peca-06 (rosé da linha editorial dela)

// Janelas em que a legenda FICA FORA — quando um cartão gráfico carrega o mesmo
// texto (legenda + cartão com as mesmas palavras é ruído). creator-2/peca-03: o
// cartão do script em 43,55–50,70 (re-sincronizado após a correção de deriva).
// ⚠️ NÃO fazer isso apagando palavras do captions.json: o
// createTikTokStyleCaptions agrupa ATRAVÉS do buraco e gera uma página de 8s
// (bug pego no QC da produção peca-03). A supressão é aqui, na renderização.
// creator-2/nao-perdeu-a-peca-06: o cartão da LACUNA (E8) carrega as mesmas palavras.
// ⚠️ A janela fecha em 40,65 e NÃO em 40,85: a supressão mata a PÁGINA inteira
// que começa dentro dela, e a página seguinte abre em "Elogio" (40,71). Com
// 40,85 essa página sumia junto e o vídeo ficava 3,9s sem legenda em vez de
// 2,5s (pego na varredura de todos os frames do alpha).
const CAPTION_OFF: [number, number][] = [[38.80, 41.38]];

const isOff = (startMs: number) =>
  CAPTION_OFF.some(([a, b]) => startMs >= a * 1000 && startMs < b * 1000);

const isEmphasis = (startMs: number) =>
  overlays.captionEmphasis.some(
    (e) => startMs >= e.startS * 1000 - 50 && startMs < e.endS * 1000
  );

const CaptionPage: React.FC<{
  page: TikTokPage;
  emphasis: boolean;
  fadeOut: boolean;
  fadeIn: boolean;
}> = ({ page, emphasis, fadeOut, fadeIn }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const absoluteTimeMs = page.startMs + (frame / fps) * 1000;

  // pop discreto (0.985→1) + fades: entra em 2 frames; sai em 5 frames SÓ
  // quando a página morre em silêncio (fadeOut) — página emendada na próxima
  // corta seco (a próxima cobre). Corte seco pra tela vazia era a "piscada"
  // do feedback do creator-1 (−30 de luminância em 1 frame, medido).
  const pop = spring({ frame, fps, config: { damping: 20, stiffness: 300 } });
  const scale = 0.985 + 0.015 * pop;
  // fade-in SÓ quando a página entra depois de pausa real (fadeIn=true).
  // Em troca emendada (ponte), a nova página entra a opacidade CHEIA —
  // o fade-in de 2 frames na emenda criava um buraco semi-transparente
  // no frame exato da troca ("piscada na entrada da legenda", feedback
  // do creator-1 na it.6; padrão dip−3/recover+3 medido).
  const inOpacity = fadeIn
    ? interpolate(frame, [0, 2], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;
  const out = fadeOut
    ? interpolate(frame, [durationInFrames - 5, durationInFrames], [1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center" }}>
      <div
        style={{
          marginBottom: emphasis ? 420 : 400,
          maxWidth: 900,
          textAlign: "center",
          transform: `scale(${scale})`,
          opacity: inOpacity * out,
          fontFamily: emphasis ? playfair.fontFamily : montserrat.fontFamily,
          fontStyle: emphasis ? "italic" : "normal",
          fontWeight: emphasis ? 600 : 700,
          fontSize: emphasis ? 78 : 58,
          lineHeight: 1.25,
          color: "white",
          whiteSpace: "pre-wrap",
          textShadow: "0 2px 8px rgba(0,0,0,0.85)",
        }}
      >
        {page.tokens.map((token) => {
          const isActive =
            token.fromMs <= absoluteTimeMs && token.toMs > absoluteTimeMs;
          return (
            <span
              key={token.fromMs}
              style={{
                // base SEMPRE branca: o "#E8FFF0" que estava aqui era verde-menta
                // residual do creator anterior e vazava na janela de ênfase (auditoria 2026-07-25)
                color: isActive ? HIGHLIGHT : "white",
              }}
            >
              {token.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const Captions: React.FC = () => {
  const { fps, durationInFrames } = useVideoConfig();
  const fimMs = (durationInFrames / fps) * 1000;

  const { pages } = useMemo(
    () =>
      createTikTokStyleCaptions({
        captions: captionsData as Caption[],
        combineTokensWithinMilliseconds: SWITCH_CAPTIONS_EVERY_MS,
      }),
    []
  );

  return (
    <AbsoluteFill>
      {pages.map((page, index) => {
        if (isOff(page.startMs)) return null;
        // página seguinte suprimida = esta morre como se fosse a última (fade),
        // senão a ponte a esticaria por cima da janela sem legenda
        const rawNext = pages[index + 1] ?? null;
        const nextPage = rawNext && isOff(rawNext.startMs) ? null : rawNext;
        const lastTokenEndMs = Math.max(...page.tokens.map((t) => t.toMs));
        // ponte anti-piscada: se a próxima página começa logo (<500ms depois
        // do fim das palavras desta), esta fica na tela até a próxima entrar;
        // só em pausa longa de fala a legenda sai — e sai com fade.
        let endMs: number;
        let fadeOut = false;
        if (nextPage && nextPage.startMs - lastTokenEndMs < 500) {
          endMs = nextPage.startMs;
        } else {
          // clampa na duração da composição: a ponte de 280ms podia passar do
          // último frame e truncar o fade (auditoria 2026-07-25)
          endMs = Math.min(lastTokenEndMs + 280, fimMs);
          fadeOut = true;
        }
        // entra com fade só se a página ANTERIOR não emendou nesta
        const prevPage = pages[index - 1] ?? null;
        const prevLastEnd = prevPage
          ? Math.max(...prevPage.tokens.map((t) => t.toMs))
          : null;
        const bridgedIn =
          prevPage !== null && page.startMs - (prevLastEnd as number) < 500;
        const startFrame = (page.startMs / 1000) * fps;
        const durationInFrames = (endMs / 1000) * fps - startFrame;
        if (durationInFrames <= 0) return null;

        return (
          <Sequence
            key={index}
            from={startFrame}
            durationInFrames={durationInFrames}
          >
            <CaptionPage
              page={page}
              emphasis={isEmphasis(page.startMs)}
              fadeOut={fadeOut}
              fadeIn={!bridgedIn}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
