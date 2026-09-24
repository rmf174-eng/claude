/**
 * ⚠️ ESTE CABEÇALHO JÁ DECLAROU "obra derivada", E ERA FALSO.
 * A medição de 2026-08-09 contou a coincidência literal com a ferramenta de
 * referência que inspirou o módulo: ZERO linhas. O que se leu lá foi a IDEIA de
 * fechar a página de legenda por largura medida em vez de por contagem de
 * palavra; a implementação, o critério de fechamento e as medições são nossas.
 */

/**
 * agrupar.ts — a página de legenda fechada por LARGURA MEDIDA (SPEC-13 §3.3).
 *
 * Hoje quem decide a página é o relógio: `createTikTokStyleCaptions` abre página
 * nova quando passaram N ms. O número de caracteres na tela vira função da
 * prosódia — quem fala rápido enche a página, quem faz pausa esvazia — e nada
 * disso tem relação com o layout. Medido sobre a peça ENTREGUE da creator-2
 * (`captions.peca-02.json`, Montserrat 700 @58 px, `maxWidth` 900):
 * 10 das 61 páginas passam do orçamento, a maior tem 1133 px, e quem escolhe
 * onde quebrar a linha é o algoritmo do Chrome, que pode cortar depois de "de",
 * "a", "que".
 *
 * Aqui a largura fecha a página, o teto de palavras é guarda-corpo (SEGUNDO
 * critério), pontuação e gap de fala continuam fechando, e a quebra de linha é
 * decidida por nós.
 *
 * 🔒 ESTE ARQUIVO NÃO IMPORTA NADA DE BROWSER, e isso é decisão de arquitetura,
 * não descuido. O medidor entra por parâmetro (`Medidor`), então o MESMO
 * algoritmo roda (a) no Chrome do Remotion com `measureText`, (b) em Node com a
 * tabela de advance widths do TTF (`medidorDeTabela`, aqui embaixo) e (c) em
 * Python na SPEC-14, com a mesma tabela. É o que torna o critério de aceite
 * executável sem render.
 *
 * 🔒 E NÃO CONHECE `creators/`, nem caminho absoluto, nem nome de creator. Estilo
 * entra por `Agrupamento`, que vem do perfil de peça.
 */
import type { Caption, TikTokToken } from "@remotion/captions";
import type { Medida, Medidor } from "./medida";

export type { Medidor };

