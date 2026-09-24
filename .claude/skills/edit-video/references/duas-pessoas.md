# Duas pessoas em quadro

> O que muda quando há **duas pessoas** em quadro (entrevista, conversa): quem fala, zona gráfica que troca de lado, cutaway de reação.

---

## 👥 DUAS PESSOAS em quadro (entrevista / conversa) — o que muda

Nasceu em `creators/creator-2/producao/peca-01/` (2026-07-31). Scripts reutilizáveis lá.

- 🔴 **"Quem fala" tem que ser fechado por mais de um sinal, e ANTES de tudo** — errar inverte todos os zooms do vídeo. O `diarize=true` do Deepgram separa as VOZES mas **não diz de que LADO do quadro** cada uma está, e onde as duas falam por cima ele **se contradiz entre word-level e utterance-level** (3 de 5 runs, nos 18s finais daquela produção). O que resolveu: (a) **movimento de boca por metade do quadro** em numpy — nas partes limpas a razão separa 3,3x, mas **fura quando a pessoa gesticula com a mão perto do rosto** (medi 18,6 de "movimento de boca" que era a mão passando); (b) identidade facial contra frame de produção anterior do creator; (c) a lógica do diálogo (quem chama a outra pelo nome não é ela); (d) para o trecho ambíguo, **Gemini com `video_metadata.fps` alto** (`quem-fala.py` — lábio não se resolve a 1 fps, que é o default da API). Bateu com o word-level em 6 de 7 linhas e **corrigiu a 7ª**.
- **"AMBAS" não é indecisão, é veredito**: quando as duas falam/riem juntas, o plano certo é o GERAL. Vale também pro CTA em que as duas viram pra câmera.
- 🔴 **O plano de dois pode não aceitar zoom nenhum.** Meça a extensão horizontal das duas: naquela cena elas ocupavam **x 0,000–0,996** e o zoom máximo matemático era 1,004. Punch-in é só pros singles.
- ✅ **Nos singles o punch-in costuma ser CORREÇÃO, não estilo**: com duas pessoas sentadas o enquadramento abre muito, e ali 63% do quadro era espaço morto (cabeças em y 0,37–0,42, mesa a partir de 0,65). 1,70x sobre 1080p ficou limpo (conferido 1:1).
- 🔴 **A ZONA GRÁFICA LIVRE TROCA DE LADO A CADA FALANTE.** No single com crop encostado numa borda, quem fala ocupa metade do quadro: cartão fixo num lado aparece em cima do rosto na metade dos beats. A saída é **repor o elemento EM CIMA DO CORTE** (dois grupos que se encostam no frame): o olho não vê a troca de lado, vê o elemento atravessando a emenda. Sem corte no meio, um slide lateral denunciaria.
- **Reação do ouvinte é cutaway de graça** — e é o que quebra um monólogo longo. Mas **escolha um trecho com a boca FECHADA**: em 2 dos 3 picos de movimento medidos ela vocalizava concordância, e cutaway com boca mexendo confunde com a legenda de quem está falando.
- ⚠️ **`medir-cabecas.py`, não `enquadrar.py`**: o do creator-3 procura UMA ilha escura. Com duas pessoas são duas ilhas (uma de cada lado do meio, por construção), e quem usa blusa preta tem cabelo e roupa fundidos numa massa só.
- ⚠️ **Terceiros no fundo são risco real de locação pública.** Naquela produção alguém atravessou o fundo por 3,8s em cima de uma fala essencial, cruzando **x 0 a 1076** — nenhum enquadramento esconde, e punch-in deixa a pessoa MAIOR. O que reduziu de 2,2s pra 0,8s foi partir a fala em dois planos aproveitando o sentido da travessia (single de quem fala enquanto ela está do outro lado → plano de reação quando ela chega). Cartão gráfico como máscara **não funcionou**: no frame em que a intrusa está mais visível o cartão ainda está entrando (6% de opacidade).

---

> Núcleo: [`../SKILL.md`](../SKILL.md) — as Regras Duras valem aqui.
