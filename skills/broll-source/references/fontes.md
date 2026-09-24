# Fontes de b-roll — o que presta, o que não presta

Regra dura do projeto: **só CC0 ou licença livre para uso COMERCIAL**. Tudo abaixo foi testado
nesta máquina (curl + ffprobe). "Funciona hoje sem chave" = requisição real bem-sucedida agora,
não promessa de documentação.

> 📷 **Este arquivo é de VÍDEO.** Foto tem escada própria (Commons primeiro), distribuição de
> licença própria e armadilhas próprias: **`imagem.md`**.
>
> 🔴 **O filtro que este arquivo prescrevia não era o que o código fazia.** A linha das
> Armadilhas abaixo já mandava *"filtrar server-side por CC0+PD+CC-BY"* desde julho; o
> `buscar.py` implementava `any(t in lic.lower() for t in ("cc0","public domain","cc by"))`,
> e `"cc by-sa 4.0"` **contém** `"cc by"`. Medido em 2026-08-08 contra a API real: **24 de 24
> candidatos passavam, 13 deles `CC BY-SA`**. Doc certa, código errado, ninguém percebeu
> porque nenhum clipe da biblioteca veio do Wikimedia. Consertado em `scripts/licenca.py`
> (cláusula antes de família, com autoteste e controle negativo).

## Tabela

| Provedor | Precisa chave | Licença | Comercial | Atribuição | Vertical 9:16 | Funciona hoje sem chave |
|---|---|---|---|---|---|---|
| **Pexels** | sim (grátis, na hora) | Pexels License (própria, não é CC0) | sim | **sim** (regra da API, não da licença) | sim — `orientation=portrait` server-side | **não** (401) |
| **Pixabay** | sim (grátis) | CC0 só se publicado antes de 2019-01-09; resto = Pixabay Content License | sim | não | **não tem filtro** — client-side por W×H | **não** (400) |
| **Mixkit** (Envato) | não | Mixkit Stock Video Free License — comercial, sublicenciável | sim | não | sim — `/discover/<tag>/?orientation=vertical` | **sim** ✅ |
| **Wikimedia Commons** | não | varia por arquivo (piso: comercial + derivadas). Maioria é **CC-BY-SA** | sim | sim (CC-BY); CC0/PD não exigem | sim, via `fileh:>1000 filew:<1000` — acervo ~1k itens seguros | **sim** ✅ |
| **Internet Archive** | não | por item, campo `licenseurl`. ~33% de stock_footage é BY-ND (inutilizável) | depende | sim (CC-BY) | **não existe** (0 verticais licenciados em 4803 arquivos) | **sim** ✅ |
| ~~Coverr~~ | sim | **ambígua** — docs da API dizem que proíbe uso comercial, página de licença diz que permite | ❓ | sim (API) | sim (`is_vertical` server-side) | não (401) |
| ~~Openverse~~ | — | — | — | — | — | **não tem vídeo** (só `/v1/audio` e `/v1/images`) |
| ~~Videvo~~ | — | — | — | — | — | **site morreu** (301 → freepik.com/videos) |

Coverr é o único com API de verdade e metadata `is_vertical`, mas licença ambígua = licença
reprovada. Fica como plano B se um dia precisarmos do filtro server-side.

## Ordem de tentativa

0. **Biblioteca local** (`baixar.py --listar`) — nunca rebaixe o que já existe.
1. **PRIMÁRIO — Pexels**, assim que a chave existir. Melhor acervo, único com filtro de
   orientação server-side numa API estável, 200 req/h de sobra. Custo zero.
2. **PRIMÁRIO DE FATO ENQUANTO NÃO HÁ CHAVE — Mixkit.** Funciona agora, licença comercial
   inequívoca e sem atribuição. Não tem API: são 3 GETs em HTML público, então é frágil a
   mudança de layout — por isso não vira primário permanente.
3. **SECUNDÁRIO — Pixabay.** Acervo de vídeo menor, quase todo landscape, e os dois filtros que
   importam (orientação e duração) são client-side — paga-se requisição pra descartar.
4. **FALLBACK SEM CHAVE — Wikimedia Commons.** Documental/amador, não stock. Serve pra
   **atmosfera e lugar real** (chuva, cidade, natureza, multidão). Não entrega plano conceitual
   de negócio.
5. **Internet Archive** — só textura/retro/found-footage, landscape, baixa resolução. Nicho.
6. **Não existe footage do que se precisa** → skill `omni-insert` (gerar).

Lembrete: vertical é desejável, **não é requisito** — o `split-broll.py` cobre ~51% da altura,
então 16:9 entra com ~1,6× de recorte. Landscape licenciado > vertical duvidoso.

## Endpoints + curl testado

