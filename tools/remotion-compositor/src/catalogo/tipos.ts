// Catálogo de estilos — o CONTRATO (SPEC-15 §3.2).
//
// Um estilo é uma entrada tipada num registro TypeScript. O registro
// (`estilos.ts`) é a fonte de verdade; `catalogo/catalogo.json` é artefato
// GERADO por `scripts/gerar-previews.py`.
//
// Por que TS e não JSON como fonte: uma entrada aponta para um componente. Em
// TS, apontar para um componente que não existe NÃO COMPILA — `npx tsc --noEmit`
// é o validador de graça. No `STYLE_CATALOG` do ref-A, que é JS solto, uma
// entrada pode nomear implementação inexistente e nada acusa.

import type React from "react";

export const CONTRATO = "benchmark.catalogo-estilos/v1";

export type Grupo = "gramatica" | "gancho" | "legenda" | "grafismo" | "tema";
export type Camada = "edl" | "pixel" | "alpha";
export type Estado = "pronto" | "candidato";
export type Placa = "vazia" | "retrato" | "paisagem" | "screencast";

export type TipoParam = "px" | "s" | "cor" | "fator" | "texto" | "bool" | "enum";

export type Param = {
  nome: string;
  tipo: TipoParam;
  padrao: unknown;
  /** só numérico */
  faixa?: [number, number];
  /** só enum */
  valores?: string[];
  nota?: string;
};

export type Medido = {
  /** a peça medida, com data */
  fonte: string;
  /**
   * nome do arquivo da ficha de modelagem que originou o estilo (só o nome:
   * a ficha é registro de quem modelou e não viaja no pacote, então um caminho
   * aqui seria ponteiro pendurado no produto).
   */
  ficha: string;
  /** YYYY-MM-DD */
  data: string;
};

export type PreviewSpec = {
  durS: number;
  placa: Placa;
  /** frame do ESTADO FINAL desenhado — §3.6 decisão 3 */
  frameCartao: number;
};

export type Estilo = {
  /** kebab-case, único no catálogo INTEIRO */
  slug: string;
  grupo: Grupo;
  /** rótulo humano PT-BR (o que a galeria mostra) */
  nome: string;
  /** UMA frase: o que aparece na tela. Sem jargão. */
  oQuePinta: string;
  /** ONDE ele age */
  camada: Camada;
  estado: Estado;
  /** obrigatório quando estado === "candidato" */
  bloqueio?: string;
  /** perfis de peça (SPEC-00) em que é oferecido */
  perfis: string[];
  /** perfis em que é o default. ⊆ perfis */
  defaultDe: string[];
  /** "arquivo.tsx:linha" do símbolo real */
  origem: string;
  /** referência direta; ausente em grupo "gramatica" e nos candidatos sem preview */
  componente?: React.FC<any>;
  /** props fixas do preview, além dos `parametros` */
  previewProps?: Record<string, unknown>;
  parametros: Param[];
  /**
   * SPEC-19 §3.8 — QUAL prop recebe a cor de destaque universal do tema
   * (`themes.ts:7`). Ausente = este estilo NÃO pinta acento.
   *
   * 🎯 Por que aqui, e não numa lista na tela: o ref-A mantém `ACCENT_USERS`
   * (`assets/preview/app.js:1051`) espelhada à mão, com o comentário "Mirrors
   * the template — update both together". Duas listas paralelas para o mesmo
   * fato é uma classe de bug garantida. Aqui a informação tem UM dono, e não é
   * booleana: nomeia o parâmetro, que é exatamente o que o renderizador precisa
   * (`params[e.acento.param] = cor`), sem tabela de tradução.
   *
   * ⚠️ Só ganha o campo quem PINTA de verdade. Um estilo cuja identidade medida
   * é `highlight: null` (`legenda-chapada`, `legenda-frio-agressivo`,
   * `legenda-frio-colorido`) NÃO recebe: injetar cor nele deixaria de ser o
   * estilo que a entrada descreve.
   */
  acento?: { param: string };
  /** procedência quando veio de model-edit */
  medido?: Medido;
  /** "arquivo.tsx:linha" das reimplementações conhecidas */
  duplicatas?: string[];
  preview: PreviewSpec;
  /** YYYY-MM-DD */
  desde: string;
};

/**
 * ⚠️ ESCALA DO OUTPUT, não da composição (§3.6 decisão 1 e §9).
 * A composição roda no canvas cheio do PERFIL; só o *output* é reduzido.
 * Baixar width/height da composição quebraria todo `fontSize`/`px` dos
 * componentes, que foram escritos para a largura cheia.
 */
export const ESCALA_PREVIEW = 0.3333;

/** Valor de `preview.durS` quando a entrada não diz outro. */
export const DUR_PADRAO_S = 3.0;

/** Atraso fixo com que todo componente de `gancho`/`grafismo` entra no preview. */
export const DELAY_PREVIEW_S = 0.3;

/** O objeto sem a função — é o que atravessa para o Python (§4.3). */
export type EstiloSerial = Omit<Estilo, "componente">;

/**
 * Projeção serializável do registro. Tira `componente` (é função) e mantém
 * todo o resto. Esta é a ÚNICA forma do registro que sai do TypeScript.
 */
export const serializar = (e: Estilo): EstiloSerial => {
  const { componente: _componente, ...resto } = e;
  return resto;
};

/**
 * Mapa de parâmetros → props, na forma que o arnês monta o componente.
 * `padrao` de cada Param vira prop de mesmo nome.
 */
export const propsDe = (e: Estilo): Record<string, unknown> => {
  const p: Record<string, unknown> = {};
  for (const par of e.parametros) p[par.nome] = par.padrao;
  return { ...p, ...(e.previewProps ?? {}) };
};
