// O ARNÊS de preview do catálogo (SPEC-15 §3.6).
//
// 🎯 A diferença que importa: o ref-A REIMPLEMENTOU cada estilo em DOM/CSS,
// copiando os números do render à mão (`assets/preview/app.js:182-188`) e até
// escreveu um solver de bézier para imitar o easing do Remotion. Duas
// implementações do mesmo look é uma classe de bug garantida. Aqui o preview é
// renderizado PELO PRÓPRIO COMPONENTE — fiel por construção, impossível de
// dessincronizar.
//
// 📐 Nenhuma dimensão literal: canvas, posições e geometria saem de `PERFIL`.
// A ESCALA do preview é do OUTPUT (`--scale`), nunca da composição — baixar
// width/height quebraria todo `fontSize` e toda coordenada de path dos
// componentes (§9).

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

import { W, H } from "../perfil";
import { neutralTheme, type Theme } from "../themes";
import { CaptionLayer, type CaptionStyle } from "../CaptionLayer";
import {
  AccentWord,
  PostItCard,
  StepTitleFlat,
  underlinePath,
  loopCirclePath,
  strikePath,
  strikeXPaths,
  arrowPath,
  squigglePath,
} from "../MotionKit";

import { Placa } from "./Placas";
import { ESTILOS, LEGENDAS, TEMAS } from "./estilos";
import { CAPS_AMOSTRA, GANCHO_AMOSTRA, ROTULOS_AMOSTRA } from "./amostra";
import { DELAY_PREVIEW_S, propsDe, type Estilo } from "./tipos";

/** Tema com que todo preview de gancho/grafismo é pintado. */
const TEMA_PREVIEW: Theme = neutralTheme;

export const acharEstilo = (slug: string): Estilo => {
  const e = ESTILOS.find((x) => x.slug === slug);
  if (!e) throw new Error(`slug fora do catálogo: ${slug}`);
  return e;
};

/* ───────────────────── geometria e conteúdo do preview ─────────────────────
 * Posição e texto NÃO são estilo: são da peça. Por isso ficam aqui, no arnês, e
 * não em `estilos.ts` — o `catalogo.json` que a galeria lê não carrega nem um
 * `x` nem uma palavra de conteúdo.
 */
const CAMINHOS: Record<string, string> = {
  sublinhado: underlinePath(W * 0.16, H * 0.52, W * 0.68),
  circulo: loopCirclePath(W * 0.5, H * 0.48, W * 0.3, H * 0.06),
  risco: strikePath(W * 0.16, H * 0.5, W * 0.68),
  xis: strikeXPaths(W * 0.24, H * 0.4, W * 0.52, H * 0.16)[0],
  seta: arrowPath(W * 0.2, H * 0.58, W * 0.78, H * 0.44),
  rabisco: squigglePath(W * 0.5, H * 0.5),
};

const RECHEIO: Record<string, React.ReactNode> = {
  "painel-rolante": (
    <div style={{ padding: W * 0.03, width: "100%", boxSizing: "border-box" }}>
      {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
        <div
          key={i}
          style={{
            height: H * 0.05,
            marginBottom: H * 0.018,
            borderRadius: W * 0.012,
            background: `rgba(255,255,255,${0.9 - i * 0.07})`,
          }}
        />
      ))}
    </div>
  ),
  "painel-lite": (
    <div
      style={{
        padding: W * 0.04,
        fontFamily: "system-ui, sans-serif",
        fontSize: W * 0.045,
        color: TEMA_PREVIEW.cardText,
      }}
    >
      {ROTULOS_AMOSTRA.medio}
    </div>
  ),
  "mockup-janela-mac": (
    <div style={{ padding: W * 0.03 }}>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            height: H * 0.028,
            marginBottom: H * 0.014,
            width: i % 2 === 0 ? "78%" : "52%",
            borderRadius: W * 0.008,
            background: "rgba(0,0,0,0.22)",
          }}
        />
      ))}
    </div>
  ),
};

