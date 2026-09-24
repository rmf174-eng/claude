---
name: video-download
description: Baixa vídeo + metadados normalizados de um link de Instagram (reel/post), TikTok, YouTube/Shorts ou qualquer site suportado pelo yt-dlp. Use quando o usuário mandar um link de vídeo pra baixar, transcrever, analisar ou benchmarkar. Bloco modular — é a etapa 1 do pipeline de benchmarking (download → transcribe → content-analysis).
---

# video-download

Bloco 1 do pipeline de benchmarking: **URL → `video.mp4` + `meta.json` normalizado**.

## Como executar

```bash
.claude/skills/video-download/scripts/download.sh "<url>" [outdir]
```

- **Sem `outdir`**: salva em `data/adhoc/<plataforma>-<id>/` (modo vídeo avulso).
- **Com `outdir`**: usado pelo orquestrador (`benchmark-profile`) pra salvar em `data/profiles/<handle>/posts/<id>/`.
- O script imprime o diretório final no stdout — capture pra encadear com o próximo bloco.
- Idempotente: se `video.mp4` já existe no destino, não baixa de novo.

## Contrato de saída (schema `benchmark.post.meta/v1`)

```
<outdir>/
├── video.mp4        # vídeo final (mp4, pronto pro ffmpeg)
├── video.jpg        # thumbnail
├── video.info.json  # dump bruto do yt-dlp (backup de tudo)
└── meta.json        # normalizado: platform, id, url, title, caption,
                     # author{handle,name}, upload_date, duration_s,
                     # metrics{views,likes,comments,shares}, files{}, fetched_at
```

Campos de `metrics` podem ser `null` — Instagram sem cookies raramente entrega views; TikTok e YouTube entregam quase tudo.

## Instagram e cookies

Reel público sai anonimamente e é o caso normal. Quando o post exige login, o script tenta nesta ordem:

1. **`BENCH_COOKIES=/caminho/cookies.txt`** (formato Netscape) — **é o caminho recomendado**. Não depende de Keychain nem de sessão interativa, então funciona igual dentro de um agente.
2. **Perfis do browser que tenham cookie do domínio alvo** — o script procura os perfis na mão porque o yt-dlp assume `Default`, que nesta máquina não existe (os perfis são `Profile 1` e `Profile 3`).

Se tudo falhar, o script **diz qual das condições faltou** e sai com status 1. As três causas exigem correções diferentes:

- **Não há sessão logada em nenhum perfil.** Nada a consertar no código: precisa logar no site pelo Chrome, ou exportar um cookies.txt.
- **Keychain nega a chave.** `security find-generic-password -w -s "Chrome Safe Storage"` devolve `User interaction is not allowed` — o macOS exige um diálogo de aprovação que não aparece em sessão de agente. O usuário roda esse comando uma vez no terminal dele e escolhe "Sempre Permitir".
- **Cookies expirados.** Reexportar o arquivo.

⚠️ **Medido em 2026-07-26**: nenhum browser desta máquina tem sessão do Instagram (Chrome `Profile 1`/`Profile 3` e Safari, todos com zero cookies de instagram.com). Então hoje, na prática, post de Instagram que exige login **não sai** por nenhum dos dois caminhos até o creator-1 logar no Chrome ou exportar cookies.

**Antes de tentar autenticar, pergunte se o vídeo alvo é um react.** Se for, o que interessa quase sempre é o clipe-fonte, não o vídeo de quem reagiu — e a fonte costuma estar num YouTube público, sem marca d'água e com a citação correta. Ver a regra em `CLAUDE.md`.

## Carrossel e foto (conteúdo estático)

O yt-dlp não baixa post de foto/carrossel. Pra esses, use o segundo script, que lê as URLs do dump bruto do Apify (`apify-posts.json`, gerado pelo `profile-extract`):

```bash
.claude/skills/video-download/scripts/download-images.sh <dir-do-perfil> <post-id> [outdir]
```

Saída: `slide-01.jpg`, `slide-02.mp4`... (na ordem do carrossel; slides de vídeo viram .mp4) + `meta.json` com `type: carousel|photo` e `files.slides[]`. **URLs de CDN do Instagram expiram em dias** — se der 403, rode o extract de novo. Pra carrossel avulso sem extração prévia (link solto), rode antes o `extract-apify-instagram.sh` do perfil, ou use a skill `use-my-browser`.

## VSL em player VTurb / ConverteAI (o player líder de VSL no Brasil)

