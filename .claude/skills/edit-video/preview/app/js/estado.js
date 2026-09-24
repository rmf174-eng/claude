/* Timeline interativa da UI de aprovação — benchmark.edit-marcacoes/v1.
 *
 * A marcação IN/OUT com instrução, a gutter sticky com máscara, o guarda de
 * pointerdown e o arranjo de uma trilha por TIPO são MECANISMO observado em
 * uma ferramenta de edição de terceiro:
 * assets/preview/app.js:981-1035,1570-1577 · app.css:243-268 · SKILL.md:135-166.
 * Nenhum código foi portado. Ver docs/specs/SPEC-18 §10.
 *
 * ESTE ARQUIVO: o laço de estado (poll com If-None-Match), a resolução de
 * formato em três degraus e a leitura dos segmentos. Nada aqui desenha.
 */

/** O estado vivo da app. Um só objeto: `S.x` é sempre a verdade corrente. */
export const S = {
  bruto: null,          // o /api/estado inteiro, como veio
  dir: null,
  etag: null,
  revisaoVista: null,
  fpCorte: null,
  fpRender: null,
  fmt: null,            // {largura, altura, fps, aspecto, fonte}
  dur: 0,
  segmentos: [],
  reguaExata: false,    // true = timeline_real; false = sem fronteiras de segmento
  strip: null,          // meta.json do filmstrip
  onda: null,           // waveform.json
  legendas: null,       // captions.json (palavras com startMs/endMs)
  chave: null,
  pps0: false,          // já houve um `fit` inicial?
  marcacoes: [],
  inPendente: null,
  contadores: { renderAll: 0, polls: 0, naoModificado: 0 },
};

const ERRO_MAX_ESPERA = 8000;

/* ─────────────────────────────────────────────────── formato em três degraus */

/**
 * O formato da SAÍDA — que é o que o creator-1 aprova, e o que decide o layout.
 * perfil (SPEC-00) → estado.formato (SPEC-16) → mídia sondada → frame decodificado.
 *
 * Por que não só o frame decodificado (que é o que o ref-A faz): antes do
 * primeiro render não HÁ frame, a app nasceria no layout errado e pularia quando
 * o `v1-montado.mp4` chegasse.
 */
export function formatoDaPeca(bruto, video) {
  const cand = [
    ['perfil', bruto?.perfil?.video],
    ['estado', bruto?.estado?.formato],
    ['medido', bruto?.midia ? { largura: bruto.midia.width, altura: bruto.midia.height,
                                fps: bruto.midia.fps } : null],
    ['decodificado', video && video.videoWidth
      ? { largura: video.videoWidth, altura: video.videoHeight, fps: null } : null],
  ];
  for (const [fonte, v] of cand) {
    if (!v) continue;
    const l = Number(v.largura), a = Number(v.altura);
    if (!(l > 0 && a > 0)) continue;
    return { largura: l, altura: a, fps: Number(v.fps) || null, aspecto: l / a, fonte };
  }
  return { largura: null, altura: null, fps: null, aspecto: null, fonte: 'desconhecido' };
}

/** As zonas proibidas de UI, em FRAÇÃO (SPEC-00 §3.4). Nunca em pixel aqui. */
export function zonasUi(bruto) {
  const z = bruto?.estado?.zonas_ui || bruto?.perfil?.zonas_ui;
  if (!z) return null;
  const n = (x) => (typeof x === 'number' && x > 0 && x < 1 ? x : null);
  return { topo: n(z.topo_pct), fundo: n(z.fundo_pct), direita: n(z.direita_pct) };
}

/* ───────────────────────────────────────────────────────────── os segmentos */

function edlSegmentos(edl) {
  if (Array.isArray(edl)) return edl;
  if (edl && Array.isArray(edl.segments)) return edl.segments;
  return [];
}

/** A timeline validada pelo pipeline. `estado.py` também a carrega para EDL v1. */
export function timelineRealDe(bruto) {
  return bruto?.timeline_real || bruto?.estado?.timeline_real || null;
}

