/* Timeline interativa da UI de aprovação — benchmark.edit-marcacoes/v1.
 *
 * O layout que segue o aspecto, a pílula de "não salvo" e as abas de fase são
 * MECANISMO observado em uma ferramenta de edição de terceiro: assets/preview/app.css:158-166 · app.js:708-715,1522-1535
 * · index.html:32-38. Nenhum código foi portado. Ver docs/specs/SPEC-18 §10.
 *
 * ESTE ARQUIVO: boot, layout por aspecto, transporte, atalhos e o registro de
 * abas de que a SPEC-19 depende.
 */
import { S, formatoDaPeca, zonasUi, segmentosDe, duracaoDe, iniciarPoll, mmss,
  urlMidia, grampear } from './estado.js';
import * as TL from './timeline.js';
import * as TR from './trilhas.js';
import * as MC from './marcacoes.js';
import { abrirModal, fecharModal } from './modal.js';

const $ = (id) => document.getElementById(id);
const video = $('player');

/* ───────────────────────────────────────────── registro de abas (SPEC-19) */

const abas = [];
let abaAtiva = null;
let contextoAprovacao = null;

/**
 * Ponto de extensão. A SPEC-19 acrescenta `js/estilos.js` chamando
 * `registrarAba({id:'estilo', ordem:1.5, montar})` e a aba aparece ENTRE as duas
 * fases — sem reescrever uma linha deste arquivo.
 */
export function registrarAba({ id, rotulo, ordem = 99, montar, habilitada = true,
                               marcador = false, dica = null }) {
  const j = abas.findIndex((a) => a.id === id);
  const def = { id, rotulo, ordem, montar, habilitada, marcador, dica };
  if (j >= 0) abas[j] = def; else abas.push(def);
  abas.sort((a, b) => a.ordem - b.ordem);
  pintarAbas();
  return def;
}
// Hook de extensão nº 2 (o nº 1 é `registrarAba`): quem precisa REAGIR ao estado
// se inscreve aqui e é chamado a cada `aplicar()`. A aba ESTILO usa isto para
// abrir/fechar conforme o portão — sem ele, ela só saberia do estado no load do
// módulo, que roda ANTES do primeiro /api/estado.
const ouvintesEstado = [];
export function aoAplicar(fn) { ouvintesEstado.push(fn); }

window.__preview = { registrarAba, aoAplicar, S, TL, TR, MC };
window.__preview.aoConexao = (detalhe = {}) => {
  const conexao = $('estado-conexao');
  const estado = detalhe.estado || 'offline';
  conexao.dataset.estado = estado;
  const texto = estado === 'online' ? 'sessão ativa'
    : (estado === 'offline' ? 'sem conexão' : 'sincronizando');
  conexao.querySelector('span').textContent = texto;
  conexao.setAttribute('aria-label', `Conexão local: ${texto}`);
  conexao.title = detalhe.detalhe || 'Estado da sessão local de preview';
};

function pintarAbas() {
  const cx = $('abas');
  if (!cx) return;
  cx.textContent = '';
  for (const [indice, a] of abas.entries()) {
    const b = document.createElement('button');
    b.type = 'button';
    b.id = `aba-${a.id}`;
    b.dataset.aba = a.id;
    const numero = document.createElement('span');
    numero.className = 'aba-indice';
    numero.textContent = String(indice + 1).padStart(2, '0');
    numero.setAttribute('aria-hidden', 'true');
    const rotulo = document.createElement('span');
    rotulo.className = 'aba-rotulo';
    rotulo.textContent = a.rotulo;
    b.append(numero, rotulo);
    // O marcador é um ponto desenhado, nunca um caractere no rótulo: ver
    // `app.css .aba-marca`. `title` é o que diz o significado em palavras.
    if (a.marcador) {
      const i = document.createElement('i');
      i.className = 'aba-marca';
      b.appendChild(i);
    }
    if (a.dica) b.title = a.dica;
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-selected', String(abaAtiva === a.id));
    // Corte/Final controlam a mesa real. Extensões com `montar()` controlam o
    // painel que elas ocupam. Apontar todas as abas para o mesmo painel oculto
    // fazia o leitor de tela anunciar uma relação que não existia.
    b.setAttribute('aria-controls', a.montar ? 'painel-aba' : 'palco');
    b.tabIndex = abaAtiva === a.id || (!abaAtiva && a.habilitada
      && !abas.slice(0, indice).some((x) => x.habilitada)) ? 0 : -1;
    b.disabled = !a.habilitada;
    b.addEventListener('click', () => trocarAba(a.id));
    b.addEventListener('keydown', (ev) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(ev.key)) return;
      ev.preventDefault();
      ev.stopPropagation();
      const disponiveis = abas.filter((x) => x.habilitada);
      const atual = Math.max(0, disponiveis.findIndex((x) => x.id === a.id));
      let destino = atual;
      if (ev.key === 'Home') destino = 0;
      if (ev.key === 'End') destino = disponiveis.length - 1;
      if (ev.key === 'ArrowLeft') destino = (atual - 1 + disponiveis.length) % disponiveis.length;
      if (ev.key === 'ArrowRight') destino = (atual + 1) % disponiveis.length;
      const proxima = disponiveis[destino];
      if (!proxima) return;
      const trocou = trocarAba(proxima.id);
      const foco = trocou ? proxima.id : a.id;
      requestAnimationFrame(() => document.getElementById(`aba-${foco}`)?.focus());
    });
    cx.appendChild(b);
  }
}

