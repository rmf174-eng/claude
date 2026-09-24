// qc-fixture-legenda.mjs — a fixture de legenda do pacote NÃO pode entrar na
// peça de quem instalou (SPEC-47 / H47-4).
//
//   node scripts/qc-fixture-legenda.mjs             mede
//   node scripts/qc-fixture-legenda.mjs --controle  planta o defeito e exige acusação
//
//   exit 0  a fixture não entra quando a peça traz camada própria
//        1  a fixture ENTRA (ou o controle não foi acusado)
//        2  não pôde medir (sem node_modules) — NÃO é verde
//
// 🔴 O DEFEITO, MEDIDO EM CAMPO (2026-08-12, A-2 do teste da v0.12): uma peça
// montada exatamente como a skill manda — entry point próprio, camada gráfica
// própria passada em `extra` — saiu do render com DUAS legendas: a do creator e
// a do produto escrevendo "Este é um exemplo de legenda" na tela. Causa:
// `Main.tsx` trocava os `Overlays` por `extra` mas renderizava `<Captions />`
// SEMPRE, e `Captions.tsx` importa `./data/captions.json`, que no pacote é a
// fixture. O contorno de quem achou (não reusar `@ilha/Main`) desliga junto tudo
// o que aquele arquivo tem de bom.
//
// COMO ISTO MEDE, e por que não é grep
// `renderToStaticMarkup` renderiza `GraphicLayers` de verdade. `Captions` e
// `Overlays` são substituídos por dublês que gravam um marcador — então o que se
// mede é ÁRVORE RENDERIZADA, não texto de arquivo. Um `grep` no `Main.tsx`
// passaria em qualquer refatoração que movesse a decisão para outro arquivo.
//
// Os dublês entram por `alias` do esbuild. Os componentes reais dependem de
// contexto de composição do Remotion (`useVideoConfig`), que não existe fora de
// um render — substituí-los é o que torna a medição possível E é o que a mantém
// rápida (esbuild + um render de string: ~1 s, sem browser, sem Chromium).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.dirname(AQUI);
const SRC = path.join(RAIZ, "src");
const controle = process.argv.includes("--controle");

let esbuild, React, renderToStaticMarkup;
try {
  esbuild = (await import("esbuild")).default ?? (await import("esbuild"));
  React = (await import("react")).default;
  ({ renderToStaticMarkup } = await import("react-dom/server"));
} catch (e) {
  console.error(
    "NÃO MEDIDO: falta esbuild/react-dom. Rode `npm ci` em " +
      "tools/remotion-compositor/.\n  (" + e.message + ")",
  );
  process.exit(2);
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "qc-fixture-legenda-"));
const dubles = path.join(tmp, "dubles");
fs.mkdirSync(dubles, { recursive: true });

// os dublês: cada um grava o próprio nome na árvore renderizada
const duble = (nome) =>
  `import React from "react";\n` +
  `export const ${nome} = () => React.createElement("div", ` +
  `{ "data-veio-de": "${nome}" });\nexport default ${nome};\n`;
fs.writeFileSync(path.join(dubles, "Captions.tsx"), duble("Captions"));
fs.writeFileSync(path.join(dubles, "Overlays.tsx"), duble("Overlays"));

// 🦷 O CONTROLE planta o defeito EXATO da v0.12: `<Captions />` incondicional.
// Sem isto, um `GraphicLayers` que nunca renderizasse legenda nenhuma passaria
// neste teste — e a legenda do caminho de demonstração é um requisito, não um
// acidente.
// ⚠️ O defeito é plantado EM MEMÓRIA, por `onLoad` do esbuild — nada é escrito
// na árvore viva, e o `Main.tsx` continua sendo resolvido a partir do lugar dele
// (senão `remotion`, `@remotion/media` e `./perfil` não resolvem).
const mainPath = path.join(SRC, "Main.tsx");
let plantado = null;
if (controle) {
  const fonte = fs.readFileSync(mainPath, "utf-8");
  plantado = fonte.replace(
    /\{captions \?\? \(extra \? null : <Captions \/>\)\}/,
    "<Captions />",
  );
  if (plantado === fonte) {
    console.error(
      "CONTROLE NÃO PLANTOU: não achei a expressão da legenda condicional em " +
        "Main.tsx. Se o conserto foi reescrito, ajuste este controle — um " +
        "controle que não planta não mede nada.",
    );
    process.exit(1);
  }
}

