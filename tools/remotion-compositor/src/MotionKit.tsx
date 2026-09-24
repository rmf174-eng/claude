import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Video } from "@remotion/media";
import { loadFont as loadCaveat } from "@remotion/google-fonts/Caveat";
import { loadFont as loadMarker } from "@remotion/google-fonts/PermanentMarker";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { loadFont as loadOswald } from "@remotion/google-fonts/Oswald";
import { loadFont as loadPen } from "@remotion/google-fonts/ShadowsIntoLightTwo";
import { DrawStroke, WriteOn } from "./HookLettering";
import { Theme, neutralTheme } from "./themes";

// ————————————————————————————————————————————————————————————————
// MotionKit — módulos genéricos do sistema "legenda semântica"
// (decodificado da ref-C: references/sistema-ref-C.md +
// análise frame a frame de 2026-07-22 em estudos/edicao-ref-C/).
// Nada aqui é específico de creator: cores/fontes via Theme, conteúdo/
// timing via props. Timing em segundos relativos ao pai (Sequence/grupo).
//
// REGRA DE ORQUESTRAÇÃO (feedback creator-1 + frames da referência):
// UMA escrita por vez — um elemento só começa quando o anterior TERMINOU.
// Frases curtas de contexto se SUBSTITUEM (SwapText), não se acumulam.
// ————————————————————————————————————————————————————————————————

const caveat = loadCaveat("normal", { weights: ["600", "700"], subsets: ["latin"] });
const marker = loadMarker("normal", { weights: ["400"], subsets: ["latin"] });
const montserrat = loadMontserrat("normal", { weights: ["700", "800"], subsets: ["latin"] });
const oswald = loadOswald("normal", { weights: ["600"], subsets: ["latin"] });
const pen = loadPen("normal", { weights: ["400"], subsets: ["latin"] });

export const FONTS = {
  // caneta fina minúscula — Shadows Into Light Two (a Nanum Pen tinha o
  // acento agudo torto no ú/í — reprovada pelo creator-1; comp FontTest compara)
  pen: pen.fontFamily,
  script: caveat.fontFamily, // cursiva (notas pequenas)
  marker: marker.fontFamily, // marcador caps grosso (usar com parcimônia)
  sans: montserrat.fontFamily,
  caption: oswald.fontFamily,
};

// ——— SFX pontual (Sequence + Audio). Volumes calibrados pelo creator-1. ———
const SFX_VOL: Record<string, number> = {
  pencil: 0.13,
  pop: 0.35,
  "pop-hi": 0.35,
  "pop-lo": 0.35,
  whoosh: 0.4,
  "whoosh-soft": 0.4,
  shutter: 0.3,
  scratch: 0.25,
  typing: 0.35,
};

// Sons de ESCRITA (lápis/risco) — categoria com desligamento próprio:
// tem creator/trecho que quer o som descrevendo, outro só a animação
// (pedido do creator-1 2026-07-23, pensando na creator-2).
const WRITING_SFX = new Set(["pencil", "scratch"]);

export type SfxSettings = {
  enabled: boolean; // desliga TODO sfx do kit
  writing: boolean; // só os sons de escrita (pencil/scratch)
  master: number; // multiplicador global de volume
};

const SfxContext = React.createContext<SfxSettings>({
  enabled: true,
  writing: true,
  master: 1,
});

// Envolva a composição (ou só um trecho) pra escolher o perfil de som:
//   <SfxProvider writing={false}> ... </SfxProvider>  → escrita muda, resto toca
export const SfxProvider: React.FC<{
  enabled?: boolean;
  writing?: boolean;
  master?: number;
  children: React.ReactNode;
}> = ({ enabled = true, writing = true, master = 1, children }) => (
  <SfxContext.Provider value={{ enabled, writing, master }}>
    {children}
  </SfxContext.Provider>
);

export const Sfx: React.FC<{
  name: string;
  atS: number;
  volume?: number;
  force?: boolean; // ignora o SfxProvider (toca sempre)
}> = ({ name, atS, volume, force }) => {
  const { fps } = useVideoConfig();
  const cfg = React.useContext(SfxContext);
  if (!force) {
    if (!cfg.enabled) return null;
    if (WRITING_SFX.has(name) && !cfg.writing) return null;
  }
  const vol = (volume ?? SFX_VOL[name] ?? 0.3) * (force ? 1 : cfg.master);
  return (
    <Sequence from={Math.round(atS * fps)}>
      <Audio src={staticFile(`sfx/${name}.wav`)} volume={vol} />
    </Sequence>
  );
};

// ——— GRUPO com limpeza conjunta (gap nº1) ————————————————————————
export const OverlayGroup: React.FC<{
  fromS: number;
  toS: number;
  exit?: "cut" | "fade";
  children: React.ReactNode;
}> = ({ fromS, toS, exit = "cut", children }) => {
  const { fps } = useVideoConfig();
  return (
    <Sequence
      from={Math.round(fromS * fps)}
      durationInFrames={Math.round((toS - fromS) * fps)}
    >
      {exit === "fade" ? <FadeOutWrap>{children}</FadeOutWrap> : <>{children}</>}
    </Sequence>
  );
};