/**
 * Os blocos a desenhar, com a régua declarada.
 *
 * Sem `timeline_real` não há fronteira de segmento para desenhar. A duração do
 * render ainda pode vir do player/ffprobe, e a coordenada de toda marcação vem
 * do `video.currentTime`, mas inventar blocos por Σ(end−start) desloca take,
 * legenda e filmstrip a cada arredondamento de frame.
 */
export function segmentosDe(bruto) {
  const tl = timelineRealDe(bruto);
  if (!Array.isArray(tl?.segments)) return [];
  const doEstado = bruto?.estado?.segmentos;
  const crus = edlSegmentos(bruto?.edl);
  const n = tl.segments.length;
  const saida = [];
  for (let i = 0; i < n; i++) {
    const c = crus[i] || {};
    const e = (doEstado && doEstado[i]) || {};
    const extras = e.extras || {};
    const linha = tl.segments[i];
    const dur = Number(linha.dur_s) || 0;
    const ini = Number(linha.start_s) || 0;
    saida.push({
      i,
      sid: e.sid || null,
      src: c.src ?? e.src ?? null,
      start: c.start ?? e.start ?? null,
      end: c.end ?? e.end ?? null,
      beat: c.beat ?? e.beat ?? null,
      quem: c.quem ?? extras.quem ?? null,
      zoom: c.zoom ?? e.zoom ?? null,
      cx: c.cx ?? e.cx ?? null,
      cy: c.cy ?? e.cy ?? null,
      arquivo: e.arquivo || null,
      ini, dur, exato: true,
    });
  }
  return saida;
}

/** A duração da régua: timeline real, ou o próprio render medido. Nunca a EDL. */
export function duracaoDe(bruto, _segs, video) {
  const tl = timelineRealDe(bruto);
  if (tl?.total_s) return { dur: tl.total_s, exata: true };
  const d = bruto?.midia?.dur || (video && isFinite(video.duration) ? video.duration : 0);
  return { dur: d || 0, exata: false };
}

/* ─────────────────────────────────────────────────────── o laço de estado */

/**
 * Poll com `If-None-Match`. 304 com a peça parada é o caso comum e não custa
 * nada (SPEC-17 §3.5).
 *
 * 🔴 A revisão vista é registrada INCONDICIONALMENTE. O `app.js:726` do ref-A só
 * a registra no ramo limpo: com ajustes sujos, cada poll cai no `else`, chama
 * `toast()`, o `clearTimeout` reprograma o timer e o aviso NUNCA some.
 */
export function iniciarPoll({ aplicar, avisar, temPendencia, intervalo = 2000 }) {
  let espera = intervalo;
  const sinalizar = (estado, detalhe) => {
    window.__preview?.aoConexao?.({ estado, detalhe, em: Date.now() });
  };
  async function passo() {
    try {
      const cab = S.etag ? { 'If-None-Match': S.etag } : {};
      const r = await fetch('api/estado', { cache: 'no-store', headers: cab });
      S.contadores.polls++;
      if (r.status === 304) {
        S.contadores.naoModificado++;
      } else if (r.ok) {
        S.etag = r.headers.get('ETag') || null;
        const novo = await r.json();
        aplicarSeCabe(novo, { aplicar, avisar, temPendencia });
      } else {
        throw new Error(`HTTP ${r.status}`);
      }
      sinalizar('online', `Preview local sincronizado às ${new Date().toLocaleTimeString('pt-BR')}`);
      espera = intervalo;
    } catch (e) {
      // silêncio aqui já custou caro neste repo: o poll é o único ponto que
      // enxerga o servidor cair, e um backoff mudo parece "a peça não mudou".
      console.error('poll do /api/estado:', e);
      sinalizar('offline', `Não foi possível ler o estado local: ${e.message || e}`);
      espera = Math.min(espera * 2, ERRO_MAX_ESPERA);
    }
    setTimeout(passo, espera);
  }
  passo();
}