const geometriaDe = (e: Estilo): Record<string, unknown> => {
  const d = DELAY_PREVIEW_S;
  switch (e.slug) {
    case "manuscrito-write-on":
      return { text: ROTULOS_AMOSTRA.medio, delayS: d, x: W * 0.12, y: H * 0.44, width: W * 0.76, theme: TEMA_PREVIEW };
    case "frase-que-troca":
      return {
        items: [
          { text: "primeira amostra", atS: d },
          { text: "segunda amostra", atS: 1.6 },
        ],
        toS: 2.9,
        x: W * 0.12,
        y: H * 0.44,
        width: W * 0.76,
        theme: TEMA_PREVIEW,
      };
    case "marca-texto":
      return { x: W * 0.18, y: H * 0.45, w: W * 0.64, h: H * 0.042, delayS: d, theme: TEMA_PREVIEW };
    case "selo-carimbado":
      return { text: ROTULOS_AMOSTRA.selo, delayS: d, x: W * 0.26, y: H * 0.43, theme: TEMA_PREVIEW };
    case "painel-rolante":
      return { delayS: d, x: W * 0.14, y: H * 0.28, w: W * 0.72, h: H * 0.34, children: RECHEIO["painel-rolante"] };
    case "passo-numerado":
      return { num: 1, label: ROTULOS_AMOSTRA.passo, delayS: d, x: W * 0.12, y: H * 0.44, theme: TEMA_PREVIEW };
    case "palavra-acento":
      return { text: ROTULOS_AMOSTRA.curto, delayS: d, x: W * 0.2, y: H * 0.44, theme: TEMA_PREVIEW };
    case "postit":
      return { text: ROTULOS_AMOSTRA.medio, delayS: d, x: W * 0.24, y: H * 0.4, width: W * 0.5, theme: TEMA_PREVIEW };
    case "painel-lite":
      return { delayS: d, x: W * 0.13, y: H * 0.36, w: W * 0.74, h: H * 0.2, theme: TEMA_PREVIEW, children: RECHEIO["painel-lite"] };
    case "traco-mao-livre":
      return { delayS: d, color: TEMA_PREVIEW.highlight, localBox: `0 0 ${W} ${H}` };
    case "mockup-janela-mac":
      return { delayS: d, x: W * 0.1, y: H * 0.32, w: W * 0.8, children: RECHEIO["mockup-janela-mac"] };
    case "mockup-lista-mensagens":
      return {
        delayS: d,
        x: W * 0.16,
        y: H * 0.28,
        w: W * 0.68,
        rows: [
          { name: "Contato 1", preview: "mensagem de amostra", badge: 2 },
          { name: "Contato 2", preview: "mensagem de amostra" },
          { name: "Contato 3", preview: "mensagem de amostra", badge: 1 },
        ],
        rowsAtS: [d + 0.2, d + 0.5, d + 0.8],
      };
    case "mockup-banner-chamada":
      return { delayS: d, x: W * 0.16, y: H * 0.4, w: W * 0.68, name: "Contato 1", subtitle: ROTULOS_AMOSTRA.curto };
    case "mockup-calendario":
      return { delayS: d, theme: TEMA_PREVIEW };
    case "hook-titulo-typeon":
    case "hook-titulo-fade":
      return { ...GANCHO_AMOSTRA, startS: d, y: Math.round(H * 0.14) };
    default:
      return { delayS: d, theme: TEMA_PREVIEW };
  }
};

/** props finais do componente: geometria + conteúdo do arnês, params do registro por cima. */
export const montarProps = (e: Estilo): Record<string, unknown> => {
  const base = geometriaDe(e);
  const p = propsDe(e);
  if (e.slug === "traco-mao-livre") {
    const ger = String(p.gerador ?? "sublinhado");
    delete p.gerador;
    return { ...base, ...p, d: CAMINHOS[ger] ?? CAMINHOS.sublinhado };
  }
  if (e.slug === "postit" && p.category === "") delete p.category;
  return { ...base, ...p };
};

/* ───────────────────────── simulação de gramática ─────────────────────────
 * `gramatica` não é componente React: mora na EDL (recorte por segmento) ou no
 * ffmpeg (split-screen). O card SIMULA o efeito sobre a placa, e a entrada diz
 * isso em `oQuePinta`. É a única coisa do catálogo que não é o próprio código
 * de produção rodando — e está declarado.
 */
const GramaticaSim: React.FC<{ e: Estilo }> = ({ e }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const p = propsDe(e);
  const num = (k: string, dflt: number) =>
    typeof p[k] === "number" ? (p[k] as number) : dflt;

  if (e.slug === "split-screen-esfumacado") {
    const desloca = num("desloca_base", 25) / 100;
    const opaco = num("opaco", 34) / 100;
    const fim = num("fim", 51) / 100;
    const entra = Math.min(1, Math.max(0, (t - DELAY_PREVIEW_S) / 0.6));
    return (
      <AbsoluteFill>
        <AbsoluteFill style={{ transform: `translateY(${desloca * H * entra}px)` }}>
          <Placa tipo={e.preview.placa} />
        </AbsoluteFill>
        <AbsoluteFill
          style={{
            opacity: entra,
            WebkitMaskImage: `linear-gradient(180deg, rgba(0,0,0,1) 0%, rgba(0,0,0,1) ${
              opaco * 100
            }%, rgba(0,0,0,0) ${fim * 100}%)`,
            maskImage: `linear-gradient(180deg, rgba(0,0,0,1) 0%, rgba(0,0,0,1) ${
              opaco * 100
            }%, rgba(0,0,0,0) ${fim * 100}%)`,
          }}
        >
          {/* ⚠️ A placa do apoio é `vazia` (xadrez), não `paisagem`: medido no
              primeiro lote — com duas placas em degradê cinza o split ficava
              INVISÍVEL no card, porque a máscara corta a paisagem justo na faixa
              de céu uniforme. O xadrez lê na hora como "outro material". */}
          <Placa tipo="vazia" />
        </AbsoluteFill>
        <Leitura
          texto={`base +${Math.round(desloca * 100)}% · rampa ${Math.round(
            opaco * 100
          )}→${Math.round(fim * 100)}%`}
        />
      </AbsoluteFill>
    );
  }

  let escala = 1;
  if (e.slug === "plano-fixo") {
    escala = num("zoom", 1.0);
  } else if (e.slug === "plano-alternado") {
    const troca = num("trocaS", 2.2);
    const fase = Math.floor(t / troca) % 2;
    escala = fase === 0 ? num("zoomA", 1.0) : num("zoomB", 1.27);
  } else if (e.slug === "punch-pontual") {
    const emS = num("emS", 1.2);
    const rampa = Math.max(0.01, num("rampaS", 0.45));
    const k = Math.min(1, Math.max(0, (t - emS) / rampa));
    escala = 1 + (num("zoom", 1.27) - 1) * k;
  }

  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <AbsoluteFill style={{ transform: `scale(${escala})`, transformOrigin: "center center" }}>
        <Placa tipo={e.preview.placa} />
      </AbsoluteFill>
      <Leitura texto={`${escala.toFixed(2).replace(".", ",")}×`} />
    </AbsoluteFill>
  );
};

