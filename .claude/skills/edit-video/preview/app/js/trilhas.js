/* Timeline interativa da UI de aprovação — benchmark.edit-marcacoes/v1.
 *
 * "Uma trilha por TIPO, e o que fica em código simplesmente não aparece" é
 * MECANISMO observado em uma ferramenta de edição de terceiro: SKILL.md:135-145 · app.js:1329-1420,1870-1877.
 * Nenhum código foi portado. Ver docs/specs/SPEC-18 §10.
 *
 * ESTE ARQUIVO: as trilhas por tipo. 🔴 Trilha sem dado desenha uma faixa
 * HACHURADA dizendo o que falta — nunca uma faixa vazia. Uma faixa vazia mente;
 * a hachurada é um argumento a favor de mover aquilo para dado.
 */
import { S } from './estado.js';
import { T, LARGURA_GUTTER, desenharRegua } from './timeline.js';

/* Espelha o enum de `digest-marcacoes.py` (SPEC-18 §4.2). Atualizar os dois juntos. */
export const TRILHAS = ['corte', 'audio', 'legenda', 'enquadramento', 'falante',
  'grafico', 'broll', 'insert', 'sfx', 'trilha-sonora', 'geral'];

const CHAVE_DOBRA = 'preview:dobras';

function el(tag, classe, pai) {
  const n = document.createElement(tag);
  if (classe) n.className = classe;
  if (pai) pai.appendChild(n);
  return n;
}

function dobrasSalvas() {
  try { return JSON.parse(localStorage.getItem(CHAVE_DOBRA) || '{}'); } catch (_) { return {}; }
}
function salvarDobra(id, aberto) {
  const d = dobrasSalvas(); d[id] = aberto;
  try { localStorage.setItem(CHAVE_DOBRA, JSON.stringify(d)); } catch (_) { /* modo privado */ }
}

/** O esqueleto de uma trilha: rótulo na gutter (sticky) + faixas. */
function moldura(def) {
  const raiz = el('div', 'trilha' + (def.vazia ? ' trilha-vazia' : ''));
  raiz.dataset.trilha = def.id;
  const rot = el('div', 'trilha-rotulo', raiz);
  if (def.dobras && def.dobras.length) {
    const b = el('button', 'caret', rot);
    b.type = 'button';
    const aberto = () => !!dobrasSalvas()[def.id];
    const pinta = () => {
      const estaAberto = aberto();
      b.textContent = estaAberto ? '▾' : '▸';
      b.setAttribute('aria-expanded', String(estaAberto));
      b.setAttribute('aria-label', `${estaAberto ? 'Recolher' : 'Expandir'} detalhes de ${def.rotulo}`);
    };
    b.addEventListener('click', () => {
      salvarDobra(def.id, !aberto());
      pinta();
      def.aplicarDobra(raiz, aberto());
    });
    pinta();
  }
  const nome = el('span', null, rot);
  nome.textContent = def.rotulo;
  const faixas = el('div', 'faixas', raiz);
  return { raiz, faixas };
}

/* A frase da FRENTE é para quem está aprovando o corte; o motivo técnico vai no
 * `title=`. Medido na tela em 2026-08-11: 4 das 8 trilhas abriam com nome de
 * script e a palavra "sidecar" — a primeira coisa que o creator lia na peça dele
 * era o vocabulário de quem escreveu a ferramenta. A declaração de ausência
 * continua ALTA (a faixa hachurada não mudou): o que mudou é a língua. */
function faixaSemDado(faixas, texto, tecnico) {
  const f = el('div', 'faixa sem-dado', faixas);
  const s = el('span', null, f);
  s.textContent = texto;
  if (tecnico) { s.title = tecnico; f.title = tecnico; }
  return f;
}

/** Posiciona por tempo dentro de `.faixas` (a origem já é t=0: a gutter é o rótulo). */
function porTempo(n, ini, dur) {
  n.style.left = (ini * T.pps) + 'px';
  n.style.width = Math.max(2, dur * T.pps) + 'px';
}

/* ───────────────────────────────────────────────────────────── vídeo + strip */

