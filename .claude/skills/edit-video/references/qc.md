# QC e entrega — etapa 8 · **e a UI de aprovação, que é etapa 6**

> O corpo da etapa **8**, o bloco mais denso deste repo em lição medida: os QCs visuais, a bateria orquestrada e a prova pela imagem. Quem está na etapa 2 não precisa abrir este arquivo.
>
> 🔴 **Mas a seção "Onde a UI aparece" (§ mais abaixo) é da ETAPA 6, não da 8.** Se
> você está no portão do corte, é aqui que está como subir o servidor de preview e
> armar o watcher — **abra este arquivo antes de aprovar qualquer coisa**. Medido em
> 2026-08-09: uma produção inteira foi da montagem à
> entrega **sem `.preview/` no disco**, porque o título deste arquivo diz "etapa 8" e
> o agente estava na 6. Ele gerou um `.mp4` proxy e mandou no chat no lugar da UI —
> o passo não falhou, foi substituído, e a sessão reportou sucesso.

---

### 8. QC visual e entrega (obrigatório ANTES de entregar)
- **QC de estado FINAL desenhado**: pra CADA elemento gráfico, extrair um frame no momento em que ele está 100% construído (fim do write-on/traço) e OLHAR a imagem (Read). Validar no meio da animação esconde bug — o círculo cortando texto e o sublinhado riscando a linha errada da peca-04 só apareceram no estado final.
- Checklist por frame: elemento inteiro dentro da zona segura? traço cruza alguma letra? quebra de linha certa? rosto livre? legenda certa?
- **QC geométrico pelo ALPHA (numérico, não no olho)**: renderizar os stills da composição `Graphics` (fundo transparente) e tirar a bbox do canal alpha → posição exata de cada elemento vs a zona segura (y>290, y<1500, x<924). Pegou 5 transbordos da coluna de botões do feed na peca-03. ⚠️ **NÃO** tente isolar o gráfico diffando o still de `Main` contra o frame do vídeo: o decode do Chrome difere do ffmpeg e o diff acende o frame inteiro.
- **QC de montagem por transcript**: retranscrever o montado e ler palavra a palavra procurando sílaba fantasma/palavra decepada nas emendas.
- **QC de A/V sync (obrigatório em talking-head)**: vale de energia do áudio em cada emenda vs a fronteira de frames do vídeo (soma dos `nb_read_frames` dos segmentos). Tem que dar ±3ms **sem tendência**. Se houver tendência crescente, é deriva de montagem (ver etapa 2) — e o teste definitivo é olhar os lábios: extrair a tira de frames no início de um segmento e comparar com o envelope do áudio (uma plosiva no começo da frase é o melhor marcador).
- 🔴 🆕 **QC de COR — `scripts/qc-cor.py <dir-producao>`. RODAR SEMPRE, e ele tem que vir ANTES do QC abaixo.** (defeito ENTREGUE em 2026-08-06, `creator-2/peca-02`: o creator-1 viu a cor alterada, "começa mais branco e depois fica mais vívido".) Duas coisas que nenhum QC deste repo fazia:  → RD-10
  - **Confere as TAGS de cor** de todo `.mp4` da produção. A LUT converte os PIXELS de HLG/BT.2020 pra SDR e **não toca no metadado** — um entregável SDR rotulado como HLG faz o player **tone-mapear de novo**: cor alterada, mais quente, e mudando ao longo do vídeo (tone-map de player é adaptativo ao conteúdo). ⚠️ **NENHUM QC por extração de frame pega isso**, porque o ffmpeg lê os pixels e ignora o rótulo: as 6 medições daquela produção deram todas certo enquanto o arquivo estava errado no player. Causa medida: neste build as flags de saída `-color_primaries`/`-color_trc` são **silenciosamente ignoradas** (só `-colorspace` pega) — as tags vão por `setparams` no filtro, ou pelo bsf `h264_metadata` pra corrigir sem re-encode. Detalhe na skill `remotion-compositor`.
  - **Compara o entregável contra a referência da APPLE** (`avconvert` = motor do app Edits da creator), que é a régua canônica. A skill já mandava "QC de cor obrigatório contra o BRUTO" mas não havia script, e o que se rodava na prática era compositado-vs-`v1-graded` — que prova só que a camada alpha não suja a cor, **não** que o grade está fiel ao original. Régua: `v1-sdr` tem que bater <2% (é só conversão de formato); o desvio do `v1-graded` é o preset e precisa ser explicado por ele.