const FadeOutWrap: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const out = interpolate(frame, [durationInFrames - 7, durationInFrames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <AbsoluteFill style={{ opacity: out }}>{children}</AbsoluteFill>;
};

// write-on com consciência de linha/palavra: revela caractere a caractere,
// quebra de linha SÓ em espaço ou \n.
const HandWriteOn: React.FC<{
  text: string;
  delayS: number;
  framesPerChar?: number;
}> = ({ text, delayS, framesPerChar = 0.9 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const base = frame - delayS * fps;
  let idx = 0;
  return (
    <>
      {text.split("\n").map((line, li) => (
        <div key={li}>
          {line.split(" ").map((word, wi) => {
            const chars = word.split("").map((ch) => {
              const i = idx++;
              const reveal = interpolate(base - i * framesPerChar, [0, 2], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              });
              return (
                <span key={i} style={{ opacity: reveal }}>
                  {ch}
                </span>
              );
            });
            idx++; // o espaço conta no ritmo da escrita
            return (
              <span key={wi} style={{ display: "inline-block", whiteSpace: "pre" }}>
                {chars}
                {wi < line.split(" ").length - 1 ? " " : ""}
              </span>
            );
          })}
        </div>
      ))}
    </>
  );
};

// duração da escrita de um texto (pra encadear o próximo elemento DEPOIS)
export const writeDurationS = (text: string, framesPerChar = 0.9, fps = 30): number =>
  (text.replace(/\n/g, " ").length * framesPerChar + 2) / fps;

// ——— Texto manuscrito write-on ————————————————————————————————————
// Estilo da referência: caneta FINA ("pen"), minúsculas, tamanho pequeno,
// sem sombra pesada. Regra do creator-1: escrita NÃO se move — só aparece.
export const HandText: React.FC<{
  text: string;
  delayS: number;
  x: number;
  y: number;
  width?: number;
  size?: number;
  rotate?: number;
  font?: "pen" | "script" | "marker";
  align?: "left" | "center" | "right";
  color?: string;
  fpc?: number; // frames por caractere (0.9 = ritmo da referência)
  lineHeight?: number;
  sfx?: boolean; // toca o lápis junto da escrita (respeita o SfxProvider)
  shadow?: string; // sombra própria (o default do theme é tight demais sobre vídeo)
  theme?: Theme;
}> = ({
  text,
  delayS,
  x,
  y,
  width,
  size = 44,
  rotate = 0,
  font = "pen",
  align = "center",
  color,
  fpc = 0.9,
  lineHeight = 1.02, // referência usa linhas BEM apertadas (creator-1 v2+v3)
  sfx = false,
  shadow,
  theme = neutralTheme,
}) => {
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: x,
          top: y,
          width,
          textAlign: align,
          transform: `rotate(${rotate}deg)`,
          transformOrigin: "left top",
          fontFamily: FONTS[font],
          fontWeight: font === "script" ? 700 : 400,
          fontSize: size,
          lineHeight,
          whiteSpace: "pre-line",
          color: color ?? theme.ink,
          textShadow: shadow ?? `0 1px 2px ${theme.inkShadow}`,
        }}
      >
        <HandWriteOn text={text} delayS={delayS} framesPerChar={fpc} />
      </div>
      {sfx ? <Sfx name="pencil" atS={delayS} /> : null}
    </>
  );
};

// ——— Frases curtas que se SUBSTITUEM (padrão da referência) ————————————
// "Você criou" → "um conflito." — cada item escreve, e ao entrar o próximo
// o anterior some (corte seco). items[i].atS relativo ao pai.
export const SwapText: React.FC<{
  items: { text: string; atS: number }[];
  toS: number; // quando o último some
  x: number;
  y: number;
  width?: number;
  size?: number;
  align?: "left" | "center";
  fpc?: number;
  theme?: Theme;
}> = ({ items, toS, x, y, width, size = 40, align = "center", fpc = 0.7, theme = neutralTheme }) => {
  const { fps } = useVideoConfig();
  return (
    <>
      {items.map((it, i) => {
        const end = i < items.length - 1 ? items[i + 1].atS : toS;
        return (
          <Sequence
            key={i}
            from={Math.round(it.atS * fps)}
            durationInFrames={Math.round((end - it.atS) * fps)}
          >
            <HandText
              theme={theme}
              text={it.text}
              delayS={0}
              x={x}
              y={y}
              width={width}
              size={size}
              align={align}
              fpc={fpc}
            />
          </Sequence>
        );
      })}
    </>
  );
};

// ——— Geradores de traço mão-livre (usar com DrawStroke) ————————————

// sublinhado ondulado sob um box
export const underlinePath = (x: number, y: number, w: number): string =>
  `M ${x} ${y} Q ${x + w * 0.3} ${y + 6} ${x + w * 0.55} ${y + 1} Q ${x + w * 0.8} ${y - 4} ${x + w} ${y + 3}`;

// elipse "circulando" fechada torta (4 quadráticas — nunca <ellipse>)
export const loopCirclePath = (cx: number, cy: number, rx: number, ry: number): string =>
  `M ${cx + rx * 0.62} ${cy - ry} Q ${cx + rx} ${cy - ry * 0.9} ${cx + rx * 0.96} ${cy + ry * 0.1} ` +
  `Q ${cx + rx * 0.88} ${cy + ry} ${cx - rx * 0.1} ${cy + ry * 0.96} ` +
  `Q ${cx - rx} ${cy + ry * 0.86} ${cx - rx * 0.94} ${cy - ry * 0.06} ` +
  `Q ${cx - rx * 0.82} ${cy - ry} ${cx + rx * 0.7} ${cy - ry * 0.94}`;

