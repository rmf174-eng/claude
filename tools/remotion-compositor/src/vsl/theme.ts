// Tema produto-1 — hexes e tipografia da skill `produto-1-brand` (v1.0, abril 2026).
// Nenhum componente da VSL hardcoda cor: tudo sai daqui.

import { loadFont as loadBricolage } from "@remotion/google-fonts/BricolageGrotesque";
import { loadFont as loadJakarta } from "@remotion/google-fonts/PlusJakartaSans";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";

const bricolage = loadBricolage();
const jakarta = loadJakarta();
const mono = loadMono();

export const SB = {
  // ——— azuis da marca ———
  blue: "#1547FF", // Electric Blue — primária, CTA, afirmação
  blueMid: "#0030E0",
  blueDeep: "#001DB0",
  bluePale: "#EAF0FF",

  // ——— neutros ———
  ink: "#090F1E",
  inkMid: "#374160",
  inkSoft: "#74809A",
  white: "#FFFFFF",

  // ——— negação ———
  // A marca não define cor de erro. Decisão desta produção: NEGAR EM CINZA
  // (`inkSoft`) — mais sóbrio, coerente com "pragmático, sem hype". O vermelho
  // fica reservado ao único beat que é literalmente um alerta (o ciclo do
  // fracasso), pra não gastar o sinal.
  nega: "#74809A",
  alerta: "#E5484D",

  // ——— superfícies sobre vídeo escuro ———
  card: "rgba(9,15,30,0.90)",
  cardBorda: "rgba(21,71,255,0.55)",
  cardBordaNeutra: "rgba(255,255,255,0.14)",
  veu: "rgba(4,7,16,0.80)", // véu do registro PLENO (cena toma a tela)
  sombra: "0 10px 40px rgba(0,0,0,0.55)",
  sombraTexto: "0 3px 12px rgba(0,0,0,0.85)",
} as const;

export const F = {
  display: bricolage.fontFamily, // títulos, chips, números
  sans: jakarta.fontFamily, // corpo, legenda
  mono: mono.fontFamily, // dados, IDs
} as const;

/** Geometria do quadro 16:9 e as zonas medidas por segmentação na v1-base. */
export const Z = {
  W: 1280,
  H: 720,
  /** faixa lateral direita — livre em TODAS as janelas de talking-head medidas */
  lat: { x: 906, y: 150, w: 344, h: 430 },
  /** registro pleno: a cena toma a tela com o véu por baixo */
  pleno: { x: 90, y: 84, w: 1100, h: 552 },
  /** faixa da legenda (não desenhar elemento aqui) */
  legenda: { y: 596, h: 96 },
} as const;

/** Timeline: converte tempo do ORIGINAL pro tempo da v1-base (corte de 2,10s em 93,93s). */
export const t2 = (tOriginal: number): number =>
  tOriginal < 93.933 ? tOriginal : tOriginal - 2.1;