- 🔊 🆕 **QC de LOUDNESS — `scripts/loudness.py <arquivo> --verificar --perfil <n>`. RODAR SEMPRE, junto do `qc-cor.py`.** (SPEC-02.) Até 2026-08-08 **nenhum** dos QCs deste repo media loudness ou true peak: `audit-emendas.py`, `qc-ataque.py`, `qc-cor.py`, `qc-emendas-asr.py`, `qc-fonemas.py` e `flicker-scan.py` são todos cegos para nível. O `peca-11/compor.sh:59` imprimia o true peak no stderr, mas não comparava com nada e não falhava — o erro de 1,75 LU saiu para o creator-1 **seis vezes sem um único alerta**. Sai **1** se o integrado estiver fora da tolerância (0,5 LU), se o true peak passar do teto, ou se o domínio de canais não bater com o do perfil. Prova de dentes rodada na entrega: varreu os **7** entregáveis reais e reprovou os 6 conhecidos aprovando o correto; com defeito plantado (o mesmo arquivo aprovado, 1 dB abaixo) acusou, e a 0,3 dB (dentro da tolerância) não acusou.
- 🫁 🆕 **QC de CAUDA — `scripts/qc-cauda.py <dir> [--edl edl.json] [--alvo S]`. O único QC que procura SILÊNCIO onde não deveria haver.** (SPEC-09.) Os cinco anteriores procuram **fala** onde não deveria haver — sílaba vazada, fonema decepado, palavra inventada. Uma cauda de 460 ms tem transcript perfeito, emenda limpa, fonema íntegro, deriva de A/V zero, `qc-fonemas.py` verde — e o vídeo respira errado. Medido na `peca-01`: **1,82 s de ar de café em 8 de 23 segmentos, 2,6 % de um vídeo de 70 s**. Sai **1** se o p90 passar de 3× o alvo; sai **3** quando a medição é inválida (piso fixo abaixo do ruído da sala — com o piso do FALLBACK, −52 dB, ele devolveria **0 ms em 23 de 23** sobre 1,82 s de defeito real, e por isso o default dele é `--floor auto`). Prova de dentes obrigatória: `--controle` planta 400 ms de silêncio em **todos** os segmentos e exige que o script acuse os 23/23 — sem isso o verde não vale nada.
- 🔊 🆕 **QC de NÍVEL DE FALA — `scripts/qc-nivel.py balanco <dir-producao> --video v1-montado.mp4`. É o GATE, e roda ANTES dos QCs de cor.** (SPEC-10; defeito ENTREGUE em `creator-2/peca-01`.) O `loudnorm` é integrado: 0,7 s a −20 dB não move o LUFS do arquivo, e nenhum outro QC daqui vê nível. O segmento 3 daquela entrega (`"vamos"`, 12,567–13,300 s no `v-final.mp4`) mede **−34,1 dBFS contra uma mediana de −13,4 dos outros 28 ranges — −20,7 dB** — enquanto o segundo pior range da mesma peça está a −2,7. O transcript está perfeito, a emenda está limpa, o corte não cai em rampa: **nenhum QC acusou, e o creator-1 ouviu.** Compara cada range contra a mediana dos **outros** (leave-one-out), então um range corrigido **para** de ser sinalizado — é isso que o torna critério de aprovação. Sai **1** se algum range estiver `LOW-LEVEL` (Δ ≤ −5,0 dB) ou `SEM-NIVEL` (tem fala dentro e nenhuma janela medível sobreviveu). Prova de dentes rodada na entrega: **1 flag em 52 ranges de 3 produções entregues**, e é o defeito verdadeiro — `peca-03` (pior Δ −4,1) e `nao-perdeu-a-peca-06` (−0,5) saem limpas. No entregável com trilha, rodar de novo com `--video v-final.mp4 --mascara palavras --balanco-db 7`. Contrato em `references/contrato-qc-nivel.md`.  → RD-8
- 🔎 O irmão dele, `scripts/qc-nivel.py achado <dir-producao>`, roda na **etapa 2** (no bruto, antes de montar) e **não aprova nada**: ele lista trechos e dimensiona o `gain_db`, e sai sempre 0. Ver a seção "QC de NÍVEL" no fim deste arquivo para o porquê.
- **QC de cor da COMPOSIÇÃO**: comparar sat/lum (PIL) de frames do compositado vs os MESMOS frames da base (v1-graded) — com a composição alpha o delta deve ser ~0 fora das áreas de overlay. Nunca comparar still-com-overlay vs frame-sem-overlay (falso alarme).
- **QC de flicker**: `scripts/flicker-scan.py <video> [ini] [dur]` — Δ de luminância frame a frame por região. Dip-e-recover de 1 frame = buraco de opacidade em elemento; salto único alinhado a corte da EDL = jump cut (inerente); rampa suave = movimento de cena.
- 🎨 **QC de CONTRASTE da tinta — medir no `v1-graded`, não no `v1-sdr`, e por RAZÃO, não por impressão.** (defeito da 1ª versão de `peca-05`, 2026-07-29.) Medi a faixa do topo no `v1-sdr` (lum 124), li "fundo claro" e escrevi a peça toda em grafite com halo branco. O preset da creator derruba a mesma faixa pra **lum ~107**, e a razão de contraste inverte a decisão: **branco 5,13 · creme 4,70 · grafite 3,21 · rosé claro 3,06 · rosé dela 2,37 · rosé escuro `#D14E72` 1,24** — o acento da 1ª versão era, na prática, **invisível**. Régua: WCAG pede 3,0 pra texto grande e 4,5 pra conforto. Medir sobre a base REAL da composição, em vários instantes, e escolher pelo número.
- 🔍 **QC de VARREDURA (todos os frames) — o que os QCs acima estruturalmente NÃO pegam.** Auditoria de 2026-07-25: a peca-03 passou por todos os QCs desta lista e ainda tinha **4 defeitos visuais reais**, porque QC de estado final olha *um frame por elemento*: não pega **tinta condicional** (cor que só aparece num modo — a palavra ativa saía verde-menta só na janela de ênfase) nem **transição** (o CTA cortava seco 7 frames antes do fim) nem **estado simultâneo** (2 tokens sobrepostos = 2 palavras acesas no mesmo frame). Receita: varrer os 1.987 frames do `graphics-alpha.mov` em numpy e contar pixels por assinatura de cor + ilhas horizontais + média do alpha na cauda. Modelo pronto: `creators/creator-2/producao/peca-03/qc-defeitos.py`.
  🆕 **Mais dois defeitos que só a varredura pega** (`peca-05`, 2026-07-29 — modelo pronto: `creators/creator-2/producao/peca-05/qc-varredura.py`):
  - **Transbordo INTERMITENTE na zona de UI.** O `spring` tem overshoot: com `transformOrigin: left` e escala inicial 1,5, a palavra "CRESCEU" chegou a **x991** (dentro da coluna de botões do feed) por **2 frames**. O still do estado final dava x843, tranquilo. Fix: origin `center` e escala menor. **Bbox por frame, não por amostra.**
  - **Buraco de legenda por supressão de PÁGINA.** O `off` do `CaptionLayer` mata a página INTEIRA que intersecta a janela, e a fronteira real de página não é a que se calcula no papel: uma janela de CTA em [42,92–46,54] deixou **2,1s sem legenda nenhuma**, e recuar o início não resolveu. Antes de usar `off`, pergunte se a supressão se justifica: se o cartão carrega só um mockup de UI (2 palavras), o conflito provavelmente é **geométrico** (aqui a seta descia até y1468 e batia na legenda em y1413–1464) — mova o elemento em vez de apagar a legenda.
  🔴 🆕 **QC VERDE SEM PROVA DE DENTES NÃO VALE NADA** (o pior defeito da produção `peca-01`, 2026-07-31, e ele era no próprio QC). Dois jeitos de o script se auto-neutralizar e imprimir "varredura limpa":
  - **inferir a fronteira gráfico/legenda a partir do alpha**: usei "linhas presentes em >25% dos frames" e a fronteira saiu em y304, porque os cartões daquela camada cobrem 36% dos frames. O script passou a medir "gráfico" só acima de y264, **não testou nada** e devolveu verde. A fronteira é CONHECIDA (yPct da legenda + fontSize) — fixe-a e **afirme a faixa neutra vazia** entre as duas, pra que uma mudança futura grite em vez de mentir.
  - **medir a coisa errada com precisão**: "corta seco" medido por ÁREA (pixels com alpha>8) acusou 7 de 7 grupos, porque o fade do `OverlayGroup` mexe no **alpha** (255→227→181→137→90→46→0) e não no tamanho. Área constante durante fade correto é o esperado. A régua é **opacidade**.

  Regra que ficou: **antes de aceitar resultado limpo, imprima quantos frames cada teste realmente varreu e injete um defeito sintético que ele TEM que acusar.** Custa 10 linhas. Na `peca-01` isso mostrou 722 frames de gráfico varridos, x máx global 911 (<924) e o controle negativo acusando — só aí o verde passou a significar algo.  → RD-7

  ⚠️ **A LEGENDA É EXCEÇÃO à zona segura, e esquecer isso gera falso-positivo em massa** (216 frames acusados numa rodada): ela é centralizada com `maxWidth 900` (logo passa de x924) e vive até y~1520. A regra `x<924 / y<1500` é pra **elemento gráfico** — aplique-a só acima da faixa da legenda.
  ⚠️ **Duas armadilhas de varredura que geram falso-positivo em massa** (as duas aconteceram): (1) **detectar cor por distância euclidiana/máx é errado pra cor quase-branca** — `|rgb − #E8FFF0| ≤ 16` acusou 1.915 frames, todos anti-aliasing neutro em ~244,244,244; o que separa é o **CAST** (`G−R ≥ 12`; branco tem 0, menta tem 23). (2) **faixa de varredura larga pega outro elemento**: y1200–1620 incluía um detalhe rosé do CTA em y1212 e contou como 2ª palavra ativa — medir a faixa real da legenda no alpha antes (aqui y1448–1520 normal / y1403–1500 ênfase).