// tachado simples (1 risco levemente inclinado)
export const strikePath = (x: number, y: number, w: number, tilt = -2): string => {
  const dy = Math.tan((tilt * Math.PI) / 180) * w;
  return `M ${x} ${y} Q ${x + w * 0.25} ${y + dy * 0.25 - 6} ${x + w * 0.5} ${y + dy * 0.5 + 2} Q ${x + w * 0.75} ${y + dy * 0.75 + 7} ${x + w} ${y + dy}`;
};

// X da referência: 2 diagonais LONGAS e finas cruzando o box inteiro
// (desenhar em sequência com ~0.15s de stagger, strokeWidth 4–5)
export const strikeXPaths = (
  x: number,
  y: number,
  w: number,
  h: number
): [string, string] => [
  `M ${x} ${y + h * 0.12} Q ${x + w * 0.5} ${y + h * 0.42} ${x + w} ${y + h * 0.92}`,
  `M ${x + w} ${y + h * 0.06} Q ${x + w * 0.5} ${y + h * 0.5} ${x} ${y + h * 0.98}`,
];

// seta conectora curvada entre dois pontos
export const arrowPath = (
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  curve = 40
): string => {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  return `M ${x1} ${y1} Q ${mx + nx * curve} ${my + ny * curve} ${x2} ${y2}`;
};

// rabisco-conector da referência (pequeno gancho ondulado, ~60px)
export const squigglePath = (cx: number, cy: number): string =>
  `M ${cx + 34} ${cy - 6} Q ${cx + 10} ${cy - 14} ${cx - 2} ${cy - 2} Q ${cx - 12} ${cy + 8} ${cx - 30} ${cy + 2}`;

// ——— Marca-texto amarelo varrendo a palavra (referência: "considerava") ———
// Renderizar ANTES do texto (fica atrás da tinta).
export const MarkerHighlight: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  delayS: number;
  sweepS?: number;
  color?: string;
  rotate?: number; // acompanha a inclinação da linha manuscrita (medido -7.5° na ref-C)
  blend?: "normal" | "multiply"; // multiply = o amarelo escurece sobre a cena, como marca-texto de verdade
  theme?: Theme;
}> = ({
  x,
  y,
  w,
  h,
  delayS,
  sweepS = 0.4,
  color,
  rotate = 0,
  blend = "normal",
  theme = neutralTheme,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = interpolate(frame, [delayS * fps, (delayS + sweepS) * fps], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        // a varredura tem que acontecer no eixo do texto: gira primeiro, depois cresce
        transform: `rotate(${rotate}deg) scaleX(${p})`,
        transformOrigin: "left center",
        background: color ?? theme.highlight,
        borderRadius: 4,
        opacity: blend === "multiply" ? 1 : 0.95,
        mixBlendMode: blend,
      }}
    />
  );
};

