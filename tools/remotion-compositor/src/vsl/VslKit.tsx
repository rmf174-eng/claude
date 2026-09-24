import React from "react";
import {
  AbsoluteFill,
  Easing,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { SB, F, Z } from "./theme";

/* ────────────────────────── utilidades de tempo ────────────────────────── */

/** progresso 0→1 de uma rampa em segundos, com easing suave */
export const rampa = (
  frame: number,
  fps: number,
  delayS: number,
  durS = 0.35
): number =>
  interpolate(frame, [delayS * fps, (delayS + durS) * fps], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

/** pop com overshoot leve (entrada padrão de cartão/chip) */
export const usePop = (delayS: number, damping = 16, stiffness = 220) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({
    frame: frame - delayS * fps,
    fps,
    config: { damping, stiffness },
  });
};

/**
 * Grupo com janela e saída em fade.
 * ⚠️ Corte seco pra tela vazia derruba a luminância num frame e LÊ como flicker
 * (feedback do creator-1 na peca-04). Todo grupo sai em fade de 6 frames por padrão.
 */
export const Grupo: React.FC<{
  de: number;
  ate: number;
  saida?: "fade" | "corte";
  children: React.ReactNode;
}> = ({ de, ate, saida = "fade", children }) => {
  const { fps } = useVideoConfig();
  return (
    <Sequence
      from={Math.round(de * fps)}
      durationInFrames={Math.max(1, Math.round((ate - de) * fps))}
      layout="none"
    >
      {saida === "fade" ? <FadeSaida>{children}</FadeSaida> : children}
    </Sequence>
  );
};

const FadeSaida: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const op = interpolate(
    frame,
    [durationInFrames - 6, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  return <AbsoluteFill style={{ opacity: op }}>{children}</AbsoluteFill>;
};

/* ────────────────────────── registro PLENO ────────────────────────── */

/**
 * Véu escuro que deixa a cena conceitual tomar a tela.
 * Não toca o pixel do vídeo (é retângulo na camada alpha) — o vídeo continua
 * visível a ~20% por baixo, então ele segue "presente" enquanto a voz conduz.
 */
export const Veu: React.FC<{ delayS?: number; durS?: number }> = ({
  delayS = 0,
  durS = 0.4,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = rampa(frame, fps, delayS, durS);
  return (
    <AbsoluteFill style={{ background: SB.veu, opacity: p }} />
  );
};

/* ────────────────────────── primitivos ────────────────────────── */

export const Card: React.FC<{
  x: number;
  y: number;
  w: number;
  h?: number;
  delayS: number;
  destaque?: boolean;
  padding?: number;
  children?: React.ReactNode;
}> = ({ x, y, w, h, delayS, destaque = false, padding = 20, children }) => {
  const pop = usePop(delayS);
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        padding,
        boxSizing: "border-box",
        background: SB.card,
        border: `1.5px solid ${destaque ? SB.cardBorda : SB.cardBordaNeutra}`,
        borderRadius: 14,
        boxShadow: SB.sombra,
        opacity: pop > 0.02 ? 1 : 0,
        transform: `scale(${0.94 + 0.06 * Math.min(pop, 1.06)})`,
        transformOrigin: "center center",
      }}
    >
      {children}
    </div>
  );
};

export const Titulo: React.FC<{
  texto: string;
  x: number;
  y: number;
  delayS: number;
  size?: number;
  cor?: string;
  peso?: number;
  align?: "left" | "center" | "right";
  w?: number;
  tracking?: number;
}> = ({
  texto,
  x,
  y,
  delayS,
  size = 54,
  cor = SB.white,
  peso = 800,
  align = "left",
  w,
  tracking = -0.02,
}) => {
  const pop = usePop(delayS, 18, 260);
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        textAlign: align,
        fontFamily: F.display,
        fontWeight: peso,
        fontSize: size,
        lineHeight: 1.02,
        letterSpacing: `${tracking}em`,
        color: cor,
        textShadow: SB.sombraTexto,
        opacity: pop > 0.02 ? 1 : 0,
        transform: `scale(${0.96 + 0.04 * Math.min(pop, 1.05)})`,
        transformOrigin: align === "center" ? "center" : `${align} center`,
        whiteSpace: "pre-line",
      }}
    >
      {texto}
    </div>
  );
};

