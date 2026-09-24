// A versão do PRODUTO de `catalogo/extras.ts` — mesma superfície, listas vazias.
//
// O catálogo (`estilos.ts`) monta `TEMAS` e `ESTILOS` espalhando estas duas
// listas no fim. Aqui elas são vazias porque as entradas que existem do outro
// lado são NOSSAS: citam marca, apontam `duplicatas` para arquivos que o corte
// subtrai e referenciam ficha de inteligência interna.
//
// Este arquivo entra no export por `MANIFESTO.export.substituicoes`, no lugar do
// `extras.ts`. Estender o catálogo com entradas próprias é escrever aqui — a
// superfície é esta e não muda.

import { type Theme } from "../themes";
import type { Estilo } from "./tipos";

/** Temas que entram no `TEMAS` do catálogo depois dos que vêm de fábrica. */
export const TEMAS_EXTRA: Record<string, Theme> = {};

/** Entradas que entram no fim de `ESTILOS`. */
export const ESTILOS_EXTRA: Estilo[] = [];