// ——— Selo carimbado ————————————————————————————————————————————————
// Medido em ref-C post-ref-C-2: retângulo amarelo SÓLIDO de bordas retas
// (não é traço de marcador), rotação -12,9°, tipografia brush/carimbo caixa alta
// preta. Estampa por cima de um mockup 0,4–0,6s depois da entrada dele.
// Serve pra VALIDAR/aprovar algo em tela ("TEMOS!", "FEITO", "INCLUÍDO").
export const StampSticker: React.FC<{
  text: string;
  delayS: number;
  x: number;
  y: number;
  size?: number;
  rotate?: number;
  padX?: number;
  padY?: number;
  color?: string; // fundo
  inkColor?: string; // texto
  font?: "marker" | "pen" | "script";
  overshoot?: number; // 1.0 = sem overshoot; a referência bate seco
  theme?: Theme;
}> = ({
  text,
  delayS,
  x,
  y,
  size = 78,
  rotate = -12.9,
  padX = 26,
  padY = 10,
  color,
  inkColor = "#000",
  font = "marker",
  overshoot = 1.06,
  theme = neutralTheme,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - delayS * fps;
  if (t < 0) return null;
  // carimbo: entra grande e assenta em 3 frames (é batida, não spring longo)
  const scale = interpolate(t, [0, 2, 4], [overshoot * 1.18, overshoot, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = interpolate(t, [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: `rotate(${rotate}deg) scale(${scale})`,
        transformOrigin: "center center",
        opacity,
        background: color ?? theme.highlight,
        padding: `${padY}px ${padX}px`,
        fontFamily: FONTS[font],
        fontSize: size,
        lineHeight: 1,
        color: inkColor,
        whiteSpace: "pre",
        boxShadow: "0 6px 18px rgba(0,0,0,0.22)",
      }}
    >
      {text}
    </div>
  );
};

// ——— Pan linear dentro de janela fixa ————————————————————————————————
// O mecanismo do "scroll" da ref-C: um print ALTO da página transladado
// dentro de uma máscara retangular fixa. Medido: 2px/frame = 60px/s, easing
// NENHUM (dedo humano desacelera; isso é interpolate linear).
// Use pra percorrer página, tela de app, thread, tabela — qualquer imagem alta.
export const ScrollPanel: React.FC<{
  src?: string; // imagem alta (staticFile). Alternativa: passar `children`.
  children?: React.ReactNode; // conteúdo próprio pra percorrer (mockup em CSS)
  delayS: number;
  x: number;
  y: number;
  w: number;
  h: number; // a JANELA (recorta)
  imgWidth?: number; // largura de render da imagem; default = w
  fromY?: number; // deslocamento inicial do conteúdo
  speedPxS?: number; // 60 = o medido na referência
  radius?: number;
  enter?: "fade" | "slide" | "cut";
  enterS?: number;
  shadow?: boolean;
}> = ({
  src,
  children,
  delayS,
  x,
  y,
  w,
  h,
  imgWidth,
  fromY = 0,
  speedPxS = 60,
  radius = 26,
  enter = "fade",
  enterS = 0.3,
  shadow = true,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - delayS * fps;
  if (t < 0) return null;
  const appear =
    enter === "cut"
      ? 1
      : interpolate(t, [0, enterS * fps], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
  const dy = fromY + (t / fps) * speedPxS; // LINEAR de propósito
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: enter === "slide" ? y + (1 - appear) * 60 : y,
        width: w,
        height: h,
        overflow: "hidden", // <- a máscara
        borderRadius: radius,
        opacity: appear,
        boxShadow: shadow ? "0 18px 50px rgba(0,0,0,0.30)" : undefined,
      }}
    >
      {src ? (
        <Img
          src={src}
          style={{
            position: "absolute",
            left: 0,
            top: -dy,
            width: imgWidth ?? w,
            display: "block",
          }}
        />
      ) : (
        <div style={{ position: "absolute", left: 0, top: -dy, width: imgWidth ?? w }}>
          {children}
        </div>
      )}
    </div>
  );
};

// ——— Título de passo "flat" (o da referência) ————————————————————
// "#N" preto num chip amarelo + label em texto AMARELO bold caps com
// sombra suave — SEM caixa em volta do label. Posição fixa por vídeo.
export const StepTitleFlat: React.FC<{
  num: number;
  label: string; // aceita \n
  delayS: number;
  x: number;
  y: number;
  size?: number;
  theme?: Theme;
}> = ({ num, label, delayS, x, y, size = 58, theme = neutralTheme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - delayS * fps;
  const pop = spring({ frame: t, fps, config: { damping: 12, stiffness: 210 } });
  const fade = interpolate(t, [1, 7], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        display: "flex",
        alignItems: "flex-start",
        gap: 14,
        fontFamily: FONTS.sans,
        fontWeight: 800,
        fontSize: size,
        lineHeight: 1.08,
        textTransform: "uppercase",
      }}
    >
      <span
        style={{
          background: theme.highlight,
          color: "#111",
          padding: "0px 10px 2px",
          borderRadius: 8,
          transform: `scale(${pop})`,
          opacity: pop > 0.03 ? 1 : 0,
          display: "inline-block",
        }}
      >
        #{num}
      </span>
      <span
        style={{
          color: theme.highlight,
          opacity: fade,
          whiteSpace: "pre-line",
          textShadow: "0 2px 10px rgba(0,0,0,0.35)",
        }}
      >
        {label}
      </span>
    </div>
  );
};

