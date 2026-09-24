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
import { Video } from "@remotion/media";
import { loadFont as loadCaveat } from "@remotion/google-fonts/Caveat";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { Captions } from "./Captions";

const caveat = loadCaveat("normal", { weights: ["700"], subsets: ["latin"] });
const montserrat = loadMontserrat("normal", {
  weights: ["800"],
  subsets: ["latin"],
});

const ROSE = "#FF8FA3";
const FPS = 30;

// ——— primitivas do efeito (estilo lettering anotado da ref-C) ———

export const WriteOn: React.FC<{
  text: string;
  delayS: number;
  style?: React.CSSProperties;
}> = ({ text, delayS, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const base = frame - delayS * fps;
  return (
    <span style={style}>
      {text.split("").map((ch, i) => {
        // escrita de verdade não tem movimento: a letra só APARECE
        // (fade de 2 frames pra não "piscar" — sem translate/spring)
        const reveal = interpolate(base - i * 1.6, [0, 2], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <span
            key={i}
            style={{
              opacity: reveal,
              display: "inline-block",
              whiteSpace: "pre",
            }}
          >
            {ch}
          </span>
        );
      })}
    </span>
  );
};

// traço SVG (sublinhado / seta / círculo) desenhando via dashoffset
export const DrawStroke: React.FC<{
  d: string;
  delayS: number;
  drawS?: number;
  strokeWidth?: number;
  color?: string;
  arrowHead?: boolean;
  // viewBox local: desenha no espaço do container pai (herda rotação dele)
  // em vez do canvas global 1080x1920
  localBox?: string;
}> = ({
  d,
  delayS,
  drawS = 0.4,
  strokeWidth = 8,
  color = "white",
  arrowHead,
  localBox,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const LEN = 1000;
  const progress = interpolate(
    frame,
    [delayS * fps, (delayS + drawS) * fps],
    [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.quad),
    }
  );
  const head = spring({
    frame: frame - (delayS + drawS) * fps,
    fps,
    config: { damping: 14, stiffness: 240 },
    durationInFrames: 8,
  });
  const headPath = arrowHead ? arrowHeadAt(d) : "";
  return (
    <svg
      viewBox={localBox ?? "0 0 1080 1920"}
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        overflow: "visible",
        filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.65))",
      }}
    >
      <path
        d={d}
        pathLength={LEN}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={LEN}
        strokeDashoffset={LEN * (1 - progress)}
      />
      {headPath ? (
        <path
          d={headPath}
          opacity={head}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />
      ) : null}
    </svg>
  );
};

const arrowHeadAt = (d: string): string => {
  const nums = d.match(/-?\d+(\.\d+)?/g)?.map(Number) ?? [];
  if (nums.length < 4) return "";
  const [x2, y2] = nums.slice(-2);
  const [x1, y1] = nums.slice(-4, -2);
  const ang = Math.atan2(y2 - y1, x2 - x1);
  const L = 30;
  const mk = (da: number) =>
    `${x2 - L * Math.cos(ang + da)} ${y2 - L * Math.sin(ang + da)}`;
  return `M ${mk(0.5)} L ${x2} ${y2} L ${mk(-0.5)}`;
};

// palavra-ênfase estilo marker: pop com overshoot
export const MarkerWord: React.FC<{
  text: string;
  delayS: number;
  style?: React.CSSProperties;
}> = ({ text, delayS, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({
    frame: frame - delayS * fps,
    fps,
    config: { damping: 10, stiffness: 200 },
  });
  return (
    <div
      style={{
        transform: `scale(${pop})`,
        opacity: pop > 0.05 ? 1 : 0,
        ...style,
      }}
    >
      {text}
    </div>
  );
};

// ——— gancho de DEMONSTRAÇÃO — o timing sai das palavras do transcript ———
// A palavra em destaque é falada em 2,51–2,98 (o ASR nem sempre transcreve o
// — o roteiro é a fonte de verdade). O marker POP sincroniza com a voz dela.
// Posição: bloco livre ESQUERDO (zona segura de UI, "quadrado proibido").

export const HookCluster: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const out = interpolate(frame, [6.35 * fps, 6.65 * fps], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ opacity: out }}>
      <div
        style={{
          position: "absolute",
          left: 36,
          top: 310,
          width: 420,
          textAlign: "center",
          transform: "rotate(-3deg)",
          color: "white",
          textShadow: "0 3px 12px rgba(0,0,0,0.8)",
        }}
      >
        <div
          style={{
            fontFamily: caveat.fontFamily,
            fontWeight: 700,
            fontSize: 52,
            lineHeight: 1.0,
          }}
        >
          <WriteOn text="a tal da" delayS={0.7} />
        </div>
        {/* wrapper relativo: a elipse é desenhada no espaço DESTA linha,
            com folga em toda a volta pra não cruzar as letras */}
        <div style={{ position: "relative", padding: "6px 0 10px" }}>
          <MarkerWord
            text="ideia nova"
            delayS={2.51}
            style={{
              fontFamily: montserrat.fontFamily,
              fontWeight: 800,
              fontSize: 64,
              color: ROSE,
              lineHeight: 1.15,
              textShadow: "0 3px 14px rgba(0,0,0,0.85)",
            }}
          />
          <DrawStroke
            localBox="0 0 420 105"
            d="M 255 -16 Q 412 -10 424 44 Q 434 98 214 106 Q -2 110 -8 52 Q -4 -2 262 -14"
            delayS={3.1}
            drawS={0.5}
            strokeWidth={6}
            color="white"
          />
        </div>
      </div>
      {/* SFX */}
      <Sequence from={Math.round(0.7 * fps)}>
        <Audio src={staticFile("sfx/pencil.wav")} volume={0.13} />
      </Sequence>
      <Sequence from={Math.round(2.51 * fps)}>
        <Audio src={staticFile("sfx/pop.wav")} volume={0.35} />
      </Sequence>
      <Sequence from={Math.round(3.1 * fps)}>
        <Audio src={staticFile("sfx/pencil.wav")} volume={0.13} />
      </Sequence>
    </AbsoluteFill>
  );
};

