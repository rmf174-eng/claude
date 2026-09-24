import fs from "node:fs";
import path from "node:path";
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setEntryPoint("src/index.ts");
// fonte HDR (BT.2020/HLG) é tone-mapped pelo Chrome; sem isso o output sai
// com tags bt470bg/range PC e os players lavam ainda mais a imagem
Config.setColorSpace("bt709");

// ── `@ilha/*` → o kit deste projeto ────────────────────────────────────────
//
// 🔴 POR QUE ESTE ALIAS EXISTE (2026-08-10, achado A6 da auditoria)
// A peça de cada produção morava DENTRO de `src/`, junto do kit. Consequências
// medidas: o export do produto saía vermelho em 3 dos 6 portões por causa de
// UMA produção; o `.tsx` do cliente moraria dentro do pacote, e um update que
// substituísse o pacote apagaria o trabalho dele.
//
// Agora a peça mora na produção — `<dir-producao>/remotion/` — e alcança o kit
// por este alias. Sem ele, o import seria `../../../../../tools/remotion-
// compositor/src/CaptionLayer`: uma afirmação sobre quantos níveis abaixo da
// raiz aquela produção está, que é exatamente a classe A que o auditor
// persegue, e que quebra assim que a produção do cliente mora noutro lugar.
//
// O alias vale para o caminho da CLI (`remotion render`, `remotion studio`),
// que é por onde toda produção renderiza. Os entry points do próprio produto
// (`index-catalogo`, `index-galeria`, `index-partitura`) vivem em `src/` e usam
// import relativo — eles não dependem disto, e por isso `bundle()` chamado
// direto pelos geradores de preview continua funcionando sem override.
// `resolve.modules` entra junto e NÃO é detalhe: webpack procura `node_modules`
// subindo a partir do arquivo que importa. Um `.tsx` que mora na produção sobe
// até `/` sem achar nada, e o erro que sai é `Can't resolve
// '@remotion/google-fonts/Montserrat'` — medido aqui em 2026-08-10, na primeira
// tentativa de resolver a produção movida. Fixar o `node_modules` do projeto faz
// a produção usar as MESMAS versões que o lock fixou, que é o ponto do lock ir
// no pacote.
//
// 🔴 `process.cwd()`, NUNCA `__dirname` — medido em 2026-08-10. Este arquivo é
// avaliado dentro do bundle da CLI, e ali `__dirname` vale
// `node_modules/@remotion/cli/dist`: o alias apontava para um `src/` que não
// existe e o erro que saía era "Can't resolve '@remotion/google-fonts/…'", que
// não fala do alias em lugar nenhum. O `cwd` é o projeto porque TODO render
// desta ilha roda com `cwd` aqui — a regra já está escrita no SKILL.md do
// compositor ("Render/still SEMPRE com cwd em tools/remotion-compositor/"), e a
// checagem abaixo transforma o descumprimento em erro nomeado.
const RAIZ = process.cwd();
const KIT = path.resolve(RAIZ, "src");
if (!fs.existsSync(path.join(KIT, "perfil.ts"))) {
  throw new Error(
    `remotion.config.ts: cwd é ${RAIZ}, que não tem src/perfil.ts. ` +
      `Rode o comando com cwd em tools/remotion-compositor/ — o alias @ilha e a ` +
      `resolução de node_modules dependem disso.`
  );
}

Config.overrideWebpackConfig((c) => ({
  ...c,
  resolve: {
    ...c.resolve,
    alias: { ...(c.resolve?.alias ?? {}), "@ilha": KIT },
    modules: [path.resolve(RAIZ, "node_modules"), "node_modules"],
  },
}));
