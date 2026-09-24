#!/usr/bin/env node
/**
 * medir-assentamento.mjs — de onde sai o `min_solo_ms` (SPEC-13 §3.5).
 *
 * Uma página de legenda com UMA palavra só na tela precisa ficar tempo bastante
 * para o olho registrar um beat, e não um piscar. Esse piso NÃO é um número de
 * gosto: ele é a duração da NOSSA animação de entrada mais uma margem de frames
 * parados. Trocar o `damping` do `AccentWord` muda o piso — e é por isso que ele
 * é medido aqui e conferido no perfil, em vez de escrito à mão.
 *
 *     min_solo_ms = t_assenta(config, fps, tol) + frames_estaveis / fps * 1000
 *
 * ⚠️ O ref-A usa `MIN_SOLO_MS = 340` (`helpers/caption_style.py:53`). NÃO É
 * TRANSFERÍVEL: (a) a animação de entrada deles encolhe com a cue
 * (`StackedCaptions.tsx:100`, `ENTER = clamp(floor(dur*0.45), 3, 8)`) e a nossa é
 * física fixa; (b) eles testam a duração da PALAVRA (`caption_style.py:104-111`)
 * enquanto o próprio código estica a cue depois (`:274-282`) — medem a coisa
 * errada. A nossa duração efetiva já é a esticada, por causa da ponte
 * anti-piscada de `CaptionLayer.tsx:151-156`.
 *
 * USO
 *     medir-assentamento.mjs --fps 30 --tol 0.02 --frames-estaveis 4 \
 *          --config accent=13,220 --config pop=20,300 [--saida <arquivo>]
 *     medir-assentamento.mjs --verificar <perfil.json>   → exit 1 se o perfil
 *                                                          trouxer valor menor
 *
 * stdout = caminho do artefato (ou o veredito do --verificar) · stderr = a conta.
 *
 * A matemática do `spring` roda em Node — não precisa de browser nem de render.
 * Nenhum valor de formato mora aqui: fps, tolerância, frames estáveis e as
 * configs entram por argumento; o `--verificar` lê o fps DO PERFIL.
 */
import { spring, measureSpring } from "remotion";
import fs from "node:fs";
import path from "node:path";

const CONTRATO = "benchmark.assentamento/v1";

/**
 * As DUAS leituras de "assentou", porque elas não coincidem e a diferença é o
 * defeito que este script existe para não deixar passar.
 *
 * `primeira_entrada` — primeiro frame com |v−1| ≤ tol. É a definição que a
 *   SPEC-13 §2.5 usou para publicar 400,0 ms / `min_solo_ms` 533.
 * `definitiva` — primeiro frame a partir do qual a curva NÃO SAI MAIS da faixa.
 *
 * 📏 MEDIDO AQUI, e é por isso que a `definitiva` é a que manda: com
 * damping 13 / stiffness 220 / fps 30 a curva ENTRA na faixa no frame 12
 * (400,0 ms, 0,9863) e SAI de novo — frame 14 vale 0,9534, um mergulho de
 * −4,7 % — voltando de vez só no frame 17 (566,7 ms). Os 400 ms são uma
 * passagem, não um assentamento: o elemento ainda está se mexendo, e é
 * exatamente o dip-e-recover que o `flicker-scan.py` classificaria como piscada.
 * A varredura é DE TRÁS PARA FRENTE de propósito — para frente ela para na
 * primeira passagem e devolve um número menor do que a física.
 */
const assentaFrames = (config, fps, tol) => {
  const horizonte = Math.max(measureSpring({ fps, config, threshold: tol / 4 }), Math.ceil(fps * 5));
  let f = horizonte;
  while (f > 0 && Math.abs(spring({ frame: f - 1, fps, config }) - 1) <= tol) f--;
  let primeira = f;
  for (let g = 0; g <= f; g++) {
    if (Math.abs(spring({ frame: g, fps, config }) - 1) <= tol) {
      primeira = g;
      break;
    }
  }
  return { frames: f, primeira, horizonte };
};

const pico = (config, fps, horizonte) => {
  let v = -Infinity;
  let frame = 0;
  for (let f = 0; f <= horizonte; f++) {
    const y = spring({ frame: f, fps, config });
    if (y > v) {
      v = y;
      frame = f;
    }
  }
  return { valor: v, frame };
};

export const medir = (config, fps, tol, framesEstaveis) => {
  const { frames, primeira, horizonte } = assentaFrames(config, fps, tol);
  const p = pico(config, fps, horizonte);
  const margemMs = (framesEstaveis / fps) * 1000;
  const assentaMs = (frames / fps) * 1000;
  const primeiraMs = (primeira / fps) * 1000;
  return {
    damping: config.damping,
    stiffness: config.stiffness,
    pico: Number(p.valor.toFixed(4)),
    pico_frame: p.frame,
    pico_ms: Number(((p.frame / fps) * 1000).toFixed(1)),
    assenta_frames: frames,
    assenta_ms: Number(assentaMs.toFixed(1)),
    min_solo_ms: Math.round(assentaMs + margemMs),
    // as duas linhas abaixo existem para a divergência ficar VISÍVEL no artefato
    // em vez de virar discussão: são os números da §2.5 da spec.
    assenta_ms_primeira_entrada: Number(primeiraMs.toFixed(1)),
    min_solo_ms_primeira_entrada: Math.round(primeiraMs + margemMs),
  };
};