export const Corpo: React.FC<{
  texto: string;
  x: number;
  y: number;
  delayS: number;
  size?: number;
  cor?: string;
  w?: number;
  peso?: number;
  align?: "left" | "center" | "right";
}> = ({
  texto,
  x,
  y,
  delayS,
  size = 24,
  cor = SB.inkSoft,
  w,
  peso = 500,
  align = "left",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = rampa(frame, fps, delayS, 0.25);
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        textAlign: align,
        fontFamily: F.sans,
        fontWeight: peso,
        fontSize: size,
        lineHeight: 1.4,
        color: cor,
        textShadow: SB.sombraTexto,
        opacity: p,
        whiteSpace: "pre-line",
      }}
    >
      {texto}
    </div>
  );
};

/** pill de rótulo — o átomo do sistema (feature, persona, selo pequeno) */
export const Chip: React.FC<{
  texto: string;
  x: number;
  y: number;
  delayS: number;
  cor?: string;
  fundo?: string;
  size?: number;
  icone?: string;
  w?: number;
}> = ({
  texto,
  x,
  y,
  delayS,
  cor = SB.white,
  fundo = SB.card,
  size = 26,
  icone,
  w,
}) => {
  const pop = usePop(delayS, 14, 240);
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: `${size * 0.42}px ${size * 0.72}px`,
        background: fundo,
        border: `1.5px solid ${
          fundo === SB.blue ? "transparent" : SB.cardBordaNeutra
        }`,
        borderRadius: 999,
        boxShadow: SB.sombra,
        fontFamily: F.display,
        fontWeight: 700,
        fontSize: size,
        letterSpacing: "0.02em",
        color: cor,
        whiteSpace: "nowrap",
        opacity: pop > 0.02 ? 1 : 0,
        transform: `scale(${0.9 + 0.1 * Math.min(pop, 1.08)})`,
        transformOrigin: "left center",
      }}
    >
      {icone ? <span style={{ fontSize: size * 1.05 }}>{icone}</span> : null}
      {texto}
    </div>
  );
};

/** traço mão-livre desenhando (dashoffset) em coordenadas 1280x720 */
export const Traco: React.FC<{
  d: string;
  delayS: number;
  durS?: number;
  cor?: string;
  largura?: number;
  ponta?: boolean;
}> = ({ d, delayS, durS = 0.32, cor = SB.white, largura = 5, ponta = false }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = rampa(frame, fps, delayS, durS);
  const L = 2000;
  return (
    <svg
      viewBox={`0 0 ${Z.W} ${Z.H}`}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
    >
      <path
        d={d}
        fill="none"
        stroke={cor}
        strokeWidth={largura}
        strokeLinecap="round"
        strokeDasharray={L}
        strokeDashoffset={L * (1 - p)}
        style={{ filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.7))" }}
      />
      {ponta && p > 0.97 ? <PontaSeta d={d} cor={cor} /> : null}
    </svg>
  );
};