VSL de página de vendas **não está no HTML** e o yt-dlp não resolve a página. Fica num player
JS que monta o HLS em runtime. Como quase todo funil de VSL brasileiro roda VTurb/ConverteAI,
isso é a diferença entre medir a oferta e só olhar a landing por fora.

```bash
bash .claude/skills/video-download/scripts/vturb-extract.sh <url-da-pagina> <outdir> [--probe-only]
```

Resolve **teste A/B** sozinho: descobre todas as variantes servidas, os pesos, os CTAs com o
segundo exato em que aparecem e os destinos dos botões — depois baixa cada variante.
`--probe-only` mapeia sem baixar (rápido e de graça).

Saída: `player-map.md` (variantes, pesos, CTAs, destinos) + `var<N>-<media_id>/video.mp4` por
variante. Idempotente por variante.

**A rota, medida em 2026-08-01:**

1. na página: `scripts.converteai.net/<conta>/ab-test/<teste>/player.js` (teste A/B) ou
   `.../players/<id>/player.js` (variante única)
2. nesse `player.js`: `children[]` com `id` + `weight` de cada variante, os `callActions` com
   `range:{start}` e as URLs de poster, que é de onde sai o `<media_id>` de cada variante
3. `https://cdn.converteai.net/<conta>/<media_id>/main.m3u8` → **200**.
   ⚠️ `master.m3u8` e `playlist.m3u8` no mesmo host dão **403**; `m3u8.vturb.net` serve
   `playlist.m3u8` e funciona como fallback (nem toda mídia responde nele).
4. `yt-dlp -f b` no m3u8, **com `--referer` da página** (sem isso a CDN recusa).

**O que o `player.js` entrega além do vídeo** e não existe em lugar nenhum da landing: o
segundo em que o botão aparece (mede quanto de VSL a pessoa engole antes da oferta), o texto
literal do CTA por variante, e o link de checkout com os parâmetros de campanha.

**Uma conta ConverteAI por projeto.** No caso medido, o funil do cliente hospedado no mesmo
domínio usava conta separada — a conta é boa chave pra separar operação própria de coprodução.

**Duas estruturas de config, e elas não se parecem** (a segunda foi medida no Tintim,
2026-08-01, e o script cobre as duas desde então):

| | estrutura nova (`ab-test/`) | estrutura v1 (`players/`, antiga) |
|---|---|---|
| onde está a config | campos soltos no bundle | objeto JSON `vTurbOriginalPlayer={…}` |
| esconder a barra | `progressBar:false` | `displays.seekbar:false` |
| CTA | `callActions[]` com `range.start` | `options.callAction[]` (pode vir **vazio**) |
| versão mobile | mesmo bundle | `vTurbAlternativePlayer` separado |

⚠️ Dois detalhes que quebram o parse do JSON v1: `!0`/`!1` no lugar de `true`/`false`, e
escapes hex `\xNN` que não são JSON válido. O script já trata ambos.

⚠️ **`callAction: []` não significa "sem CTA"** — significa que o CTA está no HTML da página,
não no vídeo. No Tintim são seis botões diferentes na landing e nenhum dentro do player.

Precedentes:
- `data/advertisers/meta-ref-E/VSL-ABTEST.md` — estrutura nova, 3 variantes de 33,3%
  testando só a abertura, corpo idêntico a partir dos ~55s.
- `data/advertisers/meta-tintim/VSL-INTEL.md` — estrutura v1, duas durações da mesma VSL
  (27min e 14min) convivendo, com o diff do que foi cortado entre elas.

**Vale transcrever e comparar versões.** Quando o anunciante mantém duas durações da mesma
VSL no ar, o diff entre elas é a evidência mais limpa que existe do que ele julga essencial:
alinhe as utterances com `difflib` e olhe o que sobreviveu, não o que saiu.

## VSL em Vimeo com whitelist de domínio

Muita landing brasileira usa Vimeo em vez de VTurb para vídeo de evento e aula. Quando o vídeo
está com "hide from vimeo.com" + domínio autorizado, `yt-dlp` sozinho devolve **HTTP 401** ou
*"blocked due to its TLS fingerprint"*, mesmo com `--referer` correto.

**A rota que funciona (medida em 2026-08-01):**

