// Preview de NÍVEL 1 — o mesmo componente do catálogo, com o TEXTO DA PEÇA
// (SPEC-19 §3.2, §3.11).
//
// 🎯 A diferença que esta spec existe para criar: o ref-A mostra sempre a frase
// genérica `CAP_TEXT = 'É assim que sua legenda irá aparecer'`
// (`assets/preview/app.js:189`) — enquanto a regra deles mesmos para gancho é
// *"Always two lines, size fitted to the text"* (`SKILL.md:190`). Ou seja: o
// texto real é justamente o que decide se o estilo funciona ou quebra, e é
// justamente o que o preview deles nunca mostra. Aqui ele entra.
//
// 📐 NENHUM número de estilo mora neste arquivo. Cor, tamanho, peso, yPct e
// timing saem de `LEGENDAS`/`propsDe()` (o registro em `estilos.ts`) e de
// `montarProps()` (o arnês em `Preview.tsx`). O que este arquivo faz é trocar o
// CONTEÚDO e injetar o acento no parâmetro que a própria entrada nomeia
// (`estilo.acento.param`, SPEC-19 §3.8) — sem tabela de tradução e sem lista
// espelhada.
//
// 📏 Canvas, fps e duração vêm da composição (`useVideoConfig`), que os recebe
// do perfil de peça (SPEC-00). Nada de 1080, 1920 ou 0.3333 aqui.

import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import type { Caption } from "@remotion/captions";

import { CaptionLayer, type CaptionStyle } from "../CaptionLayer";
import { Placa } from "./Placas";
import { LEGENDAS } from "./estilos";
import { acharEstilo, montarProps, CatalogoPreview } from "./Preview";
import { propsDe, type Estilo } from "./tipos";

export type PropsPreviewPeca = {
  slug: string;
  /** legenda REAL da peça, já recortada na janela do pior caso (§3.11) */
  captions?: Caption[];
  /** gancho REAL da peça, em duas linhas */
  gancho?: { linha1?: string; linha2?: string } | null;
  /** cor de destaque escolhida; entra no parâmetro que a entrada nomeia */
  acento?: string | null;
  /** override de parâmetro vindo do ajuste fino (diff) */
  parametros?: Record<string, unknown>;
};

/**
 * A injeção do acento. UMA linha, e é o motivo de `acento` ser `{param}` e não
 * booleano: o renderizador não precisa saber qual estilo pinta o quê.
 */
const comAcento = (
  p: Record<string, unknown>,
  e: Estilo,
  acento?: string | null
): Record<string, unknown> => {
  if (!e.acento || !acento) return p;
  return { ...p, [e.acento.param]: acento };
};

/**
 * Legenda com o texto da peça.
 *
 * ⚠️ As cinco linhas abaixo espelham `RenderEstilo` (`Preview.tsx:342-351`), que
 * não é exportado. O que NÃO é duplicado é o que importa: todo número continua
 * vindo de `LEGENDAS[slug]` e de `propsDe(e)` — a mesma fonte que o nível 0 usa.
 * Duplicar a composição do objeto é barato; duplicar os VALORES seria o defeito
 * que o `app.js:182-188` deles confessa.
 */
const LegendaDaPeca: React.FC<{
  e: Estilo;
  captions: Caption[];
  acento?: string | null;
  parametros?: Record<string, unknown>;
}> = ({ e, captions, acento, parametros }) => {
  const p = { ...propsDe(e), ...(parametros ?? {}) };
  const combinaMs = typeof p.combinaMs === "number" ? (p.combinaMs as number) : undefined;
  delete p.combinaMs;
  const estilo = { ...LEGENDAS[e.slug], ...comAcento(p, e, acento) } as CaptionStyle;
  return <CaptionLayer captions={captions} estilo={estilo} combinaMs={combinaMs} />;
};

/**
 * Gancho com o texto da peça.
 *
 * `montarProps` já resolve geometria (do arnês) e parâmetros (do registro). Só o
 * CONTEÚDO é trocado — e só quando ele existe, para que uma peça sem gancho caia
 * na amostra do catálogo em vez de renderizar duas linhas vazias.
 */
const GanchoDaPeca: React.FC<{
  e: Estilo;
  gancho?: { linha1?: string; linha2?: string } | null;
  acento?: string | null;
  parametros?: Record<string, unknown>;
}> = ({ e, gancho, acento, parametros }) => {
  const base = { ...montarProps(e), ...(parametros ?? {}) };
  const conteudo: Record<string, unknown> = {};
  if (gancho?.linha1) conteudo.linha1 = gancho.linha1;
  if (gancho?.linha2) conteudo.linha2 = gancho.linha2;
  const props = comAcento({ ...base, ...conteudo }, e, acento);
  if (!e.componente) throw new Error(`${e.slug}: sem componente para renderizar`);
  return React.createElement(e.componente, props);
};

export const PreviewPeca: React.FC<PropsPreviewPeca> = ({
  slug,
  captions,
  gancho,
  acento,
  parametros,
}) => {
  const e = acharEstilo(slug);
  // A composição existe para provar que ela é dirigida pelo perfil: ler o
  // canvas aqui é o que garante que nenhuma coordenada deste arquivo seja
  // literal. (Também é o que o `--listar` do gerador confere.)
  useVideoConfig();

  /**
   * 🔴 Grupo sem texto que mude o resultado cai no NÍVEL 0, dentro da própria
   * composição. `gramatica`, `tema` e `grafismo` não têm o que fazer com a fala
   * da peça (§3.2 regra 3) — renderizá-los aqui produziria um card idêntico ao
   * do catálogo com o selo "com o texto desta peça" mentindo em cima.
   */
  if (e.grupo === "legenda" && captions && captions.length > 0) {
    return (
      <AbsoluteFill style={{ backgroundColor: "black" }}>
        <Placa tipo={e.preview.placa} />
        <LegendaDaPeca e={e} captions={captions} acento={acento} parametros={parametros} />
      </AbsoluteFill>
    );
  }
  if (e.grupo === "gancho" && (gancho?.linha1 || gancho?.linha2)) {
    return (
      <AbsoluteFill style={{ backgroundColor: "black" }}>
        <Placa tipo={e.preview.placa} />
        <GanchoDaPeca e={e} gancho={gancho} acento={acento} parametros={parametros} />
      </AbsoluteFill>
    );
  }
  return <CatalogoPreview slug={slug} />;
};