// A aba que sai precisa PODER se desmontar. A galeria da SPEC-19 deixa `<video>`
// tocando e um timer rodando; sem isto, trocar de aba deixa preview tocando por
// baixo da timeline — e o sintoma (áudio de lugar nenhum) não parece causado por
// troca de aba. `montar()` pode devolver um Node (como antes) ou
// `{el, destruir}`; as duas formas seguem valendo.
let desmontarAba = null;
let podeDesmontarAba = null;

function sincronizarSemanticaAba(a) {
  const palco = $('palco');
  const painel = $('painel-aba');
  const painelMontado = !!a?.montar && !painel.hidden;
  if (painelMontado) {
    palco.removeAttribute('role');
    palco.removeAttribute('aria-labelledby');
    painel.setAttribute('role', 'tabpanel');
    painel.setAttribute('aria-labelledby', `aba-${a.id}`);
  } else {
    painel.removeAttribute('role');
    painel.removeAttribute('aria-labelledby');
    palco.setAttribute('role', 'tabpanel');
    palco.setAttribute('aria-labelledby', `aba-${a?.id || 'fase1'}`);
  }
}

function trocarAba(id) {
  const a = abas.find((x) => x.id === id);
  if (!a || !a.habilitada) return false;
  // Clicar de novo na aba ativa só devolve o foco. Remontá-la apagava escolhas
  // ainda não enviadas da galeria sem aviso.
  if (id === abaAtiva) return false;
  if (podeDesmontarAba && !podeDesmontarAba()) {
    MC.torrar('Aguarde o envio do look terminar antes de trocar de etapa.');
    return false;
  }
  if (desmontarAba) {
    try { desmontarAba(); } catch (e) { console.warn('desmontar aba:', e); }
    desmontarAba = null;
    podeDesmontarAba = null;
  }
  abaAtiva = id;
  const painel = $('painel-aba');
  painel.textContent = '';
  const r = a.montar ? a.montar() : null;
  const conteudo = r && r.el !== undefined ? r.el : r;
  if (r && typeof r.destruir === 'function') desmontarAba = r.destruir;
  if (r && typeof r.podeDesmontar === 'function') podeDesmontarAba = r.podeDesmontar;
  if (conteudo) { painel.appendChild(conteudo); painel.hidden = false; }
  else painel.hidden = true;
  painel.setAttribute('aria-labelledby', `aba-${a.id}`);
  // 🔴 A aba com painel esconde player e timeline (`app.css body.aba-montada`), e
  // o vídeo PAUSA: sem isto o transporte desaparece com o áudio ainda tocando, e
  // som sem player visível não tem como ser desligado por quem está olhando.
  document.body.classList.toggle('aba-montada', !painel.hidden);
  if (!painel.hidden && video && !video.paused) video.pause();
  if (painel.hidden) requestAnimationFrame(() => TL.aoMostrar());
  sincronizarSemanticaAba(a);
  pintarAbas();
  return true;
}

/* ──────────────────────────────────────────────────────────────── aplicar */

let midiaPosta = null;
let estruturaVista = null;

function aplicar(bruto) {
  S.bruto = bruto;
  S.dir = bruto.dir || null;
  S.chave = bruto.midia?.chave || null;
  S.fmt = formatoDaPeca(bruto, video);
  S.segmentos = segmentosDe(bruto);
  const d = duracaoDe(bruto, S.segmentos, video);
  S.dur = d.dur;
  S.reguaExata = d.exata;

  layoutPeloAspecto();
  pintarCabecalho();
  pintarMidia(bruto);
  pintarZonas();

  // ⚠️ reconstruir só quando a ESTRUTURA muda. Um poll de 2 s que refaz o DOM
  // inteiro é o que o aceite §7.9(a) mede (`window.__renderAll`), e é também o
  // que faria a tira de thumbs piscar a cada dois segundos.
  // Quantidade igual nao significa timeline igual. Um EDL pode aparecer depois
  // do primeiro poll com os mesmos 18 segmentos, mas agora com entrada, saida e
  // duracao reais. Assinar a estrutura inteira obriga a remontagem nesse caso.
  const assinatura = JSON.stringify([S.fpCorte, S.reguaExata, S.dur, S.segmentos,
    S.chave, !!S.onda, (S.legendas || []).length, bruto.midia?.strip?.estado]);
  if (assinatura !== estruturaVista) {
    estruturaVista = assinatura;
    TL.T.trilhas = [MC.trilha(), ...TR.padrao()];
    TL.reconstruir();
  }
  if (!S.pps0 && S.dur > 0) { S.pps0 = true; TL.fit(); }
  TL.redesenhar();
  carregarDerivados(bruto);
  atualizarBotoes();
}

/* De onde o formato veio, em português. As chaves são os `fonte` de
 * `estado.js:formatoDaPeca`; fonte que não estiver aqui cai no próprio slug, e
 * não numa string vazia — melhor um rótulo cru que um campo em branco. */
const PROCEDENCIA = {
  perfil: 'do perfil',
  estado: 'do estado da peça',
  medido: 'medido no render',
  decodificado: 'medido no player',
};

/* A aba do browser é a única parte da UI visível com DUAS produções abertas — e
 * abrir duas é o normal (compara-se corte novo com o anterior). Duas abas
 * "preview — timeline de aprovação" não se distinguem. */