```bash
# 1) venv com impersonation — o yt-dlp 2026.07 exige curl_cffi 0.10.x–0.15.x (0.16+ é rejeitada)
python3 -m venv tools/.venv-ytdlp
tools/.venv-ytdlp/bin/pip install yt-dlp "curl_cffi>=0.15,<0.16"

# 2) baixar com fingerprint de browser + referer DA PÁGINA onde o vídeo está embutido
tools/.venv-ytdlp/bin/python -m yt_dlp --impersonate Chrome-136 \
  --referer "https://dominio.com/a-pagina/" \
  -f "bv*[height<=720]+ba/b" --merge-output-format mp4 \
  -o out/video.mp4 "https://player.vimeo.com/video/<id>"
```

Não instale `curl_cffi` no Python do sistema — o macOS usa PEP 668 e `--break-system-packages`
arrisca quebrar o ambiente. O venv resolve.

**Data e título sem baixar** (útil para datar a operação antes de gastar banda):

```bash
curl -sL -e "https://dominio.com/a-pagina/" \
  "https://vimeo.com/api/oembed.json?url=https%3A%2F%2Fplayer.vimeo.com%2Fvideo%2F<id>"
```

O oEmbed **com Referer** devolve `upload_date` e `title` mesmo em vídeo restrito — sem Referer
devolve vazio. Os títulos internos costumam entregar de graça o que a página esconde: no caso
medido, `"Oferta - Funil 100 KD - 8 de julho"` e `"DEPOIMENTOS DA ENGRENAGEM 2.0 (3)"`.

⚠️ **Os IDs de formato do Vimeo são POR VÍDEO, não por conta.** Medido em
2026-08-05: duas aulas da mesma imersão, subidas no mesmo dia, na mesma conta, na
mesma resolução final de 1512x982 — e os IDs eram `hls-akfire_interconnect_quic-849`
e `hls-akfire_interconnect_quic-894`. Reaproveitar o ID do primeiro vídeo no
segundo devolve `ERROR: Requested format is not available`. Selecione por
propriedade, nunca por ID:

```bash
-f "bv*[height<=982][height>=900]/bv*"          # vídeo, pela altura
-f "ba[language=pt]/ba"                          # áudio, pelo idioma
```

⚠️ **Baixe áudio e vídeo em processos separados quando a análise começa pelo
texto.** Os dois competem pela mesma banda no mesmo host: numa aula de 2h, o
áudio (60 MB) fica preso atrás do vídeo (770 MB) e a transcrição só começa 30
minutos depois. Baixe `-x --audio-format mp3` primeiro, dispare o `transcribe`, e
só então puxe o `bv*` — o `.part` do vídeo é retomável, então pausar não custa
nada.

⚠️ **Confira a duração dos dois streams depois do merge.** Se o processo for interrompido, o
`yt-dlp` pode ter baixado o vídeo inteiro e o áudio pela metade, e o merge não reclama:
`ffprobe -show_entries stream=codec_type,duration` denuncia (aconteceu aqui: vídeo 3222s, áudio
2116s, e a transcrição saiu 35min em vez de 54min).

## Limites conhecidos

- `instagram:user` (perfil inteiro) está **quebrado** no yt-dlp — pra extrair perfil use a skill `profile-extract`.
- Stories exigem cookies sempre.
- **Alguns reels vêm SEM faixa de áudio no acesso anônimo** — e nenhum truque de download resolve. Medido em 2026-08-05 nos posts `post-ref-H-1` e `post-ref-H-2` da ref-H: `yt-dlp -F` lista **só formatos `video only`** (todos os DASH e os progressivos 0/1/2), `-f "bv*+ba/b"` não acha áudio pra mesclar, e o `videoUrl` do Apify baixado direto via curl também vem mudo. Outros posts do mesmo perfil, baixados no mesmo minuto, vêm com áudio normalmente — então não é bloqueio de conta nem rate limit, é o post. Diagnóstico em 1 comando: `ffprobe -v error -show_entries stream=codec_type -of csv=p=0 video.mp4` — se sair só `video`, é isso.
  **Saída**: se as legendas forem queimadas (caso comum em reel de aula), reconstruir a fala com o Gemini lendo a imagem, salvando em `transcript-visual.md` com o aviso de **fonte única** — pela regra do projeto nada dali vira citação literal, e os timestamps do Gemini derrapam em vídeo longo (num caso ele devolveu 206s pra um vídeo de 127s). Com cookies de sessão logada (`BENCH_COOKIES`) pode ser que o áudio apareça; não foi testado.
- VSL em VTurb: a resolução do master é a que o anunciante subiu (no caso medido, 404x720 vertical). Não existe versão maior na CDN.

## Composição

Próximo bloco: vídeo → `transcribe`; carrossel/foto → `analyze-images.py` da skill `content-analysis` (gera `slides.json`, o "transcript" do conteúdo estático).
