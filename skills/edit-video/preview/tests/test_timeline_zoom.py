"""Contrato comportamental do zoom da timeline, executado contra o JS real.

O teste usa Node apenas como runtime de ES modules. O DOM abaixo e deliberadamente
minimo: nao existe jsdom, Playwright, browser ou copia da matematica do produto.
Toda transformacao exercitada vem de ``app/js/timeline.js``.

O gate protege a invariavel que o aceite visual antigo nao media: depois de
qualquer mudanca de escala, cada indicador ainda deve representar o mesmo
instante. Mudar somente a largura da pista nao e suficiente.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


TIMELINE = Path(__file__).resolve().parents[1] / "app" / "js" / "timeline.js"
NODE = shutil.which("node")


HARNESS = r"""
import { pathToFileURL } from 'node:url';

const caminhoTimeline = process.argv[1];
if (!caminhoTimeline) throw new Error('harness: caminho de timeline.js ausente');

const quase = (recebido, esperado, tolerancia, mensagem) => {
  if (!Number.isFinite(recebido) || Math.abs(recebido - esperado) > tolerancia) {
    throw new Error(`${mensagem}: recebido=${recebido}, esperado=${esperado}, `
      + `tolerancia=${tolerancia}`);
  }
};
const afirmar = (condicao, mensagem) => {
  if (!condicao) throw new Error(mensagem);
};
const px = (elemento) => Number.parseFloat(elemento.style.left || 'NaN');

class ElementoFalso {
  constructor({ largura = 0, altura = 240, esquerda = 0 } = {}) {
    this.clientWidth = largura;
    this.clientHeight = altura;
    this.offsetWidth = largura;
    this.offsetHeight = altura;
    this.esquerda = esquerda;
    this.scrollLeft = 0;
    this.scrollTop = 0;
    this.scrollWidth = largura;
    this.scrollHeight = altura;
    this.style = {};
    this.listeners = new Map();
    this.hidden = false;
    this.textContent = '';
    this.className = '';
    this.tagName = 'DIV';
    this.parentElement = null;
    this.children = [];
    this.capturas = new Set();
  }
  addEventListener(tipo, fn) {
    const lista = this.listeners.get(tipo) || [];
    lista.push(fn);
    this.listeners.set(tipo, lista);
  }
  emitir(tipo, dados = {}) {
    const evento = {
      type: tipo,
      button: 0,
      pointerId: 1,
      pointerType: 'mouse',
      clientX: this.esquerda,
      clientY: 0,
      deltaX: 0,
      deltaY: 0,
      deltaMode: 0,
      ctrlKey: false,
      metaKey: false,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      target: this,
      ...dados,
    };
    for (const fn of this.listeners.get(tipo) || []) fn(evento);
    return evento;
  }
  getBoundingClientRect() {
    return { left: this.esquerda, top: 0, width: this.clientWidth,
      height: this.clientHeight, right: this.esquerda + this.clientWidth,
      bottom: this.clientHeight };
  }
  closest() { return null; }
  setPointerCapture(id) { this.capturas.add(id); }
  releasePointerCapture(id) { this.capturas.delete(id); }
  appendChild(filho) { this.children.push(filho); return filho; }
  append(...filhos) { this.children.push(...filhos); }
  setAttribute() {}
  removeAttribute() {}
  focus() {}
  blur() {}
}

const filaRaf = [];
globalThis.requestAnimationFrame = (fn) => { filaRaf.push(fn); return filaRaf.length; };
globalThis.cancelAnimationFrame = () => {};
const executarQuadro = () => {
  const quadro = filaRaf.splice(0, filaRaf.length);
  for (const fn of quadro) fn(16.667);
  return quadro.length;
};

