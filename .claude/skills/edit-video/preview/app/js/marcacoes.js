/* Timeline interativa da UI de aprovação — benchmark.edit-marcacoes/v1.
 *
 * ⭐⭐ O NÚCLEO: marcar IN e OUT e escrever a instrução do momento.
 *
 * Marcar IN/OUT com uma nota, a caixa centrada sobre o painel e clampada na
 * janela, e descartar a marcação nova sem texto são MECANISMO observado em
 * uma ferramenta de edição de terceiro:
 * assets/preview/app.js:981-1035 · SKILL.md:162-166. Nenhum código foi portado.
 * Ver docs/specs/SPEC-18 §10.
 *
 * 🔴 A COORDENADA VEM DO PLAYER, NUNCA DA GEOMETRIA DA TIMELINE (§3.0). A agulha
 * é um desenho; o tempo é do `video.currentTime`. É isso que faz a marcação sair
 * exata mesmo com a régua aproximada (Σ(end−start) erra 316,7 ms no fim da
 * peca-01) e é o que permite esta app existir sem SPEC-00 e sem SPEC-05.
 */
import { S, mmss, grampear } from './estado.js';
import { T, xDeTempo } from './timeline.js';
import { comConteudoEm, TRILHAS } from './trilhas.js';
import { abrirModal, fecharModal } from './modal.js';

const CONTRATO = 'benchmark.edit-marcacoes/v1';
const APP = 'preview/app v1';

let caixa, txt, chips, coord, titulo, torradeira, marcaPendente;
let editando = null;      // a marcação cuja caixa está aberta
let aoMudar = () => { };

export function iniciar(nos) {
  ({ caixa, txt, chips, coord, titulo, torradeira, marcaPendente } = nos);
  aoMudar = nos.aoMudar || aoMudar;
  nos.btnSalvarNota.addEventListener('click', () => confirmar());
  nos.btnCancelarNota.addEventListener('click', () => fechar(true));
  txt.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); confirmar(); }
    if (e.key === 'Escape') { e.preventDefault(); fechar(true); }
  });
}

/* ───────────────────────────────────────────────────────── IN / OUT (§3.4) */

function agora() {
  const v = T.video;
  return v && isFinite(v.currentTime) ? v.currentTime : 0;
}

export function marcarIn() {
  S.inPendente = agora();
  marcaPendente.hidden = false;
  reposicionarInPendente();
  aoMudar();
}

/** Reprojeta o IN aberto depois de qualquer mudanca de escala. */
export function reposicionarInPendente() {
  if (!marcaPendente || S.inPendente == null) return;
  marcaPendente.style.left = xDeTempo(S.inPendente) + 'px';
}

export function cancelarIn() {
  if (S.inPendente == null) return false;
  S.inPendente = null;
  marcaPendente.hidden = true;
  aoMudar();
  torrar('IN cancelado');
  return true;
}

export function marcarOut() {
  if (S.inPendente == null) { marcarIn(); return; }
  const a = S.inPendente, b = agora();
  S.inPendente = null;
  marcaPendente.hidden = true;
  const dur = S.dur || 0;
  let ini = grampear(Math.min(a, b), 0, dur);
  let fim = grampear(Math.max(a, b), 0, dur);
  const invertido = b < a;
  // 🔴 duração abaixo de 1 frame vira PONTO, e é salva. O ref-A RECUSA abaixo de
  // 0,05 s (`app.js:991-994`) e perde a intenção — "aqui falta um cartão" é
  // pedido legítimo, não erro de dedo.
  const umFrame = S.fmt?.fps ? 1 / S.fmt.fps : 1 / 30;
  const ponto = (fim - ini) < umFrame;
  if (ponto) fim = ini;
  if (invertido) torrar('intervalo invertido — corrigido');
  const m = {
    id: 'm' + Date.now() + '-' + (S.marcacoes.length + 1),
    tipo: ponto ? 'ponto' : 'intervalo',
    fase: S.bruto?.estado?.fase ?? 1,
    trilha: null, ref: null,
    ini, fim, texto: '',
    marcado_invertido: invertido,
    enviada: false, enviadaEm: null,
    novo: true,
  };
  abrir(m);
}

