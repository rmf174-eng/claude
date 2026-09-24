// Mede a árvore React real: plano visual decide janela, SFX, at_s e ganho.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.dirname(AQUI);
const SRC = path.join(RAIZ, "src");

let esbuild, React, renderToStaticMarkup;
try {
  esbuild = (await import("esbuild")).default ?? (await import("esbuild"));
  React = (await import("react")).default;
  ({renderToStaticMarkup} = await import("react-dom/server"));
} catch (e) {
  console.error("NÃO MEDIDO: rode `npm ci` em tools/remotion-compositor (" + e.message + ")");
  process.exit(2);
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "teste-plano-visual-"));
const dubles = path.join(tmp, "dubles");
fs.mkdirSync(dubles, {recursive: true});

fs.writeFileSync(path.join(dubles, "remotion.tsx"), `
import React from "react";
export const AbsoluteFill = ({children}) => <div data-remotion="absolute">{children}</div>;
export const Sequence = ({from, durationInFrames, children}) =>
  <div data-sequence-from={from} data-sequence-duration={durationInFrames ?? "aberta"}>{children}</div>;
export const staticFile = (p) => "PUBLIC:" + p;
export const useVideoConfig = () => ({fps: 30, width: 1080, height: 1920});
`);
fs.writeFileSync(path.join(dubles, "media.tsx"), `
import React from "react";
export const Audio = ({src, volume}) =>
  <i data-audio-src={src} data-audio-volume={String(volume)} />;
`);
fs.writeFileSync(path.join(dubles, "MotionKit.tsx"), `
import React from "react";
export const OverlayGroup = ({fromS, toS, children}) =>
  <div data-legado-from={fromS} data-legado-to={toS}>{children}</div>;
const V = ({text, label, children}) => <b data-visual="componente">{text ?? label ?? children}</b>;
export const HandText = V;
export const AccentWord = V;
export const StepTitleFlat = V;
export const MarkerHighlight = V;
export const underlinePath = () => "M0 0";
export const loopCirclePath = () => "M0 0";
export const strikePath = () => "M0 0";
export const squigglePath = () => "M0 0";
`);
fs.writeFileSync(path.join(dubles, "HookLettering.tsx"), `
import React from "react";
export const DrawStroke = () => <b data-visual="draw-stroke" />;
`);
fs.writeFileSync(path.join(dubles, "themes.ts"), `
export const neutralTheme = {ink: "#000", accent: "#f00", postits: {autoridade: "#ff0"}};
`);

const partituraPath = path.join(SRC, "Partitura.tsx");
const entrada = path.join(tmp, "entrada.tsx");
fs.writeFileSync(entrada, `
import React from "react";
import {Partitura} from ${JSON.stringify(partituraPath)};

const item = {
  id: "item-1", papel: "gancho", componente: "AccentWord", canal: "tipografia",
  texto: "VISUAL-DO-PLANO", inS: 9, outS: 9.8, zona: "topo", cor: "accent",
  score: 1, sfx: "PALPITE-DO-DIRETOR", plano_visual_evento_id: "evento-1"
};
const evento = {
  id: "evento-1", inicio_s: 1, fim_s: 2, beat: "gancho",
  visual: {tipo: "tipografia", descricao: "entra no verbo"}, zona: "topo",
  som: {decisao: "usar", asset: "ignorado.wav", asset_publico: "sfx/plano.wav", at_s: 1.3, ganho_db: -6},
  implementacao: {artefato: "partitura.json", ref: {tipo: "json-pointer", valor: "/itens/0"}}
};
const dados = (direcao, som = evento.som) => ({
  contrato: "benchmark.partitura/v1",
  _procedencia: {perfil: {video: {largura: 1080, altura: 1920, fps: 30}}, orcamento: {duracao_s: 3}},
  itens: [item],
  plano_visual: {contrato: "benchmark.plano-visual/v1", direcao_edicao: direcao,
    eventos: [{...evento, som}]}
});
const C = ({dados}) => <Partitura dados={dados} largura={1080} altura={1920} />;
export const automatico = () => <C dados={dados({modo: "animada", densidade: "equilibrada", sfx: "automatico"})} />;
export const semSfx = () => <C dados={dados({modo: "animada", densidade: "equilibrada", sfx: "sem-sfx"})} />;
export const silencio = () => <C dados={dados({modo: "animada", densidade: "equilibrada", sfx: "automatico"},
  {decisao: "silencio-intencional", motivo: "fala com ataque"})} />;
export const essencial = () => <C dados={dados({modo: "essencial", densidade: "leve", sfx: "automatico"})} />;
`);