const listenersJanela = new Map();
globalThis.window = {
  devicePixelRatio: 1,
  innerWidth: 1280,
  innerHeight: 720,
  requestAnimationFrame: globalThis.requestAnimationFrame,
  cancelAnimationFrame: globalThis.cancelAnimationFrame,
  addEventListener(tipo, fn) {
    const lista = listenersJanela.get(tipo) || [];
    lista.push(fn);
    listenersJanela.set(tipo, lista);
  },
};
globalThis.document = {
  visibilityState: 'visible',
  documentElement: { style: { setProperty() {} } },
  body: new ElementoFalso(),
  querySelector() { return null; },
  createElement() { return new ElementoFalso(); },
};
globalThis.getComputedStyle = () => ({
  color: 'rgb(255, 255, 255)',
  backgroundColor: 'rgb(20, 20, 20)',
  overflow: 'visible', overflowX: 'visible', overflowY: 'visible',
  borderLeftWidth: '0px', borderRightWidth: '0px',
  borderTopWidth: '0px', borderBottomWidth: '0px',
  getPropertyValue(nome) { return nome === '--scrollbar-timeline' ? '8px' : ''; },
});
globalThis.ResizeObserver = class {
  constructor(fn) { this.fn = fn; }
  observe() {}
  disconnect() {}
};
globalThis.WheelEvent = {
  DOM_DELTA_PIXEL: 0,
  DOM_DELTA_LINE: 1,
  DOM_DELTA_PAGE: 2,
};

const timelineUrl = pathToFileURL(caminhoTimeline);
const TL = await import(timelineUrl.href + '?contrato-zoom');
const { S } = await import(new URL('./estado.js', timelineUrl));

function montar({ duracao = 120, largura = 900, tempo = 30,
                  pps = 20, scroll = 100 } = {}) {
  filaRaf.length = 0;
  S.dur = duracao;
  S.inPendente = null;
  S.reguaExata = true;
  const painel = new ElementoFalso({ largura, esquerda: 100 });
  painel.scrollLeft = scroll;
  const pista = new ElementoFalso();
  const trilhasEl = new ElementoFalso();
  const agulha = new ElementoFalso();
  const marcaPendente = new ElementoFalso();
  marcaPendente.hidden = true;
  const video = new ElementoFalso();
  video.currentTime = tempo;
  video.paused = true;

  TL.T.pps = pps;
  TL.T.trilhas = [];
  TL.T.aoZoom = null;
  TL.T.aoTempo = null;
  TL.T.aoBuscar = null;
  TL.T.modoZoom = 'manual';
  TL.T.redesenhoPendente = false;
  TL.T.larguraVista = largura;
  TL.T.scrollEsperado = null;
  TL.T.seguirSuspenso = false;
  // Cada caso equivale a uma nova carga da pagina. Como o modulo real e
  // importado uma unica vez neste processo, zere tambem os ids de RAF que o
  // browser descartaria ao descarregar o documento anterior.
  TL.T.rafRedesenho = 0;
  TL.T.rafRegua = 0;
  TL.T.rafResize = 0;
  TL.iniciar({ painel, pista, trilhasEl, agulha, regua: null, video,
    marcaPendente });
  painel.scrollLeft = scroll;
  TL.T.pps = pps;
  TL.aplicarLargura();
  agulha.style.left = TL.xDeTempo(tempo) + 'px';
  return { painel, pista, trilhasEl, agulha, marcaPendente, video };
}

function telaX(elemento, painel) {
  return px(elemento) - painel.scrollLeft;
}

const resultados = [];
async function caso(nome, fn) {
  try {
    await fn();
    resultados.push({ nome, ok: true });
    console.log(`OK ${nome}`);
  } catch (erro) {
    resultados.push({ nome, ok: false, erro: erro?.message || String(erro) });
    console.error(`FALHA ${nome}: ${erro?.message || erro}`);
  }
}

await caso('zoom pausado mantem currentTime e reprojeta a agulha', () => {
  const c = montar({ tempo: 30.002, pps: 10, scroll: 100 });
  const tempoAntes = c.video.currentTime;
  TL.zoom(1.35);
  quase(c.video.currentTime, tempoAntes, 1e-12,
    'zoom alterou video.currentTime');
  quase(px(c.agulha), TL.xDeTempo(tempoAntes), 0.01,
    'linha laranja ficou na coordenada da escala anterior');
});

await caso('zoom de teclado ou botao preserva a agulha visivel na tela', () => {
  const c = montar({ tempo: 30, pps: 10, scroll: 100 });
  const antes = telaX(c.agulha, c.painel);
  TL.zoom(1.35);
  const depois = telaX(c.agulha, c.painel);
  quase(depois, antes, 0.01,
    'ancora padrao moveu a agulha visivel na viewport');
});

