/**
 * Entry point ISOLADO da partitura (SPEC-14).
 *
 * 🔴 Existe para NÃO tocar no `Root.tsx`. Ele puxa todas as produções do repo e
 * um import quebrado em qualquer uma delas derruba o bundle inteiro — o render
 * falha sem sair frame nenhum, e já falhou (remotion-compositor/SKILL.md:221).
 * Mesmo padrão de `index-peca-06.tsx`.
 *
 * Formato e duração vêm da PRÓPRIA partitura (`_procedencia.perfil.video` e
 * `_procedencia.orcamento.duracao_s`): nenhum número de formato mora neste
 * arquivo, e nada aqui depende de `src/data/perfil.json`, que é estado
 * compartilhado e pertence à última produção que rodou `perfil.py resolver`.
 *
 *   npx remotion compositions src/index-partitura.tsx
 *   npx remotion still        src/index-partitura.tsx Graphics /tmp/p1.png --frame=190
 */
import React from "react";
import { AbsoluteFill, Composition, registerRoot } from "remotion";
import { Partitura, type PartituraData } from "./Partitura";
import { neutralTheme, temaRoseSobreVideo, temaAmareloOferta, type Theme } from "./themes";
import partitura from "./data/partitura.json";

// Mapa nome → tema. Mantido explícito de propósito: `import * as` faria o
// `type Theme` entrar no Record e o `tsc` reclamar, e um mapa aberto aceitaria
// qualquer export deste módulo como tema.
const TEMAS: Record<string, Theme> = { neutralTheme, temaRoseSobreVideo, temaAmareloOferta };

const PADRAO = partitura as unknown as PartituraData;

const metadata = (dados: PartituraData) => {
  const {largura, altura, fps} = dados._procedencia.perfil.video;
  const duracao = dados._procedencia.orcamento.duracao_s;
  if (![largura, altura, fps, duracao].every((n) => Number.isFinite(n) && n > 0)) {
    throw new Error("partitura._procedencia não contém canvas/duração válidos");
  }
  return {
    width: largura,
    height: altura,
    fps,
    durationInFrames: Math.max(1, Math.round(duracao * fps)),
  };
};

const META_PADRAO = metadata(PADRAO);
// 🔴 TEMA QUE NÃO EXISTE FALHA ALTO (2026-08-11, achado R-8). Aqui estava
// `?? neutralTheme`: uma partitura que nomeasse um tema inexistente renderizava
// com OUTRA paleta, em silêncio, e o resultado errado saía verde. O silêncio
// ficou caro no dia em que os três temas foram renomeados para tirar nome de
// pessoa de dentro do bundle — três produções JÁ ENTREGUES carregam o nome
// antigo no `partitura.json` delas, e re-renderizar qualquer uma daria a cor
// errada sem uma linha de aviso. `tema` ausente ou nulo continua significando
// "não declarei tema" e cai no neutro, que é o default e não um chute.
const temaDaPartitura = (dados: PartituraData): Theme => {
  const nome = dados._procedencia.tema ?? null;
  const tema = nome === null ? neutralTheme : TEMAS[nome];
  if (!tema) {
    throw new Error(
      `partitura._procedencia.tema = ${JSON.stringify(nome)} não existe em ` +
        `themes.ts. Temas disponíveis: ${Object.keys(TEMAS).join(", ")}. ` +
        `Renderizar com o tema neutro no lugar dele entregaria a cor errada sem ` +
        `dizer — corrija o nome na partitura.`,
    );
  }
  return tema;
};

const Graphics: React.FC<PartituraData> = (dados) => (
  <AbsoluteFill>
    <Partitura
      dados={dados}
      tema={temaDaPartitura(dados)}
      largura={dados._procedencia.perfil.video.largura}
      altura={dados._procedencia.perfil.video.altura}
    />
  </AbsoluteFill>
);

const Root: React.FC = () => (
  <Composition
    id="Graphics"
    component={Graphics}
    durationInFrames={META_PADRAO.durationInFrames}
    fps={META_PADRAO.fps}
    width={META_PADRAO.width}
    height={META_PADRAO.height}
    defaultProps={PADRAO}
    calculateMetadata={({props}) => metadata(props)}
  />
);

registerRoot(Root);