const PontaSeta: React.FC<{ d: string; cor: string }> = ({ d, cor }) => {
  // extrai o último ponto e a direção aproximada do path pra desenhar a farpa
  const nums = d.match(/-?\d+(\.\d+)?/g)?.map(Number) ?? [];
  if (nums.length < 4) return null;
  const [x2, y2] = [nums[nums.length - 2], nums[nums.length - 1]];
  const [x1, y1] = [nums[nums.length - 4], nums[nums.length - 3]];
  const a = Math.atan2(y2 - y1, x2 - x1);
  const L = 20;
  const p1 = [x2 - L * Math.cos(a - 0.42), y2 - L * Math.sin(a - 0.42)];
  const p2 = [x2 - L * Math.cos(a + 0.42), y2 - L * Math.sin(a + 0.42)];
  return (
    <path
      d={`M ${p1[0]} ${p1[1]} L ${x2} ${y2} L ${p2[0]} ${p2[1]}`}
      fill="none"
      stroke={cor}
      strokeWidth={5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
};

/** item de lista que é NEGADO: entra, e no delay do risco é tachado */
export const ItemRiscado: React.FC<{
  texto: string;
  x: number;
  y: number;
  delayS: number;
  riscoS: number;
  size?: number;
  largura?: number;
}> = ({ texto, x, y, delayS, riscoS, size = 34, largura = 300 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = usePop(delayS, 14, 240);
  const morto = rampa(frame, fps, riscoS, 0.3);
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: x,
          top: y,
          fontFamily: F.display,
          fontWeight: 700,
          fontSize: size,
          letterSpacing: "0.01em",
          // a cor esmaece junto com o risco, mas para num cinza CLARO (#B9C0D0):
          // sobre fundo escuro o `inkSoft` puro (#74809A) fica ilegível — medido
          // no still f264, os três itens negados sumiam no cenário
          color: `rgb(${255 - 70 * morto},${255 - 63 * morto},${255 - 47 * morto})`,
          textShadow: SB.sombraTexto,
          opacity: pop > 0.02 ? 1 : 0,
          transform: `scale(${0.93 + 0.07 * Math.min(pop, 1.07)})`,
          transformOrigin: "left center",
          whiteSpace: "nowrap",
        }}
      >
        {texto}
      </div>
      <Traco
        d={risco(x - 6, y + size * 0.62, largura)}
        delayS={riscoS}
        durS={0.28}
        cor={SB.nega}
        largura={4}
      />
    </>
  );
};

/* ───────────────── geradores de path (coords 1280x720) ───────────────── */

/** tachado levemente ondulado */
export const risco = (x: number, y: number, w: number): string => {
  const dy = -4;
  return `M ${x} ${y} Q ${x + w * 0.28} ${y + dy - 4} ${x + w * 0.52} ${y + dy + 2} Q ${
    x + w * 0.78
  } ${y + dy + 6} ${x + w} ${y + dy - 1}`;
};

/** seta curvada entre dois pontos */
export const seta = (
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  curva = 30
): string => {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  return `M ${x1} ${y1} Q ${mx - (dy / len) * curva} ${my + (dx / len) * curva} ${x2} ${y2}`;
};

/** elipse mão-livre fechada (4 quadráticas — nunca <ellipse>) */
export const circulo = (
  cx: number,
  cy: number,
  rx: number,
  ry: number
): string =>
  `M ${cx + rx * 0.62} ${cy - ry} Q ${cx + rx} ${cy - ry * 0.9} ${cx + rx * 0.96} ${cy + ry * 0.1} ` +
  `Q ${cx + rx * 0.88} ${cy + ry} ${cx - rx * 0.1} ${cy + ry * 0.96} ` +
  `Q ${cx - rx} ${cy + ry * 0.86} ${cx - rx * 0.94} ${cy - ry * 0.06} ` +
  `Q ${cx - rx * 0.82} ${cy - ry} ${cx + rx * 0.7} ${cy - ry * 0.94}`;

/* ────────────────────────── marcas de estado ────────────────────────── */

export const Check: React.FC<{
  x: number;
  y: number;
  delayS: number;
  size?: number;
  cor?: string;
}> = ({ x, y, delayS, size = 34, cor = SB.blue }) => (
  <Traco
    d={`M ${x} ${y + size * 0.52} L ${x + size * 0.34} ${y + size * 0.86} L ${
      x + size
    } ${y + size * 0.1}`}
    delayS={delayS}
    durS={0.2}
    cor={cor}
    largura={Math.max(4, size * 0.16)}
  />
);

