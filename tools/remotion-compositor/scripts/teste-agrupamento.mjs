#!/usr/bin/env node
/**
 * teste-agrupamento.mjs — roda `src/texto/agrupar.ts` FORA do browser e mede
 * (SPEC-13 §8.3, §8.6). É onde os critérios de aceite 1, 2, 3, 4, 8, 9 e 11 viram
 * número.
 *
 * O agrupamento recebe o medidor por parâmetro justamente para isto: aqui o
 * medidor é a tabela de advance widths do TTF (`scripts/largura-fonte.py`), no
 * Chrome do Remotion é o `measureText`. Mesmo algoritmo, duas réguas.
 *
 * Node 22 faz type-stripping nativo: o import de `.ts` COM EXTENSÃO EXPLÍCITA
 * roda direto. Não instale `tsx` nem `ts-node`.
 *
 *   # por parâmetro solto
 *   teste-agrupamento.mjs --captions src/data/captions.peca-02.json \
 *      --larguras src/data/larguras/Montserrat-700.json \
 *      --tamanho 58 --orcamento 900 --linhas 1 --max-palavras 6 \
 *      --pausa 450 --min-solo 533 [--relatorio /tmp/r.md]
 *
 *   # dirigido pelo PERFIL DE PEÇA (é o critério 8)
 *   teste-agrupamento.mjs --captions src/data/vsl-captions.json \
 *      --perfil ../../skills/edit-video/perfis/reels.json --canvas 1080
 *
 *   # gates que não dependem de captions
 *   teste-agrupamento.mjs --espelho     # PONTE_MS/CAUDA_MS × CaptionLayer.tsx
 *   teste-agrupamento.mjs --autoteste   # planta defeitos que os gates TÊM que acusar
 *
 * `--json` troca a saída legível por uma linha de JSON.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createTikTokStyleCaptions } from "@remotion/captions";
import {
  agruparComRelatorio,
  agrupamentoDoPerfil,
  medidorDeTabela,
  duracaoEfetiva,
  PONTE_MS,
  CAUDA_MS,
} from "../src/texto/agrupar.ts";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.join(AQUI, "..");
const DIR_LARGURAS = path.join(RAIZ, "src", "data", "larguras");

const arg = (a, n, d) => (a.includes(n) ? a[a.indexOf(n) + 1] : d);
const num = (a, n, d) => Number(arg(a, n, String(d)));

// ------------------------------------------------------------------ estatística
const stats = (xs) => {
  if (!xs.length) return { n: 0, min: 0, max: 0, p50: 0, cv: 0 };
  const s = [...xs].sort((x, y) => x - y);
  const m = xs.reduce((x, y) => x + y, 0) / xs.length;
  const sd = Math.sqrt(xs.reduce((x, y) => x + (y - m) ** 2, 0) / xs.length);
  return {
    n: xs.length,
    min: Math.round(s[0]),
    max: Math.round(s[s.length - 1]),
    p50: Math.round(s[Math.floor(s.length / 2)]),
    cv: Number((sd / m).toFixed(3)),
  };
};

const normaliza = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

// -------------------------------------------------------------- gate do espelho
/**
 * A ponte anti-piscada mora em `CaptionLayer.tsx`; `agrupar.ts` guarda uma
 * CÓPIA dos dois números para calcular a duração efetiva. Cópia sem gate vira
 * divergência silenciosa — este é o gate.
 */
const espelho = () => {
  const arq = path.join(RAIZ, "src", "CaptionLayer.tsx");
  const src = fs.readFileSync(arq, "utf8");
  const mPonte = /prox\.startMs\s*-\s*ultimoFim\s*<\s*(\d+)/.exec(src);
  const mCauda = /ultimoFim\s*\+\s*(\d+)/.exec(src);
  const achados = [mPonte, mCauda].filter(Boolean).length;
  console.error(`espelho: varri ${src.split("\n").length} linhas de ${path.relative(RAIZ, arq)}, casei ${achados}/2 padrões`);
  if (!mPonte || !mCauda) {
    console.error("espelho: FALHOU — não achei a ponte no CaptionLayer.tsx. " +
      "Se a ponte mudou de forma, este gate tem que ser reescrito junto.");
    return 1;
  }
  const ok = Number(mPonte[1]) === PONTE_MS && Number(mCauda[1]) === CAUDA_MS;
  console.error(
    `espelho: CaptionLayer ponte=${mPonte[1]}ms cauda=${mCauda[1]}ms · ` +
      `agrupar.ts PONTE_MS=${PONTE_MS} CAUDA_MS=${CAUDA_MS} → ${ok ? "OK" : "DIVERGIU"}`
  );
  return ok ? 0 : 1;
};