await caso('zoom explicito preserva o instante sob o ponteiro', () => {
  const c = montar({ tempo: 12, pps: 20, scroll: 160 });
  const ancoraX = 500;
  const tempoSobPonteiro = TL.tempoDeX(ancoraX + c.painel.scrollLeft);
  TL.zoom(1.6, ancoraX);
  const tempoDepois = TL.tempoDeX(ancoraX + c.painel.scrollLeft);
  quase(tempoDepois, tempoSobPonteiro, 1e-9,
    'pinça mudou o instante sob o ponteiro');
});

await caso('slider e consumidores recebem uma unica notificacao por zoom', () => {
  montar({ tempo: 20, pps: 20 });
  afirmar(typeof TL.estadoZoom === 'function',
    'timeline.js precisa exportar estadoZoom() para haver uma verdade observavel do zoom');
  const notificacoes = [];
  TL.T.aoZoom = (estado) => notificacoes.push(estado);
  TL.zoom(1.25);
  afirmar(notificacoes.length === 1,
    `aoZoom deveria receber 1 notificacao apos zoom(), recebeu ${notificacoes.length}`);
  const alvo = 0.63;
  TL.aplicarZoomNormalizado(alvo);
  afirmar(notificacoes.length === 2,
    `aoZoom deveria receber 1 notificacao pelo slider, total=${notificacoes.length}`);
  quase(TL.zoomNormalizado(), alvo, 1e-9,
    'slider normalizado divergiu do pps efetivamente aplicado');
  const estado = TL.estadoZoom();
  afirmar(estado && Number.isFinite(estado.pps),
    'estadoZoom() nao informou o pps corrente');
  quase(estado.pps, TL.T.pps, 1e-9,
    'estadoZoom().pps divergiu de T.pps');
});

await caso('fit mostra integralmente uma duracao longa', () => {
  const c = montar({ duracao: 1800, largura: 800, tempo: 900,
    pps: 40, scroll: 500 });
  TL.fit();
  const larguraPista = Number.parseFloat(c.pista.style.width);
  afirmar(larguraPista <= c.painel.clientWidth + 0.01,
    `fit de 30 min deixou pista com ${larguraPista}px em painel de ${c.painel.clientWidth}px`);
  afirmar(TL.T.pps > 0 && TL.T.pps < 2,
    `fit longo ficou preso ao minimo manual: pps=${TL.T.pps}`);
  quase(c.painel.scrollLeft, 0, 1e-9,
    'fit nao voltou ao inicio da peca');
  quase(px(c.agulha), TL.xDeTempo(c.video.currentTime), 0.01,
    'fit nao reprojetou a linha laranja');
});

await caso('duracao tardia ainda recebe o primeiro fit valido', () => {
  const c = montar({ duracao: 0, largura: 800, tempo: 0, pps: 40, scroll: 0 });
  TL.fit({ imediato: true });
  S.dur = 600;
  TL.fit({ imediato: true });
  const larguraPista = Number.parseFloat(c.pista.style.width);
  afirmar(larguraPista <= c.painel.clientWidth + 0.01,
    `metadado tardio deixou pista com ${larguraPista}px em painel de ${c.painel.clientWidth}px`);
  afirmar(TL.T.modoZoom === 'fit', 'metadado tardio nao preservou o modo fit');
});

await caso('IN pendente e reprojetado no mesmo commit de escala', () => {
  const c = montar({ tempo: 18, pps: 12, scroll: 80 });
  S.inPendente = 18;
  c.marcaPendente.hidden = false;
  c.marcaPendente.style.left = TL.xDeTempo(S.inPendente) + 'px';
  TL.zoom(1.8);
  quase(px(c.marcaPendente), TL.xDeTempo(S.inPendente), 0.01,
    'linha de IN ficou na coordenada da escala anterior');
});

await caso('rajada de pinça coalesce redesenho e preserva a ancora', () => {
  const c = montar({ tempo: 24, pps: 20, scroll: 160 });
  let redesenhos = 0;
  TL.T.trilhas = [{ redesenhar() { redesenhos += 1; } }];
  const ancoraX = 450;
  const tempoSobPonteiro = TL.tempoDeX(ancoraX + c.painel.scrollLeft);
  for (let i = 0; i < 20; i += 1) {
    const ev = c.painel.emitir('wheel', {
      ctrlKey: true,
      clientX: c.painel.esquerda + ancoraX,
      deltaY: -2,
      deltaMode: WheelEvent.DOM_DELTA_PIXEL,
    });
    afirmar(ev.defaultPrevented, 'pinça ctrl+wheel não foi consumida pela timeline');
  }
  executarQuadro();
  afirmar(redesenhos === 1,
    `20 eventos na mesma frame causaram ${redesenhos} redesenhos, esperado 1`);
  const tempoDepois = TL.tempoDeX(ancoraX + c.painel.scrollLeft);
  quase(tempoDepois, tempoSobPonteiro, 1e-7,
    'rajada de pinça perdeu o instante sob o ponteiro');
});

