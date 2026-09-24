/* Galeria de estilos — a tela (SPEC-19 §3.6, §3.7, §3.13).
 *
 * Módulo ES autônomo:  export function montarGaleria(host, opcoes) -> {destruir}
 *
 * ────────────────────────────────────────────────────────────────────────────
 * 🎯 O QUE ESTE ARQUIVO NÃO TEM, E É O PONTO DA SPEC
 *
 * Nenhum número de estilo. Zero. O preview de cada card é um `.webm` renderizado
 * pelo NOSSO motor (Remotion), não uma reimplementação em DOM. O ref-A escreveu
 * o contrário e confessou no próprio código (`assets/preview/app.js:182-188`):
 *
 *     "Every number here is lifted from the render (Main.tsx Karaoke/Word and
 *      StackedCaptions.tsx STACK_MIXED) and scaled by boxWidth/1080 (…) If the
 *      template's caption look changes, change it HERE too — a preview that lies
 *      about the style is worse than no preview."
 *
 * — e ainda um solver de cubic-bézier em JS (`:192-197`) para imitar o easing do
 * Remotion. Duas implementações do mesmo look, sincronizadas por disciplina
 * humana. Aqui não há o que sincronizar.
 *
 * Corolário operacional, que é critério de aceite: um `grep` por valor de estilo
 * (tamanho de fonte, cor hexadecimal, curva de easing) neste arquivo tem que dar
 * ZERO. Toda cor de interface vive no `.css`; todo valor de estilo vive no
 * catálogo e chega em `galeria.json` como DADO.
 * ────────────────────────────────────────────────────────────────────────────
 */

const CONTRATO_GALERIA = "benchmark.galeria-estilos/v1";
const CONTRATO_ESTILO = "benchmark.edit-estilo/v3";
/* A versão do GERADOR que esta tela espera (`previews-peca.py: GERADOR_VERSAO`).
 * Não é o contrato: o formato não mudou, a PROSA mudou. `galeria.json` sem o
 * campo é anterior à marcação e conta como 1. Sobe junto com o gerador. */
const GERADOR_VERSAO_ESPERADA = 4;
const MODOS_DIRECAO = new Set(["essencial", "animada", "surpresa"]);
const DENSIDADES = new Set(["leve", "equilibrada", "alta"]);

/* 🔴 Teto de vídeos tocando ao mesmo tempo (§3.6). Vinte loops VP9 simultâneos
 * travam a aba; isto é critério de aceite, não recomendação. O selecionado + o
 * que está sob o cursor/foco, e mais nenhum. */
const MAX_VIDEOS = 2;
// Piso de contraste do acento (H49-12). 3,0:1 é o mínimo do WCAG para texto
// grande/gráfico — e é o número que o relatório de campo usou para medir que
// #9a3737 dava 2,89:1 e o branco 2,44:1 sobre o fundo real de uma peça.
const PISO_CONTRASTE = 3.0;
// rótulo curto de cada grupo, para a lista de folhas da proposta
const TITULO_CURTO = {
  gramatica: "plano", tema: "tema", gancho: "gancho",
  legenda: "legenda", grafismo: "grafismo",
};
const MS_REBUSCA = 3000;

const ICONES = {
  // SVG inline, nunca emoji: abaixo de ~40 px emoji vira mancha (medido neste
  // repo em 3 lugares). Mesma decisão deles (`app.js:50-58`).
  peca: '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path fill="currentColor" d="M2 3h12v2H2zm0 4h8v2H2zm0 4h11v2H2z"/></svg>',
  amostra: '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
};

const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};

/** #RGB / #RRGGBB → #rrggbb, ou null. Sem tabela de cores prontas: um swatch e
 *  um campo hex, como eles (`app.js:1058-1060`). */
function normHex(v) {
  const s = String(v || "").trim();
  let m = /^#?([0-9a-fA-F]{6})$/.exec(s);
  if (m) return "#" + m[1].toLowerCase();
  m = /^#?([0-9a-fA-F]{3})$/.exec(s);
  if (m) return "#" + m[1].split("").map((c) => c + c).join("").toLowerCase();
  return null;
}