export function alternarMarca() {
  if (S.inPendente == null) marcarIn(); else marcarOut();
}

/* ────────────────────────────────────────────────────────── a caixa de nota */

/** Centrada sobre o painel da timeline e CLAMPADA na janela (`app.js:1010-1024`). */
function posicionar() {
  const r = T.painel.getBoundingClientRect();
  caixa.hidden = false;
  const cw = caixa.offsetWidth, ch = caixa.offsetHeight;
  const x = grampear(r.left + r.width / 2 - cw / 2, 8, window.innerWidth - cw - 8);
  const y = grampear(r.top + r.height / 2 - ch / 2, 8, window.innerHeight - ch - 8);
  caixa.style.left = x + 'px';
  caixa.style.top = y + 'px';
}

function abrir(m) {
  editando = m;
  titulo.textContent = m.tipo === 'ponto' ? 'marcação de ponto' : 'marcação';
  coord.textContent = m.tipo === 'ponto'
    ? mmss(m.ini)
    : `${mmss(m.ini)} → ${mmss(m.fim)} (${(m.fim - m.ini).toFixed(3).replace('.', ',')} s)`;
  txt.value = m.texto || '';
  montarChips(m);
  posicionar();
  abrirModal(caixa, { foco: txt, fallback: T.video, aoEscape: () => fechar(true) });
  txt.select();
  aoMudar();
}

function montarChips(m) {
  chips.textContent = '';
  const presentes = comConteudoEm(m.ini, m.fim).filter((x) => TRILHAS.includes(x));
  const rot = document.createElement('span');
  rot.className = 'fraco';
  rot.textContent = presentes.length ? 'sobre:' : 'nenhuma trilha com dado nesta janela';
  chips.appendChild(rot);
  for (const id of presentes) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = id;
    b.setAttribute('aria-pressed', String(m.trilha === id));
    b.addEventListener('click', () => {
      m.trilha = (m.trilha === id) ? null : id;   // nenhuma seleção é estado válido
      montarChips(m);
      txt.focus();
    });
    chips.appendChild(b);
  }
}

function confirmar() {
  if (!editando) return;
  const t = txt.value.trim();
  if (!t) { torrar('a marcação precisa de um pedido — texto é obrigatório'); txt.focus(); return; }
  editando.texto = t;
  if (editando.novo) { delete editando.novo; S.marcacoes.push(editando); }
  fechar(false);
  salvarRascunho();
}

function fechar(descartar) {
  if (descartar && editando && editando.novo) {
    // marcação sem pedido não é dado (`app.js:1027-1035`)
    torrar('marcação descartada');
  }
  editando = null;
  caixa.hidden = true;
  // 🔴 `video.focus()` NÃO tira o foco de um <video> sem `tabindex` — e o foco
  // ficava preso no textarea ESCONDIDO, onde o guarda de foco de `main.js`
  // engole todo atalho. Sintoma: salva a primeira nota e M/I/O param de
  // funcionar, sem erro nenhum. Medido no navegador em 2026-08-09.
  txt.blur();
  fecharModal(caixa);
  aoMudar();
}

export function caixaAberta() { return !caixa.hidden; }
export function fecharCaixa() { fechar(true); }

/* ───────────────────────────────────────────────────────────── a trilha */

