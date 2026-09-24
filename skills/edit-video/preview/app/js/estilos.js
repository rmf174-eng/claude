/* Aba ESTILO da UI de aprovação — o elo que faltava (SPEC-19 §3.4).
 *
 * ────────────────────────────────────────────────────────────────────────────
 * 🔴 POR QUE ESTE ARQUIVO NÃO EXISTIA
 *
 * A galeria estava inteira e testada (`galeria/galeria.js`, contrato próprio,
 * previews de dois níveis, interruptores), e o app tinha o ponto de extensão
 * pronto (`main.js:registrarAba`). Ninguém ligava os dois: a SPEC-18 escreveu
 * que a SPEC-19 acrescentaria `js/estilos.js`, e a SPEC-19 escreveu que a
 * SPEC-18 colaria o snippet. Cada uma delegou para a outra e o snippet ficou só
 * no `galeria/README.md`. Resultado medido: a galeria só abria à mão, noutro
 * endereço, e a aba nunca apareceu na UI.
 *
 * Duas coisas que o snippet do README não dizia, e sem as quais isto não roda:
 *
 * 1. O `galeria.json` NÃO é vizinho da página. Ele mora em
 *    `<producao>/.preview/estilos/`, e a rota `/media/` recusa tudo sob
 *    `.preview/` (403, de propósito). Por isso o servidor ganhou a rota
 *    `galeria/` no mesmo commit que este arquivo, e é dela que a aba lê.
 *
 * 2. A aba precisa DESMONTAR. `montarGaleria` devolve `{destruir}` porque ela
 *    deixa `<video>` tocando e um timer rodando; trocar de aba sem chamar isso
 *    deixa preview tocando por baixo da timeline. `main.js:trocarAba` passou a
 *    honrar o `destruir` que o `montar()` devolver.
 *
 * O SAVE FECHA O LOOP. `base: '.'` faz a galeria postar em `api/salvar`, que o
 * servidor já tem (SPEC-17) e que grava um arquivo NOVO em
 * `<produção>/.preview/pendentes/` — fila append-only, nada é sobrescrito.
 * Salvar 5 vezes gera 5 eventos.
 *
 * ⚠️ E ISSO SÓ VIRA TRABALHO SE O WATCHER ESTIVER ARMADO. Com o servidor no ar e
 * o Monitor desarmado, o creator escolhe o estilo, vê o toast de confirmação e
 * NADA acontece — ele acha que avisou, e ninguém ouviu. Falha silenciosa dos dois
 * lados. Quem arma é a skill, no MESMO turno em que sobe o servidor:
 *
 *     Monitor(command="python3 <skill>/preview/watch-preview.py '<produção>'",
 *             description="escolhas e marcações salvas no preview",
 *             persistent=true)
 */
import { montarGaleria } from '../galeria/galeria.js';

const { registrarAba, aoAplicar, S } = window.__preview;

let viva = null;
let rascunho = null;
let chaveRascunho = null;

/* A galeria é desmontada ao trocar de aba. O rascunho continua em memória,
 * portanto a proteção de saída também precisa viver fora dela: recarregar em
 * Corte não pode apagar silenciosamente uma direção ainda não enviada em Look. */
function temRascunhoPendente() {
  const atual = viva?.rascunho?.();
  return atual ? !!atual.sujo : !!rascunho?.sujo;
}

function protegerSaidaComRascunho(e) {
  if (!temRascunhoPendente()) return;
  e.preventDefault();
  e.returnValue = 'Há escolhas de look que ainda não foram enviadas.';
  return e.returnValue;
}

window.addEventListener('beforeunload', protegerSaidaComRascunho);

function montar() {
  const chave = `${S.dir || ''}|${S.chave || ''}`;
  if (chaveRascunho !== chave) {
    rascunho = null;
    chaveRascunho = chave;
  }
  const host = document.createElement('div');
  host.className = 'aba-estilo';

  // `base: '.'` faz a galeria montar `./api/estado` — caminho relativo à página,
  // que já é servida sob `/<token>/`. O token nunca aparece no código do app,
  // e é assim que se quer: ele está na URL e em mais lugar nenhum.
  const g = montarGaleria(host, {
    base: '.',
    galeria: 'galeria/galeria.json',   // rota do servidor, não o dir `estilos/` da raiz
    rascunho,
  });

  viva = g;
  return { el: host, destruir: () => {
    try {
      const atual = g.rascunho?.();
      rascunho = atual?.sujo ? atual : null;
      g.destruir();
    } finally { viva = null; }
  }, podeDesmontar: () => g.podeDestruir?.() !== false };
}

// `estado.py <dir> --portao estilo` é o que ABRE a aba. Enquanto o corte não foi
// aprovado ela fica desabilitada, e enquanto houver estilo aplicado ela CONTINUA
// aberta — é assim que o creator volta, troca uma legenda e salva de novo. Essa
// segunda gravação chega com `rerender: true` no payload, e o watcher a anuncia
// como REFAÇA, não como primeira escolha.
function estadoDaAba(e) {
  const portao = e?.portao === 'estilo';
  const jaTem = !!(e?.estilo || e?.estilo_vigente);
  return { habilitada: portao || jaTem, refazer: !portao && jaTem };
}

aoAplicar((e) => {
  const { habilitada, refazer } = estadoDaAba(e);
  // O "já tem estilo aplicado, e dá para trocar" era o caractere `✎` colado no
  // rótulo. Virou um PONTO desenhado (`app.css .aba-marca`) com o significado
  // escrito no `title` — a regra escrita desta galeria proíbe caractere gráfico
  // como ícone, e valia para a aba dela também.
  registrarAba({
    id: 'estilo', rotulo: 'Look', ordem: 1.5, montar, habilitada,
    marcador: refazer,
    dica: refazer
      ? 'Já há um look aplicado. Abra para trocar e refazer a montagem.'
      : (habilitada ? 'escolher como a peça vai parecer' : 'abre quando o corte for aprovado'),
  });
});

registrarAba({
  id: 'estilo',
  rotulo: 'Look',
  // fecha até o primeiro /api/estado dizer que o portão abriu — uma aba que abre
  // antes da hora convida o creator a escolher o look de um corte não aprovado.
  habilitada: false,
  // 1.5 põe a aba ENTRE "FASE 1 · corte" (1) e "FASE 2 · visual" (2), que é a
  // ordem do trabalho: escolhe-se o estilo depois de aprovar o corte e antes de
  // montar o visual. O número está no contrato de `registrarAba`, não aqui.
  ordem: 1.5,
  montar,
});

export { viva };