### Pexels (primário)

`GET https://api.pexels.com/videos/search` — header `Authorization: <chave>` (**sem** `Bearer`).
CDN `videos.pexels.com` serve sem auth. `min_duration`/`max_duration` **não existem** no
`/search` (só em `/videos/popular`) — duração é pós-filtro.

```bash
curl -sS -H "Authorization: $PEXELS_API_KEY" \
  "https://api.pexels.com/videos/search?query=city&orientation=portrait&size=medium&per_page=80" \
| jq -r '.videos[]
    | select(.height > .width)
    | select(.duration >= 5 and .duration <= 20)
    | (.video_files | map(select(.height > .width and .width >= 1080)) | sort_by(.width) | .[0].link) as $f
    | select($f != null)
    | "\(.id)\t\(.width)x\(.height)\t\(.duration)s\t\(.user.name)\t\($f)"'
```

### Mixkit (fallback sem chave — o melhor deles)

Sem API. Cadeia de 3 GETs públicos (robots.txt `Allow: /`):

1. busca: `https://mixkit.co/free-stock-video/discover/<tag>/?orientation=vertical`
2. **gate de licença**: `https://mixkit.co/free-stock-video/<slug>-<id>/` → JSON-LD
   `"copyrightNotice":"Free"` (ok) vs `"Mixkit Restricted License"` (**descartar**)
3. arquivo: `https://mixkit.co/free-stock-video/download/<id>/?context=sidebar&type=1080p`
   → devolve `https://assets.mixkit.co/videos/<id>/<id>-1080.mp4`

```bash
UA="Mozilla/5.0"; Q="fitness"
ITEM=$(curl -sS -A "$UA" "https://mixkit.co/free-stock-video/discover/${Q}/?orientation=vertical" \
  | grep -oE 'href="/free-stock-video/[a-z0-9-]+-[0-9]+/"' | head -1 | sed 's/href="//;s/"$//')
ID=$(echo "$ITEM" | grep -oE '[0-9]+/$' | tr -d '/')

curl -sS -A "$UA" "https://mixkit.co${ITEM}" | grep -oE '"copyrightNotice":"[^"]*"' | head -1 \
  | grep -q '"Free"' || { echo "RESTRITA — descartar"; exit 1; }

URL=$(curl -sS -A "$UA" "https://mixkit.co/free-stock-video/download/${ID}/?context=sidebar&type=1080p" \
  | grep -oE 'https://assets\.mixkit\.co/[^"]+\.mp4' | head -1)
curl -sSL -A "$UA" "$URL" -o /tmp/mixkit-${ID}.mp4
# saída real (3 execuções idênticas): id=52079, h264 1080x1920, 24000/1001 fps, 6.5s, 21.851.270 bytes
```

Duração não tem parâmetro de URL — vem do sitemap (`<video:duration>` em segundos):
`https://mixkit.co/sitemaps/sitemap-video.xml.gz` → 19 shards × 2500 itens (~47.500 vídeos).
**Indexar o sitemap é ok; baixar os mp4 em massa viola os termos** (cláusula 9(10)).

### Pixabay (secundário)

`GET https://pixabay.com/api/videos/?key=<chave>&q=...` — sem filtro de orientação nem de
duração no endpoint de vídeo (o param `orientation` só existe na API de **imagens**).

```bash
curl -sS "https://pixabay.com/api/videos/?key=$PIXABAY_API_KEY&q=ocean&per_page=50&safesearch=true&order=popular" \
| jq '[.hits[]
      | select(.duration >= 4 and .duration <= 15)
      | select(.videos.medium.height > .videos.medium.width)
      | {id, duration, w:.videos.medium.width, h:.videos.medium.height, url:.videos.medium.url, pageURL}]'
```

### Wikimedia Commons (fallback sem chave)

`GET https://commons.wikimedia.org/w/api.php`. Filtra vertical no servidor e **corta share-alike**
via `haswbstatement` (CC0=Q6938433, CC-BY-4.0=Q20007257, PD=Q19652).

```bash
curl -s -A "benchmark-system/1.0 (contato@exemplo.invalid)" \
  --get "https://commons.wikimedia.org/w/api.php" \
  -d action=query -d format=json -d formatversion=2 -d generator=search \
  -d gsrnamespace=6 -d gsrlimit=50 -d prop=imageinfo \
  --data-urlencode "gsrsearch=filetype:video fileh:>1000 filew:<1000 haswbstatement:P275=Q6938433|P275=Q20007257|P275=Q19652 rain" \
  --data-urlencode "iiprop=url|size|mime|mediatype|extmetadata" \
  --data-urlencode "iiextmetadatafilter=License|LicenseShortName|LicenseUrl|Artist|AttributionRequired|Restrictions" \
| jq -r '.query.pages[] | {t:.title, ii:.imageinfo[0]}
   | select(.ii.duration >= 3 and .ii.duration <= 30)
   | select((.ii.extmetadata.Restrictions.value // "") == "")
   | "\(.ii.width)x\(.ii.height) \(.ii.duration|floor)s [\(.ii.extmetadata.License.value)] \(.ii.url)"'

# OBRIGATÓRIO na ingestão — pixel anamórfico:
ffmpeg -v error -i entrada.webm -vf "scale=iw*sar:ih,setsar=1" ... 
```