export const Xis: React.FC<{
  x: number;
  y: number;
  delayS: number;
  size?: number;
  cor?: string;
}> = ({ x, y, delayS, size = 34, cor = SB.nega }) => (
  <>
    <Traco
      d={`M ${x} ${y} L ${x + size} ${y + size}`}
      delayS={delayS}
      durS={0.16}
      cor={cor}
      largura={Math.max(4, size * 0.15)}
    />
    <Traco
      d={`M ${x + size} ${y} L ${x} ${y + size}`}
      delayS={delayS + 0.11}
      durS={0.16}
      cor={cor}
      largura={Math.max(4, size * 0.15)}
    />
  </>
);

/* ────────────────────────── bolha de WhatsApp ────────────────────────── */

/**
 * A citação do cliente na forma NATIVA do produto: balão de mensagem.
 * `digitando` faz o balão de "..." aparecer antes, como numa conversa real.
 */
export const BolhaWA: React.FC<{
  texto: string;
  x: number;
  y: number;
  w: number;
  delayS: number;
  hora?: string;
  digitandoS?: number;
  size?: number;
}> = ({ texto, x, y, w, delayS, hora = "09:14", digitandoS = 0, size = 24 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = usePop(delayS, 15, 200);
  const sobe = interpolate(pop, [0, 1], [26, 0]);
  const digOp =
    digitandoS > 0
      ? rampa(frame, fps, digitandoS, 0.2) *
        (1 - rampa(frame, fps, delayS - 0.08, 0.12))
      : 0;
  return (
    <>
      {digitandoS > 0 ? (
        <div
          style={{
            position: "absolute",
            left: x,
            top: y,
            padding: "14px 20px",
            background: "#1F2C34",
            borderRadius: "16px 16px 16px 4px",
            opacity: digOp,
            display: "flex",
            gap: 6,
          }}
        >
          {[0, 1, 2].map((i) => {
            const t = (frame / fps) * 2.6 + i * 0.5;
            const o = 0.35 + 0.65 * Math.max(0, Math.sin(t * Math.PI));
            return (
              <span
                key={i}
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: 999,
                  background: `rgba(255,255,255,${o})`,
                }}
              />
            );
          })}
        </div>
      ) : null}
      <div
        style={{
          position: "absolute",
          left: x,
          top: y,
          width: w,
          padding: "16px 18px 10px",
          boxSizing: "border-box",
          background: "#1F2C34",
          borderRadius: "16px 16px 16px 4px",
          boxShadow: SB.sombra,
          opacity: pop > 0.02 ? 1 : 0,
          transform: `translateY(${sobe}px)`,
          fontFamily: F.sans,
          fontWeight: 400,
          fontSize: size,
          lineHeight: 1.34,
          color: "#E9EDEF",
        }}
      >
        {texto}
        <div
          style={{
            marginTop: 6,
            textAlign: "right",
            fontSize: size * 0.62,
            color: "rgba(233,237,239,0.6)",
          }}
        >
          {hora} <span style={{ color: "#53BDEB" }}>✓✓</span>
        </div>
      </div>
    </>
  );
};

/* ────────────────────────── selo / badge grande ────────────────────────── */

export const Badge: React.FC<{
  linha1: string;
  linha2: string;
  x: number;
  y: number;
  delayS: number;
  w?: number;
  cor?: string;
}> = ({ linha1, linha2, x, y, delayS, w = 520, cor = SB.blue }) => {
  const pop = usePop(delayS, 13, 190);
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        padding: "22px 30px",
        boxSizing: "border-box",
        background: SB.card,
        border: `2px solid ${cor}`,
        borderRadius: 16,
        boxShadow: `0 12px 44px rgba(21,71,255,0.28), ${SB.sombra}`,
        opacity: pop > 0.02 ? 1 : 0,
        transform: `scale(${0.88 + 0.12 * Math.min(pop, 1.09)})`,
        transformOrigin: "center center",
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontFamily: F.sans,
          fontWeight: 600,
          fontSize: 20,
          letterSpacing: "0.16em",
          color: cor,
          textTransform: "uppercase",
        }}
      >
        {linha1}
      </div>
      <div
        style={{
          marginTop: 4,
          fontFamily: F.display,
          fontWeight: 800,
          fontSize: 46,
          letterSpacing: "-0.03em",
          color: SB.white,
          lineHeight: 1.05,
        }}
      >
        {linha2}
      </div>
    </div>
  );
};