export function trilha() {
  const def = { id: 'marcacoes', rotulo: '⭐ marcas', faixas: null };
  let renderizados = null;

  function estadoVisual(m) {
    return [m.id, m.tipo, m.ini, m.fim, m.texto, m.enviada, m.enviadaEm,
      m.aplicada].map((v) => String(v ?? '')).join('\u0000');
  }

  function planejar() {
    const pistas = [];
    return [...S.marcacoes].sort((a, b) => a.ini - b.ini).map((m) => {
      let faixa = pistas.findIndex((fimAnterior) => m.ini >= fimAnterior);
      if (faixa < 0) { faixa = pistas.length; pistas.push(0); }
      pistas[faixa] = Math.max(m.fim, m.ini) + 0.001;
      return { m, faixa, estado: estadoVisual(m), no: null };
    });
  }

  function posicionarMarca(no, m) {
    no.style.left = (m.ini * T.pps) + 'px';
    if (m.tipo === 'ponto') no.style.removeProperty('width');
    else no.style.width = Math.max(3, (m.fim - m.ini) * T.pps) + 'px';
  }

  function criarMarca(m) {
    const n = document.createElement('button');
    n.type = 'button';
    n.className = 'marca' + (m.tipo === 'ponto' ? ' ponto' : '')
      + (m.enviada ? ' enviada' : '')
      // H49-11: aplicada ≠ enviada. `enviada` = o POST saiu; `aplicada` = o
      // agente já mexeu no corte por causa dela.
      + (m.aplicada ? ' aplicada' : '');
    posicionarMarca(n, m);
    n.textContent = m.tipo === 'ponto' ? '' : m.texto;
    n.title = (m.aplicada ? 'APLICADA pelo agente · ' : '')
      + (m.enviada ? `enviada ${m.enviadaEm} · ` : '') + (m.texto || '');
    n.setAttribute('aria-label', `${m.tipo === 'ponto' ? 'Ponto' : 'Trecho'} em ${mmss(m.ini)}`
      + (m.fim > m.ini ? ` até ${mmss(m.fim)}` : '')
      + (m.enviada ? ', já enviado' : ', editar marcação')
      + (m.texto ? `: ${m.texto}` : ''));
    if (m.enviada) n.setAttribute('aria-disabled', 'true');
    if (!m.enviada) n.addEventListener('click', (e) => { e.stopPropagation(); abrir(m); });
    return n;
  }

  function estruturaIgual(plano) {
    if (!renderizados || renderizados.length !== plano.length) return false;
    return plano.every((item, i) => {
      const anterior = renderizados[i];
      return anterior.m === item.m && anterior.faixa === item.faixa
        && anterior.estado === item.estado
        && anterior.no?.parentElement === def.faixas.children[item.faixa];
    });
  }

  function reconstruir(plano) {
    const faixas = def.faixas;
    faixas.replaceChildren();
    const totalFaixas = Math.max(1, ...plano.map((item) => item.faixa + 1));
    for (let k = 0; k < totalFaixas; k++) {
      const f = document.createElement('div');
      f.className = 'faixa';
      faixas.appendChild(f);
    }
    for (const item of plano) {
      item.no = criarMarca(item.m);
      faixas.children[item.faixa].appendChild(item.no);
    }
    renderizados = plano;
  }

  def.montar = () => {
    const raiz = document.createElement('div');
    raiz.className = 'trilha';
    raiz.dataset.trilha = 'marcacoes';
    const rot = document.createElement('div');
    rot.className = 'trilha-rotulo';
    const nome = document.createElement('span');
    nome.textContent = 'marcas';
    rot.appendChild(nome);
    const faixas = document.createElement('div');
    faixas.className = 'faixas';
    raiz.append(rot, faixas);
    def.faixas = faixas;
    renderizados = null;
    def.redesenhar();
    return raiz;
  };
  def.redesenhar = () => {
    const faixas = def.faixas;
    if (!faixas) return;
    const plano = planejar();
    if (!estruturaIgual(plano)) { reconstruir(plano); return; }

    // Zoom muda apenas a geometria: identidade, listeners e foco sobrevivem.
    for (const item of renderizados) posicionarMarca(item.no, item.m);
  };
  def.temConteudoEm = () => false;
  return def;
}

