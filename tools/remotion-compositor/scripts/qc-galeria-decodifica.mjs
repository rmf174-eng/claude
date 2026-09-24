// qc-galeria-decodifica.mjs — os previews do catálogo DECODIFICAM num browser?
//
//   node scripts/qc-galeria-decodifica.mjs            todos os previews
//   node scripts/qc-galeria-decodifica.mjs --slug X   um só
//   node scripts/qc-galeria-decodifica.mjs --controle  planta defeito e exige acusação
//
//   exit 0  todos decodificaram (imprime quantos)
//        1  ao menos um NÃO decodificou (lista quais, com o código do erro)
//        2  não pôde medir (sem node_modules, sem browser) — NÃO é verde
//
// 🔴 POR QUE ESTE QC EXISTE, E POR QUE NENHUM DOS OUTROS O SUBSTITUI
// (2026-08-12, achado A-1 do teste de campo da v0.12, SPEC-47/H47-3.)
//
// A galeria de estilos do cliente ficou com os 37 cards PRETOS. Causa: o
// `renderMedia` do gerador não declarava espaço de cor e o libvpx carimbava
// `color_range=pc` + `color_space=bt470bg`; o Chrome 148 / Electron 42 recusava
// com `HTMLMediaElement.error.code = 3` (PIPELINE_ERROR_DECODE). Medido aqui em
// 2026-08-12, com um vídeo por iframe: **38 dos 38 previews da v0.12 falharam;
// os 39 re-renderizados com tv/bt709 passaram**.
//
// O `--check` do gerador confere sincronia registro↔JSON e, desde este conserto,
// as TAGS de cor de cada arquivo — mas nenhum dos dois DECODIFICA. Um `--check`
// que exigisse um frame decodificado teria pego isto no dia em que nasceu.
//
// ⚠️ A ARMADILHA DE MEDIÇÃO, que custou a primeira contagem errada no relatório
// de campo ("25 ok / 12 erro"): `readyState >= 1` é **HAVE_METADATA** — o
// contêiner foi lido, e nada foi decodificado. A régua é
// `requestVideoFrameCallback` (só dispara com frame pronto) confirmada por
// `readyState >= 2`. Forçando decodificação real, os 37 falharam.
//
// ⚠️ E VÁRIOS VÍDEOS NO MESMO DOCUMENTO FAZEM RUÍDO. Medido: com 3 <video> na
// mesma página, qual deles falhava mudava entre rodadas. Um por página, em
// série, dá resultado repetível. É por isso que este QC é lento de propósito.
//
// Ele usa o browser que o PRÓPRIO Remotion instala (`@remotion/renderer` →
// `openBrowser`): zero dependência nova, e é o mesmo motor que renderiza. Não é
// o Chrome do cliente — então ele prova "decodifica num Chromium moderno", não
// "decodifica em todo browser". Continua sendo infinitamente melhor que nada.
//
// 🔴 E ISSO NÃO É RETÓRICA — FOI MEDIDO (2026-08-12). O defeito de tags de cor
// reproduz no Chromium do Playwright (37 de 38 arquivos da v0.12 com erro 3) e
// **NÃO reproduz** no `chrome-headless-shell` que o Remotion instala: um preview
// re-encodado de propósito em `pc`/`bt470bg` decodificou normalmente lá. Ou
// seja: este QC, rodando com o browser do Remotion, NÃO teria pego o A-1. É por
// isso que a régua determinística de tags vive no `gerar-previews.py --check`
// (ffprobe, sem browser, sempre roda) e este script é a segunda camada — a que
// pega o que só aparece decodificando. Nenhuma das duas substitui a outra.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.dirname(AQUI);
const CATALOGO = path.join(RAIZ, "catalogo");
const PREVIEWS = path.join(CATALOGO, "previews");

const args = process.argv.slice(2);
const flag = (n) => args.includes(n);
const valor = (n) => (args.indexOf(n) >= 0 ? args[args.indexOf(n) + 1] : null);

const morre = (msg, code) => {
  console.error(msg);
  process.exit(code);
};

if (!fs.existsSync(PREVIEWS)) {
  morre(`NÃO MEDIDO: ${PREVIEWS} não existe. Rode \`npm run catalogo\` antes.`, 2);
}

let openBrowser;
try {
  ({ openBrowser } = await import("@remotion/renderer"));
} catch (e) {
  morre(
    "NÃO MEDIDO: @remotion/renderer não está instalado. Rode `npm ci` em " +
      "tools/remotion-compositor/ e tente de novo.\n  (" + e.message + ")",
    2,
  );
}

const soSlug = valor("--slug");
let arquivos = fs
  .readdirSync(PREVIEWS)
  .filter((f) => f.endsWith(".webm"))
  .filter((f) => !soSlug || f === `${soSlug}.webm`)
  .sort();

if (arquivos.length === 0) {
  morre(
    `NÃO MEDIDO: nenhum preview .webm em ${PREVIEWS}` +
      (soSlug ? ` para o slug ${soSlug}` : ""),
    2,
  );
}