- **`pix_fmt` de TODA a cadeia, não só do entregável**: `v1-graded` e a cópia em `public/` saíram em `yuv444p` / High 4:4:4 Predictive numa produção em que só os entregáveis estavam certos em `yuv420p`. Além do perfil que muita coisa não decodifica, **isso polui o QC de cor**: o Δlum "uniforme de −0,0066" que eu creditei ao re-encode x264 era 4:4:4-vs-4:2:0. Com a cadeia toda em 4:2:0 a composição alpha mede **Δlum +0,0001**. Confira `ffprobe -show_entries stream=pix_fmt,profile` em *todos* os intermediários.
- `open` do arquivo pro creator-1; iterar por feedback. Versionar dados por iteração (`overlays.vN.json`) e registrar decisões em `NOTAS.md` da produção.
- 🆕 **Ou entregar pelo preview** (`preview/README.md`): timeline com filmstrip e waveform, scrub por Range HTTP, e o feedback voltando como **evento marcado no instante**, não como recado em prosa. Cada save do creator-1 vira **um arquivo novo** em `<dir-producao>/.preview/pendentes/` — nada é sobrescrito, salvar 5 vezes gera 5 eventos. **O ACK é o move**: aplicar e mover para `<dir-producao>/.preview/aplicados/`, nunca apagar; o histórico do que ele pediu fica na produção, ao lado do `NOTAS.md`.
- ⚠️ O preview é portão de aprovação **editorial**. Não substitui `qc-fonemas.py`, `qc-cor.py`, `qc-emendas-asr.py` nem a varredura de frames — o olho acha o que o QC não acha, e o QC acha em 70 s de vídeo o que o olho não acha.
- 📝 🆕 **ENTREGÁVEIS DE PUBLICAÇÃO — rodar SEMPRE os dois, quem decide se saem é o perfil** (SPEC-21):
  ```bash
  python3 scripts/srt.py       <dir-producao>            # captions.srt (+ .vtt)
  python3 scripts/srt.py       <dir-producao> --verificar
  python3 scripts/capitulos.py <dir-producao>            # chapters.txt
  ```
  Não há orquestrador: cada script lê `publicacao.*.gerar` do perfil e **sai 0 sem escrever nada** quando está desligado (`reels` desliga os dois; `longform` liga os dois; `vsl` e `screencast` ligam só o `.srt`). **exit 2 = declarado e NÃO produzido** (faltou transcript, ou `capitulos.gerar=true` sem nenhum capítulo declarado) — é o código que a bateria de QC trata como falha sem precisar saber o que cada script faz. Ligar capítulo numa VSL é uma linha: `perfil.py resolver <dir> --perfil vsl --set publicacao.capitulos.gerar=true`.
