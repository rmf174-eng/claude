/**
 * Partitura.tsx — a camada tipográfica DIRIGIDA A DADO (SPEC-14).
 *
 * 🔒 CÓDIGO IMUTÁVEL, DADO VARIÁVEL. Este componente não conhece nenhuma
 * produção, nenhum creator e nenhuma cor. Ele lê `src/data/partitura.json` e
 * desenha o que está escrito lá. É a mesma disciplina de `estudos/Screencast.tsx`
 * (composição Remotion dirigida por JSON) e do `StackedCaptions.tsx` do ref-A
 * ("Immutable code, data-driven — same contract as Main.tsx").
 *
 * Para mudar o vídeo, rode o diretor e edite o JSON — não edite este arquivo.
 *
 * O QUE ELE **NÃO** FAZ, e é decisão de desenho: POSIÇÃO.
 * A partitura carrega uma DICA de zona (`topo` | `lateral` | `faixa-legenda` |
 * `pleno`), nunca x/y. Posição depende da zona livre medida por janela
 * (`layout-zones.sh`), da luminância do bolso e do enquadramento — três
 * medições que já têm dono e que erraram caro quando foram chutadas
 * (remotion-compositor/SKILL.md:117-121, três defeitos de estado final por
 * chutar número). Enquanto ninguém resolveu a posição, a zona vira um retângulo
 * conservador em FRAÇÃO DO QUADRO, e o still é obrigatório.
 *
 * ⚠️ QC DE ESTADO FINAL CONTINUA OBRIGATÓRIO. A partitura promete TEMPO, não
 * geometria. `OverlayGroup` tem dois referenciais de tempo e escrever timing na
 * zona errada apaga um beat inteiro sem nenhum QC acusar (medido no
 * peca-05: um beat com `fromS={37.3}` simplesmente não desenhou nada).
 */
import React from "react";
import { AbsoluteFill } from "remotion";
import {
  OverlayGroup,
  HandText,
  AccentWord,
  StepTitleFlat,
  MarkerHighlight,
  underlinePath,
  loopCirclePath,
  strikePath,
  squigglePath,
} from "./MotionKit";
// ⚠️ `DrawStroke` mora no HookLettering, não no MotionKit — e desenha num
// viewBox GLOBAL (1080x1920) quando não recebe `localBox`. Aqui ele sempre
// recebe, para o traço nascer no espaço do retângulo da zona e não no do quadro.
import { DrawStroke } from "./HookLettering";
import { neutralTheme, type Theme } from "./themes";
import partitura from "./data/partitura.json";
import {
  PlanoVisualLayer,
  type EventoPlanoVisual,
  type PlanoVisualData,
} from "./PlanoVisual";

export type Item = {
  id: string;
  papel: string;
  componente: string;
  canal: string;
  texto: string;
  inS: number;
  outS: number;
  zona: "topo" | "lateral" | "faixa-legenda" | "pleno";
  /** largura do texto em px na tipografia da legenda, medida pelo diretor */
  larguraEstimadaPx?: number | null;
  cor: string;
  score: number;
};

export type PartituraData = {
  contrato: string;
  _procedencia: {
    tema?: string | null;
    perfil: {video: {largura: number; altura: number; fps: number}};
    orcamento: {duracao_s: number};
  };
  itens: Item[];
  /** Cópia compilada, byte-semanticamente derivada de plano-visual.json. */
  plano_visual?: PlanoVisualData;
  [chave: string]: unknown;
};

/**
 * `cor` é CHAVE do tema, com caminho por ponto (`postits.autoridade`), nunca
 * hex. É o que faz a MESMA partitura servir a creator-2 (highlight #FF8FA3) e a
 * ref-C em modo oferta (#FCED65) sem reescrever nada.
 */
export const corDoTema = (tema: Theme, chave: string): string => {
  const v = chave
    .split(".")
    .reduce<unknown>((o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined), tema);
  return typeof v === "string" ? v : tema.ink;
};

/**
 * Zona → retângulo em FRAÇÃO do quadro. Fração, e não px, pela mesma razão de
 * `zonas_ui` no perfil de peça: px morrem quando a resolução muda.
 * Estes quatro retângulos são conservadores DE PROPÓSITO — eles existem para o
 * still sair legível, não para substituir a medição de bolso livre.
 */
const ZONAS: Record<Item["zona"], { x: number; y: number; w: number }> = {
  topo: { x: 0.03, y: 0.16, w: 0.8 },
  lateral: { x: 0.03, y: 0.46, w: 0.42 },
  "faixa-legenda": { x: 0.06, y: 0.66, w: 0.86 },
  pleno: { x: 0.06, y: 0.3, w: 0.86 },
};

/**
 * Gerador de traço → path no espaço LOCAL da zona (0 0 w h). Cada gerador do
 * MotionKit tem assinatura própria (`underlinePath(x,y,w)`,
 * `loopCirclePath(cx,cy,rx,ry)`, ...); esta tabela é o adaptador, e é ela que
 * permite `papel_para_componente` nomear o gerador no PERFIL em vez de o script
 * ter um `if` por papel.
 */
const GERADORES: Record<string, (w: number, h: number) => string> = {
  underlinePath: (w, h) => underlinePath(0, h * 0.8, w),
  loopCirclePath: (w, h) => loopCirclePath(w / 2, h / 2, w * 0.48, h * 0.44),
  strikePath: (w, h) => strikePath(0, h / 2, w),
  squigglePath: (w, h) => squigglePath(w / 2, h / 2),
};