function tituloDaAba(nome, e) {
  const alvo = (e.fase ?? 1) >= 2 ? 'fase-2' : 'fase-1';
  const ok = (e.aprovacoes || []).some((a) => a.alvo === alvo && a.valida);
  document.title = `${nome} · ${ok ? 'aprovado' : 'fase ' + (e.fase ?? 1)} | Ilha`;
}

function layoutPeloAspecto() {
  // uma linha: um vertical empilhado sobre timeline de largura cheia vira selo postal
  document.body.classList.toggle('vertical', (S.fmt.aspecto ?? 1) < 0.95);
}

function pintarCabecalho() {
  const e = S.bruto?.estado || {};
  document.body.dataset.fase = String(e.fase ?? 1);
  const nome = e.producao?.titulo || e.producao?.slug
    || (S.dir || '').split('/').pop() || 'produção';
  $('titulo-peca').textContent = nome;
  const f = S.fmt;
  // "· perfil" lia como se `perfil` fosse o nome do formato. `fonte` é DE ONDE o
  // número veio, e a diferença IMPORTA para quem aprova: número do perfil é
  // intenção, número medido é o que saiu. Frase por fonte, não um prefixo colado
  // no slug — "do medido" não é português.
  $('formato-peca').textContent = f.largura
    ? `${f.largura}×${f.altura}${f.fps ? ' @ ' + f.fps + ' fps' : ''} / ${PROCEDENCIA[f.fonte] || f.fonte}`
    : 'formato desconhecido';
  tituloDaAba(nome, e);
  const msg = $('mensagem-agente');
  msg.textContent = e.mensagem || '';
  msg.title = e.mensagem || '';
  msg.hidden = !e.mensagem;

  const aviso = $('regua-aviso');
  // 🔴 SEM EDL NÃO HÁ RÉGUA — nem exata nem aproximada. `reguaExata` nasce false,
  // então numa produção que ainda não montou o aviso aparecia mesmo sem existir
  // um único bloco para posicionar: o PRIMEIRO quadro de toda produção nova era
  // uma faixa de alerta citando uma spec. Medido na tela em 2026-08-10, com a UI
  // servindo um diretório recém-criado; a API respondia 200 e o DOM estava certo,
  // que é exatamente por que só olhar a tela pega isto (RD da qc.md: OLHE A TELA).
  const edl = S.bruto?.edl;
  const temCorte = (Array.isArray(edl) && edl.length > 0)
    || (Array.isArray(edl?.segments) && edl.segments.length > 0)
    || (Array.isArray(S.bruto?.estado?.segmentos) && S.bruto.estado.segmentos.length > 0);
  if (S.reguaExata || !temCorte) { aviso.hidden = true; }
  else {
    aviso.hidden = false;
    // A frase da frente diz o que muda para quem está marcando; o motivo técnico
    // vai para o `title=`. Antes, o PRIMEIRO texto de toda produção antiga citava
    // um nome de campo e um número de spec — vocabulário de quem escreveu a
    // ferramenta, na tela de quem só quer aprovar o corte.
    aviso.textContent = 'Os blocos do corte aparecem depois da primeira montagem. '
      + 'As marcações continuam exatas: elas vêm do player.';
    aviso.title = 'sem timeline_real (SPEC-05) não há fronteiras de segmento '
      + 'confiáveis; Σ(end−start) não é usado como fallback.';
  }

  const fase = e.fase ?? 1;
  // ⚠️ A guarda pergunta pelas ABAS DE FASE, não por `abas.length`. Com
  // `!abas.length` ela virou letra morta no dia em que a primeira aba de
  // extensão passou a se registrar no load do módulo: `js/estilos.js` roda antes
  // do primeiro `/api/estado`, o array já chega com 1, e as duas fases nunca
  // eram registradas — a UI abria com a aba ESTILO sozinha. Medido no browser em
  // 2026-08-09, e invisível para qualquer teste que não abrisse a página.
  if (!abas.some((a) => a.id === 'fase1')) {
    registrarAba({ id: 'fase1', rotulo: 'Corte', ordem: 1 });
    registrarAba({ id: 'fase2', rotulo: 'Final', ordem: 2, habilitada: fase >= 2 });
    abaAtiva = fase >= 2 ? 'fase2' : 'fase1';
    sincronizarSemanticaAba(abas.find((a) => a.id === abaAtiva));
    pintarAbas();
  } else {
    // a habilitação da FASE 2 acompanha a fase corrente a cada poll
    const f2 = abas.find((a) => a.id === 'fase2');
    if (f2 && f2.habilitada !== (fase >= 2)) {
      f2.habilitada = fase >= 2;
      pintarAbas();
    }
  }
  // `S.bruto`, não `bruto`: esta função recebe só `e`, e a referência ao nome
  // errado ficava PRESA no try/catch — o ouvinte nunca rodava e nada reclamava,
  // fora um warn no console do browser. Foi o warn que denunciou.
  pintarAprovacao(e);
  for (const fn of ouvintesEstado) {
    try { fn(e, S.bruto); } catch (err) { console.warn('ouvinte de estado:', err); }
  }
}

function pintarSemMidia(titulo, detalhe) {
  const semMidia = $('sem-midia');
  const simbolo = document.createElement('span');
  simbolo.setAttribute('aria-hidden', 'true');
  const forte = document.createElement('strong');
  forte.textContent = titulo;
  const pequeno = document.createElement('small');
  pequeno.textContent = detalhe;
  semMidia.replaceChildren(simbolo, forte, pequeno);
  semMidia.hidden = false;
}