// ——— cena conceitual do AHA: "submissão = SUB-MISSÃO" (32.6–37.7) ———
// Não é só texto: a palavra SE TRANSFORMA pra exemplificar o conceito.
//   local 0.0  (32.62 "Submissão é")   SUBMISSÃO inteira aparece
//   local 1.15 (33.74 "sub-missão,")   corte manuscrito parte a palavra:
//                                      SUB | MISSÃO se afastam, SUB vira rosé
//   local 2.35 (34.94 "a mesma missão") linha "= a mesma missão" escreve,
//                                      sublinhado DEBAIXO da própria linha
//   local 4.1  (36.7 "vocês dois juntos") 2 setas lado a lado no MESMO rumo
// Zona: bloco livre esquerdo (x24–470, y260–590), rotação leve.

export const AhaScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const out = interpolate(
    frame,
    [durationInFrames - 9, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const appear = spring({ frame, fps, config: { damping: 14, stiffness: 200 } });
  const split = spring({
    frame: frame - 1.05 * fps,
    fps,
    config: { damping: 12, stiffness: 170 },
  });
  const gap = split * 20; // afastamento de cada metade a partir do corte

  return (
    <AbsoluteFill style={{ opacity: out }}>
      <div
        style={{
          position: "absolute",
          left: 30,
          top: 300,
          width: 430,
          textAlign: "center",
          transform: "rotate(-3deg)",
          color: "white",
          textShadow: "0 3px 12px rgba(0,0,0,0.8)",
        }}
      >
        {/* a palavra que se parte */}
        <div
          style={{
            position: "relative",
            fontFamily: montserrat.fontFamily,
            fontWeight: 800,
            fontSize: 56,
            lineHeight: 1.25,
            transform: `scale(${appear})`,
            whiteSpace: "nowrap",
          }}
        >
          <span
            style={{
              display: "inline-block",
              transform: `translateX(${-gap}px)`,
              color: split > 0.25 ? ROSE : "white",
            }}
          >
            SUB
          </span>
          <span style={{ display: "inline-block", transform: `translateX(${gap}px)` }}>
            MISSÃO
          </span>
          {/* traço manuscrito do corte, desenhado entre as metades */}
          <DrawStroke
            localBox="0 0 430 70"
            d="M 172 0 Q 168 22 174 38 Q 180 54 170 66"
            delayS={1.05}
            drawS={0.25}
            strokeWidth={6}
            color={ROSE}
          />
        </div>
        {/* linha da síntese, com o sublinhado no espaço DELA (não risca nada) */}
        <div
          style={{
            position: "relative",
            fontFamily: caveat.fontFamily,
            fontWeight: 700,
            fontSize: 54,
            lineHeight: 1.25,
            paddingBottom: 14,
          }}
        >
          <WriteOn text="= a mesma missão" delayS={2.75} />
          <DrawStroke
            localBox="0 0 430 82"
            d="M 96 74 Q 190 82 280 75 Q 340 70 356 76"
            delayS={3.45}
            drawS={0.35}
            strokeWidth={6}
            color={ROSE}
          />
        </div>
        {/* "vocês dois juntos": as duas setas remam pro MESMO rumo */}
        <div
          style={{
            position: "relative",
            height: 92,
            fontFamily: caveat.fontFamily,
            fontWeight: 700,
            fontSize: 44,
          }}
        >
          <WriteOn text="vocês dois juntos" delayS={3.9} />
          <DrawStroke
            localBox="0 0 430 92"
            d="M 120 62 Q 170 56 218 60"
            delayS={4.35}
            drawS={0.25}
            strokeWidth={5}
            color="white"
            arrowHead
          />
          <DrawStroke
            localBox="0 0 430 92"
            d="M 120 84 Q 175 78 218 82"
            delayS={4.5}
            drawS={0.25}
            strokeWidth={5}
            color={ROSE}
            arrowHead
          />
        </div>
      </div>
      {/* SFX */}
      <Sequence from={Math.round(1.05 * fps)}>
        <Audio src={staticFile("sfx/pop.wav")} volume={0.35} />
      </Sequence>
      <Sequence from={Math.round(2.75 * fps)}>
        <Audio src={staticFile("sfx/pencil.wav")} volume={0.13} />
      </Sequence>
      <Sequence from={Math.round(4.35 * fps)}>
        <Audio src={staticFile("sfx/pencil.wav")} volume={0.12} />
      </Sequence>
    </AbsoluteFill>
  );
};

// composição de teste: só os primeiros ~9s (barata de iterar no studio)
export const HOOK_TEST_DURATION_S = 9;

export const HookTest: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <AbsoluteFill>
        <Video src={staticFile("v1-montado.mp4")} />
      </AbsoluteFill>
      <HookCluster />
      <Captions />
    </AbsoluteFill>
  );
};
