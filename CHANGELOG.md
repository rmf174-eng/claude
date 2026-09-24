# Histórico de versões

Cada rodada de feedback gera uma versão nova. Versões publicadas não são
sobrescritas. O ZIP usa `vX.Y` e o manifesto do plugin usa `X.Y.0`.

## v0.17

Direção de acabamento e planejamento visual guiados pelo feedback de uma edição
que terminou apenas com legendas e precisou receber animações e SFX em rodadas
separadas.

### Escolha de acabamento

- A aba Look começa com uma decisão obrigatória: Essencial, Com animações ou Me
  surpreenda. Não existe escolha implícita em produção nova.
- Essencial fecha em cortes e legenda, sem animações ou SFX. Com animações e Me
  surpreenda já entram no planejamento visual com densidade e política de som.
- Me surpreenda registra a delegação e a direção criativa resolvida, em vez de
  deixar a decisão perdida na conversa.

### Plano visual e som

- O novo `plano-visual.json` descreve cada beat com tempo, intenção, visual,
  zona e decisão sonora.
- Cada animação declara usar SFX, silêncio intencional com motivo ou que som não
  se aplica. Nem todo movimento precisa de som, mas nenhum pode ignorar a
  decisão.
- A Partitura agora consome os SFX declarados no plano visual e posiciona cada
  som no instante absoluto do beat, com ganho explícito e sem deixar o diretor
  legado inventar timing ou áudio.

### Gates de Fase 2

- A Fase 2 não começa sem estilo v3 e plano visual válido, ligados por hash ao
  corte, à timeline real, ao estilo vigente e ao plano editorial.
- Produções Animada ou Surpresa não podem ser entregues apenas com captions.
- O render oficial executa o Remotion com props e pasta pública vinculadas. A
  árvore de assets é congelada por caminho, tamanho e SHA-256 antes e depois da
  execução.
- O QC final verifica artefatos gráficos, referências por evento, existência
  dos assets de SFX e proveniência separada para cada final com ou sem filtro.
  Mudanças posteriores deixam o plano stale e exigem nova validação.

## v0.16

Correções guiadas por uma produção vertical real, sem reduzir limites de QC.

### Integrações e portabilidade

- Transcrição e QCs usam o resolvedor central de credenciais, com precedência
  do ambiente sobre `$ILHA_HOME/.env`, entrada oculta e nenhum `source` manual.
- `qc-cor.py` verifica `avconvert` e registra medição não realizada fora do
  macOS, sem traceback nem referência parcial.
- Testes da timeline não dependem mais da opção experimental removida e foram
  validados em Node 22 e 24.
- CLIs públicas tratam `--help`, argumentos ausentes e caminhos inválidos com
  mensagens curtas e sem traceback.

### Montagem, áudio e qualidade

- J-cut compartilha geometria em amostras inteiras entre montagem e QC, corrige
  a janela anterior ao início do áudio e mantém os limites de 1 amostra e 0,10
  amostra por take.
- Normalização de MP4 usa PCM intermediário, mux com `faststart` e publicação
  atômica somente após validar `moov`, streams, duração e decodificação integral.
- Ganho acima de 6 dB exige justificativa explícita no sidecar, sem de-esser,
  denoise ou limpeza automática.
- Divergência isolada do ASR recebe uma segunda janela com mais contexto e vira
  revisão; falhas acústicas e vazamentos plantados continuam bloqueantes.
- Ausência de `cor.json` aciona o resolvedor oficial. Material não calibrado
  bloqueia e overrides explícitos ficam registrados.
- Pausas acústicas acima do máximo do perfil aparecem como decisão pendente. O
  ajuste automático continua desligado para evitar overcut por timestamp ASR.

## v0.15

Baseline consolidada para o novo ciclo de feedbacks, construída sobre a v0.14.

### Interface e timeline

- Zoom mantém a linha laranja no tempo correto com vídeo pausado ou tocando.
- `Ctrl +`, `Ctrl -`, botões, slider e gesto de pinça usam âncoras coerentes.
- Trackpad, touch, scrub, scrollbars e acompanhamento durante playback foram
  protegidos contra buscas acidentais e perda de posição.
- Timeline real, waveform, filmstrip, marcas IN/OUT e estados de aprovação
  preservam geometria e rascunhos entre abas e redimensionamentos.
- Layout compacto, foco de modais, teclado, contraste e movimento reduzido foram
  revisados para painel lateral e larguras pequenas.

### Montagem e qualidade

- Publicação do MP4 final agora é atômica e preserva o último arquivo válido em
  caso de falha.
- Segmentos temporários não entram no áudio e J-cut desativado não exige campos
  de um plano ativo.
- Timeline medida é a autoridade para palavras, SRT, preview e janelas de QC.
- Comparação ASR trata ordem, repetição, multiplicidade, numerais e revisão
  humana sem aprovações silenciosas.
- Gates de cor detectam perfil alterado, múltiplas fontes e configuração stale.
- O orçamento de pausa por ASR permanece desligado por padrão até calibração
  acústica suficiente.

### Distribuição e segurança

- Plugin compartilhado entre Codex e Claude com aliases byte a byte idênticos.
- Preview cloud possui contrato explícito e mantém fallback local em loopback.
- Aprovação ganhou nonce de sessão e contexto, e o pacote ganhou varredura de
  segredos em conteúdo, nomes de arquivo e ZIPs.
- Export e testes foram ampliados para incluir as correções novas da árvore de
  trabalho, mesmo antes de um commit formal.