- 🔴 🆕 **As duas armadilhas que essa etapa evita, as duas já pagas neste repo.** (1) **Legenda não sai do transcript do montado** — o ASR lê a emenda como fala contínua e inventa palavra ("Você manda as empresas com o seu sócio" onde o creator-3 fala "uma das empresas que eu sou sócio"); num `.srt` isso é pior que na legenda queimada, porque fica no arquivo e vai para o índice de busca do YouTube. (2) **Posição não sai de `Σ(end−start)`** — a soma nominal é sempre menor que a saída real (medido em `c-completo`: **351,7 ms** no fim; o ref-A pagou **4,433 s** num caso de 20 takes). Sem `timeline_real` os scripts **abortam**: preferimos não entregar o arquivo a entregar um deslocado, porque **nenhum QC deste repo mede posição de texto na saída** — áudio perfeito, cor certa, emendas limpas, e a legenda meio segundo fora.
- ⚠️ 🆕 **`cps_p95` acima do teto NÃO é bug do gerador.** Em `c-completo` a fala tem **17,2 caracteres/s de média global** e **23,2 no p95 de janelas de 5 s**: o teto de 17 (convenção de mercado, não medição nossa) é fisicamente inalcançável ali sem apagar texto ou mentir no tempo. O `--verificar` reprova quando o **sidecar não declara** os cues que estouram, não quando eles existem. O número está em `captions.srt.meta.json` (`cps_p95`, `cps_excedidos`, `dur_min_violada`, `sobreposicoes_clampadas`) para quem revisa decidir: baixar o ritmo, cortar palavra, ou aceitar.

