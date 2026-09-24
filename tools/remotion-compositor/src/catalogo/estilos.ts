// O REGISTRO — a fonte de verdade do catálogo de estilos (SPEC-15 §3.8).
//
// Uma entrada APONTA para o que já existe, onde já está. Esta spec não move, não
// renomeia e não reescreve nenhum componente (§3.1): catalogar não é refatorar.
// As reimplementações conhecidas viram o campo `duplicatas` — dado, não sessão
// perdida.
//
// 🔴 REGRA QUE ESTE ARQUIVO EXISTE PARA TORNAR VERIFICÁVEL: cor nunca é literal.
// Toda entrada que tem cor REFERENCIA o objeto exportado (`temaRoseSobreVideo.captionActive`,
// `vslEstilos.mornoDestacado.estilo.highlight`) em vez de copiar o hexadecimal.
// Copiar hexes é exatamente o erro do ref-A um nível acima (`app.js:182-188`), e
// é o que fez `peca-11/Kit.tsx:8` clonar um kit inteiro de 423 linhas por causa de
// UMA cor cravada em `peca-10/Kit.tsx:18`.

import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadPoppins } from "@remotion/google-fonts/Poppins";

import type { Theme } from "../themes";
import {
  neutralTheme,
  temaRoseSobreVideo,
  temaAmareloOferta,
  temaEstudoOferta,
} from "../themes";

import { CaptionLayer, ESTILO_LEGENDA_CHAPADA, type CaptionStyle } from "../CaptionLayer";
import { vslEstilos } from "../vsl/estilos-medidos";

import {
  HandText,
  SwapText,
  MarkerHighlight,
  StampSticker,
  ScrollPanel,
  StepTitleFlat,
  AccentWord,
  PostItCard,
  PipCard,
  PanelLite,
  LowerThird,
  FlashCorte,
  Headline,
} from "../MotionKit";
import { DrawStroke, HookCluster } from "../HookLettering";
import { HookTitle, HookTitleFade } from "../TitleCard";
import {
  MacWindow,
  MessengerListMock,
  CallBannerMock,
  BigCalendarMock,
} from "../Mockups";
import {
  Chip as VslChip,
  Veu as VslVeu,
  ItemRiscado as VslItemRiscado,
  BolhaWA as VslBolhaWA,
  Badge as VslBadge,
  BotaoCta as VslBotaoCta,
  SetaBaixo as VslSetaBaixo,
} from "../vsl/VslKit";

import type { Estilo } from "./tipos";
import { TEMAS_EXTRA, ESTILOS_EXTRA } from "./extras";

// As famílias que as entradas de legenda nomeiam existem como string CSS dentro
// de `estilos-medidos.ts` e de `ESTILO_LEGENDA_CHAPADA`. Carregá-las AQUI é o que faz o
// preview mostrar a fonte certa em vez do fallback do headless — um preview que
// mente sobre o estilo é pior que preview nenhum.
const montserrat = loadMontserrat();
loadInter();
loadPoppins();

const HOJE = "2026-08-08";

// 🔴 NOME DE ARQUIVO, NÃO CAMINHO (2026-08-11). Estas três constantes
// carregavam o caminho da ficha de modelagem dentro do diretório de
// inteligência de quem modelou — um diretório que o pacote não leva. Eram 10
// ponteiros pendurados dentro do bundle, num lugar onde nenhum portão os
// enxergava: o de doc varre `.md`, o de referências varre link e import. Só o
// NOME viaja: quem tem a ficha a acha por ele, e quem não tem não recebe a
// promessa de um arquivo que não existe.
const FICHA_VSL = "vsl-rede-ref-E.md";
const FICHA_REF_D = "ref-D.md";
const FICHA_REF_C = "ref-C-oferta.md";

/** Os 4 perfis de peça que existem hoje (SPEC-00, `skills/edit-video/perfis/`). */
const TODOS_PERFIS = ["reels", "vsl", "screencast", "longform"];

// A base das duas variantes de layout: tipografia da legenda de destaque do
// tema, com o eixo `layout` ligado. Fica em const própria porque o mapa acima é
// lido por `verificarRegistro` e um spread inline lá dentro esconderia o que
// mudou entre as duas.
const _LEGENDA_LAYOUT_BASE = {
  fontFamily: montserrat.fontFamily,
  fontWeight: 800,
  fontSize: 64,
  color: "#FFFFFF",
  yPct: 75,
  maxWidth: 900,
  textShadow: "0 3px 12px rgba(0,0,0,0.85)",
} as const;

const ESTILOS_LEGENDA_BASE_EMPILHADA: CaptionStyle = {
  ..._LEGENDA_LAYOUT_BASE,
  highlight: neutralTheme.captionActive,
  layout: "empilhado",
};

const ESTILOS_LEGENDA_BASE_DISPERSA: CaptionStyle = {
  ..._LEGENDA_LAYOUT_BASE,
  highlight: neutralTheme.captionActive,
  layout: "disperso",
};

/* ──────────────────────────── legendas ────────────────────────────
 * O objeto `CaptionStyle` de cada entrada de legenda. NÃO é serializado: o que
 * vai para `catalogo.json` são os `parametros`, e cada `padrao` deles aponta
 * para o mesmo objeto — nunca para uma cópia.
 *
 * As entradas apontam para `CaptionLayer` (livre de dados), NUNCA para
 * `Captions.tsx`, que importa `./data/captions.json` (§2.4).
 */
export const LEGENDAS: Record<string, CaptionStyle> = {
  "legenda-destaque-tema": {
    fontFamily: montserrat.fontFamily,
    fontWeight: 700,
    fontSize: 58,
    color: temaRoseSobreVideo.captionBase,
    highlight: temaRoseSobreVideo.captionActive,
    yPct: 75,
    maxWidth: 900,
    textShadow: "0 3px 12px rgba(0,0,0,0.85)",
  },
  "legenda-chapada": ESTILO_LEGENDA_CHAPADA(montserrat.fontFamily),
  "legenda-frio-agressivo": vslEstilos.frioAgressivo.estilo,
  "legenda-frio-colorido": vslEstilos.frioColorido.estilo,
  "legenda-morno-destacado": vslEstilos.mornoDestacado.estilo,
  "legenda-quente-evento": vslEstilos.quenteEvento.estilo,
  // Os dois eixos de LAYOUT (SPEC-19 §catálogo): a mesma tipografia da legenda
  // de destaque, mudando só COMO a página se organiza no quadro.
  "legenda-empilhada": {
    ...ESTILOS_LEGENDA_BASE_EMPILHADA,
  },
  "legenda-dispersa": {
    ...ESTILOS_LEGENDA_BASE_DISPERSA,
  },
};

