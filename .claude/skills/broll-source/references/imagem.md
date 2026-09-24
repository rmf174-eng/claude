# Imagem estática — a escada, o gate e os números medidos

> Complementa `fontes.md`, que é de **vídeo**. Aqui é foto: a pergunta é outra, a
> distribuição de licença é outra, e as armadilhas são outras.

## O caso concreto, antes de qualquer coisa

**Foto de pessoa pública em contexto editorial ≠ foto de pessoa pública ao lado da sua
oferta.** A mesma imagem, com a mesma licença, é uso legítimo num vídeo que comenta um
fato e é problema num vídeo que vende. A licença cobre o direito **autoral** (do
fotógrafo); ela não cobre o direito de **imagem** (da pessoa) nem a **marca** (do dono
dela). Nenhum gate automático resolve isso — quem resolve é quem edita.

A licença do Pexels que já está no nosso próprio código proíbe literalmente *"sugerir
endosso"* e *"pessoa identificável em contexto negativo"*. Um rosto ao lado de um CTA é
exatamente onde isso mora. E o Commons marca alguns arquivos com
`extmetadata.Restrictions` (achamos o caso `"personality"`): **não é licença, é direito
de imagem** — o `buscar.py` avisa no stderr quando o campo vem preenchido.

## A escada é INVERTIDA em relação à de vídeo

```
IMAGEM:  1. biblioteca local  →  2. Wikimedia Commons (sem chave)  →  3. Pexels fotos
VÍDEO:   1. biblioteca local  →  2. Pexels  →  3. Mixkit  →  4. Pixabay  →  5. Wikimedia
```

Não é preferência, é o tipo de pergunta que o beat faz:

| a pergunta do beat | quem responde |
|---|---|
| "um plano de apoio de *comida*" (conceito genérico) | stock — Pexels |
| "**o** Cristo Redentor", "**o** Neymar", "**a** capa daquele livro" (referente único) | Commons. Stock literalmente não tem: pessoa pública e monumento identificável não são material de banco de imagem comercial |

Quando não existe foto do que se precisa, o degrau seguinte é **gerar** (`omni-insert`) —
e vale a mesma regra do vídeo: gerar é para quando **não existe**, não para quando dá
preguiça de procurar.

## 🔴 O gate de licença vazava — e em imagem isso seria grave

O filtro do `wikimedia()` era `any(t in lic.lower() for t in ("cc0","public domain",
"cc by"))`, com um comentário ao lado prometendo cortar `CC BY-SA` e `CC BY-NC`.
**`"cc by-sa 4.0"` contém a substring `"cc by"`**: as duas exclusões nunca aconteciam.

Medido contra a API real do Commons (2026-08-08, duas consultas de 12 resultados):

| licença devolvida | n | passava antes | passa agora |
|---|---|---|---|
| `CC0` | 1 | ✅ | ✅ sem crédito |
| `Public domain` | 1 | ✅ | ✅ sem crédito |
| `CC BY 2.0 / 3.0 / 4.0` | 9 | ✅ | ✅ **com crédito** |
| `CC BY-SA 2.0 / 3.0 de / 4.0` | **13** | ✅ | ❌ reprovada (viral) |

**24 de 24 passavam. 13 eram `CC BY-SA`** — exatamente o que o comentário dizia cortar.
A fixture com essas 24 strings vive em `scripts/tests/test_licenca.py` e o teste sai 1
se o predicado antigo parar de vazar nela (senão o verde não valeria nada).

Por que `SA` importa: a cláusula *ShareAlike* pede que a obra derivada seja licenciada
sob a mesma licença. Um reels comercial com um still `CC BY-SA` composto dentro dele é,
no mínimo, um argumento jurídico aberto sobre o vídeo inteiro. É a mesma régua que fez
esta skill descartar o **Coverr** inteiro (*"licença ambígua é licença reprovada"*) — não
faria sentido aplicá-la ao Coverr e não a si mesma.