### 🖥 Preview — ver antes de aprovar (SPEC-17)

`preview/servidor.py` serve **um diretório de produção** em `127.0.0.1`, com token no caminho. Stdlib pura: nenhuma dependência, nenhum framework, roda com o `python3` que já está na máquina. Procedimento completo em `preview/README.md`.

| serve | como |
|---|---|
| render com scrub | `media/<rel>` com Range/206/416 e `HEAD` |
| filmstrip | `gen/<chave>/thumbs/NNNN.jpg` — **contagem limitada** (24–200), intervalo derivado; peça de 30 min gera 200 thumbs, não 918 |
| waveform | `gen/<chave>/waveform.json` — min/max por balde, teto de 20.000 baldes |
| estado | `api/estado` com `ETag`; poll com `If-None-Match` responde **304 sem subprocess** |
| saves | `POST api/salvar` → fila append-only em `.preview/pendentes/` |

Três regras que não se mexem sem medir de novo:
- **Nenhum valor de formato no código.** Largura/altura/fps/aspecto saem do `ffprobe` do arquivo que está tocando; a largura do thumb sai de `scale=-2:<altura>`. É o pecado que o `montar.sh` pagou em duas rodadas (SPEC-00 tirou o `vf` do bash; SPEC-06 fechou a janela de aspecto) — não reintroduzir aqui.
- **Sem `timeline_real` (SPEC-05), não há coordenada de render.** O estado publica `timeline_real_ausente: true` e a UI **desabilita** a marcação por instante. **Somar `Σ(end−start)` da EDL é proibido** — foi assim que o ref-A acumulou 4,433 s de erro em 20 takes.
- **O servidor nunca escreve fora de `<dir-producao>/.preview/`.** Ele não toca `edl.json` nem `captions.json`: aplicar é decisão do agente, com validação. Um servidor que reescreve a EDL fura todos os QCs de emenda desta skill de uma vez.

### Onde a UI aparece — TRÊS caminhos, e o produto suporta os três

O Claude Code tem mais de uma superfície e elas não oferecem as mesmas
ferramentas. O procedimento é **condicional**, e escolher errado é o que faz um
passo falhar em silêncio. Tente na ordem; o terceiro sempre funciona.

| | quando | o creator | o agente |
|---|---|---|---|
| **A · painel** | o harness tem `preview_start` | não faz nada | vê a UI ao lado da conversa |
| **B · browser MCP** | há Playwright/Chrome MCP na sessão | não faz nada | **enxerga a tela** e pode conferir sozinho |
| **C · autônomo** | sempre | a janela abre sozinha | tem a URL no log |

#### A — painel embutido (`preview_start`)

O melhor: a UI abre ao lado da conversa, sem trocar de janela.

1. copie `preview/launch.exemplo.json` para `.claude/launch.json` na raiz do
   projeto e ajuste o `--dir` para a produção;