const entrada = path.join(tmp, "entrada.tsx");
fs.writeFileSync(
  entrada,
  `import React from "react";\n` +
    `import { GraphicLayers } from ${JSON.stringify(mainPath)};\n` +
    `export const semExtra = () => React.createElement(GraphicLayers, {});\n` +
    `export const comExtra = () => React.createElement(GraphicLayers, ` +
    `{ extra: React.createElement("div", { "data-veio-de": "peca-do-cliente" }) });\n` +
    `export const comCaptionsProprias = () => React.createElement(GraphicLayers, ` +
    `{ extra: React.createElement("div", { "data-veio-de": "peca-do-cliente" }), ` +
    `captions: React.createElement("div", { "data-veio-de": "legenda-do-cliente" }) });\n`,
);

// o bundle sai DENTRO do projeto para que `react`/`react-dom` (externals)
// resolvam pelo node_modules daqui; em /tmp o import falha com MODULE_NOT_FOUND.
const cache = path.join(RAIZ, "node_modules", ".cache", "qc-fixture-legenda");
fs.mkdirSync(cache, { recursive: true });
const bundle = path.join(cache, "bundle.mjs");
await esbuild.build({
  entryPoints: [entrada],
  outfile: bundle,
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  external: ["react", "react-dom", "react-dom/server"],
  // `alias` do esbuild não aceita caminho relativo ("Invalid alias name:
  // ./Captions") — a substituição tem que ser por plugin de resolução.
  plugins: [{
    name: "dubles",
    setup(build) {
      build.onResolve({ filter: /^\.\/(Captions|Overlays)$/ }, (a) => ({
        path: path.join(dubles, a.path.slice(2) + ".tsx"),
      }));
      if (plantado !== null) {
        const alvo = new RegExp(
          "^" + mainPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "$");
        build.onLoad({ filter: alvo }, () => ({
          contents: plantado, loader: "tsx",
        }));
      }
    },
  }],
  logLevel: "silent",
});

const mod = await import(bundle + "?t=" + process.hrtime.bigint());
const html = (fn) => renderToStaticMarkup(React.createElement(fn));

const casos = [
  { nome: "sem extra (demonstração e studio)", fn: mod.semExtra,
    exige: ["Overlays", "Captions"], proibe: [] },
  { nome: "com extra da peça (o caso do cliente)", fn: mod.comExtra,
    exige: ["peca-do-cliente"], proibe: ["Captions", "Overlays"] },
  { nome: "com extra + captions próprias", fn: mod.comCaptionsProprias,
    exige: ["peca-do-cliente", "legenda-do-cliente"],
    proibe: ["Captions", "Overlays"] },
];

let falhas = 0;
for (const c of casos) {
  const saida = html(c.fn);
  const veio = [...saida.matchAll(/data-veio-de="([^"]+)"/g)].map((m) => m[1]);
  const faltando = c.exige.filter((x) => !veio.includes(x));
  const intruso = c.proibe.filter((x) => veio.includes(x));
  const bom = faltando.length === 0 && intruso.length === 0;
  if (!bom) falhas++;
  process.stdout.write(
    `  ${bom ? "✅" : "❌"} ${c.nome.padEnd(38)} árvore: [${veio.join(", ")}]` +
      `${faltando.length ? "  faltou: " + faltando.join(",") : ""}` +
      `${intruso.length ? "  INTRUSO: " + intruso.join(",") : ""}\n`,
  );
}

fs.rmSync(tmp, { recursive: true, force: true });

if (controle) {
  if (falhas === 0) {
    console.error(
      "CONTROLE FALHOU: com `<Captions />` incondicional plantado, este QC " +
        "continuou verde — ele não mede o que diz medir.",
    );
    process.exit(1);
  }
  console.log(
    `controle: 3 casos · ${falhas} reprovado(s) com o defeito plantado · ✅ o QC tem dentes`,
  );
  process.exit(0);
}

console.log(
  `fixture de legenda: 3 caso(s) de composição medidos · ${3 - falhas} ok · ${falhas} com fixture vazando`,
);
if (falhas) {
  console.error(
    "❌ a fixture do pacote entra na peça de quem instalou (H47-4). " +
      "`GraphicLayers` só pode cair em `<Captions />` quando NINGUÉM passou " +
      "`extra` nem `captions`.",
  );
  process.exit(1);
}
process.exit(0);