await caso('pinça normaliza pixel linha e pagina e ignora wheel comum', () => {
  const razao = (deltaY, deltaMode) => {
    const c = montar({ pps: 20, scroll: 120 });
    const antes = TL.T.pps;
    const ev = c.painel.emitir('wheel', {
      ctrlKey: true,
      clientX: c.painel.esquerda + 420,
      deltaY,
      deltaMode,
    });
    afirmar(ev.defaultPrevented, `pinça deltaMode=${deltaMode} nao foi consumida`);
    return TL.T.pps / antes;
  };
  const pixel = razao(-16, WheelEvent.DOM_DELTA_PIXEL);
  const linha = razao(-1, WheelEvent.DOM_DELTA_LINE);
  const pagina = razao(-16 / 240, WheelEvent.DOM_DELTA_PAGE);
  quase(linha, pixel, 1e-12, 'delta em linha mudou a sensibilidade da pinça');
  quase(pagina, pixel, 1e-12, 'delta em pagina mudou a sensibilidade da pinça');

  const c = montar({ pps: 20 });
  const antes = TL.T.pps;
  const comum = c.painel.emitir('wheel', { deltaY: -80 });
  afirmar(!comum.defaultPrevented, 'wheel comum foi sequestrado pela timeline');
  quase(TL.T.pps, antes, 1e-12, 'wheel comum alterou o zoom');
  const meta = c.painel.emitir('wheel', { metaKey: true, deltaY: -80 });
  afirmar(!meta.defaultPrevented, 'Meta+wheel isolado foi tratado como pinça');
  quase(TL.T.pps, antes, 1e-12, 'Meta+wheel isolado alterou o zoom');
});

await caso('resize recalcula fit e preserva pps no modo manual', () => {
  const c = montar({ duracao: 120, largura: 900, pps: 20, scroll: 0 });
  TL.fit({ imediato: true });
  c.painel.clientWidth = 620;
  TL.T.observador.fn();
  executarQuadro();
  afirmar(Number.parseFloat(c.pista.style.width) <= 620.01,
    'resize em fit deixou a pista maior que o painel');

  TL.zoom(1.35);
  const manual = TL.T.pps;
  c.painel.clientWidth = 1200;
  TL.T.observador.fn();
  executarQuadro();
  quase(TL.T.pps, manual, 1e-12,
    'resize em modo manual mudou silenciosamente a escala');
  afirmar(TL.estadoZoom().modo === 'manual',
    'resize em modo manual voltou silenciosamente para fit');
});

await caso('zoom sem efeito no limite preserva o modo fit', () => {
  const c = montar({ duracao: 80, largura: 820, pps: 20, scroll: 0 });
  TL.fit({ imediato: true });
  const ajustado = TL.T.pps;
  TL.zoom(0.5);
  quase(TL.T.pps, ajustado, 1e-12,
    'zoom-out no limite alterou a escala ajustada');
  afirmar(TL.estadoZoom().modo === 'fit',
    'gesto sem efeito desligou o auto-fit');
  c.painel.clientWidth = 1120;
  c.painel.offsetWidth = 1120;
  TL.T.observador.fn();
  executarQuadro();
  afirmar(TL.T.pps > ajustado,
    'resize nao recalculou a escala depois do gesto no limite');
  afirmar(TL.estadoZoom().modo === 'fit',
    'resize perdeu o modo fit depois do gesto no limite');
});

