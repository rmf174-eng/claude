// Entry point ISOLADO do preview de NÍVEL 1 (SPEC-19 §3.1, §5).
//
// 🔴 POR QUE ISOLADO, e por que separado do `index-catalogo.tsx`:
// o motivo do isolamento é o mesmo da SPEC-15 (`remotion-compositor/SKILL.md`
// registra o caso — um import quebrado numa produção derrubou o render de
// OUTRA, o `.mov` antigo ficou no lugar e a composição ffmpeg seguinte rodou
// "com sucesso" sobre camada gráfica velha). E é um arquivo NOVO em vez de uma
// composição a mais no `index-catalogo.tsx` porque aquele arquivo é da SPEC-15:
// esta spec não o abre (§5).
//
// Consequência desejada: `npx remotion compositions` (entry padrão
// `src/index.ts`) continua listando exatamente o que listava antes.

import React from "react";
import { Composition, registerRoot } from "remotion";

import { FPS, W, H } from "./perfil";
import { PreviewPeca } from "./catalogo/PreviewPeca";
import { ESTILOS, verificarRegistro } from "./catalogo/estilos";
import { DUR_PADRAO_S } from "./catalogo/tipos";

/**
 * ⚠️ PORTÃO NO IMPORT, igual ao da SPEC-15. Registro inconsistente derruba o
 * bundle ANTES de qualquer render, com a lista de erros no console. Um catálogo
 * verde e errado custa mais que um bundle que não sobe.
 */
const erros = verificarRegistro();
if (erros.length > 0) {
  throw new Error(
    `catálogo de estilos inconsistente (${erros.length}):\n  - ${erros.join("\n  - ")}`
  );
}

/**
 * 📐 width/height/fps VIAJAM NOS PROPS, e `./perfil` é só o default.
 *
 * 🔴 Até 2026-08-10 saíam de `./perfil`, o snapshot que `perfil.py resolver`
 * copiava para `src/data/perfil.json` — um arquivo GLOBAL, dentro da fonte do
 * produto, que valia "a última produção resolvida". Dois defeitos moravam
 * nisso, e a auditoria de 2026-08-10 mediu os dois (A6/A7): a produção assinava
 * caminho absoluto de máquina e nome de creator dentro do pacote (o portão 1 do
 * exportador reprovava, e nenhum export saía), e um vizinho que resolvesse outra produção
 * no meio do lote fazia este gerador produzir card no formato dele.
 *
 * O gerador (`previews-peca.py`) já tem o perfil da PEÇA na mão: agora ele o
 * passa em `inputProps` e MEDE o PNG que voltou contra o canvas que pediu. O
 * dente saiu de "conferir a intenção antes" para "medir o pixel depois", que é
 * a régua que este repo já usa em todo lugar (RD-7).
 */
type CanvasProps = { largura?: number; altura?: number; fps?: number };

const RootGaleria: React.FC = () => (
  <Composition
    id="PreviewPeca"
    component={PreviewPeca}
    width={W}
    height={H}
    fps={FPS}
    durationInFrames={Math.round(DUR_PADRAO_S * FPS)}
    defaultProps={{ slug: ESTILOS[0].slug }}
    calculateMetadata={({ props }) => {
      const e = ESTILOS.find((x) => x.slug === props.slug);
      if (!e) throw new Error(`slug fora do catálogo: ${props.slug}`);
      const c = props as unknown as CanvasProps;
      const fps = c.fps ?? FPS;
      return {
        width: c.largura ?? W,
        height: c.altura ?? H,
        fps,
        durationInFrames: Math.round(e.preview.durS * fps),
      };
    }}
  />
);

registerRoot(RootGaleria);
