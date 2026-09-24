/**
 * PlanoVisual.tsx, consumidor Remotion de `benchmark.plano-visual/v1`.
 *
 * A direção de legenda escolhe palavras. A direção visual, aprovada depois do
 * corte, escolhe JANELAS e SOM. Este arquivo mantém as duas autoridades
 * separadas: quem renderiza o visual recebe o evento como prop; timing, política
 * sem-sfx, asset, instante e ganho vêm somente do plano visual.
 */
import React from "react";
import {Sequence, staticFile, useVideoConfig} from "remotion";
import {Audio} from "@remotion/media";

export type DecisaoSom =
  | {
      decisao: "usar";
      asset: string;
      at_s: number;
      ganho_db: number;
      /** Campo interno escrito pelo compilador, relativo ao public/ do projeto. */
      asset_publico?: string;
    }
  | {decisao: "silencio-intencional"; motivo: string}
  | {decisao: "nao-se-aplica"; motivo?: string};

export type RefImplementacao = {
  tipo: "json-pointer" | "marcador-texto";
  valor: string;
};

export type EventoPlanoVisual = {
  id: string;
  inicio_s: number;
  fim_s: number;
  beat: string;
  visual: {tipo: string; descricao: string};
  zona: string;
  som: DecisaoSom;
  implementacao?: {artefato: string; ref: RefImplementacao};
};

export type PlanoVisualData = {
  contrato: "benchmark.plano-visual/v1";
  direcao_edicao: {
    modo: "essencial" | "animada" | "surpresa";
    densidade: "leve" | "equilibrada" | "alta";
    sfx: "automatico" | "sem-sfx";
  };
  eventos: EventoPlanoVisual[];
};

export type SfxCompilado = {
  eventoId: string;
  frame: number;
  assetPublico: string;
  volume: number;
};

/** dB é ganho de amplitude: 20*log10(volume). Não trate dB como porcentagem. */
export const volumeDeGanhoDb = (ganhoDb: number): number =>
  Math.pow(10, ganhoDb / 20);

/**
 * O compilador normalmente grava `asset_publico`. O fallback cobre os 9 SFX
 * canônicos, cujos slugs vivem diretamente em public/sfx.
 */
export const caminhoPublicoDoAsset = (
  som: Extract<DecisaoSom, {decisao: "usar"}>,
): string => {
  if (som.asset_publico) return som.asset_publico;
  const limpo = som.asset.replace(/^\.\//, "");
  if (limpo.startsWith("sfx/")) {
    return /\.[a-z0-9]+$/i.test(limpo) ? limpo : `${limpo}.wav`;
  }
  const nome = limpo.split("/").pop() ?? limpo;
  return `sfx/${/\.[a-z0-9]+$/i.test(nome) ? nome : `${nome}.wav`}`;
};

/** Função pura usada pelo componente e pelo teste de contrato. */
export const sfxDoPlano = (plano: PlanoVisualData, fps: number): SfxCompilado[] => {
  if (
    plano.direcao_edicao.modo === "essencial" ||
    plano.direcao_edicao.sfx !== "automatico"
  ) return [];
  return plano.eventos.flatMap((evento) => {
    if (evento.som.decisao !== "usar") return [];
    return [{
      eventoId: evento.id,
      frame: Math.round(evento.som.at_s * fps),
      assetPublico: caminhoPublicoDoAsset(evento.som),
      volume: volumeDeGanhoDb(evento.som.ganho_db),
    }];
  });
};

/**
 * A cauda do WAV fica fora da janela visual. Colocar o Audio dentro da Sequence
 * da animação amputaria o som quando o desenho saísse antes do arquivo acabar.
 */
export const PlanoVisualSfx: React.FC<{plano: PlanoVisualData}> = ({plano}) => {
  const {fps} = useVideoConfig();
  return (
    <>
      {sfxDoPlano(plano, fps).map((som) => (
        <Sequence key={som.eventoId} from={som.frame} layout="none">
          <Audio src={staticFile(som.assetPublico)} volume={som.volume} />
        </Sequence>
      ))}
    </>
  );
};

/** Timing absoluto do plano; o filho anima no relógio local a partir do frame 0. */
export const EventoVisual: React.FC<{
  evento: EventoPlanoVisual;
  children: React.ReactNode;
}> = ({evento, children}) => {
  const {fps} = useVideoConfig();
  const inicio = Math.round(evento.inicio_s * fps);
  const duracao = Math.max(1, Math.round((evento.fim_s - evento.inicio_s) * fps));
  return (
    <Sequence from={inicio} durationInFrames={duracao}>
      {children}
    </Sequence>
  );
};

/**
 * Orquestrador genérico: cada entry point resolve o componente visual que o seu
 * artefato implementa. A Partitura é o primeiro consumidor concreto.
 */
export const PlanoVisualLayer: React.FC<{
  plano: PlanoVisualData;
  renderEvento: (evento: EventoPlanoVisual) => React.ReactNode;
}> = ({plano, renderEvento}) => {
  const eventos = plano.direcao_edicao.modo === "essencial" ? [] : plano.eventos;
  return (
    <>
      {eventos.map((evento) => (
        <EventoVisual key={evento.id} evento={evento}>
          {renderEvento(evento)}
        </EventoVisual>
      ))}
      <PlanoVisualSfx plano={plano} />
    </>
  );
};