/* ─────────────────────────────────────────── rascunho local (§3.13) */

/**
 * A chave leva o `fingerprint_render`, e não a `revisao` que a SPEC-18 §3.13
 * sugeria, por duas medições:
 *   1. `revisao` sobe a CADA escrita do `estado.py` — inclusive uma que só troca
 *      `mensagem`. Com ela na chave, rodar `estado.py` apagaria o rascunho do
 *      usuário em silêncio, que é o oposto do que o cache existe para evitar.
 *   2. a própria §3.13 diz que as marcações enviadas só somem quando o
 *      `fingerprint_render` muda. Uma chave só, com a regra certa.
 */
function chaveRascunho() {
  return `preview:${S.dir || '?'}:${S.fpRender ?? '0'}`;
}

export function salvarRascunho() {
  // ⚠️ cache de UI, nunca registro: o registro é o arquivo em `pendentes/`.
  //
  // As ENVIADAS entram aqui também, e não é dado editorial novo — é a memória de
  // "isto já foi", que a §3.13 pede para ninguém remarcar a mesma coisa duas
  // vezes. Não há outro caminho: as rotas da SPEC-17 bloqueiam `.preview/` no
  // `media/` de propósito, e esta spec não abre o `servidor.py`.
  try {
    if (S.marcacoes.length) localStorage.setItem(chaveRascunho(),
      JSON.stringify(S.marcacoes));
    else localStorage.removeItem(chaveRascunho());
  } catch (_) { /* modo privado: perder o cache não perde dado */ }
}

/** Chamado só DEPOIS do primeiro estado: antes dele não se sabe `dir` nem
 *  `revisao`, e a chave sairia errada — o rascunho ficaria órfão. */
export function restaurarRascunho() {
  try {
    const cru = localStorage.getItem(chaveRascunho());
    if (!cru) return;
    const lista = JSON.parse(cru);
    if (Array.isArray(lista) && lista.length) {
      S.marcacoes.push(...lista);
      aoMudar();
      const pend = lista.filter((m) => !m.enviada).length;
      torrar(pend
        ? `${pend} marcação(ões) de rascunho restaurada(s)`
        : `${lista.length} marcação(ões) já enviada(s) nesta revisão`);
    }
  } catch (_) { /* rascunho ilegível não é motivo para não abrir a app */ }
}

/* ──────────────────────────────────────────────────────────── o envio (§4.1) */