### Internet Archive (nicho: textura/retro)

Busca com filtro de licença **excluindo NC e ND** (obrigatório: `*by*` casa `by-nc` e `by-nd`):

```bash
curl -s -G 'https://archive.org/advancedsearch.php' \
  --data-urlencode 'q=mediatype:(movies) AND collection:(stock_footage) AND licenseurl:(*publicdomain* OR *zero* OR *by*) AND NOT licenseurl:(*nc* OR *nd*)' \
  --data-urlencode 'fl[]=identifier' --data-urlencode 'fl[]=licenseurl' \
  --data-urlencode 'rows=100' --data-urlencode 'sort[]=downloads desc' --data-urlencode 'output=json' \
| jq -r '.response.docs[] | "\(.identifier) | \(.licenseurl)"'
# numFound=1565, idêntico em 3 execuções

# nome do arquivo SEMPRE do metadata (nunca chutar) + URL-encode + --fail
ID=CoffeeBeansFastFall
F=$(curl -s "https://archive.org/metadata/$ID" | jq -r '[.files[]|select((.format//"")|test("512Kb|h.264";"i"))][0].name')
curl -sL --fail "https://archive.org/download/$ID/$(jq -rn --arg f "$F" '$f|@uri')" -o /tmp/ia.mp4
```

## O que o creator-1 precisa fazer

Só uma coisa vale o cadastro, e leva ~2 minutos:

**1. Chave do Pexels (faça)**
   1. Criar conta grátis em `pexels.com` (email ou login social).
   2. Ir em `pexels.com/api/` → "Get Started".
   3. Preencher o form curto (nome + descrição do uso).
   4. A chave sai **na hora** — sem fila, sem cartão, sem custo. Fica em `pexels.com/api/new/`.
   5. Salvar como `PEXELS_API_KEY` no `env` dos settings do Claude Code.
   6. (Opcional) Pra subir de 200 req/h: email pro suporte mostrando a atribuição implementada — grátis.

**2. Chave do Pixabay (opcional, secundário)** — conta grátis, chave em `pixabay.com/api/docs`.
   Salvar como `PIXABAY_API_KEY`. Só faz diferença se o Pexels não cobrir o termo.

**Não vale a pena:** Coverr (licença contraditória entre duas páginas oficiais + 50 req/h no
tier grátis), Openverse (não tem vídeo), Videvo (morreu).

⚠️ As keys vivem só no `env` dos settings — script rodado fora de sessão precisa delas exportadas
no shell. Conferir com `python3 scripts/buscar.py --checar-chaves`.
Hoje o `buscar.py` implementa **pexels, pixabay e wikimedia**; Mixkit e Internet Archive são manuais.

## Armadilhas

**Chaves e rate limit**
- **Pexels sem chave devolve 200 e é MENTIRA.** É cache stale do Cloudflare (`cf-cache-status: HIT`,
  `age` de ~17 dias) de uma requisição autenticada de outra pessoa. Basta um param a mais
  (`&page=1`, `&cachebust=X`) pra virar `401 Missing API key`. `orientation=portrait` deu 401 em
  5/5 testes — justamente o param que a gente precisa. Não construir em cima disso: além de
  evaporar, consome quota de terceiro e cai em "API abuse" nos termos.
- Pexels: 200 req/h, 20.000/mês. Pixabay: 100 req/60s **por chave** + dever contratual de
  **cachear as respostas por 24h** e proibição de "systematic mass downloads" — o pipeline precisa
  de cache local do JSON.
- Mixkit: sem limite documentado, mas tem Cloudflare na frente (rate limit invisível). Throttle
  voluntário ~1 req/s + User-Agent identificável.
- Wikimedia: **User-Agent vazio = HTTP 403.** Sempre `-A "app/versao (email)"`, requisições em série.

**Arquivo bruto vs derivado**
- **Internet Archive: nunca adivinhar o nome do derivado.** Chute errado → HTTP 404, mas o curl
  **grava 137KB de HTML com extensão .mp4** e o ffprobe só quebra depois. Sempre `--fail` +
  nome vindo de `/metadata/<id>`. Nomes têm espaço → URL-encode, senão HTTP 000.
