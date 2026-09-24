// Entry point ISOLADO do catálogo de estilos (SPEC-15 §3.4, §9).
//
// 🔴 POR QUE ISOLADO, e não uma entrada no `Root.tsx`:
// `remotion-compositor/SKILL.md` registra o caso — um import quebrado em
// QUALQUER produção derrubou o render de OUTRA produção sem sair um frame, o
// `.mov` antigo ficou no lugar, e a composição ffmpeg seguinte rodou "com
// sucesso" sobre camada gráfica velha. Dois defeitos já corrigidos voltaram para
// o arquivo entregue. O catálogo importa de 6 famílias diferentes; jogá-lo no
// bundle global multiplicaria essa superfície. Entry point próprio, sempre.
//
// Consequência medida e desejada: `npx remotion compositions` (entry padrão
// `src/index.ts`) continua listando exatamente o que listava antes desta spec.

import React from "react";
import { Composition, registerRoot } from "remotion";

import { FPS, W, H } from "./perfil";
import { CatalogoPreview, CatalogoDump } from "./catalogo/Preview";
import { ESTILOS, verificarRegistro } from "./catalogo/estilos";
import { CONTRATO, DUR_PADRAO_S, ESCALA_PREVIEW, serializar } from "./catalogo/tipos";

/**
 * ⚠️ PORTÃO NO IMPORT. Um registro inconsistente derruba o bundle ANTES de
 * qualquer render, com a lista de erros no console. Sucesso silencioso é o pior
 * defeito deste repo: um catálogo verde e errado custa mais que um bundle que
 * não sobe.
 */
const erros = verificarRegistro();
if (erros.length > 0) {
  throw new Error(
    `catálogo de estilos inconsistente (${erros.length}):\n  - ${erros.join("\n  - ")}`
  );
}

const REGISTRO = ESTILOS.map(serializar);

const RootCatalogo: React.FC = () => (
  <>
    <Composition
      id="CatalogoPreview"
      component={CatalogoPreview}
      width={W}
      height={H}
      fps={FPS}
      durationInFrames={Math.round(DUR_PADRAO_S * FPS)}
      defaultProps={{ slug: ESTILOS[0].slug }}
      calculateMetadata={({ props }) => {
        const e = ESTILOS.find((x) => x.slug === props.slug);
        if (!e) throw new Error(`slug fora do catálogo: ${props.slug}`);
        return { durationInFrames: Math.round(e.preview.durS * FPS) };
      }}
    />
    <Composition
      id="CatalogoDump"
      component={CatalogoDump}
      width={W}
      height={H}
      fps={FPS}
      durationInFrames={1}
      defaultProps={{
        contrato: CONTRATO,
        canvas: { largura: W, altura: H, fps: FPS, escala: ESCALA_PREVIEW },
        estilos: REGISTRO,
      }}
    />
  </>
);

registerRoot(RootCatalogo);