/**
 * Leitura do parâmetro simulado, só em `gramatica`.
 *
 * ⚠️ Por que existe: medido no primeiro lote de stills — `plano-fixo` e
 * `plano-alternado` na fase nativa produzem cards PIXEL A PIXEL iguais, porque a
 * gramática não pinta nada. Um card indistinguível de outro é um preview que
 * mente por omissão. Aqui a chapa É a simulação (a entrada declara `camada: edl`
 * / `pixel`, ou seja: isto não é desenhado na peça), então rotular o número
 * simulado informa em vez de enganar. Nenhum outro grupo ganha rótulo.
 */
const Leitura: React.FC<{ texto: string }> = ({ texto }) => (
  <div
    style={{
      position: "absolute",
      left: W * 0.035,
      bottom: H * 0.05,
      padding: `${H * 0.012}px ${W * 0.018}px`,
      borderRadius: W * 0.008,
      background: "rgba(0,0,0,0.62)",
      color: "#FFFFFF",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: W * 0.026,
      letterSpacing: 1,
    }}
  >
    {texto}
  </div>
);

/* ─────────────────────────── cartão de tema ─────────────────────────── */
const CartaoTema: React.FC<{ e: Estilo }> = ({ e }) => {
  const tema = TEMAS[e.slug];
  const d = DELAY_PREVIEW_S;
  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          background: tema.panelBg,
          top: H * 0.2,
          bottom: H * 0.2,
          left: W * 0.07,
          right: W * 0.07,
          borderRadius: W * 0.04,
        }}
      />
      <StepTitleFlat
        num={1}
        label={ROTULOS_AMOSTRA.passo}
        delayS={d}
        x={W * 0.12}
        y={H * 0.25}
        theme={tema}
      />
      <AccentWord
        text={ROTULOS_AMOSTRA.curto}
        delayS={d + 0.15}
        x={W * 0.12}
        y={H * 0.42}
        theme={tema}
      />
      <PostItCard
        text={ROTULOS_AMOSTRA.medio}
        delayS={d + 0.3}
        x={W * 0.14}
        y={H * 0.56}
        width={W * 0.5}
        theme={tema}
      />
      <div
        style={{
          position: "absolute",
          left: W * 0.12,
          top: H * 0.72,
          fontFamily: "system-ui, sans-serif",
          fontSize: W * 0.038,
          letterSpacing: 2,
          color: tema.ink,
          textShadow: `0 2px 8px ${tema.inkShadow}`,
        }}
      >
        {e.nome}
      </div>
    </AbsoluteFill>
  );
};

/* ─────────────────────────── despacho por grupo ─────────────────────────── */
const RenderEstilo: React.FC<{ e: Estilo }> = ({ e }) => {
  if (e.grupo === "legenda") {
    const base = LEGENDAS[e.slug];
    const p = propsDe(e);
    const combinaMs =
      typeof p.combinaMs === "number" ? (p.combinaMs as number) : undefined;
    delete p.combinaMs;
    const estilo = { ...base, ...p } as CaptionStyle;
    return (
      <CaptionLayer captions={CAPS_AMOSTRA} estilo={estilo} combinaMs={combinaMs} />
    );
  }
  if (e.grupo === "tema") return <CartaoTema e={e} />;
  if (!e.componente) throw new Error(`${e.slug}: sem componente para renderizar`);
  return React.createElement(e.componente, montarProps(e));
};

export const CatalogoPreview: React.FC<{ slug: string }> = ({ slug }) => {
  const e = acharEstilo(slug);
  if (e.grupo === "gramatica") {
    return (
      <AbsoluteFill style={{ backgroundColor: "black" }}>
        <GramaticaSim e={e} />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <Placa tipo={e.preview.placa} />
      <RenderEstilo e={e} />
    </AbsoluteFill>
  );
};

/**
 * A ponte TS→Python (§4.3). O registro serializado viaja em `defaultProps` desta
 * composição; o gerador lê por `getCompositions()` e nunca faz parse de
 * TypeScript. O componente em si só precisa existir.
 */
export const CatalogoDump: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "black" }} />
);
