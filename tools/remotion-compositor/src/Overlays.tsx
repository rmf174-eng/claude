import React from "react";
import {
  AbsoluteFill,
  Audio,
  Easing,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont as loadCaveat } from "@remotion/google-fonts/Caveat";
import overlays from "./data/overlays.json";

const caveat = loadCaveat("normal", {
  weights: ["600", "700"],
  subsets: ["latin"],
});

const CARD_BG = "#FFF8F0";
const CARD_TEXT = "#3D2B2F";
const ACCENT = "#D96C8A";

type Card = {
  id: string;
  kind: string;
  text: string;
  startS: number;
  endS: number;
  x?: string;
  y?: string;
  rotate?: number;
  stackRow?: number;
  fontSize?: number;
  width?: number; // com width: quebra de linha automática (sem: nowrap)
  sfx?: string;
  writeOn?: boolean;
  path?: string; // kind=arrow: path SVG em coords 1080x1920
  panel?: boolean; // renderiza no BackPanel (atrás do recorte da pessoa)
};

const cards = overlays.cards as Card[];

// Janela do efeito "painel atrás da pessoa" (estilo ref-C): painel
// gráfico entre o vídeo e o recorte dela. O recorte sai de
// edit-video/scripts/matte.py (Apple Vision) e a composição é no ffmpeg, fora do
// Chrome — a receita antiga por rembg/cutout.webm foi aposentada (SPEC-03).
export const PANEL = { startS: 31.0, endS: 39.2 };

// Só o painel de fundo — fica ATRÁS do recorte da pessoa (profundidade).
export const BackPanel: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const pop = spring({ frame, fps, config: { damping: 16, stiffness: 160 } });
  const out = interpolate(
    frame,
    [durationInFrames - 8, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill style={{ opacity: out }}>
      <div
        style={{
          position: "absolute",
          left: 50,
          top: 120,
          width: 980,
          height: 540,
          transform: `scale(${0.92 + 0.08 * pop})`,
          opacity: pop,
          background: "rgba(255, 248, 240, 0.94)",
          borderRadius: 32,
          boxShadow: "0 16px 48px rgba(0,0,0,0.35)",
        }}
      />
    </AbsoluteFill>
  );
};