function trilhaVideo() {
  const def = {
    id: 'video', rotulo: 'vídeo',
    dobras: ['enquadramento', 'falante'],
    blocos: [], faixaEnq: null, faixaQuem: null,
  };
  def.montar = () => {
    const { raiz, faixas } = moldura(def);
    const f = el('div', 'faixa', faixas);
    def.blocos = [];
    for (const s of S.segmentos) {
      const b = el('div', 'bloco', f);
      b.dataset.i = s.i;
      b.title = `${s.sid || 'seg ' + s.i} · ${s.src || ''} ${s.start ?? ''}→${s.end ?? ''}`;
      const tira = el('div', 'tira', b);
      const rot = el('div', 'rotulo', b);
      rot.textContent = s.beat || s.sid || ('seg ' + s.i);
      def.blocos.push({ s, b, tira });
    }
    def.faixaEnq = el('div', 'faixa', faixas);
    def.faixaQuem = el('div', 'faixa', faixas);
    def.faixaEnq.dataset.dobra = 'enquadramento';
    def.faixaQuem.dataset.dobra = 'falante';
    for (const s of S.segmentos) {
      const z = el('div', 'bloco zoom', def.faixaEnq);
      const r = el('div', 'rotulo', z);
      r.textContent = s.zoom != null ? `${Number(s.zoom).toFixed(2).replace('.', ',')}×` : '--';
      z.dataset.i = s.i;
      const q = el('div', 'bloco quem-' + (s.quem || 'geral'), def.faixaQuem);
      const rq = el('div', 'rotulo', q);
      rq.textContent = s.quem || '--';
      q.dataset.i = s.i;
    }
    def.aplicarDobra(raiz, !!dobrasSalvas()[def.id]);
    return raiz;
  };
  /* 🔴 A revelação anima os BLOCOS, nunca a altura da faixa: acordeão por
     `max-height` cria contêiner de scroll e encalha a gutter (§3.3). */
  def.aplicarDobra = (raiz, aberto) => {
    for (const f of raiz.querySelectorAll('[data-dobra]')) f.hidden = !aberto;
  };
  def.redesenhar = () => {
    for (const { s, b } of def.blocos) porTempo(b, s.ini, s.dur);
    for (const f of [def.faixaEnq, def.faixaQuem]) {
      if (!f) continue;
      for (const n of f.children) porTempo(n, S.segmentos[+n.dataset.i].ini,
        S.segmentos[+n.dataset.i].dur);
    }
    desenharStrip(def);
  };
  def.temConteudoEm = () => S.segmentos.length > 0;
  return def;
}

/**
 * 🔴 O bug do ref-A, e a única linha que importa: cada thumb é posicionada pelo
 * TEMPO QUE ELA RETRATA, nunca empilhada em flex a partir da borda do clipe.
 *
 * `app.js:1297-1308` faz `first = floor(clipe.out / THUMB_EVERY)` e joga a tira
 * num flex `inset:0` (`app.css:357`): a primeira imagem é pintada na borda
 * esquerda do clipe, que é o instante `clipe.out`, enquanto a imagem retrata
 * `(first)×2`. A defasagem vale [0, intervalo) e é diferente em cada clipe.
 *
 * Aqui a defasagem é ≤ intervalo/2 POR CONSTRUÇÃO — é resolução de amostragem,
 * não desalinhamento.
 */
function desenharStrip(def) {
  const meta = S.strip;
  for (const { s, tira } of def.blocos) {
    if (!meta || meta.estado !== 'pronto') {           // §3.8: gerando → 404 por design
      if (tira.childElementCount) tira.textContent = '';
      continue;
    }
    const { n, intervalo, t0 } = meta;
    const kIni = Math.max(1, Math.floor((s.ini - t0) / intervalo) + 1);
    const kFim = Math.min(n, Math.ceil((s.ini + s.dur - t0) / intervalo) + 1);
    const querido = `${kIni}:${kFim}:${S.chave}`;
    if (tira.dataset.faixa !== querido) {
      tira.textContent = '';
      tira.dataset.faixa = querido;
      for (let k = kIni; k <= kFim; k++) {
        const img = el('img', 'thumb', tira);
        img.loading = 'lazy';
        img.decoding = 'async';
        img.dataset.k = k;
        img.src = `gen/${S.chave}/thumbs/${String(k).padStart(4, '0')}.jpg`;
      }
    }
    for (const img of tira.children) {
      const k = +img.dataset.k;
      const tk = t0 + (k - 1) * intervalo;             // o instante RETRATADO
      img.style.left = ((rascunhoDe(tk - intervalo / 2) - s.ini) * T.pps) + 'px';
      img.style.width = (intervalo * T.pps) + 'px';    // o balde que ela representa
    }
  }
}

/** No MVP a timeline de rascunho É a do render (§3.0). B2 troca só esta função. */
function rascunhoDe(tRender) { return tRender; }

/* ───────────────────────────────────────────────────────────────── áudio */

