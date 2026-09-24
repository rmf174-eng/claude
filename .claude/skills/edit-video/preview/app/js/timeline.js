/* Timeline interativa da UI de aprovação — benchmark.edit-marcacoes/v1.
 *
 * A gutter fixa por sticky + máscara, o guarda de `pointerdown`, a régua em
 * canvas do tamanho da viewport e o zoom ancorado são MECANISMO observado em
 * uma ferramenta de edição de terceiro:
 * assets/preview/app.css:243-268 · app.js:906-937,1452-1500,1570-1577.
 * Nenhum código foi portado. Ver docs/specs/SPEC-18 §10.
 *
 * ESTE ARQUIVO: geometria e desenho. 🔴 A geometria serve para DESENHAR e para
 * BUSCAR. O valor gravado numa marcação é `video.currentTime` (SPEC-18 §3.0) —
 * `t = (x − gutter) / pps` NUNCA vira dado.
 */
import { S, grampear } from './estado.js';

export const LARGURA_GUTTER = 72;      // px de cromo de interface, não de vídeo
const PPS_BASE_MIN = 2, PPS_MAX = 900, FOLGA_FIT = 8;
const PPS_ABSOLUTO_MIN = 0.0001;

export const T = {
  pps: 40,
  painel: null,
  pista: null,
  trilhasEl: null,
  agulha: null,
  regua: null,
  video: null,
  marcaPendente: null,
  aoBuscar: null,        // (t) => void, injetado pelo main
  aoZoom: null,          // (estadoZoom) => void, injetado pelo main
  trilhas: [],           // definições vindas de trilhas.js
  modoZoom: 'fit',
  redesenhoPendente: false,
  rafRegua: 0,
  rafRedesenho: 0,
  rafResize: 0,
  larguraVista: 0,
  observador: null,
  scrollEsperado: null,
  ultimoScrollLeft: 0,
  seguirSuspenso: false,
};

export function iniciar({ painel, pista, trilhasEl, agulha, regua, video, marcaPendente = null }) {
  Object.assign(T, { painel, pista, trilhasEl, agulha, regua, video, marcaPendente });
  T.ultimoScrollLeft = Number(painel?.scrollLeft) || 0;
  document.documentElement.style.setProperty('--gutter', LARGURA_GUTTER + 'px');
  ligarPonteiro();
  ligarZoom();
  painel.addEventListener('scroll', aoRolarPainel, { passive: true });
  if (video && typeof video.addEventListener === 'function') {
    video.addEventListener('play', () => {
      T.seguirSuspenso = false;
      seguirAgulha();
    });
  }
  if (typeof ResizeObserver !== 'undefined') {
    const observador = new ResizeObserver(() => agendarResize());
    observador.observe(painel);
    T.observador = observador;
  } else {
    window.addEventListener('resize', agendarResize);
  }
  lacoDaAgulha();
}

/* ──────────────────────────────────────────────────────────────── geometria */

export function xDeTempo(t) { return LARGURA_GUTTER + t * T.pps; }
export function tempoDeX(x) { return (x - LARGURA_GUTTER) / T.pps; }

export function larguraDaPista() {
  return LARGURA_GUTTER + Math.max(S.dur, 0) * T.pps + FOLGA_FIT;
}

export function aplicarLargura() {
  if (T.pista) T.pista.style.width = larguraDaPista() + 'px';
}

function painelVisivel() {
  return !!T.painel && T.painel.clientWidth > 0;
}

function ppsDeAjuste() {
  if (!painelVisivel() || !(S.dur > 0)) return PPS_BASE_MIN;
  const util = T.painel.clientWidth - LARGURA_GUTTER - FOLGA_FIT;
  if (!(util > 0)) return PPS_BASE_MIN;
  return Math.min(PPS_MAX, Math.max(PPS_ABSOLUTO_MIN, util / S.dur));
}

function maxScroll() {
  if (!T.painel) return 0;
  return Math.max(0, larguraDaPista() - T.painel.clientWidth);
}

function limitarScroll(x) {
  return grampear(Number(x) || 0, 0, maxScroll());
}