function isoLocal(d = new Date()) {
  const p = (n, c = 2) => String(Math.abs(n)).padStart(c, '0');
  const off = -d.getTimezoneOffset();
  const sinal = off >= 0 ? '+' : '-';
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
    + `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
    + `${sinal}${p(Math.floor(Math.abs(off) / 60))}:${p(Math.abs(off) % 60)}`;
}

function contextoDe(m) {
  const caps = S.legendas || [];
  const palavras = [];
  for (const w of caps) {
    if (w.endMs / 1000 >= m.ini && w.startMs / 1000 <= m.fim + 1e-6) {
      palavras.push({ t: +(w.startMs / 1000).toFixed(3), w: (w.text || '').trim() });
      if (palavras.length >= 40) break;
    }
  }
  return { palavras, trilhas_com_conteudo: comConteudoEm(m.ini, m.fim) };
}

/**
 * O take sob o instante. Com `timeline_real` a atribuição é EXATA; sem ela, a
 * régua do rascunho é a única disponível e a confiança é declarada `aproximada`
 * — o digest recalcula por medição e diverge em voz alta se não bater.
 */
function takeEm(t) {
  const s = S.segmentos.find((g) => t >= g.ini - 1e-9 && t < g.ini + g.dur);
  if (!s || !s.sid) return { sid: null, conf: 'indisponivel' };
  return { sid: s.sid, conf: s.exato ? 'exata' : 'aproximada' };
}

export function montarPayload() {
  const fps = S.fmt?.fps || null;
  const pendentes = S.marcacoes.filter((m) => !m.enviada);
  return {
    contrato: CONTRATO,
    salvo_em: isoLocal(),
    revisao_base: S.bruto?.estado?.revisao ?? null,
    fingerprint_corte: S.fpCorte,
    fingerprint_render: S.fpRender,
    render_alvo: S.bruto?.estado?.render_corrente || S.bruto?.midia?.rel || null,
    formato: {
      largura: S.fmt?.largura ?? null, altura: S.fmt?.altura ?? null,
      fps, fonte: S.fmt?.fonte ?? null,
    },
    timeline_real_ausente: !!S.bruto?.timeline_real_ausente,
    app: APP,
    notas: pendentes.map((m) => {
      const t = takeEm(m.ini);
      return {
        id: m.id, tipo: m.tipo, fase: m.fase, trilha: m.trilha, ref: m.ref,
        // 🔴 rascunho == render enquanto não houver operação de corte (§3.0).
        // Os dois vêm do player: nenhum número derivado de Σ(end−start) é gravado.
        rascunho: { ini: +m.ini.toFixed(3), fim: +m.fim.toFixed(3) },
        render: { ini: +m.ini.toFixed(3), fim: +m.fim.toFixed(3) },
        render_frames: fps ? [Math.round(m.ini * fps), Math.round(m.fim * fps)] : null,
        sid: t.sid, sid_confianca: t.conf,
        marcado_invertido: !!m.marcado_invertido,
        texto: m.texto,
        contexto: contextoDe(m),
      };
    }),
  };
}

export async function salvar() {
  const pendentes = S.marcacoes.filter((m) => !m.enviada);
  if (!pendentes.length) { torrar('nada a salvar'); return false; }
  const corpo = { tipo: 'marcacoes', payload: montarPayload() };
  try {
    const r = await fetch('api/salvar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corpo),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || r.status);
    const hora = new Date().toTimeString().slice(0, 5);
    // 🔴 as marcações NÃO somem da tela (o ref-A limpa, `app.js:1822`): viram
    // chips apagados, para ninguém remarcar a mesma coisa duas vezes.
    for (const m of pendentes) { m.enviada = true; m.enviadaEm = hora; }
    salvarRascunho();
    aoMudar();
    torrar(`${pendentes.length} marcação(ões) enviada(s)`);
    return true;
  } catch (e) {
    torrar('falha ao salvar: ' + e.message);
    return false;
  }
}

export function descartar() {
  const antes = S.marcacoes.length;
  S.marcacoes = S.marcacoes.filter((m) => m.enviada);
  S.inPendente = null;
  marcaPendente.hidden = true;
  salvarRascunho();
  aoMudar();
  torrar(`${antes - S.marcacoes.length} marcação(ões) descartada(s)`);
}

export function temPendencia() {
  return S.marcacoes.some((m) => !m.enviada) || S.inPendente != null || editando != null;
}

/* ───────────────────────────────────────────────────────────────── toast */

let ultimoAviso = null;

export function torrar(texto, ms = 3200) {
  if (!torradeira) return;
  const n = document.createElement('div');
  n.className = 'torrada';
  n.textContent = texto;
  torradeira.appendChild(n);
  setTimeout(() => n.remove(), ms);
}

/** ⚠️ Uma vez por revisão. O `app.js:722-730` reprograma o timer a cada poll e o
 *  aviso nunca some — aqui a revisão vista é registrada incondicionalmente e o
 *  aviso é deduplicado pela própria revisão. */
export function avisarUmaVez(texto, chaveDaMudanca) {
  const chave = `${chaveDaMudanca ?? S.revisaoVista}|${texto}`;
  if (ultimoAviso === chave) return;
  ultimoAviso = chave;
  torrar(texto, 5000);
}