function trilhaAudio() {
  const def = { id: 'audio', rotulo: 'áudio', cv: null };
  def.montar = () => {
    const { raiz, faixas } = moldura(def);
    const f = el('div', 'faixa', faixas);
    if (!S.onda) {
      f.remove();
      def.cv = null;
      faixaSemDado(faixas, S.bruto?.midia?.waveform?.estado === 'ausente'
        ? 'este render não tem faixa de áudio'
        : 'desenhando a onda do áudio…',
        'waveform.json em geração pelo servidor de preview');
    } else {
      def.cv = el('canvas', null, f);
      def.cv.style.position = 'sticky';
      def.cv.style.left = '0';
    }
    return raiz;
  };
  def.redesenhar = def.aoRolar = () => {
    const cv = def.cv, onda = S.onda;
    if (!cv || !onda) return;
    const painel = T.painel;
    const larg = Math.max(1, painel.clientWidth - LARGURA_GUTTER);
    const alt = cv.parentElement.clientHeight || 34;
    const dpr = window.devicePixelRatio || 1;
    cv.style.width = larg + 'px'; cv.style.height = alt + 'px';
    if (cv.width !== Math.round(larg * dpr)) { cv.width = Math.round(larg * dpr); }
    if (cv.height !== Math.round(alt * dpr)) { cv.height = Math.round(alt * dpr); }
    const g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, larg, alt);
    // o pista-x da borda esquerda do canvas — vale com ou sem o sticky ativo
    const x0 = cv.getBoundingClientRect().left - painel.getBoundingClientRect().left
      + painel.scrollLeft - LARGURA_GUTTER;
    const meio = alt / 2, dur = onda.dur || S.dur || 1, n = onda.min.length;
    g.fillStyle = getComputedStyle(document.body).color;
    g.globalAlpha = 0.65;
    for (let px = 0; px < larg; px++) {
      const t = (x0 + px) / T.pps;
      if (t < 0 || t > dur) continue;
      const i = Math.min(n - 1, Math.max(0, Math.floor(t / dur * n)));
      const y0 = meio - (onda.max[i] / 100) * meio;
      const y1 = meio - (onda.min[i] / 100) * meio;
      g.fillRect(px, y0, 1, Math.max(1, y1 - y0));
    }
  };
  def.temConteudoEm = () => !!S.onda;
  return def;
}

/* ─────────────────────────────────────────────────────────────── legenda */

function trilhaLegenda() {
  const def = { id: 'legenda', rotulo: 'legenda', nos: [] };
  def.montar = () => {
    const { raiz, faixas } = moldura(def);
    const caps = S.legendas || [];
    def.nos = [];
    if (!caps.length) {
      faixaSemDado(faixas, 'esta peça ainda não tem legenda',
        'sem captions.json na produção (nem arquivo nomeado em estado.legendas)');
      return raiz;
    }
    const f = el('div', 'faixa', faixas);
    // 🔴 uma marca por PALAVRA, que é o que o dado é. Página é decisão do
    // diretor de legenda (SPEC-14, partitura.json) — inventar aqui uma
    // paginação por janela fixa seria a QUARTA cópia dessa regra no repo.
    for (const w of caps) {
      const b = el('div', 'bloco legenda', f);
      const r = el('div', 'rotulo', b);
      r.textContent = (w.text || '').trim();
      b.title = r.textContent;
      def.nos.push({ w, b });
    }
    return raiz;
  };
  def.redesenhar = () => {
    for (const { w, b } of def.nos) porTempo(b, w.startMs / 1000, (w.endMs - w.startMs) / 1000);
  };
  def.temConteudoEm = (ini, fim) => (S.legendas || []).some(
    (w) => w.endMs / 1000 >= ini && w.startMs / 1000 <= fim);
  return def;
}

/* ─────────────────────────────────── o que hoje vive em CÓDIGO, não em dado */

function trilhaSemDado(id, rotulo, texto, tecnico) {
  const def = { id, rotulo, vazia: true };
  def.montar = () => {
    const { raiz, faixas } = moldura(def);
    faixaSemDado(faixas, texto, tecnico);
    return raiz;
  };
  def.redesenhar = () => { };
  def.temConteudoEm = () => false;
  return def;
}

export function padrao() {
  return [
    trilhaVideo(),
    trilhaAudio(),
    trilhaLegenda(),
    trilhaSemDado('grafico', 'gráficos',
      'os cartões e textos na tela entram na Fase 2',
      'os cartões/overlays vivem em TSX com o tempo na prop — não editáveis aqui '
      + '(overlays.json.cards vazio)'),
    trilhaSemDado('broll', 'b-roll',
      'as imagens de apoio entram na Fase 2',
      'split-broll.py é CLI e não deixa sidecar — sem janela para desenhar'),
    trilhaSemDado('insert', 'inserts',
      'as cenas inseridas entram na Fase 2',
      'omni-insert/encaixar.py é CLI e não deixa sidecar — sem janela para desenhar'),
    trilhaSemDado('sfx', 'SFX/trilha',
      'os efeitos de som e a trilha entram na Fase 2',
      'SFX e trilha vivem no TSX e em scripts de produção — sem dado por janela'),
  ];
}

/** As trilhas que REALMENTE têm conteúdo na janela — nunca uma lista de opções
 *  inexistentes (§3.4). */
export function comConteudoEm(ini, fim) {
  const saida = [];
  for (const tr of T.trilhas) {
    if (tr.id === 'marcacoes') continue;
    if (tr.temConteudoEm && tr.temConteudoEm(ini, fim)) saida.push(tr.id);
  }
  if (saida.includes('video')) {
    saida.splice(saida.indexOf('video'), 1, 'corte');
    const s = S.segmentos.find((g) => g.ini <= fim && g.ini + g.dur >= ini);
    if (s && s.zoom != null && s.zoom !== 1) saida.push('enquadramento');
    if (s && s.quem) saida.push('falante');
  }
  return saida;
}