function limparVideo() {
  if (!video.getAttribute('src') && midiaPosta == null) return;
  try { video.pause(); } catch (_) { /* nada */ }
  video.removeAttribute('src');
  try { video.load(); } catch (_) { /* nada */ }
  midiaPosta = null;
}

function pintarMidia(bruto) {
  const m = bruto.midia;
  const semMidia = $('sem-midia');
  if (!m || !m.rel) {
    limparVideo();
    $('tempo-total').textContent = '';
    pintarSemMidia('Prévia em preparação', bruto.estado?.mensagem
      || 'O primeiro render aparece aqui sem recarregar a página.');
    return;
  }
  if (!m.servivel) {
    limparVideo();
    pintarSemMidia('Prévia indisponível',
      `${m.rel} resolve para fora da produção. O arquivo não pode ser servido nesta sessão.`);
    return;
  }
  semMidia.hidden = true;
  /* H49-8: a identidade da mídia é (arquivo, fingerprint do render) — não só o
   * nome. Remontar sem trocar de arquivo mudava os BYTES e mantinha a URL, e o
   * player ficava com meia mídia velha em buffer. Agora o `src` muda, o
   * `<video>` recarrega sozinho e o tempo corrente é preservado. */
  const urlNova = urlMidia(m.rel, true);
  if (urlNova !== midiaPosta) {
    const t = (midiaPosta && video.currentTime) ? video.currentTime : 0;
    midiaPosta = urlNova;
    video.src = urlNova;
    if (t > 0) {
      video.addEventListener('loadedmetadata', function volta() {
        video.removeEventListener('loadedmetadata', volta);
        try { video.currentTime = Math.min(t, video.duration || t); } catch (_) { /* nada */ }
      });
    }
  }
  $('tempo-total').textContent = '/ ' + mmss(m.dur || S.dur);
}

let zonasVisiveis = true;

function pintarZonas() {
  const z = zonasUi(S.bruto);
  const cx = $('zonas');
  const btn = $('btn-zonas');
  cx.textContent = '';
  cx.hidden = !z || !zonasVisiveis;
  btn.hidden = !z;
  btn.setAttribute('aria-pressed', String(!!z && zonasVisiveis));
  if (!z) return;
  // as zonas chegam em FRAÇÃO (SPEC-00 §3.4) e viram pixel só aqui, na tela
  const faixa = (estilo) => { const i = document.createElement('i');
    Object.assign(i.style, estilo); cx.appendChild(i); };
  if (z.topo) faixa({ left: 0, right: 0, top: 0, height: (z.topo * 100) + '%' });
  if (z.fundo) faixa({ left: 0, right: 0, top: (z.fundo * 100) + '%', bottom: 0 });
  if (z.direita) faixa({ left: (z.direita * 100) + '%', right: 0, top: 0, bottom: 0 });
}

/* ─────────────────────────────────── filmstrip, waveform e legendas (async) */

let stripCarregada = null, ondaCarregada = null;
let legendaCarregada = null, legendaCarregando = null;

async function carregarDerivados(bruto) {
  const m = bruto.midia;
  S.strip = m?.strip ? { ...m.strip, t0: m.strip.intervalo / 2 } : null;
  if (m?.strip?.estado === 'pronto' && stripCarregada !== m.chave) {
    stripCarregada = m.chave;
    try {
      const r = await fetch(`gen/${m.chave}/thumbs/meta.json`, { cache: 'force-cache' });
      if (r.ok) S.strip = { ...m.strip, ...(await r.json()) };   // t0 vem do meta
    } catch (_) { /* fica com o t0 derivado do intervalo */ }
    TL.redesenhar();
  }
  if (m?.waveform?.estado === 'pronto' && ondaCarregada !== m.chave) {
    ondaCarregada = m.chave;
    try {
      const r = await fetch(`gen/${m.chave}/waveform.json`, { cache: 'force-cache' });
      if (r.ok) { S.onda = await r.json(); TL.reconstruir(); TL.redesenhar(); }
    } catch (_) { /* sem waveform a faixa fica hachurada */ }
  }
  // o estado.py já varreu o disco atrás da legenda: quando ele diz `null`, pedir
  // `captions.json` só produz um 404 no console de toda produção sem legenda.
  // ⚠️ Mas essa guarda sozinha NÃO cobre a produção onde o `estado.py` nunca
  // rodou — e agora que a UI sobe na etapa 0, esse é o caso NORMAL, não a
  // exceção: `estado` chega `{}`, a chave `legendas` não existe, e toda produção
  // nova abria com um 404 vermelho no console. A segunda cláusula usa a varredura
  // do SERVIDOR (`arquivos`, alimentada por OBSERVADOS, que inclui
  // `captions.json`) — e só quando ninguém nomeou arquivo alternativo, senão uma
  // produção com `captions.peca-02.json` deixaria de carregar a própria legenda.
  const nomeado = bruto.estado?.legendas?.arquivo;
  const semLegenda = (bruto.estado && 'legendas' in bruto.estado && !bruto.estado.legendas)
    || (!nomeado && bruto.arquivos && !('captions.json' in bruto.arquivos));
  if (semLegenda && (S.legendas || []).length) {
    S.legendas = [];
    legendaCarregada = null;
    TL.reconstruir();
    TL.redesenhar();
  }
  const nome = nomeado || 'captions.json';
  const assinaturaLegenda = JSON.stringify([S.chave, nome, bruto.arquivos?.[nome] ?? null]);
  if (!semLegenda && legendaCarregada !== assinaturaLegenda
      && legendaCarregando !== assinaturaLegenda) {
    legendaCarregando = assinaturaLegenda;
    try {
      const r = await fetch(urlMidia(nome), { cache: 'no-cache' });
      if (r.ok) {
        const j = await r.json();
        if (Array.isArray(j)) {
          S.legendas = j;
          legendaCarregada = assinaturaLegenda;
          TL.reconstruir();
          TL.redesenhar();
        }
      }
    } catch (_) { /* sem legenda a faixa declara a ausência */ }
    finally {
      if (legendaCarregando === assinaturaLegenda) legendaCarregando = null;
    }
  }
}