// Cartões de texto do painel — ficam NA FRENTE do recorte: o painel dá a
// profundidade, mas o texto precisa ser legível mesmo com a pessoa no centro.
export const PanelCards: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const panelCards = cards.filter((c) => c.panel);

  const out = interpolate(
    frame,
    [durationInFrames - 8, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill style={{ opacity: out }}>
      {panelCards.map((card) => {
        const from = Math.round((card.startS - PANEL.startS) * fps);
        const row = card.stackRow ?? 0;
        return (
          <Sequence key={card.id} from={from}>
            <PanelRow text={card.text} row={row} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

const PanelRow: React.FC<{ text: string; row: number }> = ({ text, row }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 12, stiffness: 190 } });
  return (
    <div
      style={{
        position: "absolute",
        left: 110,
        top: 175 + row * 145,
        transform: `scale(${pop}) rotate(${row % 2 === 0 ? -1 : 1}deg)`,
        transformOrigin: "left center",
        background: "white",
        color: CARD_TEXT,
        fontFamily: caveat.fontFamily,
        fontWeight: 700,
        fontSize: 58,
        padding: "14px 32px",
        borderRadius: 20,
        borderLeft: `12px solid ${ACCENT}`,
        boxShadow: "0 6px 20px rgba(0,0,0,0.18)",
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
};

// Texto "sendo escrito na hora": caracteres revelados em stagger.
const WriteOnText: React.FC<{ text: string; framesPerChar?: number }> = ({
  text,
  framesPerChar = 1.6,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <span>
      {text.split("").map((ch, i) => {
        if (ch === "\n") return <br key={i} />;
        const reveal = spring({
          frame: frame - i * framesPerChar,
          fps,
          config: { damping: 16, stiffness: 260 },
          durationInFrames: 8,
        });
        return (
          <span
            key={i}
            style={{
              opacity: reveal,
              display: "inline-block",
              whiteSpace: "pre",
              transform: `translateY(${(1 - reveal) * 10}px)`,
            }}
          >
            {ch}
          </span>
        );
      })}
    </span>
  );
};

// Seta manuscrita desenhando-se (stroke-dashoffset) + ponta no final do traço.
const DRAW_FRAMES = 14;
const ArrowDrawOn: React.FC<{ card: Card }> = ({ card }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const PATH_LEN = 1000; // pathLength normalizado do SVG
  const progress = interpolate(frame, [0, DRAW_FRAMES], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.quad),
  });
  const head = spring({
    frame: frame - DRAW_FRAMES,
    fps,
    config: { damping: 14, stiffness: 240 },
    durationInFrames: 8,
  });
  const out = interpolate(
    frame,
    [durationInFrames - 6, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <svg
        viewBox="0 0 1080 1920"
        style={{ position: "absolute", width: "100%", height: "100%" }}
      >
        <path
          d={card.path}
          pathLength={PATH_LEN}
          fill="none"
          stroke="white"
          strokeWidth={9}
          strokeLinecap="round"
          strokeDasharray={PATH_LEN}
          strokeDashoffset={PATH_LEN * (1 - progress)}
          style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.7))" }}
        />
        {/* ponta da seta ancorada no fim do path, aparece quando o traço chega */}
        <g
          opacity={head}
          style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.7))" }}
        >
          <path
            d={arrowHeadAt(card.path ?? "")}
            fill="none"
            stroke="white"
            strokeWidth={9}
            strokeLinecap="round"
          />
        </g>
      </svg>
      {card.text ? (
        <div
          style={{
            position: "absolute",
            left: card.x,
            top: card.y,
            transform: `rotate(${card.rotate ?? 0}deg)`,
            fontFamily: caveat.fontFamily,
            fontWeight: 700,
            fontSize: 58,
            color: "white",
            textShadow: "0 3px 12px rgba(0,0,0,0.8)",
          }}
        >
          <WriteOnText text={card.text} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

// Ponta em "V" no ponto final do path, orientada pela tangente do último trecho.
const arrowHeadAt = (d: string): string => {
  const nums = d.match(/-?\d+(\.\d+)?/g)?.map(Number) ?? [];
  if (nums.length < 4) return "";
  const [x2, y2] = nums.slice(-2);
  const [x1, y1] = nums.slice(-4, -2);
  const ang = Math.atan2(y2 - y1, x2 - x1);
  const L = 34;
  const mk = (da: number) =>
    `${x2 - L * Math.cos(ang + da)} ${y2 - L * Math.sin(ang + da)}`;
  return `M ${mk(0.5)} L ${x2} ${y2} L ${mk(-0.5)}`;
};

const CardContent: React.FC<{ card: Card }> = ({ card }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const pop = spring({ frame, fps, config: { damping: 12, stiffness: 180 } });
  const out = interpolate(
    frame,
    [durationInFrames - 6, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const scale = pop * out;
  const rotate = card.rotate ?? 0;

  if (card.kind === "arrow") {
    return <ArrowDrawOn card={card} />;
  }

  if (card.kind === "handwritten-big") {
    const positionedHw = card.x && card.x !== "50%";
    return (
      <AbsoluteFill style={positionedHw ? undefined : { alignItems: "center" }}>
        <div
          style={{
            position: "absolute",
            top: card.y,
            ...(positionedHw ? { left: card.x } : {}),
            width: card.width,
            textAlign: "center",
            transform: card.writeOn
              ? `rotate(${rotate}deg)`
              : `scale(${scale}) rotate(${rotate}deg)`,
            transformOrigin: positionedHw ? "left center" : undefined,
            opacity: card.writeOn ? out : 1,
            fontFamily: caveat.fontFamily,
            fontWeight: 700,
            fontSize: card.fontSize ?? 110,
            lineHeight: 1.1,
            whiteSpace: "pre-line",
            color: "white",
            textShadow: "0 3px 14px rgba(0,0,0,0.8)",
          }}
        >
          {card.writeOn ? <WriteOnText text={card.text} /> : card.text}
        </div>
      </AbsoluteFill>
    );
  }

  if (card.kind === "stack-card") {
    const row = card.stackRow ?? 0;
    return (
      <AbsoluteFill>
        <div
          style={{
            position: "absolute",
            left: 44,
            top: 90 + row * 118,
            transform: `scale(${scale}) rotate(${row % 2 === 0 ? -1.2 : 1.2}deg)`,
            transformOrigin: "left center",
            background: CARD_BG,
            color: CARD_TEXT,
            fontFamily: caveat.fontFamily,
            fontWeight: 600,
            fontSize: 54,
            padding: "14px 30px",
            borderRadius: 18,
            borderLeft: `10px solid ${ACCENT}`,
            boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
            whiteSpace: "nowrap",
          }}
        >
          {card.text}
        </div>
      </AbsoluteFill>
    );
  }

  // postit (default) — com card.x posiciona pela esquerda; sem, centraliza
  const positioned = card.x && card.x !== "50%";
  return (
    <AbsoluteFill style={positioned ? undefined : { alignItems: "center" }}>
      <div
        style={{
          position: "absolute",
          top: card.y,
          ...(positioned ? { left: card.x } : {}),
          transform: `scale(${scale}) rotate(${rotate}deg)`,
          transformOrigin: positioned ? "left center" : undefined,
          background: CARD_BG,
          color: CARD_TEXT,
          fontFamily: caveat.fontFamily,
          fontWeight: 700,
          fontSize: card.fontSize ?? 62,
          lineHeight: 1.08,
          padding: "16px 30px",
          borderRadius: 20,
          boxShadow: "0 10px 30px rgba(0,0,0,0.4)",
          whiteSpace: card.width ? "normal" : "nowrap",
          width: card.width,
          textAlign: card.width ? "center" : undefined,
        }}
      >
        {card.text}
      </div>
    </AbsoluteFill>
  );
};

export const Overlays: React.FC = () => {
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill>
      {cards.map((card) => {
        if (card.panel) {
          // renderizado pelo BackPanel; aqui só dispara o SFX
          return card.sfx ? (
            <Sequence
              key={card.id}
              from={Math.round(card.startS * fps)}
              durationInFrames={Math.round((card.endS - card.startS) * fps)}
            >
              <Audio src={staticFile(`sfx/${card.sfx}.wav`)} volume={0.35} />
            </Sequence>
          ) : null;
        }
        const from = Math.round(card.startS * fps);
        const durationInFrames = Math.round((card.endS - card.startS) * fps);
        return (
          <Sequence key={card.id} from={from} durationInFrames={durationInFrames}>
            <CardContent card={card} />
            {card.sfx ? (
              <Audio
                src={staticFile(`sfx/${card.sfx}.wav`)}
                volume={card.sfx === "pencil" ? 0.13 : 0.35}
              />
            ) : null}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