function definirScroll(x) {
  const alvo = limitarScroll(x);
  T.painel.scrollLeft = alvo;
  // O browser pode arredondar ou limitar o valor. Guardar o valor efetivamente
  // aplicado separa scroll do motor de zoom de um pan feito pela pessoa.
  T.scrollEsperado = T.painel.scrollLeft;
}

function ancoraDoPlayhead() {
  const painel = T.painel;
  const t = grampear(tempoAtual(), 0, S.dur || 0);
  const xAtual = xDeTempo(t) - painel.scrollLeft;
  const visivel = xAtual >= LARGURA_GUTTER && xAtual <= painel.clientWidth - 16;
  const centro = LARGURA_GUTTER + Math.max(0, painel.clientWidth - LARGURA_GUTTER) / 2;
  return { t, x: visivel ? xAtual : centro };
}

function notificarZoom() {
  if (typeof T.aoZoom === 'function') T.aoZoom(estadoZoom());
}

function aplicarEscala(pps, { tAncora = 0, xAncora = LARGURA_GUTTER,
                              modo = 'manual', inicio = false,
                              imediato = false, preservarEscala = false } = {}) {
  T.modoZoom = modo;
  if (!painelVisivel()) {
    T.redesenhoPendente = true;
    return estadoZoom();
  }
  const piso = preservarEscala && modo === 'manual' ? PPS_ABSOLUTO_MIN : ppsDeAjuste();
  T.pps = grampear(Number(pps) || ppsDeAjuste(), piso, PPS_MAX);
  aplicarLargura();
  definirScroll(inicio ? 0 : xDeTempo(tAncora) - xAncora);
  posicionarIndicadores();
  notificarZoom();
  if (imediato) redesenhar(); else agendarRedesenho();
  return estadoZoom();
}

export function fit({ imediato = false } = {}) {
  T.modoZoom = 'fit';
  if (!painelVisivel()) {
    T.redesenhoPendente = true;
    return estadoZoom();
  }
  return aplicarEscala(ppsDeAjuste(), {
    tAncora: 0, xAncora: LARGURA_GUTTER, modo: 'fit', inicio: true, imediato,
  });
}

/** Zoom ancorado: o instante sob o âncora não se move. `app.js:906-937`. */
export function zoom(fator, ancoraX) {
  if (!painelVisivel() || !(Number(fator) > 0)) return estadoZoom();
  const painel = T.painel;
  const alvoPps = grampear(T.pps * fator, ppsDeAjuste(), PPS_MAX);
  // Um gesto no limite não muda escala e, portanto, também não pode desligar
  // o auto-fit. Sem este no-op, um pinch-out em "Ajustado" trocava o modo para
  // manual e o resize seguinte mantinha uma escala obsoleta.
  if (Math.abs(alvoPps - T.pps) <= Math.max(1, T.pps) * 1e-12) {
    return estadoZoom();
  }
  const xLimitado = ancoraX == null ? null
    : grampear(ancoraX, LARGURA_GUTTER, painel.clientWidth);
  const ancora = xLimitado == null
    ? ancoraDoPlayhead()
    : {
        x: xLimitado,
        t: grampear(tempoDeX(xLimitado + painel.scrollLeft), 0, S.dur || 0),
      };
  return aplicarEscala(alvoPps, {
    tAncora: ancora.t, xAncora: ancora.x, modo: 'manual',
  });
}

function tempoAtual() { return T.video && isFinite(T.video.currentTime) ? T.video.currentTime : 0; }

/* ─────────────────────────────────────────────── a asserção da cadeia do rótulo
 *
 * 🔴 `ref-A/SKILL.md:151-160`: nada na cadeia de ancestrais do rótulo pode ter
 * overflow ≠ visible — o sticky encalha no primeiro contêiner de scroll que
 * encontrar. O sintoma (a gutter "some ao rolar") não parece causado por
 * overflow, então o erro tem que ser LANÇADO no boot, na cara.
 *
 * Corolário que isto impõe ao desenho: a revelação de faixas dobradas anima os
 * BLOCOS, nunca a altura da faixa. Acordeão por `max-height` está proibido.
 */
