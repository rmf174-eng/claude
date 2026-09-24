// O `Root.tsx` do PRODUTO — o registro de composições que o pacote entrega.
//
// 🔴 POR QUE ESTE ARQUIVO EXISTE
// O `Root.tsx` da nossa árvore registra 20+ composições de peças nomeadas, e é
// `nunca_sai` por direito: entregá-lo seria entregar o inventário das produções.
// Só que `src/index.ts` faz `import { Root } from "./Root"`, e sem nenhum Root o
// bundle do produto não sobe — `remotion studio` e `remotion render` falham no
// primeiro import. Foi assim até 2026-08-09, e nenhum portão via: o Portão 4 só
// conferia link de Markdown.
//
// A saída não foi afrouxar o corte nem fazer o cliente escrever o arquivo: são
// DOIS Roots, o nosso e este, e `MANIFESTO.export.substituicoes` escolhe. Este
// entra no export como `src/Root.tsx`.
//
// O que entra aqui: composição de MECANISMO, que funciona sem produção nenhuma
// no disco. Peça própria do cliente entra do mesmo jeito que a nossa entra na
// nossa árvore — acrescentando um `<Composition>` aqui, ou (melhor, e é o que a
// nossa experiência mandou) num entry point isolado como os três abaixo.
//
// ⚠️ ENTRY POINTS ISOLADOS, que NÃO passam por aqui e já vão no pacote:
//   src/index-catalogo.tsx   o catálogo de estilos
//   src/index-galeria.tsx    a galeria com preview renderizado
//   src/index-partitura.tsx  a partitura de legenda
// O motivo está no cabeçalho do `index-catalogo.tsx` e é medido: um import
// quebrado em QUALQUER composição derruba o bundle inteiro e o render falha sem
// sair um frame — com o `.mov` antigo ficando no lugar e a composição ffmpeg
// seguinte rodando "com sucesso" sobre camada gráfica velha.

import React from "react";
import { Composition } from "remotion";

import { Graphics, Main, FPS, DURATION_S } from "./Main";
import { W as PERFIL_W, H as PERFIL_H } from "./perfil";
import { HookTest, HOOK_TEST_DURATION_S } from "./HookLettering";
import { SfxDemo, SFX_DEMO_DURATION_S } from "./SfxDemo";

export const Root: React.FC = () => {
  return (
    <>
      {/* Preview: vídeo + camada gráfica. `public/v1-graded.mp4` é o bruto
          montado da peça corrente; a duração vem do perfil resolvido. */}
      <Composition
        id="Main"
        component={Main}
        durationInFrames={Math.round(DURATION_S * FPS)}
        fps={FPS}
        width={PERFIL_W}
        height={PERFIL_H}
      />
      {/* Entrega: SÓ a camada gráfica, fundo transparente. É esta que se
          renderiza em ProRes 4444 e se compõe no ffmpeg por cima do v1-sdr —
          os pixels do vídeo nunca passam pelo Chrome, então a cor é fiel por
          construção. */}
      <Composition
        id="Graphics"
        component={Graphics}
        durationInFrames={Math.round(DURATION_S * FPS)}
        fps={FPS}
        width={PERFIL_W}
        height={PERFIL_H}
      />
      <Composition
        id="HookTest"
        component={HookTest}
        durationInFrames={Math.round(HOOK_TEST_DURATION_S * FPS)}
        fps={FPS}
        width={PERFIL_W}
        height={PERFIL_H}
      />
      <Composition
        id="SfxDemo"
        component={SfxDemo}
        durationInFrames={Math.round(SFX_DEMO_DURATION_S * FPS)}
        fps={FPS}
        width={PERFIL_W}
        height={PERFIL_H}
      />
    </>
  );
};