// ── o defeito plantado (RD-7): um preview com o cabeçalho do contêiner
// destruído. Um QC de decodificação que não reprova ISSO não reprova nada.
//
// ⚠️ DOIS DEFEITOS FORAM TESTADOS ANTES E NÃO SERVEM COMO CONTROLE — e as duas
// medições ficam escritas porque cada uma diz algo sobre a régua:
//   1. **truncar o arquivo em 40%**: AINDA decodifica. O primeiro cluster está
//      íntegro e o WebM é streamável, então o frame aparece. Passa.
//   2. **re-encodar em `pc`/`bt470bg`** (o defeito REAL do A-1): decodificou
//      normalmente no `chrome-headless-shell` do Remotion, embora os arquivos
//      originais com essas tags falhem 37/38 no Chromium do Playwright. O
//      defeito é sensível à build do browser — e é por isso que a régua de tags
//      é do `--check`, não deste script.
const CONTROLE = "__controle-plantado.webm";
let plantado = null;
if (flag("--controle")) {
  const fonte = path.join(PREVIEWS, arquivos[0]);
  const bytes = Buffer.from(fs.readFileSync(fonte));
  // o cabeçalho EBML/Matroska vive nos primeiros bytes; sem ele o demuxer nem
  // reconhece o formato (erro 4, MEDIA_ELEMENT_ERROR: Format error)
  bytes.fill(0x00, 0, Math.min(400, bytes.length));
  plantado = path.join(PREVIEWS, CONTROLE);
  fs.writeFileSync(plantado, bytes);
  arquivos = [arquivos[0], CONTROLE];
}

const limpar = () => {
  if (plantado && fs.existsSync(plantado)) fs.unlinkSync(plantado);
};

const PAGINA = `<!doctype html><meta charset="utf-8"><title>sonda</title>
<script>
window.__medir = (src) => new Promise((res) => {
  const v = document.createElement("video");
  v.muted = true; v.playsInline = true; v.src = src;
  document.body.appendChild(v);
  let pronto = false;
  const fim = (x) => { if (!pronto) { pronto = true; res({...x, readyState: v.readyState,
                        erro: v.error ? v.error.code : null,
                        msg: v.error ? String(v.error.message).slice(0, 90) : null}); } };
  v.addEventListener("error", () => fim({decodificou: false}));
  if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(() => fim({decodificou: true}));
  else v.addEventListener("loadeddata", () => { if (v.readyState >= 2) fim({decodificou: true}); });
  v.play().catch(() => {});
  setTimeout(() => fim({decodificou: false, timeout: true}), 10000);
});
</script>`;

const servidor = http.createServer((req, res) => {
  const rel = decodeURIComponent(req.url.split("?")[0]);
  if (rel === "/" || rel === "/index.html") {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    return res.end(PAGINA);
  }
  const alvo = path.join(PREVIEWS, path.basename(rel));
  if (!fs.existsSync(alvo)) {
    res.writeHead(404);
    return res.end("nao existe");
  }
  res.writeHead(200, { "content-type": "video/webm" });
  fs.createReadStream(alvo).pipe(res);
});

await new Promise((r) => servidor.listen(0, "127.0.0.1", r));
const porta = servidor.address().port;

let browser;
try {
  browser = await openBrowser({ browser: "chrome", logLevel: "error" });
} catch (e) {
  servidor.close();
  limpar();
  morre(
    "NÃO MEDIDO: não subiu o browser. Rode `npx remotion browser ensure` " +
      "(baixa ~193 MB) e tente de novo.\n  (" + e.message + ")",
    2,
  );
}

const maus = [];
let ok = 0;
try {
  for (const f of arquivos) {
    // 🔴 UMA PÁGINA NOVA POR ARQUIVO. Reusar a página acumula <video> no mesmo
    // documento, e foi isso que fez a medição pular de arquivo entre rodadas.
    const page = await browser.newPage({ logLevel: "error", indent: false });
    let r;
    try {
      await page.goto({ url: `http://127.0.0.1:${porta}/`, timeout: 20000 });
      r = await page.evaluate(`window.__medir(${JSON.stringify("/" + f)})`);
    } finally {
      await page.close().catch(() => {});
    }
    const bom = r && r.decodificou && r.readyState >= 2;
    if (bom) ok++;
    else
      maus.push(
        `${f} — erro ${r && r.erro !== null ? r.erro : "—"} · readyState ` +
          `${r ? r.readyState : "?"}${r && r.timeout ? " · timeout" : ""}` +
          `${r && r.msg ? " · " + r.msg : ""}`,
      );
    process.stderr.write(`  ${bom ? "✅" : "❌"} ${f}\n`);
  }
} finally {
  await browser.close().catch(() => {});
  servidor.close();
}

if (flag("--controle")) {
  const acusou = maus.some((m) => m.startsWith(CONTROLE));
  const bomPassou = ok >= 1;
  limpar();
  console.log(
    `controle: varreu ${arquivos.length} · o preview íntegro ${bomPassou ? "passou" : "REPROVOU"} · ` +
      `o defeito plantado ${acusou ? "foi ACUSADO" : "NÃO foi acusado"}`,
  );
  if (!acusou || !bomPassou) {
    console.error(
      "CONTROLE FALHOU: este QC não distingue preview bom de preview quebrado — " +
        "o defeito está no QC, não na galeria.",
    );
    process.exit(1);
  }
  console.log("✅ o QC tem dentes");
  process.exit(0);
}

console.log(
  `galeria: varreu ${arquivos.length} preview(s) · ${ok} decodificaram um FRAME ` +
    `(requestVideoFrameCallback + readyState>=2) · ${maus.length} não`,
);
if (maus.length) {
  console.error("❌ previews que NÃO decodificam no browser:");
  for (const m of maus) console.error("   " + m);
  console.error(
    "  Conserto conhecido (H47-3): o render tem que declarar `colorSpace: \"bt709\"` " +
      "em gerar-previews.py. Sem isso o libvpx carimba pc/bt470bg e o Chrome " +
      "recusa com PIPELINE_ERROR_DECODE.",
  );
  process.exit(1);
}
process.exit(0);