2. `preview_start` com o nome `ilha-preview`.

`autoPort: true` não é enfeite: o servidor toma uma porta efêmera por sessão, e
duas produções abertas ao mesmo tempo colidiriam numa porta fixa. O harness
reserva a porta em `$PORT` e o servidor a aceita por `--porta`.

#### B — browser MCP: o único caminho em que o AGENTE vê a tela

Se a sessão tem Playwright ou Chrome MCP, navegue até a URL e trabalhe ali. É
qualitativamente diferente dos outros dois: em A e C só o creator enxerga, e o
agente depende do que ele descrever.

```
browser_navigate(url)         →  a UI carrega
browser_console_messages()    →  erro de JS aparece AQUI, não no relato
browser_snapshot()            →  a árvore de acessibilidade: abas, cards, avisos
browser_click(...)            →  trocar de aba, abrir a galeria
```

⚠️ **Medido em 2026-08-09, e é a razão de este caminho estar escrito:** três
defeitos da aba ESTILO só apareceram com a página aberta — a aba nova comendo as
outras duas, todos os previews em 404, e a galeria montando sem imagem nenhuma.
**O DOM estava correto nos três**, então nenhum teste de estrutura pegaria. Quem
entrega camada visual sem olhar a tela entrega defeito visual.

⚠️ O servidor MCP padrão abre um Chromium **limpo**, sem os logins do creator. Para
o preview isso não importa (é `127.0.0.1` com token na URL), mas importa para
qualquer outra coisa.

#### C — autônomo, e é o que sempre funciona

Sem painel e sem browser MCP, sobe o servidor com `run_in_background: true`
— medido: mantém o processo vivo entre turnos e notifica quando ele cai — e
**abre a janela sozinho**:

```bash
python3 <skill>/preview/servidor.py sessao --dir <produção>
python3 <skill>/preview/servidor.py servir --dir <produção> --abrir
```

`--abrir` chama o browser padrão do SO. Ele existe porque "copie este endereço e
cole no navegador" é exatamente o passo em que uma sessão morre — e falhar aqui
(máquina sem ambiente gráfico) **não derruba o servidor**: vira uma linha de log
com a URL, não uma exceção.

⚠️ **Como escolher.** Procure a ferramenta antes de usá-la. Onde `preview_start`
não existe, o passo não falha com erro — **ele não acontece**, e o creator fica
esperando uma tela que ninguém abriu. Mesma coisa para o browser MCP.

⚠️ **Os três caminhos exigem o passo seguinte.** Painel, browser MCP ou janela do
SO, sem o watcher armado o save do creator não vira trabalho.

### 🔴 ARMAR O WATCHER NO MESMO TURNO EM QUE O SERVIDOR SOBE

Sem isto o creator escolhe o estilo ou marca um instante, **vê o toast de confirmação, e nada acontece**. Ele acha que avisou; ninguém ouviu. A falha é silenciosa dos dois lados, e é o modo de falha mais caro do preview inteiro — pior que o servidor não subir, porque um servidor fora do ar se percebe na hora.

```
Monitor(command="python3 <skill>/preview/watch-preview.py '<dir-producao>'",
        description="escolhas e marcações salvas no preview",
        persistent=true)
```

Medido de ponta a ponta em 2026-08-09: `POST api/salvar` → arquivo novo em
`.preview/pendentes/` → o watcher emite **uma linha** → a linha chega como
notificação na sessão, com o resumo do que foi pedido e o caminho do arquivo.
Latência = o `--intervalo` (2 s por default).

Três coisas que fazem este loop ser confiável, e que valem quando alguém for mexer:

- **A fila é append-only e o ACK é o MOVE.** Salvar 5 vezes gera 5 arquivos; aplicar
  é mover para `.preview/aplicados/`, nunca apagar. O watcher guarda os nomes já
  vistos, então ele não depende de ninguém limpar diretório — e o histórico do que o
  creator pediu fica na produção, ao lado do `NOTAS.md`.
- **`persistent=true`.** Sem isso o monitor morre no timeout e o silêncio volta —
  parecendo, de novo, que está tudo certo.
- **Um monitor por produção.** O caminho está no comando; dois diretórios pedem dois
  monitores.

⚠️ **`ps aux | grep watch-preview` é a checagem de um segundo** quando houver dúvida
se o loop está armado.

