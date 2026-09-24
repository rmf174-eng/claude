/* Comportamento modal compartilhado pelas caixas da Ilha.
 *
 * `aria-modal` só é verdade quando o fundo fica inerte, o foco não escapa pelo
 * Tab e volta ao disparador ao fechar. Este módulo mantém esse contrato sem
 * acoplar a caixa de marcação à caixa de aprovação. */

const abertas = new Map();
const SELETOR_FOCO = [
  'button:not([disabled])',
  'input:not([disabled])',
  'textarea:not([disabled])',
  'select:not([disabled])',
  'a[href]',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function focaveis(el) {
  return [...el.querySelectorAll(SELETOR_FOCO)]
    .filter((n) => !n.hidden && n.getAttribute('aria-hidden') !== 'true');
}

export function abrirModal(el, { foco = null, retorno = document.activeElement,
                                 fallback = null, aoEscape = null } = {}) {
  if (!el || abertas.has(el)) return;
  const fundo = [];
  for (const n of document.body.children) {
    // Live regions continuam anunciando erros da própria caixa. A torradeira
    // não tem controles nem recebe ponteiro, então não abre o fundo à interação.
    if (n === el || n.tagName === 'SCRIPT' || n.hasAttribute('aria-live')) continue;
    fundo.push([n, !!n.inert]);
    n.inert = true;
  }
  const aoTeclar = (e) => {
    if (e.defaultPrevented) return;
    if (e.key === 'Escape' && aoEscape) {
      e.preventDefault();
      aoEscape();
      return;
    }
    if (e.key !== 'Tab') return;
    const lista = focaveis(el);
    if (!lista.length) {
      e.preventDefault();
      el.focus();
      return;
    }
    const primeiro = lista[0];
    const ultimo = lista[lista.length - 1];
    if (e.shiftKey && (document.activeElement === primeiro || !el.contains(document.activeElement))) {
      e.preventDefault();
      ultimo.focus();
    } else if (!e.shiftKey && document.activeElement === ultimo) {
      e.preventDefault();
      primeiro.focus();
    }
  };
  el.tabIndex = -1;
  el.addEventListener('keydown', aoTeclar);
  abertas.set(el, { fundo, retorno, fallback, aoTeclar });
  (foco || focaveis(el)[0] || el).focus();
}

export function fecharModal(el) {
  const estado = abertas.get(el);
  if (!estado) return;
  abertas.delete(el);
  el.removeEventListener('keydown', estado.aoTeclar);
  for (const [n, eraInerte] of estado.fundo) n.inert = eraInerte;
  Promise.resolve().then(() => {
    const r = estado.retorno;
    const alvo = r?.isConnected && !r.disabled && !r.hidden && !r.inert
      ? r : estado.fallback;
    alvo?.focus?.();
  });
}