const resolverJsonPointer = (raiz: unknown, ponteiro: string): unknown => {
  if (!ponteiro.startsWith("/")) return undefined;
  return ponteiro.slice(1).split("/").reduce<unknown>((atual, parte) => {
    const chave = parte.replace(/~1/g, "/").replace(/~0/g, "~");
    if (Array.isArray(atual) && /^\d+$/.test(chave)) return atual[Number(chave)];
    if (atual && typeof atual === "object") {
      return (atual as Record<string, unknown>)[chave];
    }
    return undefined;
  }, raiz);
};

const itemDoEvento = (dados: PartituraData, evento: EventoPlanoVisual): Item => {
  const impl = evento.implementacao;
  if (impl?.ref.tipo !== "json-pointer") {
    throw new Error(
      `evento ${evento.id}: o entry point Partitura exige ref json-pointer; ` +
      `recebeu ${JSON.stringify(impl)}`,
    );
  }
  const alvo = resolverJsonPointer(dados, impl.ref.valor);
  if (!alvo || typeof alvo !== "object") {
    throw new Error(`evento ${evento.id}: ${impl.ref.valor} não existe em partitura.json`);
  }
  const item = alvo as Partial<Item> & {plano_visual_evento_id?: string};
  if (typeof item.id !== "string" || typeof item.componente !== "string") {
    throw new Error(
      `evento ${evento.id}: ${impl.ref.valor} não aponta para item visual da partitura`,
    );
  }
  if (item.plano_visual_evento_id !== evento.id) {
    throw new Error(
      `evento ${evento.id}: item não foi materializado pelo compilador do plano visual`,
    );
  }
  return item as Item;
};

const Um: React.FC<{ it: Item; tema: Theme; largura: number; altura: number }> = ({
  it,
  tema,
  largura,
  altura,
}) => {
  const z = ZONAS[it.zona] ?? ZONAS.topo;
  const x = Math.round(z.x * largura);
  const y = Math.round(z.y * altura);
  const w = Math.round(z.w * largura);
  const cor = corDoTema(tema, it.cor);
  const [base, gerador] = it.componente.split(":");

  if (base === "DrawStroke") {
    const g = GERADORES[gerador ?? "underlinePath"] ?? GERADORES.underlinePath;
    const h = Math.round(altura * 0.06);
    // ⚠️ O traço tem o tamanho do TEXTO, não o da zona. Sem isto o
    // `loopCirclePath` vira uma elipse de 929×115 px — que na tela é uma reta.
    // A largura vem medida do diretor (`larguraEstimadaPx`); na falta dela,
    // cai num box quadrado, que erra o tamanho mas não a forma.
    const wt = Math.min(w, Math.round(it.larguraEstimadaPx ?? h * 1.6) + h);
    const cx = it.zona === "faixa-legenda" || it.zona === "pleno"
      ? Math.round((largura - wt) / 2)   // a legenda é centralizada
      : x;
    return (
      <div style={{ position: "absolute", left: cx, top: y, width: wt, height: h }}>
        <DrawStroke d={g(wt, h)} delayS={0} color={cor} localBox={`0 0 ${wt} ${h}`} />
      </div>
    );
  }
  if (base === "MarkerHighlight") {
    return (
      <MarkerHighlight
        x={x}
        y={y}
        w={w}
        h={Math.round(altura * 0.05)}
        delayS={0}
        color={cor}
        theme={tema}
      />
    );
  }
  if (base === "AccentWord") {
    return <AccentWord text={it.texto} delayS={0} x={x} y={y} color={cor} theme={tema} />;
  }
  if (base === "StepTitleFlat") {
    return <StepTitleFlat num={1} label={it.texto} delayS={0} x={x} y={y} theme={tema} />;
  }
  return (
    <HandText text={it.texto} delayS={0} x={x} y={y} width={w} color={cor} theme={tema} />
  );
};

export const Partitura: React.FC<{
  tema?: Theme;
  largura: number;
  altura: number;
  /** Props de produção, normalmente vindas de `--props $D/remotion/partitura-compilada.json`. */
  dados?: PartituraData;
}> = ({ tema = neutralTheme, largura, altura, dados }) => {
  const dadosEfetivos = dados ?? (partitura as unknown as PartituraData);
  const itens = dadosEfetivos.itens ?? [];
  const plano = dadosEfetivos.plano_visual;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {plano ? (
        <PlanoVisualLayer
          plano={plano}
          renderEvento={(evento) => {
            const it = itemDoEvento(dadosEfetivos, evento);
            return <Um it={it} tema={tema} largura={largura} altura={altura} />;
          }}
        />
      ) : (
        // Compatibilidade visual para partituras anteriores ao plano v1. Não há
        // fallback de SFX: `item.sfx` era palpite por papel do diretor, não uma
        // decisão do usuário, e por isso nunca é consumido aqui.
        itens.map((it) => (
          <OverlayGroup key={it.id} fromS={it.inS} toS={it.outS} exit="fade">
            <Um it={it} tema={tema} largura={largura} altura={altura} />
          </OverlayGroup>
        ))
      )}
    </AbsoluteFill>
  );
};
