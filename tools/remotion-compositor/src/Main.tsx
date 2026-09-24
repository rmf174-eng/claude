import React from "react";
import { AbsoluteFill, staticFile } from "remotion";
import { Video } from "@remotion/media";
import { Captions } from "./Captions";
import { Overlays } from "./Overlays";
import { DURACAO_PRODUCAO_S, FPS as PERFIL_FPS } from "./perfil";

// 📐 O fps vem do perfil de peça (SPEC-00), não daqui.
export const FPS = PERFIL_FPS;

// A duração de UMA peça morava neste arquivo compartilhado (A19): 64,0667 s, a
// 30 fps. Agora vem do snapshot do perfil, que o `resolver` preenche a partir do
// v1-montado.mp4 da produção corrente. Sem v1-montado.mp4 o campo é null e vale
// o default histórico — assim nenhuma composição quebra por falta de produção
// montada.
export const DURATION_S = DURACAO_PRODUCAO_S ?? 64.0667;

// REGRA (2026-07-22): o vídeo fica NATURAL — sem grade, sem punch-in, sem
// qualquer efeito de look. Efeito de cor só quando for decisão editorial
// explícita (ex.: virada pra P&B intencional).
//
// A entrega NÃO usa esta composição: o render de produção é a composição
// Graphics (só camada gráfica, fundo transparente) composta por cima do
// v1-sdr com ffmpeg — os pixels do vídeo nunca passam pelo Chrome, então a
// cor é fiel por construção. Main existe pra preview no studio.

// ⚠️ ESTE ARQUIVO É MECANISMO, e a camada de overlays dele é a GENÉRICA —
// `Overlays`, dirigida por `data/overlays.json`. Até 2026-08-09 ele importava
// aqui a camada de UMA produção nomeada, o que o tornava mecanismo e instância
// ao mesmo tempo: o corte do produto subtraía a produção, `Main.tsx` seguia
// importando-a, e o produto exportado não compilava. Peça que precisa de camada
// própria passa a passá-la em `extra`, e quem faz isso é o entry point DELA.
//
// 🔴 E A LEGENDA SEGUE A MESMA REGRA (2026-08-12, H47-4). A troca acima cobriu
// METADE: `extra` substituía os `Overlays`, mas `<Captions />` entrava SEMPRE — e
// o `Captions.tsx` importa `./data/captions.json`, que no pacote é a FIXTURE
// ("Este é um exemplo de legenda"). Medido em campo: uma peça montada exatamente
// como a skill manda (entry point próprio, camada própria em `extra`) saiu com
// DUAS legendas, a do creator e a do nosso arquivo de exemplo, queimadas no
// vídeo dele. O contorno que ele achou — não reusar `@ilha/Main` — desliga junto
// tudo o que este arquivo tem de bom.
//
// A regra agora: `captions` explícito manda; sem ele, a fixture só entra quando
// NINGUÉM trouxe camada própria (o caminho de demonstração e o studio). Peça com
// `extra` e sem `captions` renderiza SEM legenda — que é o correto: a legenda
// dela mora na camada dela.
export const GraphicLayers: React.FC<{
  extra?: React.ReactNode;
  captions?: React.ReactNode;
}> = ({ extra, captions }) => {
  return (
    <>
      {extra ?? <Overlays />}
      {captions ?? (extra ? null : <Captions />)}
    </>
  );
};

export const Main: React.FC<{
  extra?: React.ReactNode;
  captions?: React.ReactNode;
}> = ({ extra, captions }) => {
  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <AbsoluteFill>
        <Video src={staticFile("v1-graded.mp4")} />
      </AbsoluteFill>
      <GraphicLayers extra={extra} captions={captions} />
    </AbsoluteFill>
  );
};

// Render de produção: fundo TRANSPARENTE →
//   npx remotion render Graphics graphics.mov --codec=prores --prores-profile=4444 --image-format=png
// e depois composição ffmpeg (overlay + amix dos SFX) sobre o v1-sdr.
export const Graphics: React.FC<{
  extra?: React.ReactNode;
  captions?: React.ReactNode;
}> = ({ extra, captions }) => {
  return (
    <AbsoluteFill>
      <GraphicLayers extra={extra} captions={captions} />
    </AbsoluteFill>
  );
};