await caso('painel oculto adia desenho e se recupera ao reaparecer', () => {
  const c = montar({ largura: 820, tempo: 30, pps: 18, scroll: 120 });
  const escala = TL.T.pps;
  c.painel.clientWidth = 0;
  TL.redesenhar();
  TL.zoom(1.35);
  quase(TL.T.pps, escala, 1e-12, 'zoom alterou timeline oculta');
  afirmar(TL.T.redesenhoPendente, 'painel oculto nao marcou recuperacao pendente');
  c.painel.clientWidth = 820;
  afirmar(TL.aoMostrar(), 'aoMostrar nao recuperou o painel visivel');
  quase(px(c.agulha), TL.xDeTempo(c.video.currentTime), 0.01,
    'retorno ao painel deixou agulha em geometria antiga');
  afirmar(Number.parseFloat(c.pista.style.width) > 0,
    'retorno ao painel deixou pista zerada');
});

await caso('playback segue a agulha mas respeita pan manual', () => {
  const c = montar({ duracao: 120, largura: 500, tempo: 100, pps: 20, scroll: 0 });
  c.video.paused = false;
  c.video.emitir('play');
  afirmar(c.painel.scrollLeft > 0, 'playback nao trouxe a agulha para a viewport');
  c.painel.emitir('scroll');

  const antesVertical = c.painel.scrollLeft;
  c.painel.emitir('wheel', { deltaX: 0, deltaY: 50 });
  c.painel.scrollTop = 40;
  c.painel.emitir('scroll');
  c.video.currentTime = 119;
  TL.seguirAgulha();
  afirmar(c.painel.scrollLeft !== antesVertical,
    'rolagem vertical suspendeu o acompanhamento horizontal');
  c.painel.emitir('scroll');

  c.painel.scrollLeft = 123;
  c.painel.emitir('wheel', { deltaX: 60, deltaY: 0 });
  c.painel.scrollLeft = 183;
  c.painel.emitir('scroll');
  c.video.currentTime = 115;
  TL.seguirAgulha();
  quase(c.painel.scrollLeft, 183, 1e-12,
    'acompanhamento disputou scroll com o pan manual');

  c.video.emitir('play');
  afirmar(c.painel.scrollLeft !== 183,
    'nova reproducao nao reativou o acompanhamento da agulha');
});

await caso('toque distingue tap pan vertical scrub horizontal e multitoque', () => {
  const c = montar({ largura: 700, tempo: 10, pps: 20, scroll: 0 });
  let buscas = 0;
  TL.T.aoBuscar = () => { buscas += 1; };

  c.painel.emitir('pointerdown', {
    pointerType: 'touch', pointerId: 11,
    clientX: c.painel.esquerda + 300, clientY: 80,
  });
  c.painel.emitir('pointermove', {
    pointerType: 'touch', pointerId: 11,
    clientX: c.painel.esquerda + 302, clientY: 110,
  });
  c.painel.emitir('pointerup', {
    pointerType: 'touch', pointerId: 11,
    clientX: c.painel.esquerda + 302, clientY: 110,
  });
  afirmar(buscas === 0,
    `pan vertical produziu ${buscas} seeks antes de rolar`);

  c.painel.emitir('pointerdown', {
    pointerType: 'touch', pointerId: 12,
    clientX: c.painel.esquerda + 320, clientY: 80,
  });
  c.painel.emitir('pointerup', {
    pointerType: 'touch', pointerId: 12,
    clientX: c.painel.esquerda + 320, clientY: 80,
  });
  afirmar(buscas === 1, `tap produziu ${buscas} seeks; esperado 1`);

  c.painel.emitir('pointerdown', {
    pointerType: 'touch', pointerId: 13,
    clientX: c.painel.esquerda + 330, clientY: 80,
  });
  c.painel.emitir('pointermove', {
    pointerType: 'touch', pointerId: 13,
    clientX: c.painel.esquerda + 350, clientY: 82,
  });
  c.painel.emitir('pointermove', {
    pointerType: 'touch', pointerId: 13,
    clientX: c.painel.esquerda + 390, clientY: 82,
  });
  c.painel.emitir('pointerup', {
    pointerType: 'touch', pointerId: 13,
    clientX: c.painel.esquerda + 390, clientY: 82,
  });
  afirmar(buscas === 3,
    `scrub horizontal levou o total a ${buscas} seeks; esperado 3`);

  const antesMultitoque = buscas;
  c.painel.emitir('pointerdown', {
    pointerType: 'touch', pointerId: 21,
    clientX: c.painel.esquerda + 300, clientY: 80,
  });
  c.painel.emitir('pointerdown', {
    pointerType: 'touch', pointerId: 22,
    clientX: c.painel.esquerda + 360, clientY: 80,
  });
  c.painel.emitir('pointermove', {
    pointerType: 'touch', pointerId: 21,
    clientX: c.painel.esquerda + 420, clientY: 80,
  });
  c.painel.emitir('pointerup', {
    pointerType: 'touch', pointerId: 21,
    clientX: c.painel.esquerda + 420, clientY: 80,
  });
  c.painel.emitir('pointerup', {
    pointerType: 'touch', pointerId: 22,
    clientX: c.painel.esquerda + 360, clientY: 80,
  });
  afirmar(buscas === antesMultitoque,
    `multitoque produziu ${buscas - antesMultitoque} seeks`);
});