export function conferirCadeiaDoRotulo() {
  const rotulo = document.querySelector('.trilha-rotulo');
  if (!rotulo) throw new Error('gutter: nenhum .trilha-rotulo no DOM');
  let vistos = 0;
  for (let n = rotulo.parentElement; n && n !== document.body; n = n.parentElement) {
    if (n === T.painel) { vistos++; continue; }
    const ov = getComputedStyle(n);
    vistos++;
    if ([ov.overflow, ov.overflowX, ov.overflowY].some((v) => v !== 'visible')) {
      throw new Error(`gutter encalhada: <${n.tagName.toLowerCase()} class="${n.className}">`
        + ` tem overflow ${ov.overflow} (x:${ov.overflowX} y:${ov.overflowY})`);
    }
  }
  return vistos;                 // quanto foi varrido — verde sem número não vale
}

/* ─────────────────────────────────────────────────────── ponteiro e os guardas
 *
 * 🔴 DOIS guardas, e o segundo é o que sobrevive a refactor. Sem eles o evento
 * cai no ramo de scrub (`app.js:1609-1615`), que puxa a agulha para 0 (a gutter
 * fica à esquerda de t=0, o cálculo dá tempo negativo) e chama
 * `setPointerCapture` no painel, retargando o `click` seguinte e ENGOLINDO o
 * clique real num controle da gutter. Diagnóstico confuso: `.click()`
 * programático funciona enquanto o dedo do usuário não.
 */
function ligarPonteiro() {
  const painel = T.painel;
  let arrastando = false;
  let ponteiroAtivo = null;
  let candidatoToque = null;
  let multitoque = false;
  const toquesAtivos = new Set();
  const LIMIAR_TOQUE = 6;

  const sobreBarraDeRolagem = (e) => {
    const r = painel.getBoundingClientRect();
    const estilo = getComputedStyle(painel);
    const bordaEsq = Number.parseFloat(estilo.borderLeftWidth) || 0;
    const bordaDir = Number.parseFloat(estilo.borderRightWidth) || 0;
    const bordaTopo = Number.parseFloat(estilo.borderTopWidth) || 0;
    const bordaBase = Number.parseFloat(estilo.borderBottomWidth) || 0;
    const faixaCss = Number.parseFloat(
      estilo.getPropertyValue?.('--scrollbar-timeline') || '',
    ) || 0;
    const faixaVertical = Math.max(faixaCss,
      (painel.offsetWidth || 0) - painel.clientWidth - bordaEsq - bordaDir);
    const faixaHorizontal = Math.max(faixaCss,
      (painel.offsetHeight || 0) - painel.clientHeight - bordaTopo - bordaBase);
    const temVertical = painel.scrollHeight > painel.clientHeight + 1;
    const temHorizontal = painel.scrollWidth > painel.clientWidth + 1;
    return (temVertical && faixaVertical > 0
        && e.clientX >= r.right - bordaDir - faixaVertical)
      || (temHorizontal && faixaHorizontal > 0
        && e.clientY >= r.bottom - bordaBase - faixaHorizontal);
  };

  const encerrarArrasto = (pointerId = ponteiroAtivo) => {
    if (!arrastando || pointerId !== ponteiroAtivo) return;
    arrastando = false;
    ponteiroAtivo = null;
    try { painel.releasePointerCapture(pointerId); } catch (_) { /* já solto */ }
  };

  const iniciarArrasto = (e) => {
    painel.focus({ preventScroll: true });
    arrastando = true;
    ponteiroAtivo = e.pointerId;
    T.seguirSuspenso = false;
    painel.setPointerCapture(e.pointerId);
    buscarPor(e);
  };

  painel.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (e.pointerType === 'touch') {
      toquesAtivos.add(e.pointerId);
      if (toquesAtivos.size > 1) {
        multitoque = true;
        candidatoToque = null;
        encerrarArrasto();
        return;
      }
    }
    if (e.target.closest('.trilha-rotulo, button, input, select, textarea, a')) return;
    if (sobreBarraDeRolagem(e)) return;
    const r = painel.getBoundingClientRect();
    const x = e.clientX - r.left;
    if (x < LARGURA_GUTTER) return;
    if (e.pointerType === 'touch') {
      // Não buscar no pointerdown: o mesmo início pode virar um pan vertical.
      // Um tap busca no pointerup; um movimento horizontal começa o scrub após
      // o limiar; um movimento vertical fica integralmente com o navegador.
      multitoque = false;
      candidatoToque = {
        pointerId: e.pointerId,
        x: e.clientX,
        y: e.clientY,
      };
      return;
    }
    iniciarArrasto(e);
  });
  painel.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'touch' && candidatoToque?.pointerId === e.pointerId) {
      const dx = e.clientX - candidatoToque.x;
      const dy = e.clientY - candidatoToque.y;
      if (Math.abs(dy) > LIMIAR_TOQUE && Math.abs(dy) > Math.abs(dx)) {
        candidatoToque = null;
        return;
      }
      if (Math.abs(dx) > LIMIAR_TOQUE && Math.abs(dx) >= Math.abs(dy)) {
        candidatoToque = null;
        iniciarArrasto(e);
        return;
      }
    }
    if (arrastando && e.pointerId === ponteiroAtivo) buscarPor(e);
  });
  const soltar = (e, cancelado = false) => {
    if (e.pointerType === 'touch') {
      const eraCandidato = candidatoToque?.pointerId === e.pointerId;
      if (eraCandidato) candidatoToque = null;
      if (!cancelado && eraCandidato && !multitoque) {
        painel.focus({ preventScroll: true });
        buscarPor(e);
      }
      toquesAtivos.delete(e.pointerId);
      if (toquesAtivos.size === 0) multitoque = false;
    }
    encerrarArrasto(e.pointerId);
  };
  painel.addEventListener('pointerup', soltar);
  painel.addEventListener('pointercancel', (e) => soltar(e, true));
}