// --------------------------------------------------------------------- medir
const carregaTabela = (medida, explicito) => {
  const arq =
    explicito ??
    path.join(
      DIR_LARGURAS,
      `${medida.familia.replace(/\s+/g, "")}-${medida.peso ?? 400}${medida.italico ? "-italic" : ""}.json`
    );
  if (!fs.existsSync(arq)) {
    throw new Error(
      `tabela de larguras não existe: ${arq}\n` +
        `gere com: python3 scripts/largura-fonte.py --familia "${medida.familia}" ` +
        `--peso ${medida.peso ?? 400}${medida.italico ? " --italico" : ""}`
    );
  }
  return JSON.parse(fs.readFileSync(arq, "utf8"));
};

const rodar = (captions, ag, medir, fimMs) => {
  const r = agruparComRelatorio(captions, ag, medir, fimMs);
  const larguras = r.paginas.map((p) => medir(p.tokens.map((t) => t.text).join(""), ag.medida));
  const porLayout = r.paginas
    .map((p, i) => [p, larguras[i]])
    .filter(([p]) => p.motivo === "largura" || p.motivo === "palavras")
    .map(([, w]) => w);
  const orcamento = ag.larguraMaxPx * ag.linhasMax;
  const duasLinhas = r.paginas.filter((p) => p.linhas.length === 2);
  const orfas = new Set(ag.orfas.map(normaliza));
  const orfasVistas = duasLinhas.filter((p) => {
    const cima = p.linhas[0];
    return orfas.has(normaliza(cima[cima.length - 1].text));
  });
  /**
   * Critério 9 (a parte dura): CADA órfã que sobrou tem que ter justificativa —
   * o desequilíbrio da melhor alternativa SEM órfã excede a penalidade. Isto é
   * verdade por construção quando a penalidade está de fato sendo aplicada; se
   * alguém a esquecer, aparecem órfãs com folga pequena e este número acusa.
   */
  const larg = (xs) => medir(xs.map((t) => t.text).join("").trimStart(), ag.medida);
  const justificativas = orfasVistas.map((p) => {
    const n = p.tokens.length;
    const cortes = [];
    for (let i = 1; i < n; i++) {
      const cima = p.tokens.slice(0, i);
      const baixo = p.tokens.slice(i);
      cortes.push({
        i,
        deseq: Math.abs(larg(cima) - larg(baixo)),
        orfa: orfas.has(normaliza(cima[cima.length - 1].text)),
      });
    }
    const escolhido = cortes.reduce((m, c) =>
      c.deseq + (c.orfa ? ag.penalidadeOrfaPx : 0) < m.deseq + (m.orfa ? ag.penalidadeOrfaPx : 0) ? c : m
    );
    const alternativas = cortes.filter((c) => !c.orfa);
    if (!alternativas.length) return { texto: p.text, folga: Infinity, sem_alternativa: true };
    const melhorSem = alternativas.reduce((m, c) => (c.deseq < m.deseq ? c : m));
    return {
      texto: p.text,
      folga: Math.round(melhorSem.deseq - escolhido.deseq),
      sem_alternativa: false,
    };
  });
  const orfasInjustificadas = justificativas.filter(
    (j) => !j.sem_alternativa && j.folga < ag.penalidadeOrfaPx
  );
  const solos = r.paginas.filter((p) => p.tokens.length === 1);
  const solosCurtos = r.paginas.filter(
    (p, i) => p.tokens.length === 1 && duracaoEfetiva(r.paginas, i, fimMs) < ag.minSoloMs
  );
  return {
    paginas: r.paginas.length,
    fechamentos: r.fechamentos,
    fundidas: r.fundidas,
    todas: stats(larguras),
    layout: stats(porLayout),
    estouros: larguras.filter((w) => w > orcamento + 1e-6).length,
    orcamento,
    solos: solos.length,
    solos_curtos: solosCurtos.length,
    duas_linhas: duasLinhas.length,
    orfas: orfasVistas.length,
    orfas_injustificadas: orfasInjustificadas.length,
    orfas_justificativas: justificativas,
    avisos: r.avisos,
    _r: r,
    _larguras: larguras,
  };
};