- **Wikimedia: pixel anamórfico.** A API reporta a dimensão de **exibição** (608x1080), o ffprobe
  lê a **codificada** (1920x1080, SAR 19:60). Apareceu em 1 de 3 downloads. Sem
  `scale=iw*sar:ih,setsar=1` o b-roll entra esmagado no Remotion.
- Wikimedia: codecs heterogêneos (VP8/VP9/AV1, Theora, mpeg) — não assumir H.264.
- Mixkit: bitrate altíssimo (6,5s vertical = 21MB). Reencodar ao guardar na biblioteca.
- Pexels/Mixkit: fps varia (24, 29.97) — normalizar pra timeline do projeto.

**Licença**
- **Mixkit tem DUAS licenças e as duas dizem "Free Download".** A "Restricted License" é
  **uso pessoal apenas** — proíbe explicitamente projeto comercial, anúncio, social de empresa e
  YouTube. Só aparece no HTML do item. Gate obrigatório em `"copyrightNotice":"Free"` ou
  `data-license="videoFree"`. **Nunca confiar no campo `license`** — no item restrito 27172 ele
  aponta pra `#videoFree` mesmo sendo restrito (metadata inconsistente deles).
- **Pexels exige atribuição via API**, mesmo a licença dizendo "Attribution is not required".
  Isso vale pra quem baixa pelo site; as API Guidelines exigem link visível pro Pexels + crédito
  ao fotógrafo ("Photo by [Nome] on Pexels"). Guardar `user.name` e `user.url` no INDEX desde já —
  reconstruir isso depois é impossível.
- **Pixabay: cláusula "Standalone".** Cortar b-roll dentro de um vídeo editado é permitido. Mas
  "solely using a filter, changing colors, **resizing or cropping**" continua sendo Standalone e é
  **proibido** — ou seja, publicar um clipe que é só o asset do Pixabay recortado pra 9:16 viola a
  licença. Travar isso: nunca renderizar output cujo único conteúdo visual seja um asset de banco
  sem composição própria.
- **Wikimedia: CC-BY-SA é a licença MAJORITÁRIA (15 de 40 na amostra; 13 de 24 na amostra de
  IMAGEM de 2026-08-08).** Share-alike é viral — usar num Reel que vende ebook/curso cria
  argumento de que o vídeo inteiro sai sob CC-BY-SA. Passa num filtro ingênuo de "livre pra
  comercial" — e passou no nosso por 14 dias (ver a nota no topo deste arquivo). O gate agora
  é `scripts/licenca.py`: tokeniza a string e testa **cláusula antes de família**, porque
  `"cc by-sa"` contém `"cc by"` e é assim que um filtro de substring aprova o que promete
  cortar. `--licencas` deixa incluir `cc-by-sa` conscientemente; imprime aviso e grava a
  decisão no candidato.
- **Google Custom Search fica FORA**, e a razão está registrada em `imagem.md`: no helper de
  referência, o mapa de direitos chamado `commercial` é o único que inclui `cc_noncommercial`,
  e os dois mapas misturam `sharealike`. O nome da opção contradiz o conteúdo dela — quem usa
  não tem como desconfiar. Além disso, `rights` do CSE é declaração do publicador, não licença
  verificável: é a mesma razão que reprovou o Coverr inteiro.
- Wikimedia: `haswbstatement` com `(X OR Y)` entre parênteses retorna **zero silenciosamente**.
  Sintaxe correta é pipe dentro do keyword: `haswbstatement:P275=A|P275=B`.
- Wikimedia: checar `extmetadata.Restrictions` — achei caso com `"personality"` (direito de imagem).
  Não-vazio = descartar. Preferir planos sem rosto reconhecível de qualquer jeito.
- **Internet Archive: BY-ND é NoDerivatives** — legalmente não dá pra cortar/inserir num edit, que
  é literalmente o que b-roll faz. ~33% da coleção `stock_footage` é BY-ND. E item **sem**
  `licenseurl` = inutilizável (o IA é host, não licenciador, e não garante nada).
- Pexels proíbe: pessoa identificável em contexto negativo/ofensivo, e sugerir endosso do produto
  por pessoa/marca que aparece no clipe. Vale pra qualquer beat crítico.

**Editorial**
- Pexels/Pixabay/Mixkit são **stock polido** — "cara de banco de imagem" denuncia produção
  artificial e derruba a conexão nos perfis do projeto. Usar como **textura e cutaway curto**,
  nunca como plano principal.
- Wikimedia e Internet Archive são o oposto: documental/amador/arquivo. Servem pra atmosfera e
  lugar real, não pra conceito de negócio. Não existe "empreendedor sorrindo no laptop" lá.
