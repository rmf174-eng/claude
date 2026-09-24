// Perfil de peça no lado Remotion (SPEC-00).
//
// O snapshot é escrito por `perfil.py resolver`, que grava
// <dir-producao>/perfil.json E copia para cá — o mesmo mecanismo que
// estudos/Screencast.tsx:9 já usa com screencast-plan.json.
//
// ⚠️ ESCOPO DELIBERADAMENTE ESTREITO. Leem daqui apenas as composições VIVAS:
// Main, Graphics e HookTest. As 8 constantes `*_FPS` por produção e os
// width/height das composições de produções JÁ ENTREGUES ficam congelados — a
// skill proíbe remontar entrega publicada (edit-video/SKILL.md:62), e migrá-las
// mudaria arquivo aprovado sem ganho nenhum.
//
// A regra que fica: composição NOVA lê de PERFIL; composição de produção
// entregue não se toca.

import perfil from "./data/perfil.json";

export type PerfilPeca = {
  contrato: string;
  nome: string;
  video: {
    aspecto?: string;
    largura: number;
    altura: number;
    fps: number;
    unsharp?: string | null;
  };
  legenda?: {
    ativa?: boolean;
    queimada?: boolean;
    max_palavras_pagina?: number;
    y_pct?: number;
  };
  zonas_ui?: {
    topo_pct: number;
    fundo_pct: number;
    direita_pct: number;
  } | null;
  _producao?: { duracao_s?: number | null } | null;
};

export const PERFIL = perfil as unknown as PerfilPeca;

export const FPS = PERFIL.video.fps;
export const W = PERFIL.video.largura;
export const H = PERFIL.video.altura;
export const VIEWBOX = `0 0 ${W} ${H}`;

// Zonas proibidas em PIXELS, derivadas das frações. `null` quando a peça não toca
// em feed nenhum (VSL num player web, YouTube) — e aí não há UI a evitar.
export const ZONAS_UI =
  PERFIL.zonas_ui == null
    ? null
    : {
        top: Math.round(PERFIL.zonas_ui.topo_pct * H),
        bottom: Math.round(PERFIL.zonas_ui.fundo_pct * H),
        right: Math.round(PERFIL.zonas_ui.direita_pct * W),
      };

// Duração da produção corrente, gravada pelo `resolver` a partir do
// v1-montado.mp4 quando ele existe. Sem ele, `null` — e a composição usa o
// default histórico dela.
export const DURACAO_PRODUCAO_S: number | null =
  PERFIL._producao?.duracao_s ?? null;