// ——— Título de passo em caixa (variante; a referência usa o flat) ————————
export const StepTitle: React.FC<{
  num: number;
  text: string;
  delayS: number;
  x?: number | "center";
  y: number;
  size?: number;
  enter?: "pop" | "fade";
  rotate?: number;
  theme?: Theme;
}> = ({ num, text, delayS, x = "center", y, size = 56, enter = "pop", rotate = 0, theme = neutralTheme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - delayS * fps;
  const pop = spring({ frame: t, fps, config: { damping: 11, stiffness: 190 } });
  const fade = interpolate(t, [0, 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const visible = enter === "pop" ? (pop > 0.03 ? 1 : 0) : fade;
  const scale = enter === "pop" ? pop : 1;
  return (
    <AbsoluteFill style={x === "center" ? { alignItems: "center" } : undefined}>
      <div
        style={{
          position: "absolute",
          top: y,
          ...(x !== "center" ? { left: x } : {}),
          transform: `scale(${scale}) rotate(${rotate}deg)`,
          opacity: visible,
          background: theme.highlight,
          color: theme.stepText,
          fontFamily: FONTS.sans,
          fontWeight: 800,
          fontSize: size,
          letterSpacing: 1,
          textTransform: "uppercase",
          padding: "14px 34px",
          borderRadius: 14,
          boxShadow: "0 10px 30px rgba(0,0,0,0.28)",
          whiteSpace: "pre-line",
          textAlign: "center",
        }}
      >
        {`#${num} ${text}`}
      </div>
    </AbsoluteFill>
  );
};

// ——— Palavra-destaque em cor (ex.: "15 DIAS" amarelo) ————————————————
export const AccentWord: React.FC<{
  text: string;
  delayS: number;
  x: number;
  y: number;
  size?: number;
  rotate?: number;
  color?: string;
  shadow?: string; // sobre vídeo o default é fraco — passar sombra forte
  theme?: Theme;
}> = ({ text, delayS, x, y, size = 96, rotate = 0, color, shadow, theme = neutralTheme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({
    frame: frame - delayS * fps,
    fps,
    config: { damping: 13, stiffness: 220 },
  });
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: `scale(${pop}) rotate(${rotate}deg)`,
        transformOrigin: "center center",
        opacity: pop > 0.03 ? 1 : 0,
        fontFamily: FONTS.sans,
        fontWeight: 800,
        fontSize: size,
        color: color ?? theme.highlight,
        textShadow: shadow ?? "0 2px 12px rgba(0,0,0,0.25)",
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
};

// ——— Post-it colorido (cor = CATEGORIA, vem do theme.postits) ————————
export const PostItCard: React.FC<{
  text: string;
  delayS: number;
  x: number;
  y: number;
  width?: number;
  size?: number;
  rotate?: number;
  category?: string;
  color?: string;
  theme?: Theme;
}> = ({ text, delayS, x, y, width, size = 34, rotate = 0, category, color, theme = neutralTheme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({
    frame: frame - delayS * fps,
    fps,
    config: { damping: 11, stiffness: 200 },
  });
  const bg =
    color ?? (category ? theme.postits[category] : Object.values(theme.postits)[0]);
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width,
        transform: `scale(${pop}) rotate(${rotate}deg)`,
        transformOrigin: "center center",
        opacity: pop > 0.03 ? 1 : 0,
        background: bg,
        color: theme.cardText,
        fontFamily: FONTS.sans,
        fontWeight: 700,
        fontSize: size,
        lineHeight: 1.25,
        padding: "18px 22px",
        borderRadius: 10,
        boxShadow: "0 8px 22px rgba(0,0,0,0.22)",
        whiteSpace: width ? "normal" : "nowrap",
        textAlign: "left",
      }}
    >
      {text}
    </div>
  );
};

// ——— PiP de vídeo flutuante — "provas flutuando" do gancho ———————————
// Referência: tamanhos VARIADOS, cantos ao redor da pessoa, rotação ±3–5°,
// borda branca; entram em stagger E saem em stagger (pop-out um a um).
export const PipCard: React.FC<{
  src: string;
  delayS: number;
  outS?: number;
  x: number;
  y: number;
  w: number;
  ratio?: number; // h = w * ratio (default 1.33 — card retrato)
  rotate?: number;
}> = ({ src, delayS, outS, x, y, w, ratio = 1.33, rotate = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({
    frame: frame - delayS * fps,
    fps,
    config: { damping: 11, stiffness: 210 },
  });
  const popOut =
    outS != null
      ? 1 -
        spring({
          frame: frame - outS * fps,
          fps,
          config: { damping: 14, stiffness: 260 },
          durationInFrames: 10,
        })
      : 1;
  const scale = pop * popOut;
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: w * ratio,
        transform: `scale(${scale}) rotate(${rotate}deg)`,
        opacity: scale > 0.03 ? 1 : 0,
        borderRadius: 16,
        overflow: "hidden",
        border: "6px solid white",
        boxShadow: "0 12px 34px rgba(0,0,0,0.35)",
      }}
    >
      <Video
        src={staticFile(src)}
        muted
        loop
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </div>
  );
};