/* ─────────────────────────────────────────────────────── transporte e teclas */

function passo(segundos) {
  if (!video) return;
  video.pause();
  video.currentTime = grampear((video.currentTime || 0) + segundos, 0,
    isFinite(video.duration) ? video.duration : S.dur || 0);
}

function tocarPausar() {
  if (!video || !video.src) return;
  if (video.paused) video.play().catch(() => { }); else video.pause();
}

function definirAtalhos(aberto, devolverFoco = false) {
  const painel = $('atalhos');
  const botao = $('btn-atalhos');
  painel.hidden = !aberto;
  botao.setAttribute('aria-expanded', String(aberto));
  if (aberto) painel.focus();
  else if (devolverFoco) botao.focus();
}

function ligarTeclas() {
  document.addEventListener('keydown', (e) => {
    // Um componente que já tratou a tecla manda. Isto evita a seta das abas
    // também buscar um frame e preserva Espaço/Enter nativos nos botões.
    if (e.defaultPrevented) return;
    const alvo = e.target;
    const teclaZoom = ['+', '=', '-', '_', '0'].includes(e.key);
    const teclaZoomComModificador = ['+', '=', '-', '_'].includes(e.key);
    const controleZoom = alvo?.closest?.('.transporte-zoom');
    // guarda de foco: nada de atalho enquanto se digita (`app.js:1673`)
    if (alvo && (alvo.tagName === 'INPUT' || alvo.tagName === 'TEXTAREA'
      || alvo.isContentEditable) && !(controleZoom && teclaZoom)) return;
    if (alvo?.closest?.('#atalhos')) return;
    if (alvo?.closest?.('button, a[href], select, [role="button"], [role="tab"]')
        && !(controleZoom && teclaZoom)) return;
    const timelineVisivel = !document.body.classList.contains('aba-montada');
    const contextoZoom = alvo === $('painel') || !!controleZoom || $('painel').matches(':hover');
    const modificadorDoNavegador = e.ctrlKey || e.metaKey;
    // Ctrl/Cmd/Alt pertencem ao navegador, ao sistema e a leitores de tela.
    // A única exceção intencional é o conjunto declarado de zoom, e apenas no
    // contexto da timeline. Escape continua fechando a superfície local.
    if (e.altKey && e.key !== 'Escape') return;
    if (modificadorDoNavegador && !teclaZoomComModificador && e.key !== 'Escape') return;
    const umFrame = S.fmt?.fps ? 1 / S.fmt.fps : 1 / 30;
    switch (e.key) {
      case ' ':
        if (timelineVisivel) { e.preventDefault(); tocarPausar(); }
        break;
      case 'ArrowLeft':
        if (timelineVisivel) { e.preventDefault(); passo(e.shiftKey ? -1 : -umFrame); }
        break;
      case 'ArrowRight':
        if (timelineVisivel) { e.preventDefault(); passo(e.shiftKey ? 1 : umFrame); }
        break;
      case 'm': case 'M':
        if (timelineVisivel) { e.preventDefault(); MC.alternarMarca(); }
        break;
      case 'i': case 'I':
        if (timelineVisivel) { e.preventDefault(); MC.marcarIn(); }
        break;
      case 'o': case 'O':
        if (timelineVisivel) { e.preventDefault(); MC.marcarOut(); }
        break;
      case 'Escape':
        if (!$('atalhos').hidden) definirAtalhos(false, true);
        else if (caixaAprovarAberta()) fecharCaixaAprovar();
        else if (MC.caixaAberta()) MC.fecharCaixa();
        else MC.cancelarIn();
        break;
      case '+': case '=':
        if (timelineVisivel && (!modificadorDoNavegador || contextoZoom)) {
          e.preventDefault(); TL.zoom(1.35);
        }
        break;
      case '-': case '_':
        if (timelineVisivel && (!modificadorDoNavegador || contextoZoom)) {
          e.preventDefault(); TL.zoom(1 / 1.35);
        }
        break;
      case '0':
        if (timelineVisivel && (!modificadorDoNavegador || contextoZoom)) {
          e.preventDefault(); TL.fit();
        }
        break;
      case '?': definirAtalhos($('atalhos').hidden); break;
      default: break;
    }
  });
}

