// Frase e legenda SINTÉTICAS do preview do catálogo (SPEC-15 §3.6).
//
// Mecanismo copiado do ref-A (`assets/preview/app.js:189`, `CAP_TEXT`: uma frase
// fixa em todos os cards, para o olho comparar só o que muda). O texto é nosso.
//
// 🔴 A frase NÃO cita creator, produção nem assunto de peça: o catálogo é do
// produto. E, principalmente, o preview inteiro é DESENHADO — não existe um
// frame de material de creator em `catalogo/previews/`.

import type { Caption } from "@remotion/captions";

/** Sete palavras: cabe em 3,0 s a 380 ms/palavra e ainda vira 2 páginas. */
export const FRASE_AMOSTRA = "Uma frase de amostra para comparar estilos";

/** Timing sintético por palavra. Não é fala: é régua. */
export const MS_POR_PALAVRA = 380;

export const PALAVRAS_AMOSTRA = FRASE_AMOSTRA.split(" ");

export const CAPS_AMOSTRA: Caption[] = PALAVRAS_AMOSTRA.map((p, i) => {
  const startMs = i * MS_POR_PALAVRA;
  return {
    text: (i === 0 ? "" : " ") + p,
    startMs,
    endMs: startMs + MS_POR_PALAVRA,
    timestampMs: startMs,
    confidence: 1,
  };
});

/** Duração falada da amostra, em segundos. */
export const FALA_AMOSTRA_S =
  (PALAVRAS_AMOSTRA.length * MS_POR_PALAVRA) / 1000;

/** Duas linhas curtas para os ganchos (linha1 + assinatura). */
export const GANCHO_AMOSTRA = {
  linha1: "ESTILO DE GANCHO",
  linha2: "amostra",
};

/** Rótulos curtos e neutros para dispositivos que pedem texto. */
export const ROTULOS_AMOSTRA = {
  curto: "amostra",
  medio: "texto de amostra",
  passo: "primeiro passo",
  selo: "AMOSTRA",
};