function buscarPor(e) {
  const painel = T.painel;
  /* 🔴 H49-9 (bug report F48-1: "o slider buga com zoom"). A gutter é STICKY:
   * ela flutua sobre o conteúdo na borda esquerda da VIEWPORT. Sem zoom
   * `scrollLeft` é 0 e a conta fecha; com zoom e a pista rolada, arrastar a
   * agulha para a esquerda passa o ponteiro POR BAIXO da gutter, e
   * `x + scrollLeft` devolve um instante ANTERIOR ao primeiro visível — a agulha
   * desaparece atrás da gutter e o tempo deixa de acompanhar o dedo.
   *
   * O conserto é a mesma conta que o `seguirAgulha` já fazia do outro lado:
   * o menor x utilizável é `LARGURA_GUTTER` em coordenada de viewport. */
  const xViewport = e.clientX - painel.getBoundingClientRect().left;
  const x = Math.max(xViewport, LARGURA_GUTTER) + painel.scrollLeft;
  const t = grampear(tempoDeX(x), 0, S.dur || 0);
  if (T.aoBuscar) T.aoBuscar(t);
}

/** O zoom como VALOR, para o slider: 0..1 entre `fit` e 900 px/s, em log.
 *  O piso acompanha painel e duração: 0 sempre significa peça inteira visível,
 *  inclusive em longform. */
export function zoomNormalizado() {
  const minimo = ppsDeAjuste();
  if (minimo >= PPS_MAX) return 0;
  const a = Math.log(minimo), b = Math.log(PPS_MAX);
  return (Math.log(grampear(T.pps, minimo, PPS_MAX)) - a) / (b - a);
}

export function aplicarZoomNormalizado(v) {
  const normalizado = grampear(Number(v) || 0, 0, 1);
  if (normalizado <= 0) return fit();
  const minimo = ppsDeAjuste();
  const a = Math.log(minimo), b = Math.log(PPS_MAX);
  const alvo = Math.exp(a + normalizado * (b - a));
  return zoom(alvo / T.pps);
}

export function estadoZoom() {
  const minimo = ppsDeAjuste();
  const relativo = minimo > 0 ? T.pps / minimo : 1;
  return {
    pps: T.pps,
    minimo,
    maximo: PPS_MAX,
    relativo,
    normalizado: zoomNormalizado(),
    modo: T.modoZoom,
    noMinimo: T.pps <= minimo * (1 + 1e-9),
    noMaximo: T.pps >= PPS_MAX * (1 - 1e-9),
  };
}

function deltaEmPixels(e) {
  if (e.deltaMode === 1) return e.deltaY * 16;
  if (e.deltaMode === 2) return e.deltaY * Math.max(T.painel?.clientHeight || 0, 1);
  return e.deltaY;
}