O defeito era **latente em vídeo e crítico em imagem**: o acervo de vídeo do Commons é
pequeno e quase nada é usável; em imagem, `CC BY-SA` é a licença **majoritária**.

### Onde o gate mora agora

`scripts/licenca.py`, um módulo só, usado pelo `buscar.py` e pelo `baixar.py`. Duas
decisões que valem para qualquer gate futuro:

1. **tokenizar, não fatiar string.** `"CC BY-SA 3.0 de"` → `{cc, by, sa, 3, 0, de}`.
   Acento vira ASCII antes de fatiar, senão `"domínio público"` viraria `{dom, nio, p,
   blico}` e o gate reprovaria em português e passaria em inglês.
2. **cláusula ANTES de família.** NC/ND/SA testados antes de BY. A ordem invertida É o
   bug — e o `--autoteste` roda a ordem invertida contra a mesma tabela e **exige** que
   ela acuse. Portão que não prova ter dentes é indistinguível de portão quebrado.

```bash
python3 scripts/licenca.py --autoteste        # 21 casos + 2 controles negativos
python3 scripts/licenca.py "CC BY-SA 4.0"     # cc-by-sa · REPROVA · viral
```

O domínio de slugs é **fechado**: `cc0 · dominio-publico · cc-by · cc-by-sa · cc-nc ·
cc-nd · gfdl · pexels · pixabay · mixkit · desconhecido`. **`desconhecido` nunca é
livre** — a decisão default é NÃO. A política (`--licencas`) é configurável; a régua
não. Incluir `cc-by-sa` é possível, imprime `⚠️ SA é viral` e grava `politica_licenca`
no candidato: decisão de risco que não fica escrita é decisão que ninguém audita depois.

## Números de desenho, todos medidos

- **Aproveitamento ~41% depois do gate.** Por isso `gsrlimit = n*3` em imagem (a mesma
  conclusão a que o ref-A chegou, pelo mesmo motivo).
- **Crédito é regra, não exceção**: 9 de 11 aprovadas (~78%) exigem atribuição, contra
  **0 de 2** clipes de vídeo hoje na biblioteca. Daí o `baixar.py --creditos`, que
  transforma o `exige_atribuicao` do índice em linha colável. Registrar e nunca imprimir
  equivale a não atribuir.
- **`filetype:bitmap` filtra na origem**: a busca crua por `Neymar` devolveu `audio/mpeg`
  e `image/svg+xml` entre 12 resultados; com `filetype:bitmap`, 12/12 vieram `image/*`.
  O teste de mime continua no código como segundo cinto — SVG não é foto, é vetor de
  logo, que é justamente o que não queremos.

## O que se baixa, e o que NÃO se baixa

- **Pexels: `src.original`, nunca `src.portrait`/`src.landscape`** — essas duas são
  RECORTES (800×1200 fixo). A biblioteca guarda a fonte inteira; quem enquadra é o
  `split-broll.py`/`imagem-clipe.py`. `--rendition large2x` é tamanho, não recorte.
- **Imagem não passa por ffmpeg.** Re-encodar perde qualidade e os metadados EXIF de
  autoria, que são a prova de procedência que o índice existe para guardar.
- **Extensão vem do MIME**, não fixa em `.jpg`: a consulta medida devolveu `image/png` e
  `image/tiff`. Índice que registra `.jpg` para um PNG é índice que mente.
- **`image/tiff` e afins**: o caminho é sempre o render do Commons (`--largura`), que vem
  JPEG. O TIFF cru não tem magic number na nossa lista e seria rejeitado, com razão.
- **Original grande demais** (`--max-mb`, default 25): mesma saída, render do Commons,
  com `rendition` gravado no índice pela largura **medida** — o Commons entrega o
  thumbnail existente mais próximo, não a largura pedida (medido: pedi 800, veio 960).

## Bytes: HTTP 200 não quer dizer mídia