function aplicarSeCabe(novo, { aplicar, avisar, temPendencia }) {
  const est = novo.estado || {};
  // 🔴 Chegar aqui já significa "mudou": um 200 (e não 304) é a resposta do
  // servidor a uma mudança no ETag, que cobre arquivos, fila de pendentes E
  // progresso de geração. Barrar por `estado.revisao` — que só muda quando o
  // `estado.py` roda — deixa filmstrip e waveform PRONTOS no servidor sem nunca
  // aparecerem na tela. Medido em 2026-08-09 nesta app, e o sintoma era mudo.
  S.revisaoVista = est.revisao ?? S.etag;      // SEMPRE, não só no ramo limpo
  /* H49-11: quem foi APLICADO pelo agente. Chega como lista de ids e é marcado
   * nas marcações locais — a régua para de mostrar como "esperando" o que já foi
   * atendido. Não apaga nada: a marca vira estado discreto, porque apagar seria
   * perder a memória de "já pedi isso" que a §3.13 existe para guardar. */
  const apl = new Set(novo.marcacoes_aplicadas || []);
  if (apl.size) {
    for (const m of S.marcacoes) {
      if (apl.has(m.id) && !m.aplicada) { m.aplicada = true; }
    }
  }
  const novoCorte = est.fingerprint_corte ?? null;
  const novoRender = est.fingerprint_render ?? null;
  const mudouCorte = novoCorte !== S.fpCorte;
  const mudouRender = novoRender !== S.fpRender;
  const primeiro = !S.bruto;
  if (primeiro || !temPendencia() || (!mudouCorte && !mudouRender)) {
    S.fpCorte = novoCorte;
    S.fpRender = novoRender;
    aplicar(novo);
  } else {
    // Não consuma o ETag de um estado que a tela deliberadamente NÃO aplicou.
    // Ao terminar/cancelar a edição pendente, o próximo poll precisa buscar o
    // mesmo estado de novo; com o ETag novo ele receberia 304 para sempre.
    S.etag = null;
    // a chave é o par de fingerprints NOVO: exatamente um aviso por mudança
    // invalidante, e não um por poll (o `app.js:722-730` reprograma o timer a
    // cada 2 s e o aviso nunca some).
    avisar('O corte mudou. Salve ou descarte para atualizar.',
           `${novoCorte}|${novoRender}`);
  }
}

/* ──────────────────────────────────────────────────────────────── utilidades */

export function mmss(t) {
  if (!isFinite(t)) return '--';
  const m = Math.floor(Math.abs(t) / 60);
  const s = Math.abs(t) - m * 60;
  return `${t < 0 ? '-' : ''}${m}:${s.toFixed(3).padStart(6, '0')}`;
}

export function pt(x, casas = 2) {
  return Number(x).toFixed(casas).replace('.', ',');
}

export function grampear(x, a, b) { return Math.max(a, Math.min(b, x)); }

/** Caminho de mídia relativo, com cada componente escapado (nunca barra inicial). */
export function urlMidia(rel, comFingerprint = false) {
  const base = 'media/' + String(rel).split('/').map(encodeURIComponent).join('/');
  /* 🔴 H49-8 (achado A-10, 2026-08-12). Trocar o render debaixo da aba abria
   * `ERR_ABORTED`: o browser tinha byte-ranges do arquivo ANTIGO em buffer e o
   * arquivo no disco era outro, com o MESMO nome e o MESMO Content-Length
   * provável. O creator lê isso como defeito do app.
   *
   * O `?f=<fingerprint>` faz do render uma URL diferente — cache novo, buffer
   * novo, nenhuma mistura. O dado já estava no `api/estado`
   * (`fingerprint_render`) e ninguém o usava para isto. */
  if (!comFingerprint || !S.fpRender) return base;
  return base + '?f=' + encodeURIComponent(String(S.fpRender).slice(0, 16));
}