/* ─────────────────────────────────────────────── o gesto de aprovar o corte
 *
 * 🔴 ACHADO A10 (auditoria de 2026-08-10). A tela mostrava o corte e não tinha
 * como dizer "ok": a aprovação só existia como `qc-portao.py --aprovar --por
 * <string livre>`, com o default assinando pelo dono da máquina. Resultado
 * medido em 2026-08-09: peça entregue "aprovada pelo creator", assinada pelo
 * próprio agente, com a tela nunca aberta.
 *
 * O envelope vai pela rota que já existe (`api/salvar`), e é o SERVIDOR que o
 * transforma em aprovação `fonte: ui-save` no estado — com o pid da sessão
 * dentro. É o que o CLI não consegue imitar: este POST exige a página de pé.
 */
/* ⚠️ O DIÁLOGO É DA CASA, NÃO DO SISTEMA OPERACIONAL (exame de UX, 2026-08-11).
 * Era `window.prompt()`: caixa cinza do navegador, com o texto todo numa linha
 * só, sem o nome da produção e sem o verde do botão que a abriu. O gesto que
 * fecha uma fase merecia o diálogo que esta UI já tinha para anotar uma marcação.
 *
 * O ELO NÃO MUDA: o POST, o envelope e a leitura do `fonte: ui-save` continuam
 * exatamente os mesmos — só quem coleta o texto mudou. É por isso que o
 * `qc-preview` não precisa saber que isto aconteceu. */
function abrirCaixaAprovar() {
  const e = S.bruto?.estado || {};
  contextoAprovacao = contextoAprovacaoAtual();
  const alvo = contextoAprovacao.alvo;
  /* Sem slug no estado a frase cai para um demonstrativo, e "o corte de esta
   * produção" é agramatical. A preposição entra JUNTO com o nome, para que o
   * fallback seja uma frase inteira e não um buraco preenchido. */
  const nome = e.producao?.titulo || e.producao?.slug;
  const alvoTexto = nome ? `de ${nome}` : 'desta produção';
  $('aprovar-alvo').textContent = alvo;
  const etapa = alvo === 'fase-2' ? 'a montagem final' : 'o corte';
  $('aprovar-titulo').textContent = alvo === 'fase-2' ? 'Aprovar a montagem' : 'Aprovar o corte';
  $('aprovar-prosa').textContent = `Você está aprovando ${etapa} ${alvoTexto}. `
    + 'Fica registrado com a hora, preso ao plano e ao render que estão na tela. '
    + 'Se o conteúdo mudar depois, a aprovação cai sozinha.';
  const txt = $('aprovar-texto');
  txt.value = '';
  $('caixa-aprovar').hidden = false;
  abrirModal($('caixa-aprovar'), {
    foco: txt,
    fallback: document.getElementById(`aba-${abaAtiva}`) || video,
    aoEscape: fecharCaixaAprovar,
  });
}

function fecharCaixaAprovar() {
  $('caixa-aprovar').hidden = true;
  fecharModal($('caixa-aprovar'));
  contextoAprovacao = null;
}

const caixaAprovarAberta = () => !$('caixa-aprovar').hidden;

async function aprovarCorte() {
  const btn = $('btn-aprovar');
  const motivo = $('aprovar-texto').value.trim();
  const contexto = contextoAprovacao;
  const alvo = contexto?.alvo;
  fecharCaixaAprovar();
  if (!contexto) {
    MC.torrar('A aprovação perdeu o contexto. Revise a peça e tente de novo.');
    return;
  }
  btn.disabled = true;
  try {
    const r = await fetch('api/salvar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tipo: 'aprovacao',
        payload: { alvo, motivo: motivo || null, por: 'creator (UI)', ...contexto } }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || r.status);
    if (j.erro_aprovacao) throw new Error(j.erro_aprovacao);
    if (!j.aprovacao) throw new Error('o servidor não registrou a aprovação');
    MC.torrar(`Aprovação registrada: ${j.aprovacao.alvo} / ${j.aprovacao.fonte}`);
    // O ETag some para o próximo poll vir 200 em vez de 304: a pílula acende em
    // ≤2 s sem uma rota nova só para isso.
    S.etag = null;
  } catch (err) {
    // Um nonce é de uso único mesmo quando o servidor recusa o contexto.
    // Forçar um 200 no próximo poll traz uma capacidade nova sem misturá-la
    // ao ETag ou aos fingerprints da produção.
    S.etag = null;
    MC.torrar('falha ao aprovar: ' + err.message);
  } finally {
    btn.disabled = false;
  }
}

function contextoAprovacaoAtual() {
  const e = S.bruto?.estado || {};
  return {
    alvo: (e.fase ?? 1) >= 2 ? 'fase-2' : 'fase-1',
    fingerprint_corte: S.fpCorte ?? null,
    fingerprint_render: S.fpRender ?? null,
    render_alvo: e.render_corrente ?? S.bruto?.midia?.rel ?? null,
    plano_sha256: e.plano?.sha256 ?? null,
    nonce_aprovacao: S.bruto?.sessao?.nonce_aprovacao ?? null,
  };
}

function contextoAprovacaoBate() {
  if (!contextoAprovacao) return true;
  const atual = contextoAprovacaoAtual();
  // O nonce pode ser renovado por um poll 200 sem que a peça tenha mudado.
  // Freshness editorial continua definida somente pelos cinco campos de
  // contexto; o nonce congelado ao abrir o diálogo segue válido uma vez.
  return Object.keys(atual).filter((k) => k !== 'nonce_aprovacao')
    .every((k) => atual[k] === contextoAprovacao[k]);
}