### Prova pela IMAGEM: a fronteira que a EDL afirma existe? (SPEC-26)

Auditávamos emenda de quatro maneiras — `audit-emendas`, `qc-ataque`,
`qc-fonemas`, `qc-emendas-asr` — e **as quatro são pelo áudio**. Nenhum QC deste
repo olhava a fronteira na imagem. É o que deixava aberta a classe do **segmento
órfão**: 6,25 s de vídeo errado com todos os QCs verdes, porque a trilha é
montada a partir dos frames reais e sincroniza perfeitamente com a imagem errada.

```bash
python3 .claude/skills/edit-video/scripts/qc-corte-imagem.py <dir> [--video v1-montado.mp4]
```

**Como ela decide** — e por que não é um `threshold` de `scdet`:

- **limiar absoluto NÃO separa.** Medido em `ovo-de-pascoa`: o maior score fora
  de fronteira (**2,612**) é maior que o menor score **em** fronteira (**2,267**).
  Qualquer corte global produz falso positivo e falso negativo na mesma peça. O
  que separa é a **razão contra a vizinhança local** (janela ±1,5 s, p95, piso
  0,30) — mesma família do piso local do `bordas.py`;
- **a expectativa sai da EDL, antes do score.** `src` diferente ou
  reenquadramento → `esperado_visivel = sim` (**pode virar FALHA**); jump cut de
  mesmo enquadramento → `provável` (**nunca** falha, é confirmação); contíguo e
  mesmo enquadramento → `não`, e o silêncio da sonda é o resultado **certo**;
- **o índice é de DECODIFICAÇÃO.** `round(lavfi.scd.time × fps)` desloca as 16
  fronteiras da `peca-04` em +1, porque o `start_time` dela é `0,021029`. A
  igualdade `len(linhas) == nb_read_frames` é obrigatória — é a prova de dentes
  da sonda;
- **tendência antes de item.** Deslocamento uniforme vira **uma** linha
  `DESLOCAMENTO-SISTEMATICO`, não N achados: uniforme é bug de cadeia, isolado é
  bug daquela fronteira.

**Medido em 4 produções** (8.035 frames, 83 fronteiras):

| produção | fronteiras | confirmadas | falso positivo | deslocamento |
|---|---|---|---|---|
| `peca-01` | 28 | 28 | 0 | 0 |
| `peca-03` | 19 | 19 | 0 | 0 |
| `peca-04` | 16 | 16 | 0 | 0 |
| `ovo-de-pascoa` | 20 | 18 (2 `SEM-MARCADOR`: razão 7,56 e 5,98) | 0 | 0 |

Os dois controles do método, os dois no `test_qc_corte_imagem.py`: junção
**contígua de verdade** (segmento partido e re-encodado) dá razão **0,41** e sai
`ESPERADO-INVISIVEL`; o **mesmo par** refeito com `-ss 2 -c copy` (que busca
keyframe e pula frames) dá **20,94** e sai `IMAGEM-SEM-FRONTEIRA`. Sem o
positivo, o negativo não provaria nada.

⚠️ **Órfão é recusa, não medição.** `ovo-de-pascoa` tem **22 arquivos em `segs/`
para 21 segmentos na EDL**. A sonda emite `EDL-VS-SEGS` e sai por
`NÃO VERIFICADO` — nunca por OK, e sem adivinhar qual arquivo sobra. Para medir
mesmo assim existe `--orfao-prefixo`, que só aceita a hipótese "os N primeiros"
depois de conferir que a soma dos frames bate com o vídeo.

---

## Bateria de QC — um comando, um veredito

```bash
python3 .claude/skills/edit-video/scripts/qc.py <dir-producao>
```

É o **primeiro** comando de QC a rodar. Ele escolhe quais dos 19 QCs cabem no
estágio da produção, roda em paralelo, e devolve **um** veredito de ~500–900
chars no lugar dos 5.624 (~1.400 tokens) que três dos QCs sozinhos despejavam. Os
scripts individuais continuam existindo para quando o veredito apontar **onde
ouvir**.