function ligarZoom() {
  T.painel.addEventListener('wheel', (e) => {
    // Pinça de trackpad chega como wheel+ctrlKey. Meta+wheel continua livre para
    // o navegador e para tecnologias assistivas.
    if (!e.ctrlKey || !painelVisivel()) return;
    e.preventDefault();
    const x = e.clientX - T.painel.getBoundingClientRect().left;
    zoom(Math.exp(-deltaEmPixels(e) / 260), Math.max(x, LARGURA_GUTTER));
  }, { passive: false });
}

/* ───────────────────────────────────────────────────────────────── a agulha */

export function posicionarIndicadores() {
  const t = tempoAtual();
  if (T.agulha) T.agulha.style.left = xDeTempo(t) + 'px';
  if (T.marcaPendente && S.inPendente != null) {
    T.marcaPendente.style.left = xDeTempo(S.inPendente) + 'px';
  }
}

function lacoDaAgulha() {
  let ultimo = -1, ultimaEscala = -1;
  const passo = () => {
    const t = tempoAtual();
    if (t !== ultimo || T.pps !== ultimaEscala) {
      const tempoMudou = t !== ultimo;
      ultimo = t;
      ultimaEscala = T.pps;
      posicionarIndicadores();
      if (tempoMudou && T.aoTempo) T.aoTempo(t);
      if (tempoMudou && T.video && !T.video.paused) seguirAgulha();
    }
    requestAnimationFrame(passo);
  };
  requestAnimationFrame(passo);
}

/** Traz a agulha para dentro da viewport quando ela sai andando. */
export function seguirAgulha() {
  if (T.seguirSuspenso) return false;
  const painel = T.painel;
  const x = xDeTempo(tempoAtual());
  const esq = painel.scrollLeft + LARGURA_GUTTER;
  const dir = painel.scrollLeft + painel.clientWidth;
  if (x < esq || x > dir - 24) {
    definirScroll(x - painel.clientWidth / 2);
  }
  return true;
}

/* ─────────────────────────────────────────────────────── a régua em canvas
 *
 * Canvas do tamanho da VIEWPORT, sticky à esquerda, redesenhado no scroll — em
 * vez de um canvas do tamanho da pista inteira, que a 900 px/s de zoom seria um
 * bitmap de dezenas de milhares de pixels.
 */
export function desenharRegua() {
  const cv = T.regua, painel = T.painel;
  if (!cv || !painel || !painelVisivel()) {
    T.redesenhoPendente = true;
    return;
  }
  const larg = painel.clientWidth, alt = 26;
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(larg * dpr) || cv.height !== Math.round(alt * dpr)) {
    cv.width = Math.round(larg * dpr);
    cv.height = Math.round(alt * dpr);
    cv.style.width = larg + 'px';
    cv.style.height = alt + 'px';
  }
  const g = cv.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  // ⚠️ cores RESOLVIDAS (rgb) do DOM. `getPropertyValue('--painel')` devolve o
  // texto `color-mix(...)`, que o canvas 2D ignora em silêncio — e o rótulo
  // ficaria pintado com a cor anterior sem nada acusar.
  const tinta = getComputedStyle(document.body).color;
  const fundoPainel = getComputedStyle(painel).backgroundColor;
  g.clearRect(0, 0, larg, alt);

  const passo = passoDaRegua(T.pps);
  const t0 = Math.max(0, tempoDeX(painel.scrollLeft));
  const t1 = tempoDeX(painel.scrollLeft + larg);
  g.strokeStyle = tinta;
  g.fillStyle = tinta;
  g.globalAlpha = S.reguaExata ? 0.75 : 0.45;
  g.font = '10px ui-monospace, Menlo, monospace';
  g.beginPath();
  for (let t = Math.floor(t0 / passo) * passo; t <= t1; t += passo) {
    if (t < 0) continue;
    const x = Math.round(xDeTempo(t) - painel.scrollLeft) + 0.5;
    if (x < LARGURA_GUTTER) continue;
    g.moveTo(x, alt - 7); g.lineTo(x, alt);
    g.fillText(rotuloDeTempo(t, passo), x + 3, 11);
  }
  g.stroke();

  // a gutter da régua: máscara + o mesmo divisor do rótulo
  g.globalAlpha = 1;
  g.fillStyle = fundoPainel;
  g.fillRect(0, 0, LARGURA_GUTTER, alt);
  g.globalAlpha = 0.3;
  g.strokeStyle = tinta;
  g.beginPath();
  g.moveTo(LARGURA_GUTTER - 0.5, 0); g.lineTo(LARGURA_GUTTER - 0.5, alt);
  g.stroke();
  if (!S.reguaExata) {
    g.globalAlpha = 0.5; g.fillStyle = tinta;
    g.fillText('~', 6, 11);
  }
}