/* ───────────────────────────── temas ─────────────────────────────
 * A entrada de tema REFERENCIA o objeto exportado. `themes.ts` continua sendo o
 * único lugar de verdade sobre cor: se um dia divergirem, `themes.ts` ganha
 * (§9). Por isso as entradas de tema têm `parametros: []` — um tema é um pacote
 * que se escolhe, não uma paleta que se afina no card.
 */
export const TEMAS: Record<string, Theme> = {
  "tema-neutro": neutralTheme,
  "tema-creator-2": temaRoseSobreVideo,
  "tema-ref-c-oferta": temaAmareloOferta,
  "tema-estudo-ref-c": temaEstudoOferta,
  ...TEMAS_EXTRA,
};

/**
 * Símbolos que uma entrada cita mas não usa como `componente` principal.
 * Existir aqui é o que faz `npx tsc --noEmit` reprovar se algum deles sumir —
 * é o teste que o `STYLE_CATALOG` do ref-A (JS solto) não tem.
 */
export const SIMBOLOS_CITADOS = {
  "cta-botao-seta/seta": VslSetaBaixo,
} as const;

export const ESTILOS: Estilo[] = [
  /* ═══════════════════════ gramática (4) ═══════════════════════
   * Camada `edl`/`pixel`: nenhuma delas é componente React. Elas mandam no
   * recorte e no corte, não no que se desenha por cima. Declarar isso impede
   * alguém de implementar no Remotion um estilo que tem que viver no ffmpeg —
   * a regra já escrita em `remotion-compositor/SKILL.md`.
   */
  {
    slug: "plano-fixo",
    grupo: "gramatica",
    nome: "Plano fixo",
    oQuePinta:
      "Um enquadramento só do começo ao fim; o corte de fala aparece como jump cut assumido.",
    camada: "edl",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: ["reels", "longform"],
    origem: "skills/edit-video/perfis/reels.json:ritmo.gramatica_plano",
    parametros: [
      {
        nome: "zoom",
        tipo: "fator",
        padrao: 1.0,
        faixa: [1.0, 1.6],
        nota: "recorte único aplicado a todos os segmentos da EDL",
      },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "plano-alternado",
    grupo: "gramatica",
    nome: "Plano alternado",
    oQuePinta:
      "Alterna enquadramento nativo e punch-in a cada frase, e o jump cut passa a ler como troca de plano.",
    camada: "edl",
    estado: "pronto",
    perfis: ["reels", "vsl", "longform"],
    defaultDe: [],
    origem: "skills/edit-video/perfis/_base.json:ritmo.zoom_alternado",
    parametros: [
      { nome: "zoomA", tipo: "fator", padrao: 1.0, faixa: [1.0, 1.2] },
      {
        nome: "zoomB",
        tipo: "fator",
        padrao: 1.27,
        faixa: [1.1, 1.6],
        nota: "faixa medida na referência: 1,22–1,31",
      },
      {
        nome: "trocaS",
        tipo: "s",
        padrao: 2.2,
        faixa: [0.8, 8.0],
        nota: "na peça real a troca é por FRASE; no preview é periódica",
      },
    ],
    medido: {
      fonte: "ref-D, take único 4K, 23 s (modelado 2026-07-25)",
      ficha: FICHA_REF_D,
      data: "2026-07-25",
    },
    duplicatas: [],
    preview: { durS: 4.6, placa: "retrato", frameCartao: 96 },
    desde: HOJE,
  },
  {
    slug: "punch-pontual",
    grupo: "gramatica",
    nome: "Punch-in pontual",
    oQuePinta:
      "Um único avanço de enquadramento num beat de ênfase; o resto da peça fica no plano nativo.",
    camada: "edl",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: ["vsl", "screencast"],
    origem: "skills/edit-video/perfis/vsl.json:ritmo.gramatica_plano",
    parametros: [
      { nome: "zoom", tipo: "fator", padrao: 1.27, faixa: [1.05, 1.6] },
      { nome: "emS", tipo: "s", padrao: 1.2, faixa: [0.0, 60.0] },
      { nome: "rampaS", tipo: "s", padrao: 0.45, faixa: [0.1, 2.0] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "split-screen-esfumacado",
    grupo: "gramatica",
    nome: "Split-screen esfumaçado",
    // O `oQuePinta` é a única prosa deste catálogo que o CREATOR lê na tela de
    // escolha (galeria.js:295). O nome do script que faz a conta já vive no
    // `origem` logo abaixo, que é onde quem mantém o código o procura — citá-lo
    // aqui era gastar a linha da tela com um endereço (achado A-F2).
    oQuePinta:
      "Encaixa o apoio no topo, REENQUADRA a base para o rosto cair abaixo da rampa e dissolve a emenda numa rampa longa de alpha. O deslocamento é MEDIDO por segmento do vídeo, não escolhido no olho.",
    camada: "pixel",
    estado: "pronto",
    perfis: ["reels", "vsl", "longform"],
    defaultDe: [],
    origem: "skills/edit-video/scripts/split-broll.py:56",
    parametros: [
      {
        nome: "opacoPct",
        tipo: "fator",
        padrao: 34,
        faixa: [20, 45],
        nota: "fração da altura",
      },
      {
        nome: "fimPct",
        tipo: "fator",
        padrao: 51,
        faixa: [30, 60],
        nota: "% onde o alpha chega a zero — a diferença para `opacoPct` É a rampa",
      },
      {
        nome: "folgaTopoPct",
        tipo: "fator",
        padrao: 3.6,
        faixa: [1, 8],
        nota: "respiro entre o fim da rampa e o topo da cabeça; o deslocamento é MEDIDO, não escolhido",
      },
      {
        nome: "escalaMax",
        tipo: "fator",
        padrao: 1.08,
        faixa: [1.0, 1.25],
        nota: "teto do upscale da base; estourar é exit 1, nunca clamp silencioso",
      },
    ],
    medido: {
      fonte:
        "ref-D — rampa longa (17% da altura) no trecho remendado; enquadramento medido por matte de pessoa em 35 amostras (SPEC-28): sem plano, 12,2% de mediana de b-roll sobre o topo da cabeça; com plano, 0,00%",
      ficha: FICHA_REF_D,
      data: "2026-08-09",
    },
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },

  /* ═══════════════════════ gancho (3) ═══════════════════════ */
  {
    slug: "hook-titulo-typeon",
    grupo: "gancho",
    nome: "Gancho digitado",
    oQuePinta:
      "Uma linha em caixa alta condensada digita letra a letra e uma serif itálica entra seca embaixo, deslocada.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: ["reels"],
    origem: "src/TitleCard.tsx:82",
    componente: HookTitle,
    parametros: [
      {
        nome: "fpc",
        tipo: "fator",
        padrao: 1.1,
        faixa: [0.4, 3.0],
        nota: "frames por caractere digitado",
      },
      { nome: "fontSize1", tipo: "px", padrao: 128, faixa: [48, 220] },
      { nome: "fontSize2", tipo: "px", padrao: 150, faixa: [48, 240] },
      { nome: "gap2", tipo: "px", padrao: -34, faixa: [-140, 140] },
      {
        nome: "align2",
        tipo: "enum",
        padrao: "right",
        valores: ["center", "right", "left"],
        nota: "o degrau assimétrico é o que dá o ar de assinatura",
      },
      { nome: "inset2", tipo: "px", padrao: 140, faixa: [0, 400] },
      {
        nome: "ajustar",
        tipo: "bool",
        padrao: false,
        nota: "SPEC-13: liga o ajuste por largura medida; exige fonte já carregada",
      },
    ],
    medido: {
      fonte: "ref-D — abertura tipográfica dos 2 primeiros segundos",
      ficha: FICHA_REF_D,
      data: "2026-07-25",
    },
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 66 },
    desde: HOJE,
  },
  {
    slug: "hook-titulo-fade",
    grupo: "gancho",
    nome: "Gancho digitado com saída em fade",
    oQuePinta:
      "O mesmo gancho digitado, mas com um instante declarado em que ele sai de cena por fade.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/TitleCard.tsx:216",
    componente: HookTitleFade,
    parametros: [
      { nome: "fadeAtS", tipo: "s", padrao: 2.2, faixa: [0.5, 12.0] },
      { nome: "fpc", tipo: "fator", padrao: 1.1, faixa: [0.4, 3.0] },
      { nome: "fontSize1", tipo: "px", padrao: 128, faixa: [48, 220] },
      { nome: "fontSize2", tipo: "px", padrao: 150, faixa: [48, 240] },
      {
        nome: "align2",
        tipo: "enum",
        padrao: "right",
        valores: ["center", "right", "left"],
      },
    ],
    medido: {
      fonte: "ref-D — mesma abertura, com a saída declarada",
      ficha: FICHA_REF_D,
      data: "2026-07-25",
    },
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "hook-lettering-anotado",
    grupo: "gancho",
    nome: "Gancho manuscrito anotado",
    oQuePinta:
      "Bloco manuscrito no canto livre, com palavra marcada em pop e traço desenhado por cima.",
    camada: "alpha",
    estado: "candidato",
    bloqueio:
      "`HookLettering.tsx:182` (HookCluster) não tem prop nenhuma: texto, posição e timings são literais de UMA peça, e ele toca `staticFile(\"sfx/*.wav\")`, que não existe no pacote (`**/public/*` é ignorado). Precisa receber texto, posição e timings por prop, e o SFX por opção, antes de virar `pronto`.",
    perfis: ["reels"],
    defaultDe: [],
    origem: "src/HookLettering.tsx:182",
    componente: HookCluster,
    parametros: [],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },

  /* ═══════════════════════ legenda (6) ═══════════════════════ */
  {
    slug: "legenda-destaque-tema",
    grupo: "legenda",
    nome: "Branca com destaque do tema",
    oQuePinta:
      "Legenda branca grande com a palavra ativa na cor de destaque do tema escolhido.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["reels", "longform"],
    defaultDe: ["reels"],
    origem: "src/CaptionLayer.tsx:123",
    componente: CaptionLayer,
    // SPEC-19 §3.8 — pinta acento: a palavra ativa É a cor de destaque do tema
    // (`highlight: temaRoseSobreVideo.captionActive`, LEGENDAS acima).
    acento: { param: "highlight" },
    parametros: [
      {
        nome: "fontSize",
        tipo: "px",
        padrao: LEGENDAS["legenda-destaque-tema"].fontSize,
        faixa: [24, 80],
      },
      {
        nome: "yPct",
        tipo: "fator",
        padrao: LEGENDAS["legenda-destaque-tema"].yPct,
        faixa: [40, 85],
      },
      {
        nome: "maxWidth",
        tipo: "px",
        padrao: LEGENDAS["legenda-destaque-tema"].maxWidth,
        faixa: [300, 1000],
      },
      {
        nome: "combinaMs",
        tipo: "s",
        padrao: 1100,
        faixa: [700, 3000],
        nota: "milissegundos de agrupamento por página",
      },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "legenda-chapada",
    grupo: "legenda",
    nome: "Branca chapada, pequena",
    oQuePinta:
      "Legenda branca pequena, sem palavra ativa, baixa no quadro; não disputa com o rosto nem com o ritmo de corte.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/CaptionLayer.tsx:301",
    componente: CaptionLayer,
    parametros: [
      {
        nome: "fontSize",
        tipo: "px",
        padrao: LEGENDAS["legenda-chapada"].fontSize,
        faixa: [24, 80],
      },
      {
        nome: "yPct",
        tipo: "fator",
        padrao: LEGENDAS["legenda-chapada"].yPct,
        faixa: [40, 85],
      },
      {
        nome: "maxWidth",
        tipo: "px",
        padrao: LEGENDAS["legenda-chapada"].maxWidth,
        faixa: [300, 1000],
      },
      { nome: "combinaMs", tipo: "s", padrao: 1100, faixa: [700, 3000] },
    ],
    medido: {
      fonte: "ref-D (talking-head 23 s, modelado 2026-07-25)",
      ficha: FICHA_REF_D,
      data: "2026-07-25",
    },
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "legenda-frio-agressivo",
    grupo: "legenda",
    nome: "Frio total — chapada e curta",
    oQuePinta:
      "Uma a três palavras por página, brancas, sem cor nenhuma: o protagonista é o ritmo de corte.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["vsl", "reels"],
    defaultDe: [],
    origem: "src/vsl/estilos-medidos.ts:35",
    componente: CaptionLayer,
    parametros: [
      {
        nome: "fontSize",
        tipo: "px",
        padrao: vslEstilos.frioAgressivo.estilo.fontSize,
        faixa: [24, 64],
      },
      {
        nome: "yPct",
        tipo: "fator",
        padrao: vslEstilos.frioAgressivo.estilo.yPct,
        faixa: [40, 85],
      },
      {
        nome: "maxWidth",
        tipo: "px",
        padrao: vslEstilos.frioAgressivo.estilo.maxWidth,
        faixa: [300, 1000],
      },
      {
        nome: "combinaMs",
        tipo: "s",
        padrao: vslEstilos.frioAgressivo.combinaMs,
        faixa: [900, 3000],
      },
    ],
    medido: {
      fonte: vslEstilos.frioAgressivo.fonte,
      ficha: FICHA_VSL,
      data: "2026-08-01",
    },
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "legenda-frio-colorido",
    grupo: "legenda",
    nome: "Frio — toda colorida, itálica",
    oQuePinta:
      "A legenda inteira sai numa cor só, em itálico; não existe palavra ativa porque tudo já é destaque.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["vsl", "reels"],
    defaultDe: [],
    origem: "src/vsl/estilos-medidos.ts:60",
    componente: CaptionLayer,
    parametros: [
      {
        nome: "fontSize",
        tipo: "px",
        padrao: vslEstilos.frioColorido.estilo.fontSize,
        faixa: [24, 64],
      },
      {
        nome: "color",
        tipo: "cor",
        padrao: vslEstilos.frioColorido.estilo.color,
        nota: "medido no núcleo do glifo — a legenda toda, não só o destaque",
      },
      {
        nome: "yPct",
        tipo: "fator",
        padrao: vslEstilos.frioColorido.estilo.yPct,
        faixa: [40, 85],
      },
      {
        nome: "maxWidth",
        tipo: "px",
        padrao: vslEstilos.frioColorido.estilo.maxWidth,
        faixa: [300, 1000],
      },
      {
        nome: "combinaMs",
        tipo: "s",
        padrao: vslEstilos.frioColorido.combinaMs,
        faixa: [900, 3000],
      },
    ],
    medido: {
      fonte: vslEstilos.frioColorido.fonte,
      ficha: FICHA_VSL,
      data: "2026-08-01",
    },
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "legenda-morno-destacado",
    grupo: "legenda",
    nome: "Destaque morno",
    oQuePinta:
      "Legenda branca com a palavra ativa numa cor quente; cinco a seis palavras por página.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["vsl", "reels", "longform"],
    defaultDe: ["vsl"],
    origem: "src/vsl/estilos-medidos.ts:87",
    componente: CaptionLayer,
    // SPEC-19 §3.8 — pinta acento: `highlight: "#F14418"` medido no núcleo do
    // glifo (`estilos-medidos.ts:95`). A cor escolhida na galeria entra aqui.
    acento: { param: "highlight" },
    parametros: [
      {
        nome: "fontSize",
        tipo: "px",
        padrao: vslEstilos.mornoDestacado.estilo.fontSize,
        faixa: [24, 64],
      },
      {
        nome: "highlight",
        tipo: "cor",
        padrao: vslEstilos.mornoDestacado.estilo.highlight,
        nota: "medido no núcleo do glifo",
      },
      {
        nome: "yPct",
        tipo: "fator",
        padrao: vslEstilos.mornoDestacado.estilo.yPct,
        faixa: [40, 85],
      },
      {
        nome: "maxWidth",
        tipo: "px",
        padrao: vslEstilos.mornoDestacado.estilo.maxWidth,
        faixa: [300, 1000],
      },
      {
        nome: "combinaMs",
        tipo: "s",
        padrao: vslEstilos.mornoDestacado.combinaMs,
        faixa: [900, 3000],
      },
    ],
    medido: {
      fonte: vslEstilos.mornoDestacado.fonte,
      ficha: FICHA_VSL,
      data: "2026-08-01",
    },
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "legenda-quente-evento",
    grupo: "legenda",
    nome: "Quente — maior e mais baixa",
    oQuePinta:
      "Legenda maior, mais baixa no quadro e com pouco destaque; a carga gráfica migra para as cartelas.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["vsl", "longform"],
    defaultDe: [],
    origem: "src/vsl/estilos-medidos.ts:112",
    componente: CaptionLayer,
    // SPEC-19 §3.8 — pinta acento: `highlight: "#FE5410"`
    // (`estilos-medidos.ts:120`).
    acento: { param: "highlight" },
    parametros: [
      {
        nome: "fontSize",
        tipo: "px",
        padrao: vslEstilos.quenteEvento.estilo.fontSize,
        faixa: [24, 72],
      },
      {
        nome: "highlight",
        tipo: "cor",
        padrao: vslEstilos.quenteEvento.estilo.highlight,
      },
      {
        nome: "yPct",
        tipo: "fator",
        padrao: vslEstilos.quenteEvento.estilo.yPct,
        faixa: [40, 85],
      },
      {
        nome: "maxWidth",
        tipo: "px",
        padrao: vslEstilos.quenteEvento.estilo.maxWidth,
        faixa: [300, 1000],
      },
      {
        nome: "combinaMs",
        tipo: "s",
        padrao: vslEstilos.quenteEvento.combinaMs,
        faixa: [900, 3000],
      },
    ],
    medido: {
      fonte: vslEstilos.quenteEvento.fonte,
      ficha: FICHA_VSL,
      data: "2026-08-01",
    },
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 78 },
    desde: HOJE,
  },

  /* ═══════════════════════ tema (5) ═══════════════════════
   * `parametros: []` de propósito: um tema é um pacote que se escolhe. Afinar a
   * paleta no card do catálogo criaria um segundo lugar de verdade sobre cor, e
   * `themes.ts` tem que continuar sendo o único (§9).
   */
  {
    slug: "tema-neutro",
    grupo: "tema",
    nome: "Neutro",
    oQuePinta:
      "Tinta escura sobre fundo claro, destaque amarelo e cinco cores de post-it por categoria.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: TODOS_PERFIS,
    origem: "src/themes.ts:17",
    parametros: [],
    duplicatas: [],
    preview: { durS: 3.0, placa: "vazia", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "tema-creator-2",
    grupo: "tema",
    nome: "Rosé sobre vídeo",
    oQuePinta:
      "Tinta branca com sombra escura para viver sobre vídeo, destaque rosé e papelaria creme.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["reels", "longform"],
    defaultDe: [],
    origem: "src/themes.ts:38",
    parametros: [],
    duplicatas: [],
    preview: { durS: 3.0, placa: "vazia", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "tema-ref-c-oferta",
    grupo: "tema",
    nome: "Amarelo limão de oferta",
    oQuePinta:
      "Tinta quase preta e um amarelo limão único, sem paleta de post-it; feito para cena acromática.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["reels", "vsl"],
    defaultDe: [],
    origem: "src/themes.ts:58",
    parametros: [],
    medido: {
      fonte: "ref-C em modo oferta (post-ref-C-2, 70 s)",
      ficha: FICHA_REF_C,
      data: "2026-07-29",
    },
    duplicatas: [],
    preview: { durS: 3.0, placa: "vazia", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "tema-estudo-ref-c",
    grupo: "tema",
    nome: "Amarelo educativo",
    oQuePinta:
      "Variante do neutro com tinta mais escura e post-its nomeados por categoria editorial.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["reels"],
    defaultDe: [],
    origem: "src/themes.ts:67",
    parametros: [],
    duplicatas: [],
    preview: { durS: 3.0, placa: "vazia", frameCartao: 54 },
    desde: HOJE,
  },

  /* ═══════════════════════ grafismo pronto (14) ═══════════════════════ */
  {
    slug: "manuscrito-write-on",
    grupo: "grafismo",
    nome: "Manuscrito que aparece",
    oQuePinta:
      "Texto de caneta fina que surge letra a letra sem se mover, como se estivesse sendo escrito.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:190",
    componente: HandText,
    parametros: [
      { nome: "size", tipo: "px", padrao: 44, faixa: [20, 140] },
      {
        nome: "font",
        tipo: "enum",
        padrao: "pen",
        valores: ["pen", "script", "marker"],
      },
      {
        nome: "align",
        tipo: "enum",
        padrao: "center",
        valores: ["left", "center", "right"],
      },
      { nome: "rotate", tipo: "fator", padrao: 0, faixa: [-20, 20] },
      {
        nome: "fpc",
        tipo: "fator",
        padrao: 0.9,
        faixa: [0.3, 3.0],
        nota: "frames por caractere",
      },
      { nome: "lineHeight", tipo: "fator", padrao: 1.15, faixa: [0.9, 2.0] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "frase-que-troca",
    grupo: "grafismo",
    nome: "Frase que troca",
    oQuePinta:
      "Uma frase manuscrita dá lugar à seguinte no mesmo ponto da tela, em tempos declarados.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:253",
    componente: SwapText,
    parametros: [
      { nome: "size", tipo: "px", padrao: 40, faixa: [20, 120] },
      {
        nome: "align",
        tipo: "enum",
        padrao: "center",
        valores: ["left", "center"],
      },
      { nome: "fpc", tipo: "fator", padrao: 0.7, faixa: [0.3, 3.0] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "marca-texto",
    grupo: "grafismo",
    nome: "Marca-texto",
    oQuePinta:
      "Uma faixa de marca-texto varre da esquerda para a direita por baixo de um trecho já escrito.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:348",
    componente: MarkerHighlight,
    parametros: [
      { nome: "sweepS", tipo: "s", padrao: 0.4, faixa: [0.1, 2.0] },
      {
        nome: "rotate",
        tipo: "fator",
        padrao: 0,
        faixa: [-20, 20],
        nota: "acompanha a inclinação da linha manuscrita",
      },
      {
        nome: "blend",
        tipo: "enum",
        padrao: "normal",
        valores: ["normal", "multiply"],
        nota: "multiply escurece sobre a cena, como marca-texto de verdade",
      },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "selo-carimbado",
    grupo: "grafismo",
    nome: "Selo carimbado",
    oQuePinta:
      "Um selo inclinado bate na tela e assenta em três frames, como carimbo de verdade.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:402",
    componente: StampSticker,
    parametros: [
      { nome: "size", tipo: "px", padrao: 78, faixa: [28, 180] },
      { nome: "rotate", tipo: "fator", padrao: -12.9, faixa: [-30, 30] },
      { nome: "padX", tipo: "px", padrao: 26, faixa: [0, 80] },
      { nome: "padY", tipo: "px", padrao: 10, faixa: [0, 60] },
      {
        nome: "font",
        tipo: "enum",
        padrao: "marker",
        valores: ["marker", "pen", "script"],
      },
      {
        nome: "overshoot",
        tipo: "fator",
        padrao: 1.06,
        faixa: [1.0, 1.4],
        nota: "1,0 = sem overshoot; a referência bate seco",
      },
    ],
    duplicatas: ["src/MaeDoMarido.tsx:123", "src/MesaComAmiga.tsx:241"],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "painel-rolante",
    grupo: "grafismo",
    nome: "Painel rolante",
    oQuePinta:
      "Uma janela recorta um conteúdo mais alto que ela e o percorre de cima para baixo em velocidade constante.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:473",
    componente: ScrollPanel,
    parametros: [
      { nome: "speedPxS", tipo: "px", padrao: 60, faixa: [10, 400] },
      { nome: "radius", tipo: "px", padrao: 26, faixa: [0, 80] },
      {
        nome: "enter",
        tipo: "enum",
        padrao: "fade",
        valores: ["fade", "slide", "cut"],
      },
      { nome: "enterS", tipo: "s", padrao: 0.3, faixa: [0.0, 2.0] },
      { nome: "shadow", tipo: "bool", padrao: true },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "vazia", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "passo-numerado",
    grupo: "grafismo",
    nome: "Passo numerado",
    oQuePinta: "Um número em bloco colorido entra em mola com o rótulo do passo ao lado.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:553",
    componente: StepTitleFlat,
    parametros: [{ nome: "size", tipo: "px", padrao: 58, faixa: [24, 140] }],
    duplicatas: [
      "src/MotionKit.tsx:614",
      "src/peca-11/Kit.tsx:186",
      "src/MesaComAmiga.tsx:120",
      "src/peca-10/Kit.tsx:253",
    ],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "palavra-acento",
    grupo: "grafismo",
    nome: "Palavra de acento",
    oQuePinta: "Uma palavra grande entra em mola, inclinada, na cor de destaque do tema.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:665",
    componente: AccentWord,
    parametros: [
      { nome: "size", tipo: "px", padrao: 96, faixa: [32, 220] },
      { nome: "rotate", tipo: "fator", padrao: 0, faixa: [-25, 25] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "postit",
    grupo: "grafismo",
    nome: "Post-it",
    oQuePinta:
      "Um cartão de papel colorido entra em mola, levemente torto, com texto curto dentro.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:706",
    componente: PostItCard,
    parametros: [
      { nome: "size", tipo: "px", padrao: 34, faixa: [16, 90] },
      { nome: "rotate", tipo: "fator", padrao: 0, faixa: [-20, 20] },
      {
        nome: "category",
        tipo: "texto",
        padrao: "",
        nota: "chave da paleta semântica do tema; vazio = a primeira cor",
      },
    ],
    duplicatas: [
      "src/vsl/VslKit.tsx:95",
      "src/MesaComAmiga.tsx:72",
      "src/peca-03.tsx:492",
    ],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "pip-flutuante",
    grupo: "grafismo",
    nome: "Cartão flutuante de mídia",
    oQuePinta:
      "Um cartão retrato com mídia dentro entra em mola por cima da cena e pode sair no tempo declarado.",
    camada: "alpha",
    estado: "candidato",
    bloqueio:
      "`MotionKit.tsx:803` chama `staticFile(src)`: a entrada exige um arquivo em `public/`, que não vai no pacote (`**/public/*` é ignorado) e não existe na máquina do cliente. Precisa aceitar `src` já resolvido (URL ou data-URI) antes de virar `pronto` — e só então ganha preview.",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:758",
    componente: PipCard,
    parametros: [
      { nome: "ratio", tipo: "fator", padrao: 1.33, faixa: [0.5, 2.5] },
      { nome: "rotate", tipo: "fator", padrao: 0, faixa: [-20, 20] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "painel-lite",
    grupo: "grafismo",
    nome: "Painel leve",
    oQuePinta:
      "Um retângulo semitransparente entra por baixo do conteúdo para dar leitura sobre vídeo.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:813",
    componente: PanelLite,
    parametros: [
      {
        nome: "enter",
        tipo: "enum",
        padrao: "fade",
        valores: ["fade", "slide"],
      },
      { nome: "radius", tipo: "px", padrao: 26, faixa: [0, 90] },
      { nome: "opacity", tipo: "fator", padrao: 1, faixa: [0.15, 1] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "tarja-identificacao",
    grupo: "grafismo",
    nome: "Tarja de identificação",
    oQuePinta:
      "Uma tarja entra deslizando pela esquerda com uma ou duas linhas — quem fala, o que é aquilo — e um botão opcional que pulsa uma vez.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:LowerThird",
    componente: LowerThird,
    parametros: [
      { nome: "linha1", tipo: "texto", padrao: "Nome de quem fala" },
      { nome: "linha2", tipo: "texto", padrao: "o que ele é" },
      { nome: "botao", tipo: "texto", padrao: "" },
      // ⚠️ `y` NÃO é parâmetro de catálogo, de propósito. O schema de `Param`
      // exige `padrao`, e o default honesto deste componente é DERIVADO (61,5%
      // da altura da composição) — cravar um px aqui reintroduziria valor de
      // formato no catálogo, que é o pecado que o perfil de peça existe para não
      // repetir. Quem precisa de outra altura passa `y` na prop.
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "legenda-empilhada",
    grupo: "legenda",
    nome: "Empilhada",
    oQuePinta:
      "As linhas da página entram uma por vez e ficam: a frase se constrói na tela em vez de aparecer pronta.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["reels", "longform"],
    defaultDe: [],
    origem: "src/CaptionLayer.tsx:CaptionStyle.layout",
    componente: CaptionLayer,
    acento: { param: "highlight" },
    parametros: [
      { nome: "fontSize", tipo: "px", padrao: LEGENDAS["legenda-empilhada"].fontSize, faixa: [24, 80] },
      { nome: "yPct", tipo: "fator", padrao: LEGENDAS["legenda-empilhada"].yPct, faixa: [40, 92] },
      { nome: "highlight", tipo: "cor", padrao: LEGENDAS["legenda-empilhada"].highlight },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "legenda-dispersa",
    grupo: "legenda",
    nome: "Dispersa",
    oQuePinta:
      "Cada palavra ganha um deslocamento e uma inclinação próprios, com a página inteira ainda legível.",
    camada: "alpha",
    estado: "pronto",
    perfis: ["reels", "longform"],
    defaultDe: [],
    origem: "src/CaptionLayer.tsx:CaptionStyle.layout",
    componente: CaptionLayer,
    acento: { param: "highlight" },
    parametros: [
      { nome: "fontSize", tipo: "px", padrao: LEGENDAS["legenda-dispersa"].fontSize, faixa: [24, 80] },
      { nome: "yPct", tipo: "fator", padrao: LEGENDAS["legenda-dispersa"].yPct, faixa: [40, 92] },
      { nome: "highlight", tipo: "cor", padrao: LEGENDAS["legenda-dispersa"].highlight },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "headline-outline",
    grupo: "gancho",
    nome: "Headline Contorno",
    oQuePinta:
      "Texto grande com contorno grosso e sombra, sem caixa: a imagem continua vendo-se atrás dele.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:Headline",
    componente: Headline,
    parametros: [
      { nome: "look", tipo: "enum", padrao: "outline", valores: ["outline", "card", "realce", "misto"] },
      { nome: "linha1", tipo: "texto", padrao: "A frase que segura" },
      { nome: "linha2", tipo: "texto", padrao: "o primeiro segundo" },
      { nome: "yPct", tipo: "fator", padrao: 0.18, faixa: [0.04, 0.7] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "headline-card",
    grupo: "gancho",
    nome: "Headline Cartão",
    oQuePinta:
      "As duas linhas dentro de retângulos do painel do tema — o tratamento mais legível sobre qualquer imagem.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:Headline",
    componente: Headline,
    parametros: [
      { nome: "look", tipo: "enum", padrao: "card", valores: ["outline", "card", "realce", "misto"] },
      { nome: "linha1", tipo: "texto", padrao: "A frase que segura" },
      { nome: "linha2", tipo: "texto", padrao: "o primeiro segundo" },
      { nome: "yPct", tipo: "fator", padrao: 0.18, faixa: [0.04, 0.7] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "headline-realce",
    grupo: "gancho",
    nome: "Headline Realce",
    oQuePinta:
      "Marca-texto na cor de destaque atrás das palavras, como se alguém tivesse grifado a frase.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:Headline",
    componente: Headline,
    parametros: [
      { nome: "look", tipo: "enum", padrao: "realce", valores: ["outline", "card", "realce", "misto"] },
      { nome: "linha1", tipo: "texto", padrao: "A frase que segura" },
      { nome: "linha2", tipo: "texto", padrao: "o primeiro segundo" },
      { nome: "yPct", tipo: "fator", padrao: 0.18, faixa: [0.04, 0.7] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "headline-misto",
    grupo: "gancho",
    nome: "Headline Misto",
    oQuePinta:
      "Primeira linha em cartão, segunda em realce — o degrau que separa a afirmação da assinatura.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:Headline",
    componente: Headline,
    parametros: [
      { nome: "look", tipo: "enum", padrao: "misto", valores: ["outline", "card", "realce", "misto"] },
      { nome: "linha1", tipo: "texto", padrao: "A frase que segura" },
      { nome: "linha2", tipo: "texto", padrao: "o primeiro segundo" },
      { nome: "yPct", tipo: "fator", padrao: 0.18, faixa: [0.04, 0.7] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "flash-no-corte",
    grupo: "grafismo",
    nome: "Flash na transição",
    oQuePinta:
      "Um clarão curto na cor de destaque cobre a emenda: ele COMEÇA antes do corte, tem o pico no frame da emenda e apaga logo depois.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/MotionKit.tsx:FlashCorte",
    componente: FlashCorte,
    parametros: [
      { nome: "lidera", tipo: "px", padrao: 2, faixa: [0, 6] },
      { nome: "apaga", tipo: "px", padrao: 2, faixa: [1, 8] },
      { nome: "forca", tipo: "fator", padrao: 0.42, faixa: [0.1, 1] },
    ],
    duplicatas: [],
    // ⚠️ `frameCartao` no PICO do efeito, não no default. O flash inteiro dura 4
    // frames (2 antes + 2 depois) no meio da janela de 3 s a 30 fps = frame 45; o
    // 54 de sempre cai DEPOIS dele e o cartão do catálogo saía sem o efeito — um
    // preview que não mostra o que vende.
    preview: { durS: 3.0, placa: "retrato", frameCartao: 45 },
    desde: HOJE,
  },
  {
    slug: "traco-mao-livre",
    grupo: "grafismo",
    nome: "Traço à mão livre",
    oQuePinta:
      "Um traço desenha sozinho ao longo de um caminho: sublinhado, círculo, risco ou seta.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/HookLettering.tsx:64",
    componente: DrawStroke,
    parametros: [
      { nome: "drawS", tipo: "s", padrao: 0.4, faixa: [0.1, 3.0] },
      { nome: "strokeWidth", tipo: "px", padrao: 8, faixa: [2, 40] },
      { nome: "arrowHead", tipo: "bool", padrao: false },
      {
        nome: "gerador",
        tipo: "enum",
        padrao: "sublinhado",
        valores: ["sublinhado", "circulo", "risco", "xis", "seta", "rabisco"],
        nota: "geradores de caminho em MotionKit.tsx:296-343",
      },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "mockup-janela-mac",
    grupo: "grafismo",
    nome: "Janela de sistema",
    oQuePinta:
      "Uma janela de aplicativo com barra de título entra deslizando e serve de moldura para o conteúdo.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/Mockups.tsx:29",
    componente: MacWindow,
    parametros: [
      {
        nome: "enter",
        tipo: "enum",
        padrao: "slide-right",
        valores: ["slide-right", "slide-up", "pop"],
      },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "vazia", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "mockup-lista-mensagens",
    grupo: "grafismo",
    nome: "Lista de conversas",
    oQuePinta:
      "Uma caixa de entrada de mensagens sobe na tela e as conversas aparecem uma a uma.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/Mockups.tsx:165",
    componente: MessengerListMock,
    parametros: [
      { nome: "header", tipo: "texto", padrao: "Mensagens" },
      { nome: "headerColor", tipo: "cor", padrao: "#22B357" },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "vazia", frameCartao: 78 },
    desde: HOJE,
  },
  {
    slug: "mockup-banner-chamada",
    grupo: "grafismo",
    nome: "Banner de chamada",
    oQuePinta:
      "O aviso de chamada recebida ou perdida desce do topo, com nome e legenda curta.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/Mockups.tsx:312",
    componente: CallBannerMock,
    parametros: [
      {
        nome: "mode",
        tipo: "enum",
        padrao: "incoming",
        valores: ["incoming", "missed"],
      },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "vazia", frameCartao: 54 },
    desde: HOJE,
  },
  {
    slug: "mockup-calendario",
    grupo: "grafismo",
    nome: "Calendário cheio",
    oQuePinta:
      "Uma grade de calendário com compromissos coloridos aparece e desliza lateralmente durante a cena.",
    camada: "alpha",
    estado: "pronto",
    perfis: TODOS_PERFIS,
    defaultDe: [],
    origem: "src/Mockups.tsx:477",
    componente: BigCalendarMock,
    parametros: [
      { nome: "panPx", tipo: "px", padrao: 220, faixa: [0, 700] },
      { nome: "opacity", tipo: "fator", padrao: 0.88, faixa: [0.2, 1] },
    ],
    duplicatas: [],
    preview: { durS: 3.0, placa: "vazia", frameCartao: 78 },
    desde: HOJE,
  },

  /* ═══════════════ grafismo candidato (6) ═══════════════
   * Todos de `vsl/VslKit.tsx`, todos com o MESMO bloqueio. Registrá-los como
   * candidatos é honesto hoje e vira a lista de trabalho de amanhã: a
   * alternativa era mentir (marcar pronto) ou esconder (não registrar), e
   * esconder é o defeito que esta spec existe para corrigir (§3.2).
   */
  ...(
    [
      {
        slug: "chip",
        nome: "Chip",
        oQuePinta:
          "Uma pílula escura com borda colorida e texto curto entra em mola.",
        origem: "src/vsl/VslKit.tsx:228",
        componente: VslChip,
        duplicatas: [
          "src/peca-11/Kit.tsx:146",
          "src/peca-10/Kit.tsx:36",
          "src/peca-06.tsx:376",
        ],
      },
      {
        slug: "veu-pleno",
        nome: "Véu do registro pleno",
        oQuePinta:
          "Um véu escuro cobre a cena inteira para o gráfico tomar a tela sem competir com o vídeo.",
        origem: "src/vsl/VslKit.tsx:81",
        componente: VslVeu,
        duplicatas: [],
      },
      {
        slug: "item-riscado",
        nome: "Item riscado",
        oQuePinta:
          "Um item de lista entra inteiro e depois é riscado, apagando enquanto o traço passa.",
        origem: "src/vsl/VslKit.tsx:340",
        componente: VslItemRiscado,
        duplicatas: ["src/vsl/VslKit.tsx:446", "src/peca-03.tsx:46"],
      },
      {
        slug: "balao-whatsapp",
        nome: "Balão de mensagem",
        oQuePinta:
          "Um balão de conversa sobe com indicador de digitando antes do texto aparecer.",
        origem: "src/vsl/VslKit.tsx:477",
        componente: VslBolhaWA,
        duplicatas: ["src/peca-06.tsx:448", "src/peca-03.tsx:232"],
      },
      {
        slug: "badge",
        nome: "Selo de duas linhas",
        oQuePinta:
          "Um cartão pequeno de duas linhas entra em mola, tipo etiqueta de dado.",
        origem: "src/vsl/VslKit.tsx:567",
        componente: VslBadge,
        duplicatas: [],
      },
      {
        slug: "cta-botao-seta",
        nome: "Botão de CTA com seta",
        oQuePinta:
          "Um botão largo entra, dá dois micro-pulos e uma seta pulsa apontando para ele.",
        origem: "src/vsl/VslKit.tsx:627",
        componente: VslBotaoCta,
        duplicatas: [],
      },
    ] as const
  ).map(
    (c): Estilo => ({
      slug: c.slug,
      grupo: "grafismo",
      nome: c.nome,
      oQuePinta: c.oQuePinta,
      camada: "alpha",
      estado: "candidato",
      bloqueio:
        "importa `vsl/theme.ts:49-58`, que crava a geometria de uma produção 16:9 em pixels; precisa receber as zonas por prop antes de virar `pronto` (SPEC-00 §3.1)",
      perfis: ["vsl"],
      defaultDe: [],
      origem: c.origem,
      componente: c.componente,
      parametros: [],
      duplicatas: [...c.duplicatas],
      preview: { durS: 3.0, placa: "retrato", frameCartao: 54 },
      desde: HOJE,
    })
  ),
  ...ESTILOS_EXTRA,
];

/**
 * ⚠️ PORTÃO DE MÓDULO — roda no import, dentro do bundle. Um registro
 * inconsistente derruba o entry point ANTES de qualquer render, em vez de
 * produzir um catálogo verde e errado. Sucesso silencioso é o pior defeito
 * daqui.
 */
export const verificarRegistro = (): string[] => {
  const erros: string[] = [];
  const vistos = new Set<string>();
  const defaults = new Map<string, string>(); // `${grupo}|${perfil}` → slug

  for (const e of ESTILOS) {
    if (vistos.has(e.slug)) erros.push(`slug duplicado: ${e.slug}`);
    vistos.add(e.slug);

    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(e.slug))
      erros.push(`slug fora de kebab-case: ${e.slug}`);

    if (e.estado === "candidato" && !e.bloqueio)
      erros.push(`candidato sem bloqueio: ${e.slug}`);

    for (const p of e.defaultDe) {
      if (!e.perfis.includes(p))
        erros.push(`${e.slug}: defaultDe "${p}" fora de perfis`);
      const chave = `${e.grupo}|${p}`;
      const dono = defaults.get(chave);
      if (dono) erros.push(`dois defaults de ${e.grupo} para ${p}: ${dono} e ${e.slug}`);
      else defaults.set(chave, e.slug);
    }

    if (e.estado === "candidato" && e.defaultDe.length > 0)
      erros.push(`${e.slug}: candidato não pode ser default`);

    if (e.grupo === "legenda" && !LEGENDAS[e.slug])
      erros.push(`${e.slug}: entrada de legenda sem CaptionStyle em LEGENDAS`);

    if (e.grupo === "tema" && !TEMAS[e.slug])
      erros.push(`${e.slug}: entrada de tema sem objeto em TEMAS`);

    if (e.grupo !== "gramatica" && e.grupo !== "tema" && !e.componente)
      erros.push(`${e.slug}: grupo ${e.grupo} exige componente`);

    if (e.preview.frameCartao < 0)
      erros.push(`${e.slug}: frameCartao negativo`);
  }
  return erros;
};
