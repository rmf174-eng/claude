import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Video } from "@remotion/media";
import { loadFont as loadCaveat } from "@remotion/google-fonts/Caveat";
import { loadFont as loadSpaceMono } from "@remotion/google-fonts/SpaceMono";
import { WriteOn } from "./HookLettering";

const caveat = loadCaveat("normal", { weights: ["700"], subsets: ["latin"] });
const spaceMono = loadSpaceMono("normal", {
  weights: ["400", "700"],
  subsets: ["latin"],
});

const ROSE = "#FF8FA3";

// Demo dos SFX em contexto (estilo ref-C): trecho 42.3–54.3s do vídeo da creator-2
// ("chocolate guardado não fica mais doce ... não existe guardar para depois")
const SLICE_START_S = 42.3;
export const SFX_DEMO_DURATION_S = 12;

// texto digitando char a char, com cursor — pra acompanhar o typing.wav
const TypeOn: React.FC<{ text: string; framesPerChar?: number }> = ({
  text,
  framesPerChar = 3,
}) => {
  const frame = useCurrentFrame();
  const shown = Math.min(text.length, Math.floor(frame / framesPerChar));
  const done = shown >= text.length;
  const cursorOn = done ? Math.floor(frame / 15) % 2 === 0 : true;
  return (
    <span>
      {text.slice(0, shown)}
      <span style={{ opacity: cursorOn ? 1 : 0, color: ROSE }}>▍</span>
    </span>
  );
};

export const SfxDemo: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const notePop = spring({
    frame: frame - 6 * fps,
    fps,
    config: { damping: 14, stiffness: 200 },
  });
  const noteOut = interpolate(
    frame,
    [11.4 * fps, 11.9 * fps],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const penOut = interpolate(frame, [5.2 * fps, 5.6 * fps], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <Video
        src={staticFile("v1-montado.mp4")}
        trimBefore={Math.round(SLICE_START_S * fps)}
      />

      {/* 1) LÁPIS: manuscrito escrevendo enquanto ela fala (0.6s–5.6s) */}
      <Sequence from={Math.round(0.6 * fps)}>
        <AbsoluteFill style={{ alignItems: "center", opacity: penOut }}>
          <div
            style={{
              position: "absolute",
              top: 90,
              transform: "rotate(-2deg)",
              fontFamily: caveat.fontFamily,
              fontWeight: 700,
              fontSize: 84,
              color: "white",
              textShadow: "0 3px 12px rgba(0,0,0,0.8)",
            }}
          >
            <WriteOn text="chocolate guardado só vence" delayS={0} />
          </div>
        </AbsoluteFill>
        <Audio src={staticFile("sfx/pencil.wav")} volume={0.15} />
      </Sequence>

      {/* 2) TECLADO: nota digital digitando (6.0s–11.9s) */}
      <Sequence from={Math.round(6 * fps)}>
        <AbsoluteFill style={{ alignItems: "center", opacity: noteOut }}>
          <div
            style={{
              position: "absolute",
              top: 110,
              width: 760,
              transform: `scale(${notePop === 0 ? 0 : 0.9 + 0.1 * notePop})`,
              opacity: notePop,
              background: "rgba(255,255,255,0.96)",
              borderRadius: 24,
              padding: "26px 34px 30px",
              boxShadow: "0 14px 40px rgba(0,0,0,0.35)",
            }}
          >
            <div
              style={{
                fontFamily: spaceMono.fontFamily,
                fontWeight: 700,
                fontSize: 30,
                color: "#B0A9A4",
                letterSpacing: 2,
                marginBottom: 10,
              }}
            >
              NOTAS
            </div>
            <div
              style={{
                fontFamily: spaceMono.fontFamily,
                fontWeight: 400,
                fontSize: 44,
                lineHeight: 1.35,
                color: "#3D2B2F",
              }}
            >
              <TypeOn text="o amor não guarda. vive." />
            </div>
          </div>
        </AbsoluteFill>
        {/* teclas cobrindo a duração da digitação (24 chars × 3f ≈ 2.4s) */}
        <Audio src={staticFile("sfx/typing.wav")} volume={0.4} />
        <Sequence from={Math.round(2.2 * fps)}>
          <Audio
            src={staticFile("sfx/typing.wav")}
            volume={0.32}
            endAt={Math.round(0.5 * fps)}
          />
        </Sequence>
      </Sequence>
    </AbsoluteFill>
  );
};