/** O baseline de hoje: agrupamento por TEMPO, com o mesmo medidor. */
const legado = (captions, ag, medir, combinaMs) => {
  const { pages } = createTikTokStyleCaptions({
    captions,
    combineTokensWithinMilliseconds: combinaMs,
  });
  const larguras = pages.map((p) => medir(p.tokens.map((t) => t.text).join(""), ag.medida));
  const orcamento = ag.larguraMaxPx * ag.linhasMax;
  return {
    paginas: pages.length,
    todas: stats(larguras),
    estouros: larguras.filter((w) => w > orcamento + 1e-6).length,
    tempo_na_tela: pages.reduce((s, _, i) => s + duracaoEfetiva(pages, i), 0),
  };
};

// ----------------------------------------------------------------- autoteste
/**
 * 🔴 Portão verde e portão quebrado são indistinguíveis sem isto. Cada caso
 * planta um defeito que um gate ESPECÍFICO tem que acusar; se algum passar
 * limpo, o gate correspondente está cego.
 */
const autoteste = () => {
  const tab = JSON.parse(fs.readFileSync(path.join(DIR_LARGURAS, "Montserrat-700.json"), "utf8"));
  const medir = medidorDeTabela(tab);
  const base = {
    medida: { familia: "Montserrat", peso: 700, tamanho: 58, entreletras: 0, caixa: null },
    larguraMaxPx: 900,
    linhasMax: 1,
    maxPalavras: 6,
    pausaQuebraMs: 450,
    quebraEmPontuacao: true,
    minSoloMs: 533,
    penalidadeOrfaPx: 200,
    orfas: ["o", "a", "de", "que"],
  };
  // 🔴 A FIXTURE DO AUTOTESTE NÃO PODE SER FALA DE CREATOR (2026-08-12, H47-9).
  // Aqui estava `src/data/captions.peca-02.json`, cravado: é fala literal
  // transcrita de uma pessoa real, classificada `nunca_sai`, e por isso NÃO
  // embarca. No pacote o `--autoteste` morria de `ENOENT` — a prova de dentes
  // deste arquivo simplesmente não existia na máquina de quem instalou.
  // A ordem abaixo é preferência, e a última é o que o pacote tem
  // (`captions.exemplo.json` vira `captions.json` no export). Nenhuma existindo,
  // o autoteste DECLARA que não mediu e sai 2 — nunca verde.
  const candidatas = [
    "captions.autoteste.json", // ESCRITA para este autoteste (nada de creator)
    "captions.json",           // o que o pacote tem, se a de cima faltar
  ];
  const fCaps = candidatas
    .map((f) => path.join(RAIZ, "src", "data", f))
    .find((p) => fs.existsSync(p));
  if (!fCaps) {
    console.error(
      "NÃO MEDIDO: nenhuma fixture de legenda em src/data/ (procurei " +
        candidatas.join(", ") + "). O autoteste do agrupamento precisa de " +
        "captions para plantar defeito — sem elas não há verde, há ausência.",
    );
    process.exit(2);
  }
  console.error(`autoteste: fixture ${path.basename(fCaps)}`);
  const caps = JSON.parse(fs.readFileSync(fCaps, "utf8"));
  const casos = [];

  // 1. orçamento absurdamente grande → o gate de estouro NÃO pode acusar, mas o
  //    de dispersão TEM que explodir (uma página só, ou pouquíssimas).
  // (o teto aqui é 2× o orçamento real: sem critério de largura a página só é
  // fechada por pontuação/pausa, e a maior frase corrida mede ~2757px)
  const solto = rodar(caps, { ...base, larguraMaxPx: 100000, maxPalavras: 9999 }, medir);
  casos.push([
    "sem critério de largura a página passa de 2× o orçamento",
    solto.todas.max > 2 * base.larguraMaxPx,
    `max=${solto.todas.max}px vs orçamento ${base.larguraMaxPx}px`,
  ]);

  // 2. orçamento minúsculo → tem que gerar MUITAS páginas e nenhum estouro
  //    (toda palavra sozinha), provando que o critério de largura morde.
  const apertado = rodar(caps, { ...base, larguraMaxPx: 200, minSoloMs: 0 }, medir);
  casos.push([
    "orçamento 200px força página por palavra",
    apertado.paginas > 150,
    `${apertado.paginas} páginas`,
  ]);

  // 3. minSolo absurdo → o gate 4 TEM que acusar solo curto sobrando (avisos),
  //    porque nenhuma fusão cabe.
  const solo = rodar(caps, { ...base, minSoloMs: 99999 }, medir);
  casos.push([
    "min_solo 99999ms deixa solo sem fundir e AVISA",
    solo.avisos.some((x) => x.tipo === "solo-nao-fundido"),
    `${solo.avisos.filter((x) => x.tipo === "solo-nao-fundido").length} avisos`,
  ]);

  // 4. linha estourada com linhasMax 2 e orçamento por linha pequeno.
  const l2 = rodar(caps, { ...base, linhasMax: 2, larguraMaxPx: 300, minSoloMs: 0 }, medir);
  casos.push([
    "linhasMax 2 com orçamento apertado gera linha-estourada",
    l2.avisos.some((x) => x.tipo === "linha-estourada"),
    `${l2.avisos.filter((x) => x.tipo === "linha-estourada").length} avisos`,
  ]);

  // 5. medidor que sempre devolve 0 → só o teto de palavras fecha página.
  const cego = rodar(caps, base, () => 0);
  casos.push([
    "medidor cego (0px) faz o teto de palavras ser o único critério",
    cego.fechamentos.largura === 0 && cego.fechamentos.palavras > 0,
    `largura=${cego.fechamentos.largura} palavras=${cego.fechamentos.palavras}`,
  ]);

  // 6. 🔴 A FUSÃO TEM QUE FUNDIR. Com o orçamento real (900px) as páginas ficam
  //    cheias e NENHUMA fusão cabe — o contador fica 0/0, que é indistinguível
  //    de um passe morto. Com folga no orçamento ela dispara: é este caso que
  //    prova que o passe existe.
  const folgado = rodar(caps, { ...base, larguraMaxPx: 1000 }, medir);
  casos.push([
    "com folga no orçamento a fusão de solo DISPARA",
    folgado.fundidas.tras + folgado.fundidas.frente > 0,
    `← ${folgado.fundidas.tras} → ${folgado.fundidas.frente}`,
  ]);

  // 7. e a fusão NUNCA pode estourar o orçamento — é o defeito que a spec conserta.
  casos.push([
    "nenhuma fusão estourou o orçamento",
    folgado.estouros === 0,
    `${folgado.estouros} estouros, max ${folgado.todas.max}px de ${Math.round(folgado.orcamento)}px`,
  ]);

  let mau = 0;
  for (const [nome, ok, det] of casos) {
    console.error(`${ok ? "  ok  " : "FALHOU"}  ${nome}  (${det})`);
    if (!ok) mau++;
  }
  console.error(`autoteste: ${casos.length - mau}/${casos.length} defeitos plantados foram acusados`);
  return mau === 0 ? 0 : 1;
};