/** Pontuação que fecha página. */
const PONTUACAO = /[.,!?…;:]["'”’)]*$/;

/**
 * 🔁 ESPELHO de `CaptionLayer.tsx:151-156` — a ponte anti-piscada. A página fica
 * até a próxima entrar quando a distância de fala é menor que `PONTE_MS`; senão
 * sai com `CAUDA_MS` de sobra e fade.
 *
 * Estes dois números NÃO são donos aqui: eles moram no componente, e a duplicata
 * existe só porque a fusão de solos (§3.5) precisa saber a duração EFETIVA da
 * página — que é a esticada pela ponte, não `end − start` da palavra. É
 * exatamente o erro do ref-A, que rejeita cue "curta demais" olhando
 * `endMs − startMs` (`caption_style.py:104-111`) enquanto o próprio código
 * estica a cue logo depois (`:274-282`).
 *
 * O espelho é conferido por gate em `scripts/teste-agrupamento.mjs --espelho`,
 * que lê o `CaptionLayer.tsx` e reprova se os números divergirem. Se você mudar
 * a ponte lá, o gate acusa aqui.
 */
export const PONTE_MS = 500;
export const CAUDA_MS = 280;

export type Agrupamento = {
  medida: Medida;
  /** orçamento POR LINHA, em px */
  larguraMaxPx: number;
  linhasMax: 1 | 2;
  /** guarda-corpo, NÃO o critério primário */
  maxPalavras: number;
  pausaQuebraMs: number;
  quebraEmPontuacao: boolean;
  /** derivado por `scripts/medir-assentamento.mjs` — nunca chutado */
  minSoloMs: number;
  penalidadeOrfaPx: number;
  orfas: string[];
};

export type Motivo = "largura" | "palavras" | "semantica" | "fim";

export type Pagina = {
  text: string;
  startMs: number;
  durationMs: number;
  tokens: TikTokToken[];
  linhas: TikTokToken[][];
  /** o que fechou a página. `largura`+`palavras` = "fechada por layout". */
  motivo: Motivo;
};

export type Aviso = {
  tipo: "solo-nao-fundido" | "linha-estourada";
  startMs: number;
  texto: string;
  detalhe: string;
};

export type Relatorio = {
  paginas: Pagina[];
  avisos: Aviso[];
  fechamentos: Record<Motivo, number>;
  fundidas: { tras: number; frente: number };
};

// --------------------------------------------------------------- medidores
/**
 * Medidor de FORA do browser: soma os advance widths da tabela gerada por
 * `scripts/largura-fonte.py`.
 *
 * O que ele não faz, e está declarado no próprio JSON: kerning (GPOS),
 * ligaduras e shaping. A divergência contra o Chrome é o critério de aceite nº 6
 * da SPEC-13 e é [verif] — enquanto não for medida, `correcao` vale `null` e
 * aqui se multiplica por 1. `null` quer dizer "não medido", não "1,0 conferido".
 *
 * ⚠️ `entreletras` é somado por CARACTERE (n), não por par (n−1): é o
 * comportamento do Chrome, que aplica letter-spacing depois de cada caractere
 * inclusive o último. Nas legendas `entreletras` é 0, então isto só pesa no
 * `HookTitle` (Anton com +1 px) — e é lá que o critério 6 tem que conferir.
 */
export type TabelaLarguras = {
  familia: string;
  peso: number;
  italico: boolean;
  unitsPerEm: number;
  fallback: number;
  correcao: number | null;
  advance: Record<string, number>;
};

export const medidorDeTabela = (tab: TabelaLarguras): Medidor => {
  const k = tab.correcao ?? 1;
  return (texto, m) => {
    const t = m.caixa === "uppercase" ? texto.toUpperCase() : texto;
    let unidades = 0;
    let n = 0;
    for (const ch of t) {
      unidades += tab.advance[String(ch.codePointAt(0))] ?? tab.fallback;
      n++;
    }
    return ((unidades / tab.unitsPerEm) * m.tamanho + (m.entreletras ?? 0) * n) * k;
  };
};

// ------------------------------------------------------------- quebra de linha
const normaliza = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

/**
 * Índice de corte que minimiza o desequilíbrio de largura entre as duas linhas,
 * com penalidade quando a linha de cima termina em palavra órfã. É o `splitTwo`
 * do ref-A (`SimpleCaptions.tsx:130-144`).
 *
 * Genérico de propósito: `medida.ts` chama com strings, `agrupar` com tokens.
 */
export function melhorQuebra<T>(
  itens: T[],
  largEsq: (xs: T[]) => number,
  largDir: (xs: T[]) => number,
  penalidadeOrfaPx: number,
  orfas: string[],
  textoDe: (x: T) => string = (x) => String(x)
): number {
  const orfasSet = new Set(orfas.map(normaliza));
  let melhor = 1;
  let melhorCusto = Infinity;
  for (let i = 1; i < itens.length; i++) {
    const cima = itens.slice(0, i);
    const baixo = itens.slice(i);
    const ultima = normaliza(textoDe(cima[cima.length - 1]));
    const custo =
      Math.abs(largEsq(cima) - largDir(baixo)) +
      (orfasSet.has(ultima) ? penalidadeOrfaPx : 0);
    if (custo < melhorCusto) {
      melhorCusto = custo;
      melhor = i;
    }
  }
  return melhor;
}

// ------------------------------------------------------------------ agrupar
const textoDaPagina = (tokens: TikTokToken[]) => tokens.map((t) => t.text).join("");

const fimDe = (p: { tokens: TikTokToken[] }) => Math.max(...p.tokens.map((t) => t.toMs));

/**
 * Duração EFETIVA de uma página, aplicando a mesma ponte de
 * `CaptionLayer.tsx:151-156`. É esta — e não `end − start` da palavra — que o
 * piso de solo tem que medir.
 */
export const duracaoEfetiva = (
  paginas: { startMs: number; tokens: TikTokToken[] }[],
  i: number,
  fimMs = Infinity
): number => {
  const p = paginas[i];
  const prox = paginas[i + 1] ?? null;
  const ultimoFim = fimDe(p);
  const fim =
    prox && prox.startMs - ultimoFim < PONTE_MS
      ? prox.startMs
      : Math.min(ultimoFim + CAUDA_MS, fimMs);
  return fim - p.startMs;
};

const montaLinhas = (tokens: TikTokToken[], a: Agrupamento, medir: Medidor): TikTokToken[][] => {
  if (a.linhasMax < 2 || tokens.length < 2) return [tokens];
  const corte = melhorQuebra(
    tokens,
    (xs) => medir(textoDaPagina(xs).trimStart(), a.medida),
    (xs) => medir(textoDaPagina(xs).trimStart(), a.medida),
    a.penalidadeOrfaPx,
    a.orfas,
    (t) => t.text
  );
  const cima = tokens.slice(0, corte);
  const baixo = tokens.slice(corte);
  // a primeira palavra da linha de baixo perde o espaço à esquerda: ela passa a
  // ser início de linha, e o espaço herdado deslocaria a centralização.
  baixo[0] = { ...baixo[0], text: baixo[0].text.trimStart() };
  return [cima, baixo];
};

/**
 * O algoritmo. Mecanismo de `SimpleCaptions.tsx:100-122`, reescrito.
 *
 * A ORDEM DOS CRITÉRIOS IMPORTA e está medida (SPEC-13 §3.3): com o teto de
 * palavras baixo, ele volta a ser o critério primário e a largura continua
 * dispersa — teto 3 devolve CV 0,278, praticamente o 0,275 de hoje.
 */
export function agruparComRelatorio(
  captions: Caption[],
  a: Agrupamento,
  medir: Medidor,
  fimMs = Infinity
): Relatorio {
  const orcamento = a.larguraMaxPx * a.linhasMax;
  const itens = captions.filter((c) => c.text.trim() !== "");
  /**
   * O teste de "cabe". Com `linhasMax: 1` é só o total. Com 2 é o total E CADA
   * LINHA — e essa segunda metade não é preciosismo: medido na `vsl-captions.json`
   * a 1920 px, o teste só pelo total deixa passar linha de 1322 px num orçamento
   * de 1190 px por linha, e é o Chrome que decide onde ela quebra. Seria o defeito
   * que esta spec conserta, sobrevivendo dentro do caminho novo.
   */
  const cabeNaPagina = (tokens: TikTokToken[]) => {
    if (medir(textoDaPagina(tokens), a.medida) > orcamento) return false;
    if (a.linhasMax < 2 || tokens.length < 2) return true;
    return montaLinhas(tokens, a, medir).every(
      (ln) => medir(textoDaPagina(ln).trimStart(), a.medida) <= a.larguraMaxPx
    );
  };
  const fechamentos: Record<Motivo, number> = { largura: 0, palavras: 0, semantica: 0, fim: 0 };
  const avisos: Aviso[] = [];

  type Cru = { tokens: TikTokToken[]; motivo: Motivo };
  const cruas: Cru[] = [];
  let atual: TikTokToken[] = [];

  const fecha = (motivo: Motivo) => {
    if (!atual.length) return;
    cruas.push({ tokens: atual, motivo });
    fechamentos[motivo]++;
    atual = [];
  };
  const comoPrimeiro = (t: TikTokToken): TikTokToken => ({ ...t, text: t.text.trimStart() });

  for (let i = 0; i < itens.length; i++) {
    const c = itens[i];
    const tk: TikTokToken = { text: c.text, fromMs: c.startMs, toMs: c.endMs };

    if (atual.length) {
      const tentativa = [...atual, tk];
      const excedeLargura = !cabeNaPagina(tentativa);
      const excedePalavras = tentativa.length > a.maxPalavras;
      if (excedeLargura || excedePalavras) {
        // largura primeiro: quando os dois estouram juntos, quem mandou foi o
        // espaço na tela — é o que a tabela do §3.3 separa em 27/2.
        fecha(excedeLargura ? "largura" : "palavras");
        atual = [comoPrimeiro(tk)];
      } else {
        atual = tentativa;
      }
    } else {
      atual = [comoPrimeiro(tk)];
    }

    const prox = itens[i + 1];
    const gap = prox ? prox.startMs - c.endMs : Infinity;
    const pontua = a.quebraEmPontuacao && PONTUACAO.test(c.text.trimEnd());
    if (prox && (pontua || gap > a.pausaQuebraMs)) fecha("semantica");
  }
  fecha("fim");

  // ------------------------------------------------- passe de fusão de solos
  // Mecanismo de `caption_style.py:134-165` (para trás primeiro, depois para
  // frente), reescrito. O NÚMERO (`minSoloMs`) é nosso e derivado — ver
  // scripts/medir-assentamento.mjs.
  const fundidas = { tras: 0, frente: 0 };
  const cabe = cabeNaPagina;
  const comEspaco = (t: TikTokToken): TikTokToken =>
    t.text.startsWith(" ") ? t : { ...t, text: ` ${t.text}` };
  const semEspaco = (t: TikTokToken): TikTokToken => ({ ...t, text: t.text.trimStart() });
  /** houve SILÊNCIO REAL entre a página i e a i+1? */
  const pausaReal = (i: number) =>
    cruas[i + 1] !== undefined &&
    cruas[i + 1].tokens[0].fromMs - fimDe(cruas[i]) > a.pausaQuebraMs;
  const soloCurto = (i: number, atuais: Cru[]) => {
    if (atuais[i].tokens.length !== 1) return false;
    const comStart = atuais.map((c) => ({ startMs: c.tokens[0].fromMs, tokens: c.tokens }));
    return duracaoEfetiva(comStart, i, fimMs) < a.minSoloMs;
  };

  let mudou = true;
  while (mudou) {
    mudou = false;
    for (let i = 0; i < cruas.length; i++) {
      if (!soloCurto(i, cruas)) continue;
      const solo = cruas[i].tokens[0];
      // ⚠️ NÃO fundir através de uma PAUSA REAL: a fronteira existe porque houve
      // silêncio. Fundir por cima dela desfaz a decisão semântica e cola duas
      // frases numa página só. Fronteira de pontuação com fala contínua, sim.
      const tras = i > 0 && !pausaReal(i - 1) ? cruas[i - 1] : null;
      if (tras && cabe([...tras.tokens, comEspaco(solo)])) {
        tras.tokens = [...tras.tokens, comEspaco(solo)];
        cruas.splice(i, 1);
        fundidas.tras++;
        mudou = true;
        break;
      }
      const frente = i + 1 < cruas.length && !pausaReal(i) ? cruas[i + 1] : null;
      if (frente && cabe([semEspaco(solo), ...frente.tokens.map(comEspaco)])) {
        frente.tokens = [semEspaco(solo), ...frente.tokens.map(comEspaco)];
        cruas.splice(i, 1);
        fundidas.frente++;
        mudou = true;
        break;
      }
    }
  }

  // 🔴 O que sobrou de solo curto FICA, e vira aviso. Fundir estourando o
  // orçamento reintroduz exatamente o defeito que esta spec conserta.
  for (let i = 0; i < cruas.length; i++) {
    if (!soloCurto(i, cruas)) continue;
    const comStart = cruas.map((c) => ({ startMs: c.tokens[0].fromMs, tokens: c.tokens }));
    avisos.push({
      tipo: "solo-nao-fundido",
      startMs: cruas[i].tokens[0].fromMs,
      texto: cruas[i].tokens[0].text.trim(),
      detalhe: `duração efetiva ${Math.round(
        duracaoEfetiva(comStart, i, fimMs)
      )}ms < min_solo ${a.minSoloMs}ms; vizinhas sem espaço no orçamento`,
    });
  }

  // ------------------------------------------------------------- linhas + saída
  const paginas: Pagina[] = cruas.map((c) => ({
    text: textoDaPagina(c.tokens).trimStart(),
    startMs: c.tokens[0].fromMs,
    durationMs: 0,
    tokens: c.tokens,
    linhas: montaLinhas(c.tokens, a, medir),
    motivo: c.motivo,
  }));
  for (let i = 0; i < paginas.length; i++) {
    paginas[i].durationMs = duracaoEfetiva(paginas, i, fimMs);
    for (const ln of paginas[i].linhas) {
      const w = medir(textoDaPagina(ln).trimStart(), a.medida);
      if (w > a.larguraMaxPx) {
        avisos.push({
          tipo: "linha-estourada",
          startMs: paginas[i].startMs,
          texto: textoDaPagina(ln).trim(),
          detalhe: `${Math.round(w)}px > ${Math.round(a.larguraMaxPx)}px`,
        });
      }
    }
  }

  return { paginas, avisos, fechamentos, fundidas };
}

/** A assinatura da §3.3: só as páginas. */
export const agrupar = (
  captions: Caption[],
  a: Agrupamento,
  medir: Medidor,
  fimMs = Infinity
): Pagina[] => agruparComRelatorio(captions, a, medir, fimMs).paginas;

// ------------------------------------------------------- do perfil para os px
type PerfilLegenda = {
  legenda?: {
    max_palavras_pagina?: number;
    estilo?: {
      familia: string;
      peso?: number;
      italico?: boolean;
      tamanho_pct: number;
      entreletras_pct?: number;
      altura_linha?: number;
      caixa?: "uppercase" | null;
    };
    agrupamento?: {
      largura_max_pct: number;
      linhas_max: 1 | 2;
      pausa_quebra_ms: number;
      quebra_em_pontuacao: boolean;
      min_solo_ms: number | null;
      penalidade_orfa_px: number;
      orfas: string[];
    } | null;
  } | null;
};

/**
 * Perfil de peça → `Agrupamento` em px. Tudo no perfil é FRAÇÃO DO QUADRO, pela
 * mesma razão da SPEC-00 §3.4 para `zonas_ui`: px morrem quando a resolução
 * muda. A conversão acontece aqui, na hora do render, com a largura real do
 * canvas.
 *
 * `null` quando a peça não tem agrupamento (longform: legenda é `.srt` não
 * queimada, e quebra de `.srt` é por caracteres e convenção de broadcast).
 */
export const agrupamentoDoPerfil = (
  p: PerfilLegenda,
  larguraCanvas: number
): Agrupamento | null => {
  const leg = p.legenda;
  const ag = leg?.agrupamento;
  if (!leg || !ag) return null;
  const est = leg.estilo;
  if (!est) throw new Error("perfil com legenda.agrupamento mas sem legenda.estilo");
  if (ag.min_solo_ms === null || ag.min_solo_ms === undefined) {
    throw new Error(
      "legenda.agrupamento.min_solo_ms está null: rode " +
        "scripts/medir-assentamento.mjs e grave o valor derivado no perfil."
    );
  }
  return {
    medida: {
      familia: est.familia,
      peso: est.peso,
      italico: est.italico,
      tamanho: est.tamanho_pct * larguraCanvas,
      entreletras: (est.entreletras_pct ?? 0) * larguraCanvas,
      caixa: est.caixa ?? null,
    },
    larguraMaxPx: ag.largura_max_pct * larguraCanvas,
    linhasMax: ag.linhas_max,
    maxPalavras: leg.max_palavras_pagina ?? 6,
    pausaQuebraMs: ag.pausa_quebra_ms,
    quebraEmPontuacao: ag.quebra_em_pontuacao,
    minSoloMs: ag.min_solo_ms,
    penalidadeOrfaPx: ag.penalidade_orfa_px,
    orfas: ag.orfas,
  };
};