/* ────────────────────────── CTA ────────────────────────── */

export const BotaoCta: React.FC<{
  texto: string;
  delayS: number;
  y?: number;
  w?: number;
}> = ({ texto, delayS, y = 556, w = 540 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = usePop(delayS, 12, 180);
  // micro-bounce de 2 ciclos depois de entrar (chama o clique sem ser pisca-pisca)
  const t = (frame - (delayS + 0.5) * fps) / fps;
  const bounce =
    t > 0 && t < 1.6 ? Math.sin(t * Math.PI * 2.4) * 4 * (1 - t / 1.6) : 0;
  return (
    <div
      style={{
        position: "absolute",
        left: (Z.W - w) / 2,
        top: y,
        width: w,
        padding: "20px 28px",
        boxSizing: "border-box",
        background: SB.blue,
        borderRadius: 12,
        boxShadow: `0 14px 46px rgba(21,71,255,0.45)`,
        textAlign: "center",
        fontFamily: F.display,
        fontWeight: 800,
        fontSize: 34,
        letterSpacing: "-0.01em",
        color: SB.white,
        opacity: pop > 0.02 ? 1 : 0,
        transform: `scale(${0.9 + 0.1 * Math.min(pop, 1.08)}) translateY(${bounce}px)`,
        transformOrigin: "center center",
      }}
    >
      {texto}
    </div>
  );
};

/** seta apontando pra baixo, pro botão real da PÁGINA (abaixo do player) */
export const SetaBaixo: React.FC<{ delayS: number; x?: number; y?: number }> = ({
  delayS,
  x = Z.W / 2,
  y = 640,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = rampa(frame, fps, delayS, 0.3);
  const t = (frame - delayS * fps) / fps;
  const dy = t > 0 ? Math.sin(t * Math.PI * 1.6) * 7 : 0;
  return (
    <div style={{ position: "absolute", inset: 0, opacity: p }}>
      <svg
        viewBox={`0 0 ${Z.W} ${Z.H}`}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      >
        <g transform={`translate(0 ${dy})`}>
          <path
            d={`M ${x} ${y - 42} L ${x} ${y + 10}`}
            stroke={SB.blue}
            strokeWidth={7}
            strokeLinecap="round"
          />
          <path
            d={`M ${x - 17} ${y - 8} L ${x} ${y + 12} L ${x + 17} ${y - 8}`}
            fill="none"
            stroke={SB.blue}
            strokeWidth={7}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      </svg>
    </div>
  );
};

/* ────────────────────────── transição de ato ────────────────────────── */

/**
 * Wipe que marca virada de ato. Nesta produção ele tem uma segunda função:
 * cobrir os 8 frames de talking-head que sobram entre a emenda de áudio
 * (93,93s) e o corte de cena original pro screencast (94,20s).
 */
export const WipeAto: React.FC<{
  delayS: number;
  durS?: number;
  cor?: string;
}> = ({ delayS, durS = 0.42, cor = SB.blue }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = interpolate(frame, [delayS * fps, (delayS + durS) * fps], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  // duas metades que entram, cobrem e saem — cobertura total no meio da rampa
  const cobre = 1 - Math.abs(p - 0.5) * 2;
  const desl = interpolate(p, [0, 1], [-Z.W, Z.W]);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `linear-gradient(100deg, transparent 0%, ${cor} 22%, ${SB.ink} 50%, ${cor} 78%, transparent 100%)`,
          transform: `translateX(${desl}px)`,
          opacity: 0.15 + 0.85 * cobre,
        }}
      />
    </AbsoluteFill>
  );
};