// ----------------------------------------------------------- gate de regressão
/**
 * Critério 7 (a metade barata): o caminho LEGADO — `CaptionLayer` sem
 * `agrupamento` e sem `paginas` — tem que produzir a MESMA lista de `startMs` de
 * página que o código de hoje, por igualdade exata, em todos os `captions.*.json`
 * do `src/data/`.
 *
 *   --regressao --gravar /tmp/base.json   (rodar ANTES de editar)
 *   --regressao /tmp/base.json            (rodar DEPOIS)
 *
 * A outra metade — que o COMPONENTE de fato cai no ramo legado — só um still
 * responde, e está listada como [verif].
 */
const regressao = (a) => {
  const dir = path.join(RAIZ, "src", "data");
  const arqs = fs
    .readdirSync(dir)
    .filter((x) => x.startsWith("captions.") || x === "vsl-captions.json")
    .sort();
  const combinaMs = num(a, "--combina-ms", 1100);
  const atual = {};
  for (const f of arqs) {
    const caps = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
    atual[f] = createTikTokStyleCaptions({
      captions: caps,
      combineTokensWithinMilliseconds: combinaMs,
    }).pages.map((p) => p.startMs);
  }
  const total = Object.values(atual).reduce((s, v) => s + v.length, 0);
  const gravar = arg(a, "--gravar");
  if (gravar) {
    fs.writeFileSync(gravar, JSON.stringify(atual));
    console.error(`regressão: baseline gravado — ${arqs.length} arquivos, ${total} páginas → ${gravar}`);
    console.log(path.resolve(gravar));
    return 0;
  }
  const fBase = a[a.indexOf("--regressao") + 1];
  if (!fBase || fBase.startsWith("--")) {
    console.error("uso: --regressao <baseline.json>  |  --regressao --gravar <baseline.json>");
    return 64;
  }
  const base = JSON.parse(fs.readFileSync(fBase, "utf8"));
  let dif = 0;
  const chaves = new Set([...Object.keys(base), ...Object.keys(atual)]);
  for (const k of chaves) {
    const x = JSON.stringify(base[k] ?? null);
    const y = JSON.stringify(atual[k] ?? null);
    if (x !== y) {
      dif++;
      console.error(`  DIVERGIU ${k}: ${(base[k] ?? []).length} → ${(atual[k] ?? []).length} páginas`);
    }
  }
  console.error(
    `regressão: comparei ${chaves.size} arquivos / ${total} páginas de fronteira · ${dif} divergências`
  );
  return dif === 0 ? 0 : 1;
};