function pintarAprovacao(e) {
  if (!contextoAprovacaoBate()) {
    fecharCaixaAprovar();
    MC.torrar('O conteúdo mudou enquanto a aprovação estava aberta. Revise antes de aprovar.');
  }
  const alvo = (e.fase ?? 1) >= 2 ? 'fase-2' : 'fase-1';
  const validas = (e.aprovacoes || []).filter((a) => a.alvo === alvo && a.valida);
  const ap = validas[validas.length - 1] || null;
  const pil = $('pilula-aprovado');
  const btnAprovar = $('btn-aprovar');
  // O botão some quando já existe aprovação VÁLIDA — e volta sozinho quando o
  // corte muda, porque aí `valida` cai para false no estado. É o mesmo dado que
  // o `qc-portao.py` usa para o exit 2 "aprovou e depois mudou".
  const midiaAprovavel = !!S.bruto?.midia?.rel && !!S.bruto?.midia?.servivel;
  btnAprovar.dataset.elegivel = String(!ap && midiaAprovavel);
  btnAprovar.hidden = !!ap || !midiaAprovavel
    || MC.temPendencia();
  btnAprovar.textContent = alvo === 'fase-2' ? 'Aprovar montagem' : 'Aprovar corte';
  // Se a aprovação chegou por outro caminho (CLI, outra aba) enquanto o diálogo
  // estava aberto, ele fecha: um diálogo pedindo o que já foi feito é o começo de
  // uma aprovação duplicada.
  if ($('btn-aprovar').hidden && caixaAprovarAberta()) fecharCaixaAprovar();
  pil.hidden = !ap;
  if (ap) {
    pil.textContent = `Aprovado${ap.em ? ' ' + ap.em.slice(11, 16) : ''}`;
    pil.title = `${ap.alvo} / por ${ap.por || 'não informado'} / fonte ${ap.fonte || 'não informada'}`
      + (ap.motivo_da_aprovacao ? `\n${ap.motivo_da_aprovacao}` : '');
  }
}

/** O slider REFLETE o zoom, sempre — inclusive quando ele mudou pela pinça do
 *  trackpad, pelo `fit` ou pelos botões. Um slider que só escreve e nunca lê é a
 *  segunda fonte de verdade que o bug report do zoom já custou uma vez. */
function sincZoom(estado = TL.estadoZoom()) {
  const el = $('zoom-slider');
  if (!el) return;
  const ajustado = estado.modo === 'fit';
  const multiplicador = Math.max(0.01, estado.relativo || 1);
  const texto = ajustado ? 'Ajustado' : `${multiplicador.toFixed(1).replace('.', ',')}x`;
  el.value = String(Math.round(estado.normalizado * 1000));
  el.setAttribute('aria-valuetext', ajustado
    ? 'Ajustado, peça inteira visível'
    : `${multiplicador.toFixed(1).replace('.', ',')} vezes o ajuste`);
  el.title = `Zoom da régua: ${texto}`;
  const valor = $('zoom-valor');
  if (valor) valor.textContent = texto;
  $('btn-menos').disabled = estado.noMinimo;
  $('btn-mais').disabled = estado.noMaximo;
}

function atualizarBotoes() {
  const pend = S.marcacoes.filter((m) => !m.enviada).length;
  const inAberto = S.inPendente != null;
  const notaAberta = MC.caixaAberta();
  const temPendencia = MC.temPendencia();
  $('btn-salvar').hidden = pend === 0;
  $('btn-descartar').hidden = pend === 0 && !inAberto;
  /* 🔴 H49-6 (achado A-8, 2026-08-12): o `Salvar` era um DEGRAU SILENCIOSO. A
   * marcação escrita ficava no `localStorage` com `enviada: false` e nunca virava
   * POST — e, do lado do agente, isso é indistinguível de "não escreveu nada". O
   * watcher vigia o DISCO; o buraco é antes dele.
   *
   * Três consertos pequenos, nenhum deles "salvar sozinho" (auto-save mandaria
   * pedido pela metade ao agente): a contagem entra no RÓTULO do botão, a pílula
   * fica em tom de alerta, e sair da página com pendência pede confirmação. */
  const b = $('btn-salvar');
  b.textContent = pend ? `Salvar (${pend})` : 'Salvar';
  b.classList.toggle('urgente', pend > 0);
  const p = $('pilula-pendente');
  p.hidden = !temPendencia;
  p.className = 'pilula' + (temPendencia ? ' pilula--pendente' : '');
  p.textContent = pend ? `${pend} não enviada${pend === 1 ? '' : 's'}`
    : (inAberto ? 'IN aberto' : (notaAberta ? 'Nota aberta' : ''));
  p.title = pend ? 'Quem está editando só recebe essas marcações depois de Salvar.'
    : (inAberto ? 'Marque OUT ou descarte antes de aprovar.'
      : (notaAberta ? 'Conclua ou cancele a nota antes de aprovar.' : ''));
  const aprovar = $('btn-aprovar');
  aprovar.hidden = aprovar.dataset.elegivel !== 'true' || temPendencia;
  aprovar.title = temPendencia
    ? 'Salve ou descarte as marcações antes de aprovar.'
    : (aprovar.textContent || 'Aprovar');
  $('btn-in').textContent = S.inPendente == null ? 'IN' : 'OUT';
  const tr = TL.T.trilhas.find((t) => t.id === 'marcacoes');
  if (tr) tr.redesenhar();
  sincZoom();
}

/* ────────────────────────────────────────────────────────────────── boot */