```
QC montado · peca-01 · perfil reels · 29 segs · 96s

FALHA 1
  qc-fonemas    seg08 fim 37.450 SILABA-TRUNCADA (oclusão; fim real 37.793)

ACHADO 2  (esperado por construção — não bloqueia)
  audit-emendas 29× CLIP-FIM · 29× CLIP-INICIO
  qc-nivel-achado 5× NIVEL-RUN

OK 4  integridade-edl(29/29) · cortes-do-bruto(2/2) · qc-ataque(22/28) · av-sync(6/28)

NÃO VERIFICADO 2
  varredura-alpha sem-script — declare o seu em qc/local.json
  qc-jcut         insumo — falta jcut.json

CEGO SEMPRE: ritmo e humor, escolha de música, o que só o ouvido pega. Assista antes de entregar.
detalhe: qc/relatorio.json · logs: qc/*.log
```

### O que muda na sua cabeça

| antes | agora |
|---|---|
| lembrar de rodar N scripts na ordem certa | `qc.py <dir>` |
| exit 1 do `audit-emendas` bloqueava entrega aprovada | **ACHADO** não bloqueia; só convergência vira FALHA |
| QC prescrito e sem script = silêncio | bloco **NÃO VERIFICADO**, com a causa nomeada |
| "não achei nada" ≡ "está bom" | `unidades == 0` **nunca** é `ok`; exit 3 = bateria vazia |

**Detector ≠ teste de convergência.** Um QC que seleciona o item por estar de um
lado de um limiar mede o limiar que o selecionou — o item está do lado errado por
construção, e o número dele nunca converge a zero. Só QC cuja régua é
**independente do critério de seleção** (os pares, o corpo da palavra vizinha, a
fronteira de frames, um alvo do contrato) pode reprovar. Quem classifica é o
catálogo `qc/bateria.json`, não o agente.  → RD-9

### Estágio

`--estagio auto` (default) escolhe o **mais avançado** cujo artefato existe, e diz
por quê. `montado` (`v1-montado.mp4`) → borda de corte · `compositado`
(`*-alpha.mov/webm`) → camada alpha e insert · `final` (`v-final*.mp4`) → cor,
loudness, frame preto. `--completo` roda os três.

| exit | |
|---|---|
| 0 | nenhuma FALHA (com ou sem achados) |
| 1 | ao menos uma FALHA |
| 2 | erro de uso |
| 3 | **bateria vazia** — nenhum QC pôde rodar |

### `qc-avsync.py` — o QC que a etapa 8 mandava fazer e não existia

A verificação de A/V (`vale de energia por emenda vs fronteira de frames, ±3 ms
sem tendência`) era prescrita aqui e **não existia em código**. Agora existe, e
tem duas pernas: a **mediana** e a **tendência** (regressão do offset contra o
índice da emenda). O bug de 2026-07-25 não era um offset grande, era um offset que
CRESCIA — +0,04 s na primeira metade, +0,17 s na segunda.

Fronteira **contígua** ou com `ritmo.fade_modo so-descontinuidade` não tem
descontinuidade de áudio: ela entra em `sem_marcador`, **nunca** em `ok`.

⚠️ Medido ao escrever: o estimador óbvio (`argmin` do envelope) é **enviesado** —
com os dois lados do corte em níveis diferentes ele é puxado para o lado
silencioso em ≈ metade da janela de RMS (±5,4 ms com janela de 10 ms), o que torna
o alvo de ±3 ms inalcançável. O que decide é o **cruzamento dos dois lados**, cada
lado normalizado pelo próprio platô. O número enviesado continua no JSON, ao lado,
de propósito.

### Acrescentar um QC, ou uma sonda

Tudo em `.claude/skills/edit-video/qc/README.md`. Em uma linha: a bateria é
**dado**; um QC novo é uma entrada em `qc/bateria.json` (ou um arquivo em
`qc/bateria.d/`, que é mesclado por `id` — para não editar o mesmo JSON em duas
frentes), mais um adaptador em `qc.py`. QC que só a sua produção conhece vai em
`<dir>/qc/local.json` → `extras`.

### O portão do portão

```bash
python3 scripts/qc.py --autoteste                                # tem que sair 0
python3 scripts/qc.py --autoteste --desligar-regra unidade-zero  # tem que sair 1
```

21 fixtures, 6 defeitos plantados de propósito, e o controle negativo: desligar
qualquer uma das 4 regras de classificação **tem** que pintar o autoteste de
vermelho. Regra que pode ser desligada sem mudar nada é regra que não está
implementada.

---

> Núcleo: [`../SKILL.md`](../SKILL.md) — as Regras Duras valem aqui.