// ——— Painel semi-transparente SEM recorte ————————————————————————
export const PanelLite: React.FC<{
  delayS: number;
  x: number;
  y: number;
  w: number;
  h: number;
  enter?: "fade" | "slide";
  radius?: number;
  opacity?: number;
  theme?: Theme;
  children?: React.ReactNode;
}> = ({ delayS, x, y, w, h, enter = "fade", radius = 26, opacity = 1, theme = neutralTheme, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - delayS * fps;
  const p = spring({ frame: t, fps, config: { damping: 16, stiffness: 150 } });
  const fade = interpolate(t, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        left: enter === "slide" ? x + (1 - p) * 80 : x,
        top: y,
        width: w,
        height: h,
        opacity: (enter === "fade" ? fade : p) * opacity,
        background: theme.panelBg,
        borderRadius: radius,
        boxShadow: "0 18px 50px rgba(0,0,0,0.30)",
        padding: 28,
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
};

// ——— Punch de cena (punch-corte, não zoom animado) ————————————————
export const ScenePunch: React.FC<{
  punches: { atS: number; scale: number }[];
  children: React.ReactNode;
}> = ({ punches, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const nowS = frame / fps;
  let scale = 1;
  for (const p of punches) {
    if (nowS >= p.atS) scale = p.scale;
  }
  return (
    <AbsoluteFill style={{ transform: `scale(${scale})`, transformOrigin: "50% 30%" }}>
      {children}
    </AbsoluteFill>
  );
};

// ——— Legenda palavra-a-palavra (modo 2 — usar SÓ quando a referência
// do creator pede; o modo padrão do estilo é SEM caption layer) ————————
export type TimedWord = { w: string; s: number; e: number };

export const WordCaptions: React.FC<{
  words: TimedWord[];
  yPct?: number;
  size?: number;
  maxWordsPerPage?: number;
  theme?: Theme;
}> = ({ words, yPct = 50, size = 64, maxWordsPerPage = 4, theme = neutralTheme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const nowS = frame / fps;

  const pages: TimedWord[][] = [];
  let cur: TimedWord[] = [];
  for (const wd of words) {
    cur.push(wd);
    const endsSentence = /[.!?,]$/.test(wd.w);
    if (cur.length >= maxWordsPerPage || (endsSentence && cur.length >= 2)) {
      pages.push(cur);
      cur = [];
    }
  }
  if (cur.length) pages.push(cur);

  const page = pages.find(
    (p) => nowS >= p[0].s && nowS < (p[p.length - 1].e ?? p[0].s) + 0.12
  );
  if (!page) return null;

  return (
    <AbsoluteFill style={{ alignItems: "center" }}>
      <div
        style={{
          position: "absolute",
          top: `${yPct}%`,
          maxWidth: 950,
          textAlign: "center",
          fontFamily: FONTS.caption,
          fontWeight: 600,
          fontSize: size,
          lineHeight: 1.2,
          textTransform: "uppercase",
          letterSpacing: 1,
        }}
      >
        {page.map((wd, i) => {
          const active = nowS >= wd.s && nowS < wd.e;
          return (
            <span
              key={i}
              style={{
                color: active ? theme.captionActive : theme.captionBase,
                display: "inline-block",
                transform: active ? "scale(1.08)" : "scale(1)",
                WebkitTextStroke: "2px rgba(0,0,0,0.85)",
                textShadow: "0 3px 10px rgba(0,0,0,0.6)",
                marginRight: 14,
              }}
            >
              {wd.w}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export { DrawStroke, WriteOn };

/** Luminância relativa aproximada de uma cor CSS (#rgb, #rrggbb ou rgb/rgba).
 *  Serve para escolher tinta sobre superfície — não para colorimetria. */
function luminanciaDe(cor: string): number {
  let r = 255, g = 255, b = 255;
  const hex = cor.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  const rgb = cor.trim().match(/^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/i);
  if (hex) {
    const h = hex[1].length === 3
      ? hex[1].split("").map((c) => c + c).join("")
      : hex[1];
    r = parseInt(h.slice(0, 2), 16);
    g = parseInt(h.slice(2, 4), 16);
    b = parseInt(h.slice(4, 6), 16);
  } else if (rgb) {
    r = +rgb[1]; g = +rgb[2]; b = +rgb[3];
  }
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

/* ─────────────────────────────────────────────────────────── LowerThird ─────
 * Tarja de identificação que entra deslizando pela esquerda: uma ou duas linhas,
 * com um botão opcional que pulsa uma vez. É o "quem está falando" / "o que é
 * isto" de peça longa, e o lugar canônico de uma chamada de ação discreta.
 *
 * 🔴 POR QUE ELE VIVE AQUI E NÃO NUMA PEÇA. Ele já existia DUAS vezes no repo —
 * uma versão completa num kit de peça e outra reduzida noutra — e não estava no
 * catálogo. A nossa própria regra do segundo uso proíbe exatamente isso: o que é
 * escrito duas vezes é vocabulário, e vocabulário mora no catálogo, temável.
 * As constantes de cor das duas cópias viraram campos de `Theme`.
 */
export const LowerThird: React.FC<{
  linha1: string;
  linha2?: string;
  botao?: string;
  /** y em px do perfil; sem ele, 61,5% da altura (a faixa de terço inferior). */
  y?: number;
  theme?: Theme;
}> = ({ linha1, linha2, botao, y, theme = neutralTheme }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, height } = useVideoConfig();
  // 📐 nenhum valor de formato aqui: o default sai da altura da composição.
  const topo = y ?? Math.round(height * 0.615);
  const s = spring({ frame, fps, config: { damping: 15, mass: 0.6 } });
  const x = interpolate(s, [0, 1], [-460, 0]);
  const out = interpolate(frame, [durationInFrames - 8, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const p = spring({
    frame: frame - Math.round(fps * 0.55),
    fps,
    config: { damping: 9, mass: 0.4 },
  });
  const pulse = 1 + 0.07 * Math.sin(p * Math.PI);
  // 🔴 A TINTA SAI DA LUMINÂNCIA DO PAINEL, não de um campo fixo.
  // `panelBg` é claro em uns temas (rgba(255,255,255,0.93)) e escuro em outros, e
  // `captionBase` é branco em quase todos: cravar `captionBase` aqui deu texto
  // branco sobre painel branco no primeiro preview — ilegível, e invisível para
  // qualquer teste que não olhasse a imagem. É o mesmo defeito que o comentário
  // de `cardText` já documentava noutro tema, repetido por outro caminho.
  const tinta = luminanciaDe(theme.panelBg) > 0.5 ? theme.cardText : theme.captionBase;
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <div style={{ position: "absolute", top: topo, left: 56, transform: `translateX(${x}px)` }}>
        <div
          style={{
            background: theme.panelBg,
            border: `2px solid ${theme.highlight}`,
            borderRadius: 14,
            padding: "14px 22px",
            fontFamily: "Montserrat, system-ui, sans-serif",
            color: tinta,
            fontWeight: 800,
            fontSize: 46,
            letterSpacing: -0.5,
            display: "inline-block",
            boxShadow: "0 8px 30px rgba(0,0,0,0.45)",
          }}
        >
          {linha1}
          {linha2 ? (
            <div style={{ fontSize: 32, fontWeight: 700, color: theme.highlight, marginTop: 4 }}>
              {linha2}
            </div>
          ) : null}
        </div>
        {botao ? (
          <div
            style={{
              marginTop: 14,
              display: "inline-block",
              transform: `scale(${pulse})`,
              transformOrigin: "left center",
              background: theme.highlight,
              color: theme.stepText,
              borderRadius: 12,
              padding: "10px 20px",
              fontFamily: "Montserrat, system-ui, sans-serif",
              fontWeight: 800,
              fontSize: 34,
            }}
          >
            {botao}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

/* ──────────────────────────────────────────────────────────── FlashCorte ────
 * O clarão de transição — e a forma dele importa mais que a existência.
 *
 * 🔴 O QUE NÃO FAZER, MEDIDO: um frame branco chapado NA emenda. É o efeito pior
 * possível: o olho lê como falha de sinal, não como corte com intenção, e num
 * corte que já é jump cut ele CHAMA atenção para a emenda em vez de escondê-la.
 *
 * A receita que funciona é um feixe que LIDERA o corte: começa `lidera` frames
 * ANTES, cresce até o pico exatamente no frame da emenda e apaga logo depois. O
 * clarão então cobre a descontinuidade em vez de anunciá-la, e some antes de o
 * espectador conseguir olhar para ele.
 *
 * Também não é branco: é a cor de destaque do tema com opacidade baixa, sobre um
 * gradiente que abre do centro. Branco puro estoura em qualquer imagem clara.
 *
 * ⚠️ `flash_no_corte` era um interruptor do contrato de estilo QUE NÃO LIGAVA
 * NADA — declarado, validado, viajando no payload, e sem uma linha de
 * implementação do outro lado. Este componente é o outro lado.
 */
export const FlashCorte: React.FC<{
  /** instantes de corte, em segundos na timeline da composição.
   *  Sem ele, o componente pisca UMA vez no meio da própria janela — é o que
   *  faz o card do catálogo se demonstrar sozinho, sem props de sessão. */
  emS?: number[];
  /** quantos frames o clarão começa ANTES do corte */
  lidera?: number;
  /** quantos frames ele leva para apagar depois do pico */
  apaga?: number;
  /** opacidade do pico */
  forca?: number;
  theme?: Theme;
}> = ({ emS, lidera = 2, apaga = 2, forca = 0.42, theme = neutralTheme }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const cortes = emS && emS.length ? emS : [durationInFrames / fps / 2];
  let op = 0;
  for (const s of cortes) {
    const corte = Math.round(s * fps);
    // sobe de (corte − lidera) até `corte`, desce de `corte` até (corte + apaga)
    const o = interpolate(
      frame,
      [corte - lidera, corte, corte + apaga],
      [0, forca, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
    );
    if (o > op) op = o;
  }
  if (op <= 0.001) return null;
  return (
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        opacity: op,
        background:
          `radial-gradient(120% 80% at 50% 50%, ${theme.highlight} 0%, ` +
          `${theme.highlight}00 70%)`,
        mixBlendMode: "screen",
      }}
    />
  );
};

/* ───────────────────────────────────────────────────────────── Headline ─────
 * O gancho de duas linhas, em quatro tratamentos. É o vocabulário que faltava:
 * o catálogo tinha três entradas de gancho e nenhuma delas era um LOOK — eram
 * animações (digitado, fade, anotado). Look e animação são eixos diferentes, e
 * separá-los é o que deixa o creator escolher "quero com cartão" sem herdar uma
 * animação junto.
 *
 *   outline  contorno grosso, sem fundo — some sobre imagem clara se o contorno
 *            for fino, por isso ele é grosso e a sombra fica
 *   card     dentro de um retângulo do painel do tema — o mais legível sobre
 *            qualquer imagem, e o mais "pesado" na composição
 *   realce   marca-texto atrás das palavras, na cor de destaque
 *   misto    linha 1 em card, linha 2 em realce — o degrau assimétrico que
 *            separa afirmação de assinatura
 *
 * 📐 Nenhum px de formato: os tamanhos saem de frações da ALTURA da composição.
 */
export type LookHeadline = "outline" | "card" | "realce" | "misto";

export const Headline: React.FC<{
  linha1?: string;
  linha2?: string;
  look?: LookHeadline;
  /** y como fração da altura; default 0,18 (terço superior, fora da zona de UI) */
  yPct?: number;
  entraS?: number;
  theme?: Theme;
}> = ({
  linha1 = "A frase que segura",
  linha2 = "o primeiro segundo",
  look = "card",
  yPct = 0.18,
  entraS = 0.15,
  theme = neutralTheme,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const s = spring({
    frame: frame - Math.round(entraS * fps),
    fps,
    config: { damping: 16, mass: 0.7 },
  });
  const sobe = interpolate(s, [0, 1], [26, 0]);
  const tamanho1 = Math.round(height * 0.042);
  const tamanho2 = Math.round(height * 0.032);
  const tintaCard = luminanciaDe(theme.panelBg) > 0.5 ? theme.cardText : theme.captionBase;

  const base: React.CSSProperties = {
    fontFamily: "Montserrat, system-ui, sans-serif",
    fontWeight: 800,
    letterSpacing: -0.5,
    lineHeight: 1.1,
    display: "inline-block",
  };
  // ⚠️ O CONTORNO PRECISA CONTRASTAR COM A TINTA, e `inkShadow` não serve: no
  // tema neutro ele é branco translúcido, e o primeiro preview saiu com contorno
  // branco sobre texto branco — o look `outline` sem outline nenhum. O contorno é
  // o OPOSTO da tinta em luminância, sempre.
  const tintaSolta = theme.captionBase;
  const corContorno = luminanciaDe(tintaSolta) > 0.5 ? "#0B0B0B" : "#FFFFFF";
  const contorno: React.CSSProperties = {
    ...base,
    color: tintaSolta,
    WebkitTextStroke: `${Math.max(3, Math.round(height * 0.0045))}px ${corContorno}`,
    paintOrder: "stroke fill",
    textShadow: "0 4px 14px rgba(0,0,0,0.55)",
  };
  const cartao: React.CSSProperties = {
    ...base,
    color: tintaCard,
    background: theme.panelBg,
    borderRadius: 14,
    padding: "10px 20px",
    boxShadow: "0 8px 30px rgba(0,0,0,0.4)",
  };
  const realce: React.CSSProperties = {
    ...base,
    color: theme.stepText,
    background: theme.highlight,
    borderRadius: 8,
    padding: "6px 16px",
    boxShadow: "0 4px 16px rgba(0,0,0,0.28)",
  };
  const estilo1 =
    look === "outline" ? contorno : look === "realce" ? realce : cartao;
  const estilo2 =
    look === "outline" ? contorno : look === "card" ? cartao : realce;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          top: Math.round(height * yPct),
          left: Math.round(width * 0.06),
          width: Math.round(width * 0.88),
          opacity: s,
          transform: `translateY(${sobe}px)`,
        }}
      >
        <div style={{ ...estilo1, fontSize: tamanho1 }}>{linha1}</div>
        {linha2 ? (
          <div style={{ marginTop: 10 }}>
            <div style={{ ...estilo2, fontSize: tamanho2 }}>{linha2}</div>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

/* ────────────────────────────────────────────────────────── CameraSegue ─────
 * A câmera dinâmica: com punch-in aplicado, mantém a LINHA DOS OLHOS num alvo
 * fixo do quadro em vez de deixar a pessoa passear pela borda.
 *
 * Come o `track.json` de `rastrear-rosto.py` (contrato benchmark.track-rosto/v1),
 * que traz um ponto normalizado por frame de AMOSTRA — aqui se interpola para o
 * fps da composição, porque a resolução do movimento é decisão do pré-passo e
 * não do render.
 *
 * 🔴 A REGRA QUE IMPEDE A BORDA PRETA. Com zoom `z`, o deslocamento máximo em
 * cada eixo é `(z − 1) / (2z)` da dimensão — passou disso, aparece fundo. Todo
 * deslocamento é grampeado nesse limite, sempre. É por isso que o seguimento é
 * "gentil": ele não persegue o rosto até o canto, ele acompanha até onde o
 * enquadramento permite e para.
 *
 * ⚠️ E POR ISSO ELE NÃO FUNCIONA SEM ZOOM. Com `z = 1` o limite é 0 e o
 * componente não move nada — de propósito, e não em silêncio: sem margem para
 * deslocar, seguir é impossível.
 */
export type TrackRosto = {
  fps: number;
  pontos: [number, number][] | number[][];
  cobertura?: number;
};

export const CameraSegue: React.FC<{
  track: TrackRosto;
  /** zoom aplicado; 1 = sem punch-in, e aí não há margem para seguir */
  zoom?: number;
  /** onde o olhar deve ficar, em fração do quadro (0,5 / 0,42 = regra de terços alta) */
  alvo?: [number, number];
  /** 0 = não segue · 1 = segue integralmente até o limite */
  forca?: number;
  children?: React.ReactNode;
}> = ({ track, zoom = 1.18, alvo = [0.5, 0.42], forca = 1, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pts = track?.pontos || [];
  if (!pts.length || zoom <= 1) {
    return <AbsoluteFill>{children}</AbsoluteFill>;
  }
  // frame da composição → índice de amostra, com interpolação linear
  const t = (frame / fps) * (track.fps || fps);
  const i = Math.min(pts.length - 1, Math.max(0, Math.floor(t)));
  const j = Math.min(pts.length - 1, i + 1);
  const f = t - i;
  const cx = pts[i][0] + (pts[j][0] - pts[i][0]) * f;
  const cy = pts[i][1] + (pts[j][1] - pts[i][1]) * f;

  // deslocamento que traria o ponto ao alvo, em fração do quadro JÁ AMPLIADO
  const limite = (zoom - 1) / (2 * zoom);
  const dx = Math.max(-limite, Math.min(limite, (alvo[0] - cx) * forca));
  const dy = Math.max(-limite, Math.min(limite, (alvo[1] - cy) * forca));

  return (
    <AbsoluteFill
      style={{
        transform: `scale(${zoom}) translate(${dx * 100}%, ${dy * 100}%)`,
        transformOrigin: "center center",
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