O thumb server do Commons devolve **página HTML de erro com status 200**. Em vídeo o
ffmpeg continha o estrago (com o diagnóstico errado: "Invalid data found" quando a causa
é "o servidor devolveu uma página"). **Em imagem não há ffmpeg no caminho** — sem
validação, um HTML de erro viraria `imagens/cristo-redentor.jpg` com licença registrada e
tudo.

Regra, escrita uma vez e valendo para os dois tipos:

1. `Content-Type` é conferido — **aviso, não veto**. Servidor mente nos dois sentidos.
2. O **primeiro bloco lido** é inspecionado: `<!doctype` / `<html` / `<?xml` → **aborta**,
   e o parcial é apagado (`try/finally`).
3. Imagem: magic number (JPEG/PNG/GIF/WEBP) sobre o arquivo baixado.

`scripts/tests/test_bytes.py` sobe um servidor local que devolve HTML com 200 e exige
exit ≠ 0, zero arquivo novo, zero `.download` e `INDEX.json` intocado — **mais um
controle positivo** (JPEG 1×1 real que TEM que entrar). Sem essa segunda metade, "0
arquivos na biblioteca" seria verde de graça.

## Da foto ao plano inserível

`split-broll.py` recebe `<broll.mp4>`: uma JPEG ali vira um stream de 1 frame. O
conversor é o `imagem-clipe.py`.

```bash
python3 scripts/imagem-clipe.py <imagem> <saida.mp4> \
    --dur 4 --movimento zoom-in --foco centro --perfil reels
```

- **Zero número de formato no script**: dimensão, fps, pix_fmt, crf, preset e tags de cor
  vêm do **perfil de peça**; movimento, duração, zoom máximo e upscale vêm do bloco
  `broll.imagem` do perfil (`reels` 4 s/1,15 · `vsl` e `longform` 6 s/1,10 · `screencast`
  estático 5 s — a imagem ali é evidência de UI, mover atrapalha ler).
- **O upscale prévio é o que separa Ken Burns de tremor.** O `zoompan` calcula o
  retângulo de corte na grade de pixels **da entrada**: sem upscale, o retângulo anda em
  passos inteiros e o movimento sai aos trancos. Medido: coeficiente de variação da
  diferença interquadro **0,099** com upscale 4× contra **0,221** sem — 2,2× pior.
- ⚠️ **A régua NÃO é o `mpdecimate`**: ele devolve 120/120 frames nos **dois** casos,
  porque mede *frame repetido* e o defeito do zoompan é *passo desigual*. Quem
  "verificar suavidade" com `mpdecimate` conclui que está tudo bem nos dois. Ele serve só
  para o controle negativo do movimento `estatico` (1/120).
- **Sidecar obrigatório**: `<saida>.json` com licença, autor e página da origem. Sem ele
  a licença morre na primeira transformação, e *"licença sem procedência é licença que
  ninguém consegue provar depois"* valeria só para o primeiro passo do pipeline.

## Google Custom Search fica FORA — e a razão fica escrita

O terceiro degrau do ref-A (`google_images.py`) não entra. O mapa de direitos deles:

```python
RIGHTS = {
    "cc":         "cc_publicdomain|cc_attribute|cc_sharealike",
    "commercial": "cc_publicdomain|cc_attribute|cc_sharealike|cc_noncommercial",
}
```

A opção chamada **`commercial`** é a única que admite explicitamente `cc_noncommercial`, e
as duas misturam `sharealike`. É a mesma classe de erro do nosso §1.2, com um agravante:
o nome da opção **contradiz** o conteúdo, então quem usa não tem como desconfiar.

E, mesmo consertado, o eixo colide com três regras já escritas nesta skill: buscar na web
aberta é o oposto de partir de um acervo licenciado; o `rights` do CSE é **declaração do
publicador**, não licença verificável (foi o que matou o Coverr); e o caso de uso
declarado deles é literalmente *"A24 studio logo"*, ou seja, marca registrada em b-roll.

Se um dia for necessário, é decisão do creator-1, com o mapa consertado, gate manual antes de
publicar e a decisão registrada em `fontes.md` — **nunca** como fallback automático de um
script.