export function montarGaleria(host, opcoes = {}) {
  const base = (opcoes.base || "").replace(/\/$/, "");
  const qs = new URLSearchParams(location.search);
  /* Onde mora o galeria.json.
   *
   * ⚠️ A §3.4 previa `../../media/.preview/estilos/galeria.json`. MEDIDO em
   * 2026-08-08 contra o servidor da SPEC-17 já entregue: a rota `/media/` recusa
   * TUDO que está sob `.preview/` (`preview/servidor.py:872-874`,
   * `{"erro":"fora da raiz"}`, 403), enquanto o mesmo arquivo fora do `.preview/`
   * responde 200. Por isso o default aqui é o vizinho `./galeria.json` — que é o
   * que os modos `--pacote` e `--fixture` do gerador montam — e o caminho da
   * §3.4 continua disponível por `?galeria=`. Um default que sempre 403 seria
   * um produto quebrado com um comentário bonito. */
  const urlGaleria = qs.get("galeria") || opcoes.galeria || "./galeria.json";
  /* 🔴 O `webm`/`poster` de cada item é relativo ao PRÓPRIO galeria.json, não à
   * página. Enquanto os dois foram vizinhos (`--fixture`, `--pacote`) a
   * diferença não aparecia; servido de `estilos/galeria.json` o browser resolvia
   * `previews/x.png` contra `/<token>/` e devolvia 404 em TODOS os cards — a
   * galeria montava, os cards apareciam, e não havia imagem nenhuma. Medido no
   * browser em 2026-08-09; nenhum teste de DOM pegaria, porque o DOM estava
   * certo. Resolver contra a URL do JSON vale para os dois casos. */
  const baseMidia = new URL(urlGaleria, location.href);
  const midia = (rel) => (rel ? new URL(rel, baseMidia).href : rel);
  const urlEstado = opcoes.estado || (base ? base + "/api/estado" : null);
  const urlSalvar = opcoes.salvar || (base ? base + "/api/salvar" : null);
  const modoFixture = qs.get("fixture") === "1" || !!opcoes.fixture;

  const raiz = el("div", "galeria");
  raiz.setAttribute("aria-busy", "true");
  host.innerHTML = "";
  host.appendChild(raiz);

  const S = {
    dados: null,
    estado: null,
    vigente: null,
    escolha: {},          // grupo -> slug (seleção única)
    grafismos: new Set(),
    elementos: {},        // mapa COMPLETO (§3.9-1)
    acento: null,
    parametros: {},       // diff: só o que o usuário mexeu
    observacao: "",
    tocando: [],
    timer: null,
    vivo: true,
    propostaEscolhida: null,
    aprendizadoResposta: null,
    indice: null,
    medidores: [],
    verTodosGrafismos: false,
    direcaoEdicao: null,
    sfxTocado: false,
    ajustesAbertos: false,
    detalhesAbertos: new Set(),
    focoDepoisDoDesenho: null,
    sujo: false,
    enviando: false,
  };

  const protegerSaidaPendente = (e) => {
    if (!S.enviando && !S.sujo) return;
    e.preventDefault();
    e.returnValue = S.enviando
      ? "O look ainda está sendo enviado. Aguarde terminar antes de sair."
      : "Há escolhas de look que ainda não foram enviadas.";
    return e.returnValue;
  };
  window.addEventListener("beforeunload", protegerSaidaPendente);

  /* ───────────────────────────── carga ───────────────────────────── */
  async function carregar() {
    const r = await fetch(urlGaleria, { cache: "no-store" });
    if (!r.ok) {
      throw new Error(
        `GET ${urlGaleria} → HTTP ${r.status}. ` +
        (r.status === 403
          ? "A rota /media/ do servidor recusa tudo sob .preview/ " +
            "(servidor.py:872-874). Sirva a galeria pelo pacote " +
            "(`previews-peca.py <dir> --pacote <dst>` + `servir --app <dst>`) " +
            "ou aponte ?galeria= para um caminho servível."
          : "")
      );
    }
    const g = await r.json();
    if (g.contrato !== CONTRATO_GALERIA) {
      throw new Error(`contrato ${g.contrato} != ${CONTRATO_GALERIA}`);
    }
    return g;
  }

  async function carregarEstado() {
    if (!urlEstado) return null;
    try {
      const r = await fetch(urlEstado, { cache: "no-store" });
      return r.ok ? await r.json() : null;
    } catch (_) {
      return null;
    }
  }

  /* Semântica do portão, idêntica à deles (`app.js:1236`,
   * `rerender = !S.state.awaitingStyle`) — e SEM inventar campo novo no
   * `benchmark.edit-estado/v1` da SPEC-16. O papel que lá é a "escrita de volta"
   * do estilo aqui é o arquivo `estilo-vigente.json` (§3.10). */
  const portaoAberto = () => (S.estado ? S.estado.portao === "estilo" : true);
  const jaTemEstilo = () => !!S.dados?.vigente;
  const rerender = () => !portaoAberto() && jaTemEstilo();

  function direcaoValida(d) {
    return !!d && MODOS_DIRECAO.has(d.modo)
      && DENSIDADES.has(d.densidade)
      && ["automatico", "sem-sfx"].includes(d.sfx);
  }

  function aplicarRestricoesEssencial() {
    if (S.direcaoEdicao?.modo !== "essencial") return;
    S.direcaoEdicao = { modo: "essencial", densidade: "leve", sfx: "sem-sfx" };
    S.grafismos.clear();
    delete S.escolha.gancho;
    const fixo = S.dados?.grupos?.find((g) => g.id === "gramatica")?.estilos
      ?.find((e) => e.slug === "plano-fixo" && e.estado !== "candidato");
    if (fixo) S.escolha.gramatica = fixo.slug;
    else delete S.escolha.gramatica;
    for (const id of ["sfx", "split_broll", "flash_no_corte", "tracking"]) {
      if (id in S.elementos) S.elementos[id] = false;
    }
  }

  /* ─────────────────────── seleção inicial ─────────────────────── */
  function semear() {
    const g = S.dados;
    /* 🔴 `vigente` PRIMEIRO, `semente` só na ausência dele (SPEC-41).
     *
     * `semente` é o estilo do usuário sugerindo (extraído de N referências, ou
     * salvo por ele) — pré-seleção, não escolha. `vigente` é o que já foi
     * escolhido PARA ESTA PEÇA. Quem já escolheu manda, sempre: senão a peça em
     * que o creator trocou o gancho na mão voltaria ao gancho da biblioteca no
     * reload seguinte, sem ninguém ter pedido.
     *
     * `rerender()` continua olhando SÓ para `vigente` — semear não é refazer. */
    const vig = g.vigente?.estilo || g.semente?.estilo || null;
    for (const grupo of g.grupos) {
      if (grupo.seletor === "multi") {
        for (const e of grupo.estilos) {
          if (vig?.grafismos?.includes(e.slug)) S.grafismos.add(e.slug);
        }
        continue;
      }
      const doVigente = vig?.[grupo.id];
      const escolhivel = grupo.estilos.filter((e) => e.estado !== "candidato");
      const achado =
        escolhivel.find((e) => e.slug === doVigente) ||
        escolhivel.find((e) => e.padrao) ||
        null;
      // 🔴 Sem `defaultDe`, NADA fica marcado. O ref-A marca `edits[0]` — o
      // primeiro do array (`app.js:592`) — e aí reordenar o catálogo muda a
      // escolha default do usuário sem ninguém perceber.
      if (achado) S.escolha[grupo.id] = achado.slug;
    }
    for (const i of g.interruptores || []) {
      S.elementos[i.id] = vig?.elementos?.[i.id] ?? !!i.padrao;
    }
    if (typeof g.vigente?.estilo?.elementos?.sfx === "boolean") {
      // Restyle legado v1/v2: o interruptor já foi salvo e não vira default.
      S.sfxTocado = true;
    }
    // A semente pode sugerir folhas visuais, mas nunca responde esta pergunta.
    // Produção nova só nasce escolhida quando há uma decisão vigente da peça.
    const direcaoPersistida = g.vigente?.estilo?.direcao_edicao;
    if (direcaoValida(direcaoPersistida)) {
      S.direcaoEdicao = { ...direcaoPersistida };
      // Num estilo já aplicado, o estado do SFX é uma decisão persistida.
      S.sfxTocado = true;
      aplicarRestricoesEssencial();
    }
    S.acento = normHex(vig?.acento || g.acento_default) || null;
    S.observacao = vig?.observacao || "";
    S.parametros = JSON.parse(JSON.stringify(vig?.parametros || {}));
  }

  /* Trocar de etapa desmonta a galeria para parar vídeo e polling, mas não pode
   * apagar uma direção ainda não enviada. O rascunho vive só na memória da aba
   * do browser e é revalidado contra o catálogo atual ao remontar. */
  function restaurarRascunho(r) {
    if (!r?.sujo) return;
    const grupos = new Map(S.dados.grupos.map((g) => [g.id, g]));
    for (const [gid, slug] of Object.entries(r.escolha || {})) {
      const g = grupos.get(gid);
      if (g?.seletor !== "multi" && g?.estilos.some(
        (e) => e.slug === slug && e.estado !== "candidato")) S.escolha[gid] = slug;
    }
    const gm = grupos.get("grafismo");
    const grafismosValidos = new Set((gm?.estilos || [])
      .filter((e) => e.estado !== "candidato").map((e) => e.slug));
    S.grafismos = new Set((r.grafismos || []).filter((slug) => grafismosValidos.has(slug)));
    for (const id of Object.keys(S.elementos)) {
      if (Object.prototype.hasOwnProperty.call(r.elementos || {}, id)) {
        S.elementos[id] = !!r.elementos[id];
      }
    }
    const modosOferecidos = new Set((S.dados.direcoes_edicao || []).map((d) => d.modo));
    if (direcaoValida(r.direcaoEdicao) && modosOferecidos.has(r.direcaoEdicao.modo)) {
      S.direcaoEdicao = { ...r.direcaoEdicao };
      S.sfxTocado = !!r.sfxTocado;
      aplicarRestricoesEssencial();
    }
    S.acento = normHex(r.acento) || S.acento;
    S.parametros = r.parametros && typeof r.parametros === "object"
      ? JSON.parse(JSON.stringify(r.parametros)) : S.parametros;
    S.observacao = typeof r.observacao === "string" ? r.observacao : S.observacao;
    S.propostaEscolhida = r.propostaEscolhida || null;
    S.aprendizadoResposta = ["sim", "nao"].includes(r.aprendizadoResposta)
      ? r.aprendizadoResposta : null;
    S.verTodosGrafismos = !!r.verTodosGrafismos;
    S.ajustesAbertos = !!r.ajustesAbertos;
    S.detalhesAbertos = new Set(r.detalhesAbertos || []);
    S.sujo = true;
  }

  function rascunhoAtual() {
    if (!S.dados) return null;
    return {
      versao: 2,
      sujo: S.sujo,
      escolha: { ...S.escolha },
      grafismos: [...S.grafismos],
      elementos: { ...S.elementos },
      acento: S.acento,
      parametros: JSON.parse(JSON.stringify(S.parametros)),
      observacao: S.observacao,
      propostaEscolhida: S.propostaEscolhida,
      aprendizadoResposta: S.aprendizadoResposta,
      verTodosGrafismos: S.verTodosGrafismos,
      direcaoEdicao: S.direcaoEdicao ? { ...S.direcaoEdicao } : null,
      sfxTocado: S.sfxTocado,
      ajustesAbertos: S.ajustesAbertos,
      detalhesAbertos: [...S.detalhesAbertos],
    };
  }

  const marcarSujo = () => { S.sujo = true; };

  /* ───────────────────────── acento derivado ───────────────────────── */
  function indice() {
    const ix = {};
    for (const g of S.dados.grupos) for (const e of g.estilos) ix[e.slug] = { ...e, _grupo: g.id };
    return ix;
  }

  /** `acento_usado = escolhidos.some(e => e.acento)`. Zero lista paralela: o
   *  fato mora no catálogo (§3.8). Eles mantêm `ACCENT_USERS` espelhada à mão
   *  (`app.js:1051`, "Mirrors the template — update both together"). */
  function acentoDerivado() {
    const ix = indice();
    const ordem = ["gramatica", "tema", "gancho", "legenda", "grafismo"];
    const onde = [];
    const escolhidos = [...Object.values(S.escolha), ...S.grafismos];
    for (const slug of escolhidos) {
      const e = ix[slug];
      if (e?.acento && !onde.includes(e._grupo)) onde.push(e._grupo);
    }
    onde.sort((a, b) => ordem.indexOf(a) - ordem.indexOf(b));
    return { usado: onde.length > 0, onde };
  }

  /* ───────────────────────── mídia dos cards ───────────────────────── */
  const semMovimento = () =>
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function rotularControleReducao(v, ativo) {
    const controle = v?._controleReducao;
    if (!controle) return;
    controle.setAttribute("aria-pressed", String(ativo));
    controle.innerHTML = ICONES.amostra + (ativo ? " pausar animação" : " ver animação");
  }

  function pararExcedentes() {
    while (S.tocando.length > MAX_VIDEOS) {
      const v = S.tocando.shift();
      try { v.pause(); v.removeAttribute("src"); v.load(); } catch (_) { /* nada */ }
      v.hidden = true;
      if (v._poster) v._poster.hidden = false;
      rotularControleReducao(v, false);
    }
  }

  function tocar(caixa) {
    if (semMovimento()) return;              // reduced-motion: NUNCA toca (§3.6)
    const v = caixa.querySelector("video");
    if (!v || !v.dataset.src) return;
    if (!v.getAttribute("src")) v.setAttribute("src", v.dataset.src);
    v.hidden = false;
    if (v._poster) v._poster.hidden = true;
    const i = S.tocando.indexOf(v);
    if (i >= 0) S.tocando.splice(i, 1);
    S.tocando.push(v);
    pararExcedentes();
    const p = v.play();
    if (p && p.catch) p.catch(() => { /* autoplay negado: fica no poster */ });
  }

  function parar(caixa, forcar) {
    const v = caixa.querySelector("video");
    if (!v) return;
    const card = caixa.closest(".galeria-card");
    if (!forcar && card && card.getAttribute("aria-pressed") === "true") return;
    const i = S.tocando.indexOf(v);
    if (i >= 0) S.tocando.splice(i, 1);
    try { v.pause(); } catch (_) { /* nada */ }
    v.hidden = true;
    if (v._poster) v._poster.hidden = false;
    rotularControleReducao(v, false);
  }

  function caixaDe(e) {
    const cx = el("div", "galeria-caixa");
    const p = e.preview;
    if (!p) {
      // A chapa DIZ o que é a ausência. Sem a legenda, uma caixa texturizada e
      // vazia é indistinguível de um card que falhou ao carregar a imagem.
      const h = el("div", "galeria-hachura");
      h.textContent = "prévia ainda não renderizada";
      cx.appendChild(h);
      return cx;
    }
    // 🔴 A razão vem do JSON, nunca do CSS: é o que faz um perfil 16:9
    // renderizar cards deitados sem uma linha diferente.
    if (p.w && p.h) cx.style.setProperty("--g-razao", `${p.w} / ${p.h}`);
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "";
    img.src = midia(p.poster);
    cx.appendChild(img);
    const v = document.createElement("video");
    v.muted = true; v.loop = true; v.playsInline = true;
    v.preload = "none"; v.hidden = true;
    v.dataset.src = midia(p.webm);
    v._poster = img;
    cx.appendChild(v);
    return cx;
  }

  /* ───────────────────────────── cards ───────────────────────────── */
  function card(grupo, e) {
    const b = el("button", "galeria-card");
    b.type = "button";
    b.dataset.foco = `card:${grupo.id}:${e.slug}`;
    const multi = grupo.seletor === "multi";
    const ligado = multi ? S.grafismos.has(e.slug) : S.escolha[grupo.id] === e.slug;
    b.setAttribute("aria-pressed", String(!!ligado));
    const bloqueadoPeloEssencial = S.direcaoEdicao?.modo === "essencial"
      && (grupo.id === "gancho" || grupo.id === "grafismo"
        || (grupo.id === "gramatica" && e.slug !== "plano-fixo"));
    if (e.estado === "candidato" || bloqueadoPeloEssencial) {
      b.disabled = true;
      b.title = bloqueadoPeloEssencial
        ? "O acabamento Essencial usa plano fixo e não inclui animações."
        : (e.bloqueio || "");
    }
    const cx = caixaDe(e);
    b.appendChild(cx);
    b.appendChild(el("p", "galeria-nome", esc(e.nome)));
    b.appendChild(el("p", "galeria-pinta", esc(e.oQuePinta)));
    if (e.preview?.nivel === 1) {
      b.appendChild(el("span", "galeria-selo", ICONES.peca + " com o texto desta peça"));
    }
    if (e.estado === "candidato") {
      // o texto do bloqueio VISÍVEL no card, não só em title=
      b.appendChild(el("p", "galeria-bloqueio", esc(e.bloqueio || "ainda não disponível")));
    }
    b.addEventListener("mouseenter", () => tocar(cx));
    b.addEventListener("focus", () => tocar(cx));
    b.addEventListener("mouseleave", () => parar(cx, false));
    b.addEventListener("blur", () => parar(cx, false));
    b.addEventListener("click", () => {
      if (b.disabled) return;
      if (multi) {
        if (S.grafismos.has(e.slug)) S.grafismos.delete(e.slug);
        else S.grafismos.add(e.slug);
      } else {
        S.escolha[grupo.id] = e.slug;
      }
      marcarSujo();
      S.focoDepoisDoDesenho = b.dataset.foco;
      desenhar();
    });
    if (e.preview && semMovimento()) {
      /* A opção explícita fica FORA do botão que escolhe o card. Assim ela é
       * alcançável por teclado e não cria vídeo/controle interativo aninhado. */
      const envoltorio = el("div", "galeria-card-wrap");
      envoltorio.appendChild(b);
      const ver = el("button", "galeria-ver-animacao");
      ver.type = "button";
      ver.setAttribute("aria-pressed", "false");
      ver.innerHTML = ICONES.amostra + " ver animação";
      const videoReducao = cx.querySelector("video");
      if (videoReducao) videoReducao._controleReducao = ver;
      ver.addEventListener("click", () => {
        const v = cx.querySelector("video");
        if (!v) return;
        const ligar = v.hidden || v.paused;
        if (ligar) {
          if (!v.getAttribute("src")) v.setAttribute("src", v.dataset.src);
          v.hidden = false;
          if (v._poster) v._poster.hidden = true;
          const anterior = S.tocando.indexOf(v);
          if (anterior >= 0) S.tocando.splice(anterior, 1);
          S.tocando.push(v);
          pararExcedentes();
          rotularControleReducao(v, true);
          v.play().catch(() => {
            const i = S.tocando.indexOf(v);
            if (i >= 0) S.tocando.splice(i, 1);
            v.hidden = true;
            if (v._poster) v._poster.hidden = false;
            rotularControleReducao(v, false);
          });
        } else {
          const i = S.tocando.indexOf(v);
          if (i >= 0) S.tocando.splice(i, 1);
          v.pause();
          v.hidden = true;
          if (v._poster) v._poster.hidden = false;
          rotularControleReducao(v, false);
        }
      });
      envoltorio.appendChild(ver);
      return envoltorio;
    }
    return b;
  }

  /* ───────────── decisão de acabamento: antes do vocabulário visual ───────── */
  function selecionarDirecao(d) {
    if (!direcaoValida(d)) return;
    const mesmoModo = S.direcaoEdicao?.modo === d.modo;
    if (d.modo === "essencial") {
      S.direcaoEdicao = { modo: d.modo, densidade: "leve", sfx: "sem-sfx" };
      aplicarRestricoesEssencial();
    } else {
      if (!S.sfxTocado && "sfx" in S.elementos) {
        S.elementos.sfx = d.sfx === "automatico";
      }
      S.direcaoEdicao = {
        modo: d.modo,
        densidade: mesmoModo ? S.direcaoEdicao.densidade : d.densidade,
        sfx: S.elementos.sfx === false ? "sem-sfx" : "automatico",
      };
    }
    marcarSujo();
    S.focoDepoisDoDesenho = `direcao:${d.modo}`;
    desenhar();
  }

  function secaoDirecaoEdicao() {
    const s = el("section", "galeria-direcao");
    s.appendChild(el("span", "galeria-direcao-etapa", "Primeiro, escolha o acabamento"));
    s.appendChild(el("h2", null, "Como você quer que esta edição fique?"));
    s.appendChild(el("p", "galeria-sub",
      "Essa decisão entra no planejamento das animações e dos sons, antes da montagem."));
    const direcoes = S.dados.direcoes_edicao || [];
    if (direcoes.length !== 3) {
      const aviso = el("p", "galeria-direcao-aviso",
        "As opções de acabamento não vieram nesta galeria. Gere a galeria da peça novamente.");
      aviso.setAttribute("role", "alert");
      s.appendChild(aviso);
      return s;
    }
    const grade = el("div", "galeria-direcao-grade");
    for (const d of direcoes) {
      const b = el("button", "galeria-direcao-card");
      b.type = "button";
      b.dataset.foco = `direcao:${d.modo}`;
      const ativo = S.direcaoEdicao?.modo === d.modo;
      b.setAttribute("aria-pressed", String(ativo));
      b.appendChild(el("span", "galeria-direcao-modo", esc(d.nome)));
      b.appendChild(el("strong", null, esc(d.descricao)));
      const rod = d.modo === "essencial"
        ? "Sem animações · sem SFX"
        : `Densidade ${esc(d.densidade)} · SFX automático`;
      b.appendChild(el("span", "galeria-direcao-meta", rod));
      b.addEventListener("click", () => selecionarDirecao(d));
      grade.appendChild(b);
    }
    s.appendChild(grade);

    if (!S.direcaoEdicao) {
      const p = el("p", "galeria-direcao-pendente",
        "Escolha uma das três opções para liberar o envio do look.");
      p.setAttribute("role", "status");
      s.appendChild(p);
      return s;
    }

    const linha = el("div", "galeria-densidade");
    linha.appendChild(el("span", "galeria-densidade-rotulo", "Densidade de animações"));
    const botoes = el("div", "galeria-densidade-opcoes");
    const nomes = { leve: "Leve", equilibrada: "Equilibrada", alta: "Alta" };
    for (const densidade of DENSIDADES) {
      const b = el("button", "galeria-densidade-botao");
      b.type = "button";
      b.dataset.foco = `densidade:${densidade}`;
      b.textContent = nomes[densidade];
      b.setAttribute("aria-pressed", String(S.direcaoEdicao.densidade === densidade));
      b.disabled = S.direcaoEdicao.modo === "essencial";
      b.addEventListener("click", () => {
        S.direcaoEdicao.densidade = densidade;
        marcarSujo();
        S.focoDepoisDoDesenho = b.dataset.foco;
        desenhar();
      });
      botoes.appendChild(b);
    }
    linha.appendChild(botoes);
    linha.appendChild(el("p", "galeria-direcao-nota",
      S.direcaoEdicao.modo === "essencial"
        ? "Essencial fica em leve e mantém animações e SFX desligados."
        : (S.elementos.sfx === false
          ? "SFX está desligado. Você pode religar nos ajustes finos."
          : "Os SFX das animações entram automaticamente. Você ainda pode desligá-los.")));
    s.appendChild(linha);
    return s;
  }


  /* ══════════════════ A PROPOSTA (SPEC-49 / H49-1, H49-3, H49-12) ═════════════
   *
   * 🔴 A TELA ERA UM FORMULÁRIO. Diagnóstico do dono, com 8 prints (2026-08-12):
   * "MUITO poluído — um monte de template que a maioria não vai utilizar; a cor
   * está escondida e não reflete nos previews". Ele escolheu a direção: **1 look
   * completo montado para esta peça + 2 variações completas**, e as seis seções
   * viram "ajustes finos".
   *
   * O que NÃO mudou, de propósito: o vocabulário continua vindo de `grupos`, a
   * escolha continua sendo `S.escolha`/`S.grafismos`, e o payload é o mesmo — uma
   * proposta é um ATALHO que marca várias folhas de uma vez, não um caminho novo.
   * Por isso o rastro (fonte, eventos, digest) não muda um byte.
   *
   * `propostas` ausente (galeria gerada antes desta spec) → a tela desenha as
   * seções abertas, como antes. Degradação honesta.
   */
  function aplicarProposta(p) {
    for (const [gid, slug] of Object.entries(p.escolhas || {})) {
      if (S.direcaoEdicao?.modo === "essencial"
          && !["tema", "legenda"].includes(gid)) continue;
      S.escolha[gid] = slug;
    }
    if (S.direcaoEdicao?.modo !== "essencial" && Array.isArray(p.grafismos)) {
      S.grafismos = new Set(p.grafismos);
    }
    aplicarRestricoesEssencial();
    S.propostaEscolhida = p.id;
    marcarSujo();
    S.focoDepoisDoDesenho = `proposta:${p.id}`;
    desenhar();
  }

  function combina(p) {
    const folhas = Object.entries(p.escolhas || {}).every(([g, s]) => S.escolha[g] === s);
    const proposta = [...(p.grafismos || [])].sort();
    const atual = [...S.grafismos].sort();
    return folhas && JSON.stringify(proposta) === JSON.stringify(atual);
  }

  /* Contraste do acento contra os pixels SOB A FAIXA da prévia (H49-12).
   * Medir o frame inteiro aprova um rodapé escuro sobre uma faixa clara. A
   * geometria vem do próprio elemento CSS, depois do layout responsivo, e a
   * mídia é desenhada no canvas com o mesmo `object-fit: contain` da tela. */
  function razaoContraste(hex, lum2) {
    const c = hex.slice(1).match(/../g).map((x) => parseInt(x, 16) / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)));
    const l1 = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    const [a, b] = l1 > lum2 ? [l1, lum2] : [lum2, l1];
    return (a + 0.05) / (b + 0.05);
  }

  /* A fonte do pixel é o POSTER, e só o vídeo quando ele já decodificou.
   * Medido na tela (2026-08-12): a caixa carrega `preload="none"` e só põe o
   * `src` no vídeo quando alguém passa o mouse — então medir só pelo vídeo dava
   * contraste NENHUM no carregamento, que é justamente quando o aviso importa.
   * O poster é o MESMO frame, já no DOM, e não custa rede nova. */
  function medirContraste(caixa, alvo) {
    if (!S.acento || !caixa) return;
    const v = caixa.querySelector("video");
    const img = caixa.querySelector("img");
    const faixa = caixa.querySelector(".galeria-camada-acento");
    const fonte = (v && v.readyState >= 2) ? v
      : (img && img.complete && img.naturalWidth ? img : null);
    const fonteW = fonte === v ? v?.videoWidth : img?.naturalWidth;
    const fonteH = fonte === v ? v?.videoHeight : img?.naturalHeight;
    const caixaW = caixa.clientWidth;
    const caixaH = caixa.clientHeight;
    if (!fonte || !fonteW || !fonteH || !faixa || !caixaW || !caixaH) return;
    try {
      const cv = document.createElement("canvas");
      cv.width = Math.max(48, Math.min(192, Math.round(caixaW)));
      cv.height = Math.max(1, Math.round(cv.width * caixaH / caixaW));
      const cx2 = cv.getContext("2d");
      cx2.fillStyle = getComputedStyle(caixa).backgroundColor || "black";
      cx2.fillRect(0, 0, cv.width, cv.height);

      const escalaMidia = Math.min(cv.width / fonteW, cv.height / fonteH);
      const midiaW = fonteW * escalaMidia;
      const midiaH = fonteH * escalaMidia;
      cx2.drawImage(fonte, (cv.width - midiaW) / 2, (cv.height - midiaH) / 2,
                    midiaW, midiaH);

      const sx = cv.width / caixaW;
      const sy = cv.height / caixaH;
      /* A faixa tem borda de 1px. A amostra usa só a área preenchida pelo
       * acento, que é a superfície cuja legibilidade estamos prometendo. */
      const borda = 1;
      const x = Math.max(0, Math.floor((faixa.offsetLeft + borda) * sx));
      const y = Math.max(0, Math.floor((faixa.offsetTop + borda) * sy));
      const direita = Math.min(cv.width,
        Math.ceil((faixa.offsetLeft + faixa.offsetWidth - borda) * sx));
      const fundo = Math.min(cv.height,
        Math.ceil((faixa.offsetTop + faixa.offsetHeight - borda) * sy));
      const largura = Math.max(1, direita - x);
      const altura = Math.max(1, fundo - y);
      const d = cx2.getImageData(x, y, largura, altura).data;
      let soma = 0, n = 0;
      for (let i = 0; i < d.length; i += 4) {
        const f = [d[i], d[i + 1], d[i + 2]].map((v) => v / 255)
          .map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)));
        soma += 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
        n++;
      }
      if (!n) return;
      const r = razaoContraste(S.acento, soma / n);
      alvo.textContent = `Contraste ${r.toFixed(2)}:1`;
      alvo.className = "galeria-contraste" + (r < PISO_CONTRASTE ? " galeria-contraste--baixo" : "");
      if (r < PISO_CONTRASTE) {
        alvo.textContent = `Contraste baixo (${r.toFixed(2)}:1)`;
        alvo.title = `Abaixo do piso ${PISO_CONTRASTE.toFixed(1)}:1. `
          + "O destaque pode perder legibilidade neste fundo.";
      } else {
        alvo.title = "Contraste medido contra os pixels sob a faixa desta proposta.";
      }
    } catch (_) { /* canvas sujo por origem: sem número, sem chute */ }
  }

  function cartaoProposta(p, indice) {
    const art = el("article", "galeria-proposta"
      + (indice === 0 ? " galeria-proposta--principal" : " galeria-proposta--variacao")
      + (combina(p) ? " galeria-proposta--ativa" : ""));
    art.appendChild(el("span", "galeria-proposta-tipo",
      indice === 0 ? "Direção recomendada" : `Variação ${String(indice).padStart(2, "0")}`));
    art.appendChild(el("h3", "galeria-proposta-titulo", esc(p.titulo)));
    art.appendChild(el("p", "galeria-proposta-porque", esc(p.porque || "")));

    if (p.cartao?.preview) {
      const cx = caixaDe({ slug: p.cartao.slug, preview: p.cartao.preview,
                           nome: p.cartao.slug });
      /* 🔴 A COR REFLETE AO VIVO (H49-3). O `.webm` tem a cor COZIDA e não
       * repinta — então o acento entra como CAMADA DOM/CSS por cima do vídeo,
       * rotulada como amostra. É o que o concorrente ganha de graça (o preview
       * dele é DOM falso) sem perder o que a gente ganha (o preview é o render
       * de verdade). Trocar a cor no topo repinta ISTO na hora. */
      const camada = el("i", "galeria-camada-acento");
      cx.appendChild(camada);
      art.appendChild(cx);
      const contraste = el("p", "galeria-contraste");
      art.appendChild(contraste);
      const medir = () => medirContraste(cx, contraste);
      const img = cx.querySelector("img");
      const v = cx.querySelector("video");
      if (img) img.addEventListener("load", medir);
      if (v) v.addEventListener("loadeddata", medir);
      S.medidores.push(medir);
      setTimeout(medir, 60);
      art.appendChild(el("p", "galeria-nota", ICONES.amostra
        + " A faixa é uma amostra. O motor aplica a cor na montagem."));
    }

    const ul = el("ul", "galeria-folhas");
    for (const [gid, slug] of Object.entries(p.escolhas || {})) {
      const e = S.indice?.[slug];
      const proc = (p.procedencia || {})[gid] || {};
      const li = el("li", null,
        `<b>${esc(TITULO_CURTO[gid] || gid)}</b> ${esc(e?.nome || slug)}`
        + ` <span class="galeria-proc" data-fonte="${esc(proc.fonte || "")}">`
        + `${esc(proc.diz || "")}</span>`);
      ul.appendChild(li);
    }
    for (const slug of p.grafismos || []) {
      const e = S.indice?.[slug];
      ul.appendChild(el("li", null,
        `<b>grafismo</b> ${esc(e?.nome || slug)}`
        + ` <span class="galeria-proc" data-fonte="plano">do plano desta peça</span>`));
    }
    art.appendChild(ul);

    const b = el("button", "galeria-usar" + (combina(p) ? " galeria-usar--ativa" : ""));
    b.type = "button";
    b.dataset.foco = `proposta:${p.id}`;
    b.setAttribute("aria-pressed", String(combina(p)));
    b.textContent = combina(p) ? "Proposta escolhida"
      : (S.direcaoEdicao?.modo === "essencial" ? "Usar cores e legenda" : "Usar proposta");
    b.addEventListener("click", () => aplicarProposta(p));
    art.appendChild(b);
    return art;
  }

  /* ════════════ O ESTILO APRENDE, NA TELA (SPEC-49 / H49-4) ═══════════════
   *
   * "Quanto mais usa, mais entende os gostos" — decisão do dono. O loop
   * sinais→propor→promover já existia inteiro (SPEC-24/41) e morria num comando
   * que só nós rodávamos. Aqui ele aparece onde a escolha acontece.
   *
   * 🔴 A TELA NÃO PROMOVE. O "sim" manda um EVENTO; quem escreve versão nova é o
   * `estilo.py promover --confirmar`, e a regra é do dono: propor exige 3
   * produções distintas, promover é decisão dele. Um botão que promovesse
   * sozinho transformaria "a máquina aprendeu" em "a máquina decidiu". */
  function blocoAprendizado() {
    const ap = S.dados.aprendizado;
    if (!ap || !(ap.propostas || []).length) return null;
    const s = el("section", "galeria-aprendizado");
    const n = Math.max(...ap.propostas.map((p) => p.n_producoes || 0));
    s.appendChild(el("h2", null, "O seu estilo quer aprender"));
    s.appendChild(el("p", "galeria-sub",
      `Nas últimas ${n} peças você corrigiu sempre na mesma direção. `
      + "Quer que isso vire o seu padrão?"));
    const ul = el("ul", "galeria-folhas");
    for (const p of ap.propostas) {
      ul.appendChild(el("li", null,
        `<b>${esc(p.path)}</b> ${esc(String(p.de ?? "não definido"))} → `
        + `<b>${esc(String(p.para))}</b> `
        + `<span class="galeria-proc" data-fonte="medido">${esc(p.motivo || "")}</span>`));
    }
    s.appendChild(ul);
    const linha = el("div", "galeria-aprendizado-acoes");
    const sim = el("button", "galeria-usar");
    sim.type = "button";
    sim.textContent = "sim, virar meu padrão";
    const nao = el("button", "galeria-usar");
    nao.type = "button";
    nao.textContent = "não, só nesta peça";
    const eco = el("p", "galeria-nota");
    sim.addEventListener("click", () => {
      S.aprendizadoResposta = "sim";
      marcarSujo();
      /* O comando fica VISÍVEL, e é o mesmo que vai no payload. Quem aprova vê o
       * que vai acontecer antes de acontecer — e, se preferir, roda na mão. */
      eco.innerHTML = "anotado: vai junto no pedido, e a promoção só acontece "
        + `quando alguém rodar <code>${esc(ap.comando)}</code>`;
      atualizarRodape();
    });
    nao.addEventListener("click", () => {
      S.aprendizadoResposta = "nao";
      marcarSujo();
      eco.textContent = "anotado: fica só nesta peça, e o estilo não muda.";
      atualizarRodape();
    });
    linha.appendChild(sim);
    linha.appendChild(nao);
    s.appendChild(linha);
    s.appendChild(eco);
    return s;
  }

  function blocoPropostas() {
    const props = S.dados.propostas || [];
    if (!props.length) return null;
    const s = el("section", "galeria-propostas");
    s.appendChild(el("h2", null, "Direção visual"));
    const variacoes = Math.max(0, Math.min(props.length, 3) - 1);
    const complemento = variacoes === 0 ? "sem variação adicional."
      : (variacoes === 1 ? "com uma variação controlada."
        : "com duas variações controladas.");
    s.appendChild(el("p", "galeria-sub",
      `Uma proposta completa para esta peça, ${complemento}`));
    s.appendChild(blocoAcentoTopo());
    const grade = el("div", "galeria-propostas-grade");
    for (const [indice, p] of props.slice(0, 3).entries()) {
      grade.appendChild(cartaoProposta(p, indice));
    }
    s.appendChild(grade);
    return s;
  }

  function secaoGrupo(grupo) {
    const s = el("section", "galeria-secao");
    s.appendChild(el("h2", null, esc(grupo.titulo)));
    const escolhiveis = grupo.estilos.filter((e) => e.estado !== "candidato");
    const grade = el("div", "galeria-grade");
    /* 🔴 H49-2: OS GRAFISMOS VÊM DO PLANO, não de menu. Decisão do dono: "os
     * motions de cada peça nascem do PLANO-EDICAO, por beat, sob medida; a seção
     * mostra SÓ o que o plano desta peça pede". A tela oferecia 16 cards de
     * catálogo como se fossem proposta. O catálogo continua alcançável — atrás de
     * "ver todos" — porque esconder o vocabulário é o defeito oposto. */
    const dp = S.dados.grafismos_do_plano;
    let mostrar = grupo.estilos;
    if (grupo.id === "grafismo" && dp && !S.verTodosGrafismos) {
      const doPlano = new Set(dp.slugs || []);
      mostrar = grupo.estilos.filter(
        (e) => doPlano.has(e.slug) || S.grafismos.has(e.slug));
      const linha = el("p", "galeria-nota", esc(dp.porque || "")
        + (dp.fonte ? ` <span class="galeria-proc" data-fonte="plano">${esc(dp.fonte)}</span>` : ""));
      s.appendChild(linha);
      const ver = el("button", "galeria-vertodos");
      ver.type = "button";
      ver.textContent = `ver todos (${grupo.estilos.length} do catálogo)`;
      ver.addEventListener("click", () => { S.verTodosGrafismos = true; desenhar(); });
      s.appendChild(ver);
      if (!mostrar.length) {
        s.appendChild(el("p", "galeria-fantasma",
          "Nenhum grafismo foi pedido para esta peça. Isso também é uma direção válida."));
      }
    }
    for (const e of mostrar) grade.appendChild(card(grupo, e));
    /* 🔴 Grupo com menos de 2 escolhíveis NÃO some. O ref-A admite que num job
     * longform o portão "has nothing to offer yet" e manda PULAR o portão,
     * voltando a pergunta para o chat (`ref-A/SKILL.md:210-212`). Esconder é o
     * que faz o vocabulário faltante de um perfil novo nunca ser notado. */
    if (escolhiveis.length < 2) {
      const p = S.dados.perfil;
      grade.appendChild(el("div", "galeria-fantasma",
        `mais estilos em breve para o perfil <b>${esc(p.vocabulario || p.nome)}</b>`));
    }
    s.appendChild(grade);
    const sel = grupo.seletor === "multi" ? null : S.escolha[grupo.id];
    if (sel) {
      const e = grupo.estilos.find((x) => x.slug === sel);
      const aj = blocoAjuste(e);
      if (aj) s.appendChild(aj);
    }
    return s;
  }

  /* O MESMO seletor de acento, no TOPO (H49-3). Antes ele vivia enterrado sob a
   * seção `tema`, e o dono não o achava ("a cor está escondida"). Aqui ele é a
   * primeira coisa depois do título, e repinta a camada DOM das propostas na
   * hora — sem inventar um segundo lugar de verdade: a função abaixo é a mesma,
   * `blocoAcento()`, com outro invólucro. */
  function blocoAcentoTopo() {
    const box = el("div", "galeria-acento-topo");
    box.appendChild(el("span", "galeria-acento-rotulo", "Cor de destaque"));
    box.appendChild(blocoAcento());
    return box;
  }

  /* ─────────────────── acento: a troca honesta (§3.3) ─────────────────── */
  function blocoAcento() {
    const box = el("div", "galeria-acento");
    const cor = document.createElement("input");
    cor.type = "color";
    cor.dataset.foco = "acento:cor";
    cor.setAttribute("aria-label", "Escolher cor de destaque");
    cor.value = S.acento || "#000000";
    const hex = document.createElement("input");
    hex.type = "text";
    hex.dataset.foco = "acento:hex";
    hex.setAttribute("aria-label", "Cor de destaque em hexadecimal");
    hex.inputMode = "text";
    hex.placeholder = "#rrggbb";
    hex.value = S.acento || "";
    const aplica = (v) => {
      const n = normHex(v);
      if (!n) return;
      S.acento = n;
      marcarSujo();
      cor.value = n; hex.value = n;
      box.style.setProperty("--g-amostra", n);
      // 🔴 H49-3: a cor vira variável CSS na RAIZ da galeria, e a camada DOM das
      // propostas a herda — é isso que faz o card mudar na hora. E o contraste é
      // remedido no mesmo gesto: um aviso que só aparece no reload é um aviso que
      // ninguém lê.
      raiz.style.setProperty("--g-acento", n);
      for (const m of S.medidores) { try { m(); } catch (_) { /* nada */ } }
      atualizarRodape();
    };
    cor.addEventListener("input", () => aplica(cor.value));
    hex.addEventListener("input", () => { if (normHex(hex.value)) aplica(hex.value); });
    hex.addEventListener("change", () => aplica(hex.value));
    box.appendChild(cor);
    box.appendChild(hex);
    if (S.acento) box.style.setProperty("--g-amostra", S.acento);

    const der = acentoDerivado();
    if (der.usado) {
      /* Vídeo renderizado não repinta ao vivo. Eles ganham o acento instantâneo
       * porque o preview deles é DOM falso (`applyAccent`, `app.js:1054-1056`).
       * A troca é deliberada: eles ganham reatividade, nós ganhamos fidelidade.
       * O swatch é DOM e está ROTULADO como amostra — nunca como render. */
      box.appendChild(el("span", "galeria-amostra", "<i></i> amostra da cor"));
    }
    const nota = el("p", "galeria-nota");
    nota.textContent = der.usado
      ? "A amostra muda agora. A cor renderizada aparece na próxima montagem."
      : "O look atual não usa destaque, então a cor não será aplicada à força.";
    const env = el("div");
    env.appendChild(box);
    env.appendChild(nota);
    return env;
  }

  /* ─────────────── ajuste fino, dobrado, só do selecionado ─────────────── */
  function blocoAjuste(e) {
    if (!e) return null;
    const uteis = (e.parametros || []).filter(
      (p) => ["cor", "px", "fator"].includes(p.tipo) &&
             (p.tipo === "cor" || Array.isArray(p.faixa)));
    if (!uteis.length) return null;
    const d = document.createElement("details");
    d.className = "galeria-ajuste";
    const chaveDetalhe = `ajuste:${e.slug}`;
    d.dataset.detalhe = chaveDetalhe;
    d.open = S.detalhesAbertos.has(chaveDetalhe);
    d.addEventListener("toggle", () => {
      if (d.open) S.detalhesAbertos.add(chaveDetalhe);
      else S.detalhesAbertos.delete(chaveDetalhe);
    });
    const sum = document.createElement("summary");
    sum.textContent = `ajuste fino de ${e.nome}`;
    d.appendChild(sum);
    for (const p of uteis) {
      const linha = el("div", "galeria-slider");
      const rotulo = el("label", null, esc(p.nome));
      const atual = S.parametros[e.slug]?.[p.nome];
      let campo;
      if (p.tipo === "cor") {
        campo = document.createElement("input");
        campo.type = "color";
        campo.value = normHex(atual ?? p.padrao) || "#000000";
      } else {
        campo = document.createElement("input");
        campo.type = "range";
        campo.min = String(p.faixa[0]);
        campo.max = String(p.faixa[1]);
        campo.step = p.tipo === "px" ? "1" : "0.01";
        campo.value = String(atual ?? p.padrao);
      }
      const campoId = `ajuste-${e.slug}-${p.nome}`.replace(/[^a-zA-Z0-9_-]/g, "-");
      campo.id = campoId;
      rotulo.htmlFor = campoId;
      linha.appendChild(rotulo);
      const leitura = el("span", "galeria-num", esc(campo.value));
      campo.addEventListener("input", () => {
        leitura.textContent = campo.value;
        const v = p.tipo === "cor" ? campo.value : Number(campo.value);
        // DIFF: só o que o usuário mexeu entra no payload
        if (v === p.padrao) {
          if (S.parametros[e.slug]) delete S.parametros[e.slug][p.nome];
        } else {
          S.parametros[e.slug] = S.parametros[e.slug] || {};
          S.parametros[e.slug][p.nome] = v;
        }
        marcarSujo();
        atualizarRodape();
      });
      linha.appendChild(campo);
      linha.appendChild(leitura);
      d.appendChild(linha);
    }
    d.appendChild(el("p", "galeria-nota",
      "a prévia mostra os valores padrão; o ajuste entra no próximo render"));
    return d;
  }

  /* ───────────────────────── interruptores ───────────────────────── */
  function secaoInterruptores() {
    const s = el("section", "galeria-secao");
    s.appendChild(el("h2", null, "Interruptores"));
    s.appendChild(el("p", null,
      "liga/desliga de pipeline. O que fica DESMARCADO vai no pedido como um " +
      "não explícito, nomeado."));
    const fs = el("fieldset", "galeria-chaves");
    for (const i of S.dados.interruptores || []) {
      const lab = el("label", "galeria-chave");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.foco = `interruptor:${i.id}`;
      cb.checked = !!S.elementos[i.id];
      const travaEssencial = S.direcaoEdicao?.modo === "essencial"
        && ["sfx", "split_broll", "flash_no_corte", "tracking"].includes(i.id);
      cb.disabled = travaEssencial;
      if (travaEssencial) lab.classList.add("galeria-chave--travada");
      cb.addEventListener("change", () => {
        S.elementos[i.id] = cb.checked;
        if (i.id === "sfx") {
          S.sfxTocado = true;
          if (S.direcaoEdicao && S.direcaoEdicao.modo !== "essencial") {
            S.direcaoEdicao.sfx = cb.checked ? "automatico" : "sem-sfx";
          }
        }
        marcarSujo();
        if (i.id === "sfx" && S.direcaoEdicao) {
          S.focoDepoisDoDesenho = cb.dataset.foco;
          desenhar();
        } else atualizarRodape();
      });
      lab.appendChild(cb);
      const txt = el("div");
      txt.appendChild(el("div", null, esc(i.nome)));
      /* A mesma régua do F1-5 (achado A-F2): o creator lê o que o interruptor
       * FAZ com o vídeo dele; o nome do script e o número da SPEC ficam no
       * `title=`, acessíveis a quem mantém o código sem ocupar a tela de quem
       * está editando. Sem `tecnico` o rótulo continua só com a prosa — um
       * interruptor antigo não quebra a tela. */
      if (i.aplica) txt.appendChild(el("span", null, esc(i.aplica)));
      if (travaEssencial) {
        txt.appendChild(el("span", "galeria-chave-trava",
          "desligado pelo acabamento Essencial"));
      }
      if (i.tecnico) lab.title = i.tecnico;
      lab.appendChild(txt);
      fs.appendChild(lab);
    }
    s.appendChild(fs);
    return s;
  }

  function secaoObservacao() {
    const s = el("section", "galeria-secao");
    s.appendChild(el("h2", null, "Observação livre"));
    const t = document.createElement("textarea");
    t.className = "galeria-obs";
    t.dataset.foco = "observacao";
    t.setAttribute("aria-label", "Observação livre para a montagem");
    t.value = S.observacao;
    t.placeholder = "o que a galeria não pergunta";
    t.addEventListener("input", () => { S.observacao = t.value; marcarSujo(); });
    s.appendChild(t);
    return s;
  }

  /* ───────────────────────────── payload ───────────────────────────── */
  function payload() {
    aplicarRestricoesEssencial();
    const g = S.dados;
    const ix = indice();
    const der = acentoDerivado();
    const oferecidos = (g.grupos.find((x) => x.id === "grafismo")?.estilos || [])
      .filter((e) => e.estado !== "candidato").map((e) => e.slug);
    const dentro = oferecidos.filter((s) => S.grafismos.has(s));
    let direcao = S.direcaoEdicao ? { ...S.direcaoEdicao } : null;
    if (direcao && direcao.modo !== "essencial") {
      direcao.sfx = S.elementos.sfx === false ? "sem-sfx" : "automatico";
      S.direcaoEdicao.sfx = direcao.sfx;
    }
    const p = {
      contrato: CONTRATO_ESTILO,
      salvo_em: new Date().toISOString(),
      revisao_base: S.estado?.revisao ?? 0,
      fonte: "galeria",
      rerender: rerender(),
      direcao_edicao: direcao,
      gramatica: S.escolha.gramatica || null,
      tema: S.escolha.tema || null,
      gancho: S.escolha.gancho || null,
      legenda: S.escolha.legenda || null,
      acento: S.acento || null,
      acento_usado: der.usado,
      acento_onde: der.onde,
      grafismos: dentro,
      // 🔴 O COMPLEMENTO, nomeado. "Tudo que NÃO foi escolhido é instrução
      // também — é o que tem que ficar de fora" (`watch_edits.py:93-95`).
      grafismos_fora: oferecidos.filter((s) => !S.grafismos.has(s)),
      // mapa COMPLETO de interruptores, com os `false` explícitos
      elementos: { ...S.elementos },
      parametros: {},
      observacao: S.observacao || "",
      perfil: g.perfil.vocabulario || g.perfil.nome,
      catalogo_gerado_em: g.catalogo_gerado_em || "",
    };
    // H49-4: a resposta ao aprendizado viaja no payload, nomeada. Sem resposta o
    // campo não existe (o `for (null) delete` abaixo cuida disso) — silêncio não
    // vira "sim" nem "não".
    if (S.aprendizadoResposta && S.dados.aprendizado) {
      p.aprendizado = {
        resposta: S.aprendizadoResposta,
        estilo: S.dados.aprendizado.estilo,
        comando: S.dados.aprendizado.comando,
        propostas: (S.dados.aprendizado.propostas || []).map((x) => x.path),
      };
    }
    const gram = ix[p.gramatica || ""];
    if (gram?.aplica?.perfil_campo) p.gramatica_plano = gram.aplica.valor;
    for (const [slug, diff] of Object.entries(S.parametros)) {
      if (diff && Object.keys(diff).length) p.parametros[slug] = diff;
    }
    for (const k of Object.keys(p)) if (p[k] === null) delete p[k];
    return p;
  }

  function linhaResumo() {
    const ix = indice();
    const nome = (s) => (ix[s]?.nome || s);
    const nomesDirecao = { essencial: "Essencial", animada: "Com animações",
                           surpresa: "Me surpreenda" };
    const partes = [S.direcaoEdicao
      ? `${nomesDirecao[S.direcaoEdicao.modo]} · ${S.direcaoEdicao.densidade}`
      : "escolha o acabamento"];
    partes.push(...["gramatica", "tema", "gancho", "legenda"]
      .filter((g) => S.escolha[g]).map((g) => nome(S.escolha[g]));
    const der = acentoDerivado();
    partes.push(`${S.grafismos.size} grafismo(s)`);
    const ligados = Object.values(S.elementos).filter(Boolean).length;
    const total = Object.keys(S.elementos).length;
    partes.push(`${ligados}/${total} interruptores`);
    partes.push(der.usado
      ? `destaque ${S.acento || "(sem cor)"}`
      : "destaque não se aplica");
    return partes.join(" / ");
  }

  /* ══════════════ CONFLITO E ECO NA ESCOLHA (SPEC-49 / H49-5) ═════════════
   *
   * Dois achados do teste de campo (A-13 e A-13b, 2026-08-12), e os dois são de
   * SILÊNCIO:
   *
   *   · CONFLITO — o digest saiu com o MESMO efeito "liberado como grafismo" E
   *     "desligado como interruptor". Duas instruções contraditórias, sem ⚠️. O
   *     agente do outro lado tem que escolher uma, e ele escolhe sozinho.
   *   · ECO — dois saves IDÊNTICOS foram processados como novos. Do lado do
   *     agente, "confirmou de novo" e "mudou de ideia" chegam iguais.
   *
   * A tela avisa; ela NÃO decide por ninguém. Desmarcar o homônimo
   * automaticamente seria a tela editando a escolha do creator sem ele pedir. */
  function conflitos() {
    const fora = [];
    const nomeInt = {};
    for (const i of S.dados.interruptores || []) nomeInt[i.id] = i.nome || i.id;
    /* O vínculo é DADO, não adivinhação: a entrada do catálogo declara
     * `aplica.liga = <id do interruptor>` (é o que faz `punch-pontual` acender o
     * `tracking` e `split-screen-esfumacado` acender o `split_broll`). Escolher a
     * folha e deixar o interruptor desligado é pedir e desmandar na mesma tela. */
    const escolhidos = [...Object.values(S.escolha), ...S.grafismos];
    for (const slug of escolhidos) {
      const liga = S.indice?.[slug]?.aplica?.liga;
      if (!liga) continue;
      if (!(liga in S.elementos)) continue;
      if (S.elementos[liga]) continue;
      fora.push(`"${S.indice[slug].nome || slug}" precisa de `
        + `"${nomeInt[liga] || liga}", e esse interruptor está desligado. `
        + "as duas instruções vão juntas no pedido, e quem monta escolhe uma");
    }
    return fora;
  }

  function ecoDoVigente() {
    const vig = S.dados.vigente?.estilo;
    if (!vig) return false;
    const atual = payload();
    const iguais = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
    const campos = ["direcao_edicao", "gramatica", "tema", "gancho", "legenda", "acento",
                    "elementos", "parametros", "observacao"];
    const mesmasFolhas = campos.every((c) => iguais(atual[c], vig[c]));
    const g1 = [...(atual.grafismos || [])].sort();
    const g2 = [...(vig.grafismos || [])].sort();
    return mesmasFolhas && iguais(g1, g2);
  }

  /* ───────────────────────────── rodapé ───────────────────────────── */
  let elResumo = null, elBotao = null, elToast = null, elPayload = null;
  let elAvisos = null;

  function rotularBotaoEnvio() {
    if (!elBotao) return;
    elBotao.disabled = S.enviando || !S.direcaoEdicao;
    elBotao.title = S.direcaoEdicao
      ? "" : "Escolha Essencial, Com animações ou Me surpreenda antes de enviar.";
    elBotao.textContent = S.enviando ? "Enviando..."
      : (!S.direcaoEdicao ? "Escolha o acabamento"
        : (rerender() ? "Aplicar e refazer montagem" : "Aplicar look e montar"));
  }

  function atualizarRodape() {
    if (elResumo) elResumo.textContent = linhaResumo();
    if (elPayload) elPayload.value = JSON.stringify(payload(), null, 1);
    const box = raiz.querySelector(".galeria-acento");
    if (box && S.acento) box.style.setProperty("--g-amostra", S.acento);
    if (elAvisos) {
      const linhas = conflitos().map((c) => "CONFLITO: " + c);
      if (ecoDoVigente()) {
        linhas.push("Esta escolha é idêntica à que já está aplicada. "
          + "Salvar de novo refaz a montagem sem mudar o look.");
      }
      elAvisos.innerHTML = linhas.map((l) => `<li>${esc(l)}</li>`).join("");
      elAvisos.hidden = linhas.length === 0;
    }
  }

  function rodape() {
    const r = el("div", "galeria-rodape");
    elResumo = el("p", "galeria-resumo");
    elAvisos = el("ul", "galeria-conflitos");
    elAvisos.hidden = true;
    r.appendChild(elAvisos);
    elToast = el("p", "galeria-toast");
    elToast.setAttribute("role", "status");
    elToast.setAttribute("aria-live", "polite");
    // A COR acompanha o rótulo (F1-4): verde no primeiro envio, âmbar quando o
    // clique vai mandar refazer a Fase 2. A classe sai da MESMA função
    // `rerender()` que escolhe o texto — duas fontes de verdade aqui seriam um
    // botão âmbar dizendo "Confirmar".
    elBotao = el("button", "galeria-botao" + (rerender() ? " galeria-botao--refaz" : ""));
    elBotao.type = "button";
    // rótulo condicional, adotado literalmente (`app.js:1162-1164`)
    rotularBotaoEnvio();
    elBotao.addEventListener("click", enviar);
    r.appendChild(elResumo);
    r.appendChild(elToast);
    r.appendChild(elBotao);
    return r;
  }

  async function enviar() {
    if (S.enviando) return;
    if (!S.direcaoEdicao) {
      elToast.textContent = "Escolha o acabamento da edição antes de enviar.";
      return;
    }
    const corpo = { tipo: "estilo", payload: payload() };
    if (modoFixture || !urlSalvar) {
      elToast.textContent = "modo fixture: o payload está na caixa abaixo (nada foi enviado)";
      return;
    }
    S.enviando = true;
    rotularBotaoEnvio();
    elToast.textContent = "Enviando instruções para a montagem...";
    try {
      const r = await fetch(urlSalvar, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      S.sujo = false;
      elToast.textContent = rerender()
        ? "Novo look enviado. A montagem será refeita com ele."
        : "Look enviado. A montagem pode começar.";
    } catch (err) {
      elToast.textContent = "falhou ao enviar: " + err.message;
    } finally {
      S.enviando = false;
      rotularBotaoEnvio();
    }
  }

  /* ───────────────────────────── desenho ───────────────────────────── */
  function desenhar() {
    const ajustesNoDom = raiz.querySelector(".galeria-ajustes");
    if (ajustesNoDom) S.ajustesAbertos = ajustesNoDom.open;
    const ativo = document.activeElement;
    if (!S.focoDepoisDoDesenho && ativo && raiz.contains(ativo)) {
      S.focoDepoisDoDesenho = ativo.dataset?.foco
        || (ativo.id ? `id:${ativo.id}` : null);
    }
    for (const v of S.tocando.slice()) {
      try { v.pause(); } catch (_) { /* nada */ }
    }
    S.tocando = [];
    raiz.innerHTML = "";
    raiz.setAttribute("aria-busy", "false");
    const g = S.dados;
    const cab = el("header", "galeria-cabecalho");
    cab.appendChild(el("span", "galeria-etapa", "Etapa 02 / Look"));
    cab.appendChild(el("h1", "galeria-titulo", "Defina o look da peça"));
    const p = g.perfil;
    cab.appendChild(el("p", "galeria-sub",
      `${esc(g.producao.slug)} / <span class="galeria-num">${esc(p.nome)}</span> / ` +
      `${p.largura}×${p.altura} @ ${p.fps} fps` +
      (rerender() ? " / <b>look já aplicado</b>" : "")));
    /* 🔴 A TELA VELHA NÃO SE ANUNCIAVA (achado D-3, 2026-08-11). Os textos que a
     * SPEC-40 reescreveu nascem no GERADOR: uma peça cujo `galeria.json` foi
     * gravado antes dela segue mostrando a prosa antiga, e não havia nada na
     * tela que dissesse isso — o creator lia o texto velho achando que era o
     * atual. Aqui a tela compara o que ela espera com o que o arquivo declara e
     * FALA. Não regenera: regerar é render de preview, e ninguém deve descobrir
     * isso porque a página travou por um minuto e meio. */
    const avisos = (g.avisos || []).slice();
    const vGer = Number(g.gerador_versao || 1);
    if (vGer < GERADOR_VERSAO_ESPERADA) {
      avisos.unshift("esta tela foi montada por uma versão anterior do programa, "
        + "então alguns textos aqui podem estar desatualizados; para atualizar, "
        + "peça para gerar a galeria desta peça de novo");
    }
    if (avisos.length) {
      const ul = el("ul", "galeria-avisos");
      for (const a of avisos) {
        const li = el("li", null, esc(a));
        if (a === avisos[0] && vGer < GERADOR_VERSAO_ESPERADA) {
          li.title = `galeria.json gerado_versao=${vGer} < ${GERADOR_VERSAO_ESPERADA}`
            + " (previews-peca.py). Regerar: previews-peca.py <dir-producao>";
        }
        ul.appendChild(li);
      }
      cab.appendChild(ul);
    }
    raiz.appendChild(cab);

    S.indice = indice();
    S.medidores = [];
    if (S.acento) raiz.style.setProperty("--g-acento", S.acento);

    raiz.appendChild(secaoDirecaoEdicao());
    const prop = blocoPropostas();
    if (prop) raiz.appendChild(prop);
    else raiz.appendChild(blocoAcentoTopo());
    const apr = blocoAprendizado();
    if (apr) raiz.appendChild(apr);

    /* 🔴 AS SEIS SEÇÕES VIRAM AJUSTE FINO (H49-1). Elas continuam INTEIRAS e
     * alcançáveis — progressive disclosure, não corte: o vocabulário completo é o
     * que impede a galeria de virar caixa preta. O que muda é a ordem de leitura.
     * Sem `propostas` (galeria antiga), tudo abre como antes. */
    const alvo = prop ? el("details", "galeria-ajustes") : raiz;
    if (prop) {
      const sum = document.createElement("summary");
      sum.textContent = "Ajustes finos";
      alvo.appendChild(sum);
      alvo.open = S.ajustesAbertos;
      alvo.addEventListener("toggle", () => { S.ajustesAbertos = alvo.open; });
      raiz.appendChild(alvo);
    }
    for (const grupo of g.grupos) alvo.appendChild(secaoGrupo(grupo));
    alvo.appendChild(secaoInterruptores());
    alvo.appendChild(secaoObservacao());
    raiz.appendChild(rodape());

    if (modoFixture || !urlSalvar) {
      elPayload = document.createElement("textarea");
      elPayload.className = "galeria-payload";
      elPayload.readOnly = true;
      raiz.appendChild(elPayload);
    }
    atualizarRodape();

    if (S.focoDepoisDoDesenho) {
      const chave = S.focoDepoisDoDesenho;
      S.focoDepoisDoDesenho = null;
      requestAnimationFrame(() => {
        const destino = chave.startsWith("id:")
          ? document.getElementById(chave.slice(3))
          : [...raiz.querySelectorAll("[data-foco]")]
            .find((n) => n.dataset.foco === chave);
        if (destino) destino.focus();
      });
    }

    // toca o selecionado de cada grupo, respeitando o teto
    for (const b of raiz.querySelectorAll('.galeria-card[aria-pressed="true"]')) {
      tocar(b.querySelector(".galeria-caixa"));
    }
  }

  function falhar(err) {
    raiz.innerHTML = "";
    raiz.setAttribute("aria-busy", "false");
    const f = el("div", "galeria-falha");
    f.appendChild(el("h2", null, "Não consegui montar as opções de estilo"));
    // 🔴 A FALHA CONTINUA ALTA — é isto que não pode se perder. O que mudou é a
    // ordem: primeiro o que aconteceu e o que fazer, em português; depois o
    // diagnóstico literal, no <pre>, para quem vai consertar. Um modo degradado
    // silencioso seria oferecer uma lista curta e deixar o creator escolher
    // achando que viu tudo.
    f.appendChild(el("p", null,
      "Nenhuma opção é inventada aqui: sem a lista de estilos desta peça não há " +
      "o que oferecer, e mostrar uma parte seria pior que mostrar nada. " +
      "Avise quem está editando. O detalhe abaixo diz onde travou."));
    f.appendChild(el("pre", null, esc(err.message || String(err))));
    raiz.appendChild(f);
  }

  function mostrarCarregando() {
    const c = el("div", "galeria-carregando");
    c.appendChild(el("span", "galeria-etapa", "Etapa 02 / Look"));
    c.appendChild(el("div", "galeria-esqueleto galeria-esqueleto--titulo"));
    const grade = el("div", "galeria-esqueleto-grade");
    grade.appendChild(el("div", "galeria-esqueleto galeria-esqueleto--principal"));
    grade.appendChild(el("div", "galeria-esqueleto"));
    grade.appendChild(el("div", "galeria-esqueleto"));
    c.appendChild(grade);
    const status = el("p", "galeria-sub", "Montando propostas com o texto desta peça...");
    status.setAttribute("role", "status");
    c.appendChild(status);
    raiz.replaceChildren(c);
  }

  /* re-busca enquanto há preview em fila, e PARA depois. O `/api/state` deles
   * chama ffprobe a cada poll de 2 s; aqui o alvo é um JSON estático. */
  function agendar() {
    if (S.timer) clearTimeout(S.timer);
    if (!S.vivo || !(S.dados?.pendentes > 0)) return;
    S.timer = setTimeout(async () => {
      try {
        const novosDados = await carregar();
        // O arquivo costuma ficar idêntico por vários polls. Remontar nesse caso
        // roubava foco, fechava details e reiniciava os previews sem mudança.
        if (JSON.stringify(novosDados) !== JSON.stringify(S.dados)) {
          S.dados = novosDados;
          desenhar();
        }
      } catch (_) { /* mantém a tela anterior */ }
      agendar();
    }, MS_REBUSCA);
  }

  mostrarCarregando();

  (async () => {
    try {
      S.dados = await carregar();
      S.estado = await carregarEstado();
      semear();
      restaurarRascunho(opcoes.rascunho);
      desenhar();
      agendar();
    } catch (err) {
      falhar(err);
    }
  })();

  return {
    rascunho: rascunhoAtual,
    podeDestruir: () => !S.enviando,
    destruir() {
      S.vivo = false;
      window.removeEventListener("beforeunload", protegerSaidaPendente);
      if (S.timer) clearTimeout(S.timer);
      for (const v of S.tocando) { try { v.pause(); } catch (_) { /* nada */ } }
      S.tocando = [];
      host.innerHTML = "";
    },
  };
}