// ---------------------------------------------------------------------- CLI
const arg = (a, nome, def) => (a.includes(nome) ? a[a.indexOf(nome) + 1] : def);
const todos = (a, nome) => a.flatMap((x, i) => (x === nome ? [a[i + 1]] : []));

const parseConfigs = (specs) => {
  const out = {};
  for (const s of specs) {
    const m = /^([A-Za-z0-9_-]+)=(-?[\d.]+),(-?[\d.]+)$/.exec(s ?? "");
    if (!m) {
      console.error(`--config inválido: ${JSON.stringify(s)} (esperado nome=damping,stiffness)`);
      process.exit(64);
    }
    out[m[1]] = { damping: Number(m[2]), stiffness: Number(m[3]) };
  }
  return out;
};

const CONFIGS_PADRAO = ["accent=13,220", "pop=20,300"];

const main = (a) => {
  const tol = Number(arg(a, "--tol", "0.02"));
  const framesEstaveis = Number(arg(a, "--frames-estaveis", "4"));
  const specs = todos(a, "--config");
  const configs = parseConfigs(specs.length ? specs : CONFIGS_PADRAO);

  if (a.includes("--verificar")) {
    const arq = arg(a, "--verificar");
    if (!arq) {
      console.error("uso: --verificar <perfil.json>");
      return 64;
    }
    const p = JSON.parse(fs.readFileSync(arq, "utf8"));
    // o fps vem DO PERFIL: o piso em ms muda pouco com o fps, mas quem decide o
    // fps é o formato, nunca este script.
    const fps = Number(p?.video?.fps ?? arg(a, "--fps", "30"));
    const ag = p?.legenda?.agrupamento;
    if (ag === null || ag === undefined) {
      console.log(`${arq}: sem legenda.agrupamento — nada a verificar`);
      return 0;
    }
    const medidas = Object.entries(configs).map(([n, c]) => [n, medir(c, fps, tol, framesEstaveis)]);
    // O piso é o MAIOR dos componentes que podem estar na página: uma palavra
    // solo tem que sobreviver à animação mais lenta que pode cair sobre ela.
    const [nomeAlto, alto] = medidas.reduce((m, x) => (x[1].min_solo_ms > m[1].min_solo_ms ? x : m));
    const tem = ag.min_solo_ms;
    console.error(
      `${arq}: fps=${fps} tol=${tol} frames_estaveis=${framesEstaveis} · ` +
        medidas.map(([n, m]) => `${n}=${m.min_solo_ms}ms`).join(" ") +
        ` · piso=${alto.min_solo_ms}ms (${nomeAlto})`
    );
    if (tem === null || tem === undefined) {
      console.error(
        `${arq}: legenda.agrupamento.min_solo_ms é null — preencha com ${alto.min_solo_ms} ` +
          `(derivado de ${nomeAlto}: damping ${alto.damping}, stiffness ${alto.stiffness})`
      );
      return 1;
    }
    if (Number(tem) < alto.min_solo_ms) {
      console.error(
        `${arq}: min_solo_ms=${tem} é MENOR que o derivado ${alto.min_solo_ms} ` +
          `(${nomeAlto}: assenta ${alto.assenta_ms}ms + ${framesEstaveis} frames). ` +
          `Uma página de 1 palavra sairia da tela antes de a animação assentar.`
      );
      return 1;
    }
    console.log(`${arq}: OK — min_solo_ms=${tem} ≥ ${alto.min_solo_ms} (${nomeAlto})`);
    return 0;
  }

  const fps = Number(arg(a, "--fps", "30"));
  const componentes = {};
  for (const [n, c] of Object.entries(configs)) {
    const m = medir(c, fps, tol, framesEstaveis);
    componentes[n] = m;
    console.error(
      `${n.padEnd(7)}: pico ${m.pico.toFixed(4)} @${m.pico_ms}ms · ` +
        `assenta ${m.assenta_ms}ms (frame ${m.assenta_frames}) · min_solo ${m.min_solo_ms}ms` +
        (m.assenta_ms === m.assenta_ms_primeira_entrada
          ? ""
          : `  ⚠️ primeira entrada na faixa aos ${m.assenta_ms_primeira_entrada}ms ` +
            `(min_solo ${m.min_solo_ms_primeira_entrada}) — é PASSAGEM, a curva sai de novo`)
    );
  }
  const doc = { contrato: CONTRATO, fps, tol, frames_estaveis: framesEstaveis, componentes };
  const saida = arg(a, "--saida", "assentamento.json");
  fs.mkdirSync(path.dirname(path.resolve(saida)), { recursive: true });
  fs.writeFileSync(saida, JSON.stringify(doc, null, 1) + "\n");
  console.log(path.resolve(saida));
  return 0;
};

if (import.meta.url === `file://${process.argv[1]}`) {
  process.exit(main(process.argv.slice(2)));
}