function boot() {
  /* H49-6: a pendência sobrevive ao fechar a aba (fica no localStorage), mas o
   * AGENTE não a vê. Perguntar é o mínimo — e é o que o relatório de campo pediu
   * ("beforeunload com pendência"). */
  window.addEventListener('beforeunload', (e) => {
    const pend = S.marcacoes.filter((m) => !m.enviada).length;
    const inAberto = S.inPendente != null;
    const notaAberta = MC.caixaAberta();
    if (!pend && !inAberto && !notaAberta) return;
    e.preventDefault();
    e.returnValue = notaAberta && !pend && !inAberto
      ? 'Há uma nota em edição. Conclua ou cancele antes de sair.'
      : inAberto && !pend
      ? 'Há uma marcação IN sem OUT. Conclua ou descarte antes de sair.'
      : `${pend} marcação(ões) não enviada(s): quem está editando não `
        + 'vai vê-las até você clicar em Salvar.';
    return e.returnValue;
  });
  TL.iniciar({
    painel: $('painel'), pista: $('pista'), trilhasEl: $('trilhas'),
    agulha: $('agulha'), regua: $('regua'), video,
    marcaPendente: $('marca-pendente'),
  });
  TL.T.aoBuscar = (t) => { video.pause(); video.currentTime = t; };
  TL.T.aoTempo = (t) => { $('tempo').textContent = mmss(t); };
  TL.T.aoZoom = sincZoom;
  sincZoom();

  MC.iniciar({
    caixa: $('caixa-nota'), txt: $('caixa-texto'), chips: $('caixa-chips'),
    coord: $('caixa-coord'), titulo: $('caixa-titulo'),
    torradeira: $('torradeira'), marcaPendente: $('marca-pendente'),
    btnSalvarNota: $('caixa-salvar'), btnCancelarNota: $('caixa-cancelar'),
    aoMudar: atualizarBotoes,
  });

  $('btn-play').addEventListener('click', tocarPausar);
  $('btn-zonas').addEventListener('click', () => {
    zonasVisiveis = !zonasVisiveis;
    pintarZonas();
  });
  $('btn-in').addEventListener('click', () => MC.alternarMarca());
  $('btn-mais').addEventListener('click', () => TL.zoom(1.35));
  $('btn-menos').addEventListener('click', () => TL.zoom(1 / 1.35));
  // H49-9: o slider e os botões são a MESMA verdade (`T.pps`); o slider só a
  // exibe. Duas fontes de zoom seria o defeito que o bug report descreve.
  $('zoom-slider').addEventListener('input', (e) => {
    TL.aplicarZoomNormalizado(Number(e.target.value) / 1000);
  });
  $('btn-fit').addEventListener('click', () => TL.fit());
  $('btn-salvar').addEventListener('click', async () => {
    const btn = $('btn-salvar');
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    btn.textContent = 'Salvando...';
    try { await MC.salvar(); }
    finally {
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      atualizarBotoes();
    }
  });
  $('btn-aprovar').addEventListener('click', abrirCaixaAprovar);
  $('aprovar-confirmar').addEventListener('click', aprovarCorte);
  $('aprovar-cancelar').addEventListener('click', fecharCaixaAprovar);
  // Os atalhos globais não chegam aqui: `ligarTeclas` sai fora quando o foco está
  // num TEXTAREA, e o foco vai para o textarea ao abrir. Sem estas duas linhas o
  // Esc não fecharia o diálogo — o mesmo Esc que fecha a caixa de nota.
  $('aprovar-texto').addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') { ev.preventDefault(); fecharCaixaAprovar(); }
    if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); aprovarCorte(); }
  });
  $('btn-descartar').addEventListener('click', () => MC.descartar());
  $('btn-atalhos').addEventListener('click', () => {
    definirAtalhos($('atalhos').hidden);
  });
  $('atalhos-fechar').addEventListener('click', () => definirAtalhos(false, true));
  $('atalhos').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); definirAtalhos(false, true); }
  });
  video.addEventListener('loadedmetadata', () => {
    if (S.fmt?.fonte === 'desconhecido') { S.fmt = formatoDaPeca(S.bruto, video); layoutPeloAspecto(); }
    if (!S.dur && isFinite(video.duration)) {
      S.dur = video.duration;
      S.pps0 = true;
      TL.fit({ imediato: true });
    }
  });
  video.addEventListener('play', () => {
    $('btn-play').textContent = '❚❚';
    $('btn-play').setAttribute('aria-label', 'Pausar');
  });
  video.addEventListener('pause', () => {
    $('btn-play').textContent = '▶';
    $('btn-play').setAttribute('aria-label', 'Reproduzir');
  });
  ligarTeclas();

  iniciarPoll({
    aplicar: (novo) => {
      const primeiro = !S.dir;
      aplicar(novo);
      if (primeiro) MC.restaurarRascunho();
      // 🔴 A asserção da gutter roda depois do primeiro DOM real, e LANÇA — fora
      // do try/catch do poll, senão o backoff engoliria o erro e o sintoma
      // (gutter que "some ao rolar") voltaria a não ter causa visível.
      if (!window.__gutterConferida) {
        setTimeout(() => { window.__gutterConferida = TL.conferirCadeiaDoRotulo(); }, 0);
      }
    },
    avisar: MC.avisarUmaVez,
    temPendencia: MC.temPendencia,
  });
}

boot();