const cache = path.join(RAIZ, "node_modules", ".cache", "teste-plano-visual");
fs.mkdirSync(cache, {recursive: true});
const bundle = path.join(cache, "bundle.mjs");
await esbuild.build({
  entryPoints: [entrada], outfile: bundle, bundle: true, format: "esm", platform: "node",
  jsx: "automatic", external: ["react", "react-dom", "react-dom/server"],
  plugins: [{
    name: "dubles-plano-visual",
    setup(build) {
      build.onResolve({filter: /^remotion$/}, () => ({path: path.join(dubles, "remotion.tsx")}));
      build.onResolve({filter: /^@remotion\/media$/}, () => ({path: path.join(dubles, "media.tsx")}));
      build.onResolve({filter: /^\.\/MotionKit$/}, () => ({path: path.join(dubles, "MotionKit.tsx")}));
      build.onResolve({filter: /^\.\/HookLettering$/}, () => ({path: path.join(dubles, "HookLettering.tsx")}));
      build.onResolve({filter: /^\.\/themes$/}, () => ({path: path.join(dubles, "themes.ts")}));
    },
  }],
  logLevel: "silent",
});

const mod = await import(bundle + "?t=" + process.hrtime.bigint());
const html = (componente) => renderToStaticMarkup(React.createElement(componente));
const auto = html(mod.automatico);
const sem = html(mod.semSfx);
const silencio = html(mod.silencio);
const essencial = html(mod.essencial);

const falhas = [];
const exige = (condicao, mensagem) => { if (!condicao) falhas.push(mensagem); };
exige(auto.includes('data-sequence-from="30"') && auto.includes('data-sequence-duration="30"'),
  "janela visual não veio de inicio_s/fim_s");
exige(auto.includes('data-sequence-from="39"'), "SFX não veio de at_s=1.3");
exige(auto.includes('data-audio-src="PUBLIC:sfx/plano.wav"'), "asset compilado não chegou ao Audio");
const volume = Number(auto.match(/data-audio-volume="([^"]+)"/)?.[1]);
exige(Math.abs(volume - Math.pow(10, -6 / 20)) < 1e-12, "ganho_db=-6 não virou amplitude linear");
exige(auto.includes("VISUAL-DO-PLANO"), "evento não chegou ao componente visual");
exige(!auto.includes("PALPITE-DO-DIRETOR") && !auto.includes('data-sequence-from="270"'),
  "render consumiu SFX/timing legado inventado pelo diretor");
exige(!sem.includes("data-audio-src"), "política sem-sfx ainda renderizou Audio");
exige(!silencio.includes("data-audio-src"), "silêncio intencional ainda renderizou Audio");
exige(!essencial.includes("data-audio-src") && !essencial.includes("VISUAL-DO-PLANO"),
  "modo essencial inválido não foi contido no render");

fs.rmSync(tmp, {recursive: true, force: true});
if (falhas.length) {
  for (const falha of falhas) console.error("FALHOU - " + falha);
  process.exit(1);
}
console.log("plano visual renderizado: 4/4 casos aprovados");
console.log("ok - timing visual 1.0s, SFX 1.3s, asset do plano e ganho -6 dB");
console.log("ok - sem-sfx, silêncio intencional e essencial não renderizam Audio");
console.log("ok - item.sfx/inS legado do diretor não tem autoridade no caminho compilado");