// ---------------------------------------------------------------------- main
const main = (a) => {
  if (a.includes("--espelho")) return espelho();
  if (a.includes("--autoteste")) return autoteste();
  if (a.includes("--regressao")) return regressao(a);

  const fCaps = arg(a, "--captions");
  if (!fCaps) {
    console.error(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("*/")[0]);
    return 64;
  }
  const captions = JSON.parse(fs.readFileSync(fCaps, "utf8"));

  let ag;
  const fPerfil = arg(a, "--perfil");
  if (fPerfil) {
    const p = JSON.parse(fs.readFileSync(fPerfil, "utf8"));
    const canvas = num(a, "--canvas", p?.video?.largura ?? 1080);
    ag = agrupamentoDoPerfil(p, canvas);
    if (ag === null) {
      console.error(`${fPerfil}: legenda.agrupamento é null — esta peça não usa o CaptionLayer`);
      if (a.includes("--json")) console.log(JSON.stringify({ perfil: fPerfil, agrupamento: null }));
      return 0;
    }
  } else {
    ag = {
      medida: {
        familia: arg(a, "--familia", "Montserrat"),
        peso: num(a, "--peso", 700),
        italico: a.includes("--italico"),
        tamanho: num(a, "--tamanho", 58),
        entreletras: num(a, "--entreletras", 0),
        caixa: null,
      },
      larguraMaxPx: num(a, "--orcamento", 900),
      linhasMax: num(a, "--linhas", 1),
      maxPalavras: num(a, "--max-palavras", 6),
      pausaQuebraMs: num(a, "--pausa", 450),
      quebraEmPontuacao: !a.includes("--sem-pontuacao"),
      minSoloMs: num(a, "--min-solo", 533),
      penalidadeOrfaPx: num(a, "--penalidade-orfa", 200),
      orfas: (arg(a, "--orfas", "o,a,os,as,e,é,de,do,da,em,no,na,um,uma,que,se,ao,à,por,com")).split(","),
    };
  }

  const tab = carregaTabela(ag.medida, arg(a, "--larguras"));
  const medir = medidorDeTabela(tab);
  const fimMs = num(a, "--fim-ms", Infinity);

  const novo = rodar(captions, ag, medir, fimMs);
  const velho = legado(captions, ag, medir, num(a, "--combina-ms", 1100));
  const tempoNovo = novo._r.paginas.reduce((s, _, i) => s + duracaoEfetiva(novo._r.paginas, i, fimMs), 0);

  const resumo = {
    captions: path.basename(fCaps),
    perfil: fPerfil ? path.basename(fPerfil) : null,
    fonte: `${tab.familia} ${tab.peso}${tab.italico ? " italic" : ""} @${Math.round(ag.medida.tamanho)}px`,
    orcamento_px: Math.round(novo.orcamento),
    linhas_max: ag.linhasMax,
    max_palavras: ag.maxPalavras,
    min_solo_ms: ag.minSoloMs,
    hoje: {
      paginas: velho.paginas,
      largura_p50: velho.todas.p50,
      largura_max: velho.todas.max,
      cv: velho.todas.cv,
      estouros: velho.estouros,
      tempo_na_tela_ms: Math.round(velho.tempo_na_tela),
    },
    novo: {
      paginas: novo.paginas,
      fechamentos: novo.fechamentos,
      fundidas: novo.fundidas,
      largura_p50: novo.todas.p50,
      largura_max: novo.todas.max,
      cv_todas: novo.todas.cv,
      cv_layout: novo.layout.cv,
      n_layout: novo.layout.n,
      estouros: novo.estouros,
      solos: novo.solos,
      solos_curtos: novo.solos_curtos,
      duas_linhas: novo.duas_linhas,
      orfas: novo.orfas,
      orfas_pct: novo.duas_linhas ? Number(((novo.orfas / novo.duas_linhas) * 100).toFixed(1)) : 0,
      orfas_injustificadas: novo.orfas_injustificadas,
      avisos: novo.avisos.length,
      tempo_na_tela_ms: Math.round(tempoNovo),
    },
    delta_paginas_pct: Number((((novo.paginas - velho.paginas) / velho.paginas) * 100).toFixed(1)),
    delta_tempo_na_tela_pct: Number(
      (((tempoNovo - velho.tempo_na_tela) / velho.tempo_na_tela) * 100).toFixed(1)
    ),
  };

  if (a.includes("--json")) {
    console.log(JSON.stringify(resumo));
  } else {
    console.error(`\n${resumo.captions}  ·  ${resumo.fonte}  ·  orçamento ${resumo.orcamento_px}px × ${ag.linhasMax} linha(s)`);
    console.error(
      `  hoje (combinaMs 1100): ${velho.paginas} pág · p50 ${velho.todas.p50}px · max ${velho.todas.max}px · CV ${velho.todas.cv} · ${velho.estouros} estouros`
    );
    console.error(
      `  novo                 : ${novo.paginas} pág · p50 ${novo.todas.p50}px · max ${novo.todas.max}px · CV(layout) ${novo.layout.cv} (n=${novo.layout.n}) · ${novo.estouros} estouros`
    );
    console.error(
      `  fecha por            : largura ${novo.fechamentos.largura} / palavras ${novo.fechamentos.palavras} / semântica ${novo.fechamentos.semantica} / fim ${novo.fechamentos.fim}`
    );
    console.error(
      `  solos                : ${novo.solos} (curtos ${novo.solos_curtos}) · fundidas ← ${novo.fundidas.tras} → ${novo.fundidas.frente}`
    );
    if (ag.linhasMax === 2)
      console.error(
        `  2 linhas             : ${novo.duas_linhas} páginas · ${novo.orfas} com órfã no fim de cima ` +
          `(${novo.duas_linhas ? ((novo.orfas / novo.duas_linhas) * 100).toFixed(1) : 0}%) · ` +
          `${novo.orfas_injustificadas} sem justificativa (folga < ${ag.penalidadeOrfaPx}px)`
      );
    console.error(
      `  ritmo                : ${resumo.delta_paginas_pct >= 0 ? "+" : ""}${resumo.delta_paginas_pct}% de páginas · tempo na tela ${resumo.delta_tempo_na_tela_pct >= 0 ? "+" : ""}${resumo.delta_tempo_na_tela_pct}%`
    );
    for (const v of novo.avisos.slice(0, 10)) console.error(`  ⚠️  ${v.tipo}: "${v.texto}" — ${v.detalhe}`);
    if (novo.avisos.length > 10) console.error(`  ⚠️  … +${novo.avisos.length - 10} avisos`);
  }

  const rel = arg(a, "--relatorio");
  if (rel) {
    const linhas = [
      `# agrupamento — ${resumo.captions}`,
      "",
      "```json",
      JSON.stringify(resumo, null, 1),
      "```",
      "",
      "| # | motivo | ms | px | linhas | texto |",
      "|---|---|---|---|---|---|",
      ...novo._r.paginas.map(
        (p, i) =>
          `| ${i} | ${p.motivo} | ${p.startMs} | ${Math.round(novo._larguras[i])} | ${p.linhas.length} | ${p.text.replace(/\|/g, "\\|")} |`
      ),
    ];
    fs.mkdirSync(path.dirname(path.resolve(rel)), { recursive: true });
    fs.writeFileSync(rel, linhas.join("\n") + "\n");
    console.log(path.resolve(rel));
  }
  return 0;
};

process.exit(main(process.argv.slice(2)));