function passoDaRegua(pps) {
  const candidatos = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
  for (const c of candidatos) if (c * pps >= 56) return c;
  return candidatos[candidatos.length - 1];
}

function rotuloDeTempo(t, passo) {
  const m = Math.floor(t / 60), s = t - m * 60;
  if (passo < 1) return `${m}:${s.toFixed(1).padStart(4, '0')}`;
  return `${m}:${String(Math.round(s)).padStart(2, '0')}`;
}

/* ─────────────────────────────────────────────────────── redesenho das faixas */

function agendarRegua() {
  if (T.rafRegua) return;
  T.rafRegua = requestAnimationFrame(() => {
    T.rafRegua = 0;
    desenharRegua();
    for (const tr of T.trilhas) if (tr.aoRolar) tr.aoRolar();
  });
}

function aoRolarPainel() {
  const atual = Number(T.painel.scrollLeft) || 0;
  const mudouHorizontal = Math.abs(atual - T.ultimoScrollLeft) > 0.5;
  const esperado = T.scrollEsperado;
  const programatico = esperado != null
    && Math.abs(atual - esperado) <= 1;
  T.scrollEsperado = null;
  T.ultimoScrollLeft = atual;
  if (mudouHorizontal && !programatico && T.video && !T.video.paused) {
    T.seguirSuspenso = true;
  }
  agendarRegua();
}

function agendarRedesenho() {
  if (T.rafRedesenho) return;
  T.rafRedesenho = requestAnimationFrame(() => {
    T.rafRedesenho = 0;
    redesenhar();
  });
}

function agendarResize() {
  if (T.rafResize) return;
  T.rafResize = requestAnimationFrame(() => {
    T.rafResize = 0;
    aoMostrar();
  });
}

export function aoMostrar() {
  if (!painelVisivel()) {
    T.redesenhoPendente = true;
    return false;
  }
  const larguraMudou = T.larguraVista !== T.painel.clientWidth;
  T.larguraVista = T.painel.clientWidth;
  if (T.modoZoom === 'fit') {
    aplicarEscala(ppsDeAjuste(), {
      tAncora: 0, xAncora: LARGURA_GUTTER, modo: 'fit', inicio: true, imediato: true,
    });
  } else if (larguraMudou || T.redesenhoPendente) {
    const ancora = ancoraDoPlayhead();
    aplicarEscala(T.pps, {
      tAncora: ancora.t, xAncora: ancora.x, modo: 'manual', imediato: true,
      preservarEscala: true,
    });
  } else {
    redesenhar();
    notificarZoom();
  }
  T.redesenhoPendente = false;
  return true;
}

export function redesenhar() {
  if (T.rafRedesenho) {
    cancelAnimationFrame(T.rafRedesenho);
    T.rafRedesenho = 0;
  }
  if (!painelVisivel()) {
    T.redesenhoPendente = true;
    return false;
  }
  if (T.modoZoom === 'fit') T.pps = ppsDeAjuste();
  else T.pps = grampear(T.pps, PPS_ABSOLUTO_MIN, PPS_MAX);
  T.larguraVista = T.painel.clientWidth;
  aplicarLargura();
  posicionarIndicadores();
  desenharRegua();
  for (const tr of T.trilhas) if (tr.redesenhar) tr.redesenhar();
  T.redesenhoPendente = false;
  return true;
}

export function reconstruir() {
  S.contadores.renderAll++;
  window.__renderAll = S.contadores.renderAll;
  T.trilhasEl.textContent = '';
  for (const tr of T.trilhas) T.trilhasEl.appendChild(tr.montar());
  aplicarLargura();
  posicionarIndicadores();
  if (painelVisivel()) desenharRegua();
  else T.redesenhoPendente = true;
}