await caso('barras de rolagem nao iniciam scrub nem captura', () => {
  const c = montar({ largura: 700, tempo: 10, pps: 20, scroll: 0 });
  c.painel.scrollWidth = 1400;
  c.painel.scrollHeight = 600;
  let buscas = 0;
  TL.T.aoBuscar = () => { buscas += 1; };
  c.painel.emitir('pointerdown', {
    pointerId: 31, clientX: c.painel.esquerda + 697, clientY: 100,
  });
  c.painel.emitir('pointerdown', {
    pointerId: 32, clientX: c.painel.esquerda + 350, clientY: 237,
  });
  afirmar(buscas === 0, `barras nativas produziram ${buscas} seeks`);
  afirmar(c.painel.capturas.size === 0,
    'barra nativa foi sequestrada por setPointerCapture');
  c.painel.emitir('pointerdown', {
    pointerId: 33, clientX: c.painel.esquerda + 350, clientY: 100,
  });
  afirmar(buscas === 1, 'superficie util deixou de iniciar scrub por mouse');
  afirmar(c.painel.capturas.has(33),
    'scrub valido nao capturou o ponteiro');
  c.painel.emitir('pointerup', {
    pointerId: 33, clientX: c.painel.esquerda + 350, clientY: 100,
  });
});

await caso('controle negativo detecta uma coordenada laranja congelada', () => {
  const c = montar({ tempo: 30, pps: 10, scroll: 100 });
  const esquerdaVelha = px(c.agulha);
  TL.T.pps *= 1.35;
  c.agulha.style.left = esquerdaVelha + 'px';
  let detectou = false;
  try {
    quase(px(c.agulha), TL.xDeTempo(c.video.currentTime), 0.01,
      'controle negativo: linha congelada nao detectada');
  } catch (erro) {
    detectou = String(erro.message).includes('linha congelada');
  }
  afirmar(detectou,
    'controle negativo falhou: o oraculo nao acusa a regressao original');
});

const falhas = resultados.filter((r) => !r.ok);
if (falhas.length) {
  console.error(`RESUMO: ${falhas.length}/${resultados.length} casos falharam em ${caminhoTimeline}`);
  process.exitCode = 1;
} else {
  console.log(`RESUMO: ${resultados.length}/${resultados.length} casos verdes em ${caminhoTimeline}`);
}
"""


def test_contrato_comportamental_do_zoom_da_timeline_real():
    """Executa dezesseis invariantes contra o modulo entregue, sem copiar o zoom."""

    assert TIMELINE.is_file(), f"timeline.js real nao encontrado: {TIMELINE}"
    assert NODE, "Node e obrigatorio para validar o ES module timeline.js real"
    ambiente = dict(os.environ)
    ambiente["NODE_NO_WARNINGS"] = "1"
    resultado = subprocess.run(
        [
            NODE,
            "--input-type=module",
            "-e",
            HARNESS,
            str(TIMELINE),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=ambiente,
    )
    saida = "\n".join(x for x in (resultado.stdout, resultado.stderr) if x).strip()
    assert resultado.returncode == 0, (
        "Contrato do zoom reprovado. Cada linha FALHA nomeia a invariavel quebrada.\n"
        + saida
    )
    assert "RESUMO: 16/16 casos verdes" in saida, (
        "Harness terminou sem comprovar os dezesseis casos esperados:\n" + saida
    )


if __name__ == "__main__":
    test_contrato_comportamental_do_zoom_da_timeline_real()
    print("16 casos verdes: geometria, entradas, resize, abas, playback, touch e scroll")
