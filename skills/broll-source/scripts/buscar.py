#!/usr/bin/env python3
"""buscar — procura b-roll com licença livre para uso COMERCIAL em vários bancos.

Devolve candidatos em JSON **e monta uma folha de contato com as miniaturas**, porque
a escolha do plano é editorial: eu (Claude) OLHO as miniaturas e escolho. O script
não decide nada — ele só traz opções com a licença carimbada.

Uso:
    buscar.py "<termo>" [--tipo video|imagem] [--n 12] [--vertical] [--dur-max 20]
                        [--provedores pexels,mixkit,pixabay,wikimedia]
                        [--licencas cc0,dominio-publico,cc-by] [--rendition original|large2x|large]
    buscar.py --checar-chaves

Saída:
    stdout                        JSON com os candidatos (id, provedor, licença, links)
    <BROLL_DIR>/busca-<slug>/     miniaturas + contato.png  (OLHE antes de baixar)

Env:
    PEXELS_API_KEY    ✅ JÁ CONFIGURADA (env dos settings). Melhor acervo; verticais 4K nativos
    PIXABAY_API_KEY   grátis em pixabay.com/api/docs
    BROLL_DIR         default: tools/broll-library

⚠️ REGRA DURA DO PROJETO: só CC0 / licença livre para uso comercial. Nada de rip de
   vídeo alheio (o "hack" de baixar b-roll de virais é violação de direito autoral).
   Todo candidato carrega `licenca` e `exige_atribuicao` — se exigir, o crédito TEM
   que entrar na legenda do post; prefira as fontes que não exigem.

📷 `--tipo imagem` (SPEC-29): a escada é INVERTIDA em relação à de vídeo —
   Wikimedia Commons primeiro, Pexels depois. O motivo é o tipo de pergunta: stock
   responde "um plano de comida"; só o Commons responde "O Cristo Redentor", "O
   Neymar" (referente único). Medido: em imagem, 59% do acervo do Commons é
   `CC BY-SA` — que esta skill REPROVA. Ver references/imagem.md.
"""
import argparse, json, os, re, subprocess, sys, unicodedata, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import licenca as lic_mod     # noqa: E402  (o gate único — SPEC-29 §3.2)

import perfil_do_bloco as perfil_mod   # noqa: E402  (SPEC-33 / achado A21)

RAIZ = os.environ.get("BROLL_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "tools", "broll-library")
RAIZ = os.path.abspath(RAIZ)
# ⚠️ NÃO REMOVA o User-Agent: o Pexels devolve 403 pro UA padrão do urllib
# ("Python-urllib/3.x") mesmo com a chave correta. Medido 2026-07-25: UA padrão → 403,
# este UA → 200. O curl passa porque manda UA próprio.
UA = {"User-Agent": "benchmark-system/1.0 (b-roll sourcing; contato via creator-1)"}


def http(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def slug(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40]


LICENCA_PEXELS = ("Pexels License — comercial livre; NÃO é CC0. Proíbe: vender cópia "
                  "crua, sugerir endosso, pessoa identificável em contexto negativo, "
                  "virar marca. Crédito não é exigido pelo conteúdo (é pelos Termos da API).")

MIME_POR_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp", "gif": "image/gif", "tif": "image/tiff",
                "tiff": "image/tiff"}


def mime_da_url(url, padrao="image/jpeg"):
    ext = re.sub(r"[?#].*$", "", url or "").rsplit(".", 1)[-1].lower()
    return MIME_POR_EXT.get(ext, padrao)


# ---------------------------------------------------------------- provedores
# Assinatura comum: (termo, n, vertical, dur_max, ctx) → (candidatos, aviso|None).
# `ctx` carrega o que é da BUSCA e não do provedor: tipo de mídia, política de
# licença e rendition. Provedor não decide política — ele só carimba a licença.
def pexels(q, n, vertical, dur_max, ctx):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return [], "sem PEXELS_API_KEY (grátis em pexels.com/api)"
    if ctx["tipo"] == "imagem":
        return pexels_imagem(q, n, vertical, key, ctx)
    p = {"query": q, "per_page": min(n * 2, 80)}
    if vertical:
        p["orientation"] = "portrait"
    d = http("https://api.pexels.com/videos/search?" + urllib.parse.urlencode(p),
             {"Authorization": key})
    out = []
    for v in d.get("videos", []):
        if dur_max and v.get("duration", 0) > dur_max:
            continue
        arqs = sorted(v["video_files"], key=lambda f: -(f.get("width") or 0))
        if not arqs:
            continue
        out.append({"provedor": "pexels", "tipo": "video", "id": str(v["id"]),
                    "mime": "video/mp4",
                    "w": v["width"], "h": v["height"], "dur": v.get("duration"),
                    "autor": v.get("user", {}).get("name"), "pagina": v.get("url"),
                    "thumb": v.get("image"), "download": arqs[0]["link"],
                    "licenca": LICENCA_PEXELS,
                    "exige_atribuicao": False})
    return out[:n], None


def pexels_imagem(q, n, vertical, key, ctx):
    """Mesmo host, mesma chave, mesmo header — troca `videos/search` por `v1/search`.

    ⚠️ A rendition baixada é `src.original`. `src.portrait` e `src.landscape` são
    RECORTES (800×1200 fixo), e guardar recorte viola a regra que esta skill já
    escreveu: os clipes não são recortados na hora de guardar — quem enquadra é o
    `split-broll.py` (ou o `imagem-clipe.py`). `--rendition large2x` existe para
    quem quiser economizar banda; é TAMANHO, não recorte.
    """
    p = {"query": q, "per_page": min(n * 2, 80)}
    if vertical:
        p["orientation"] = "portrait"
    d = http("https://api.pexels.com/v1/search?" + urllib.parse.urlencode(p),
             {"Authorization": key})
    out = []
    for f in d.get("photos", []):
        src = f.get("src", {}) or {}
        url = src.get(ctx["rendition"]) or src.get("original")
        if not url:
            continue
        out.append({"provedor": "pexels", "tipo": "imagem", "id": str(f["id"]),
                    "mime": mime_da_url(url),
                    "w": f.get("width"), "h": f.get("height"), "dur": None,
                    "autor": f.get("photographer"), "pagina": f.get("url"),
                    "thumb": src.get("medium") or src.get("small"),
                    "download": url,
                    "rendition": ctx["rendition"],
                    "licenca": LICENCA_PEXELS,
                    "exige_atribuicao": False})
    return out[:n], None


def pixabay(q, n, vertical, dur_max, ctx):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return [], "sem PIXABAY_API_KEY (grátis em pixabay.com/api/docs)"
    p = {"key": key, "q": q, "per_page": min(max(n * 2, 3), 200), "video_type": "film"}
    d = http("https://pixabay.com/api/videos/?" + urllib.parse.urlencode(p))
    out = []
    for v in d.get("hits", []):
        if dur_max and v.get("duration", 0) > dur_max:
            continue
        vs = v.get("videos", {})
        melhor = max(vs.values(), key=lambda f: f.get("width", 0)) if vs else None
        if not melhor:
            continue
        if vertical and melhor.get("width", 0) >= melhor.get("height", 1):
            continue
        out.append({"provedor": "pixabay", "tipo": "video", "id": str(v["id"]),
                    "mime": "video/mp4",
                    "w": melhor.get("width"), "h": melhor.get("height"), "dur": v.get("duration"),
                    "autor": v.get("user"), "pagina": v.get("pageURL"),
                    "thumb": (vs.get("tiny") or {}).get("thumbnail"),
                    "download": melhor["url"],
                    # ⚠️ duas camadas: CC0 só pra publicações ANTERIORES a 2019-01-09; o resto é a
                    # Pixabay Content License, que proíbe uso "Standalone" — e recortar/redimensionar
                    # SOZINHO ainda conta como standalone. Compor com fala + legenda + corte (o que a
                    # nossa ilha faz) é obra nova e está liberado. Marca/logo reconhecível em uso
                    # comercial é proibido explicitamente.
                    "licenca": "Pixabay Content License — comercial livre desde que COMPOSTO "
                               "(recorte sozinho ainda conta como redistribuição). Sem marca/logo.",
                    "exige_atribuicao": False})
    return out[:n], None


def wikimedia(q, n, vertical, dur_max, ctx):
    """Sem chave. Em VÍDEO é plano C (acervo documental/amador); em IMAGEM é o
    PRIMEIRO degrau, porque só ele responde a referente único (uma pessoa, um
    monumento, uma obra) — stock não tem.

    🔴 O gate de licença aqui era por substring de família e VAZAVA: `"cc by-sa
    4.0"` contém `"cc by"`, então `CC BY-SA` e `CC BY-NC` passavam apesar do
    comentário dizer o contrário (medido: 24/24 candidatos passando, 13 deles
    BY-SA). Agora é `licenca.classificar()` — cláusula antes de família, e a
    política vem de `--licencas`. O conserto vale para vídeo TAMBÉM.
    """
    imagem = ctx["tipo"] == "imagem"
    # `filetype:bitmap` exclui SVG, áudio e vídeo NA ORIGEM. Medido: a busca crua
    # por "Neymar" devolveu audio/mpeg e image/svg+xml entre 12; com bitmap, 12/12
    # vieram image/*. O gate de mime abaixo é o segundo cinto.
    # gsrlimit n*3 em imagem: só ~41% do acervo sobrevive ao gate de licença (§2.4).
    p = {"action": "query", "format": "json", "generator": "search",
         "gsrsearch": f"filetype:{'bitmap' if imagem else 'video'} {q}",
         "gsrnamespace": "6",
         "gsrlimit": str(min(n * 3, 50) if imagem else min(n * 2, 50)),
         "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": "480"}
    d = http("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(p))
    out = []
    for pg in (d.get("query", {}).get("pages", {}) or {}).values():
        ii = (pg.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {}) or {}
        lic = (meta.get("LicenseShortName", {}) or {}).get("value", "?")
        mime = ii.get("mime", "") or ""
        ctx["vistos"] += 1
        if imagem and (not mime.startswith("image/") or mime == "image/svg+xml"):
            ctx["descartes"]["mime:" + (mime or "?")] += 1
            continue      # SVG não é foto: é vetor de logo, justamente o que não queremos
        cl = lic_mod.classificar(lic)
        ok, motivo = lic_mod.aprovado(cl, ctx["politica"])
        if not ok:
            ctx["descartes"][cl["slug"]] += 1
            continue
        # `Restrictions` do Commons é direito de IMAGEM, não licença: o
        # references/fontes.md:211 desta skill já registra o caso `"personality"`.
        # Em vídeo quase não aparece; em imagem de pessoa é o normal. Aviso, não
        # veto — quem decide se o uso é editorial é quem edita, não o script.
        restr = (meta.get("Restrictions", {}) or {}).get("value", "") or ""
        if restr:
            print(f"  ⚠️ {pg.get('title')}: Restrictions={restr!r} — direito de imagem "
                  f"(não é licença). Só uso editorial, nunca ao lado de oferta.",
                  file=sys.stderr)
        ctx["aprovados"] += 1     # ANTES do out[:n] — a contagem do gate não pode
        #                           depender do truncamento, senão --licencas some
        #                           dentro do corte e o número deixa de ser prova.
        out.append({"provedor": "wikimedia", "tipo": ctx["tipo"], "id": pg.get("title"),
                    "mime": mime or (None if imagem else "video/*"),
                    "w": ii.get("width"), "h": ii.get("height"), "dur": None,
                    "autor": re.sub("<[^>]+>", "", (meta.get("Artist", {}) or {}).get("value", "") or ""),
                    "pagina": ii.get("descriptionurl"), "thumb": ii.get("thumburl"),
                    "download": ii.get("url"), "licenca": f"Wikimedia — {lic}",
                    "licenca_slug": cl["slug"], "restricoes": restr or None,
                    "exige_atribuicao": cl["exige_atribuicao"]})
    return out[:n], None


def mixkit(q, n, vertical, dur_max, ctx):
    """SEM CHAVE e com stock POLIDO (é o braço gratuito da Envato) — o provedor padrão.

    Não tem API REST: é uma cadeia de páginas públicas (robots.txt `Allow: /`).
    ⚠️ **GATE DE LICENÇA OBRIGATÓRIO**: o mesmo acervo mistura a *Stock Video Free
    License* (comercial liberado) com a *Restricted License* (**pessoal apenas** —
    proíbe explicitamente "Commercial Projects, Advertising, Company Social Media
    posts, YouTube videos"). Os dois aparecem lado a lado na busca e os dois dizem
    "Free Download". A diferença só existe no HTML do item: `"copyrightNotice":"Free"`.
    Sem checar item a item, o pipeline puxa material PROIBIDO. Por isso o custo de
    1 request por candidato aqui não é negociável.
    ⚠️ O filtro de orientação SÓ funciona na rota `/discover/<tag>/` — em
    `/free-stock-video/<tag>/?orientation=...` ele é silenciosamente ignorado.
    """
    tag = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")
    url = f"https://mixkit.co/free-stock-video/discover/{urllib.parse.quote(tag)}/"
    if vertical:
        url += "?orientation=vertical"
    req = urllib.request.Request(url, headers={**UA, "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        html = r.read().decode("utf-8", "replace")
    itens, vistos = [], set()
    for m in re.finditer(r'href="(/free-stock-video/([a-z0-9-]+)-(\d+)/)"', html):
        if m.group(3) in vistos:
            continue
        vistos.add(m.group(3))
        itens.append((m.group(1), m.group(3)))
    if not itens:
        # ⚠️ `/discover/<tag>/` é TAXONOMIA, não busca livre: tag inexistente devolve
        # HTTP 200 com página vazia (não 404). Medido: "drive-thru" → 0 itens;
        # "burger" → 3; "food" → 24; "restaurant" → 14. Termo composto quase sempre falha.
        return [], (f"mixkit: a tag '{tag}' não existe na taxonomia deles (página vazia, não 404). "
                    f"Tente UMA palavra concreta: food, burger, restaurant, kitchen, city, business…")
    out = []
    for caminho, vid in itens[: n * 3]:
        if len(out) >= n:
            break
        try:
            rq = urllib.request.Request("https://mixkit.co" + caminho,
                                        headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(rq, timeout=25) as r:
                pg = r.read().decode("utf-8", "replace")
        except Exception:
            continue
        lic = (re.findall(r'"copyrightNotice"\s*:\s*"([^"]*)"', pg) or [""])[0]
        if lic.strip().lower() != "free":       # gate: Restricted é uso PESSOAL
            continue
        iso = (re.findall(r'"duration"\s*:\s*"(PT[^"]*)"', pg) or [""])[0]
        mm = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", iso)
        dur = (int(mm.group(1) or 0) * 60 + int(mm.group(2) or 0)) if mm else None
        if dur_max and dur and dur > dur_max:
            continue
        thumb = (re.findall(r'"thumbnailUrl"\s*:\s*"([^"]*)"', pg) or [None])[0]
        out.append({"provedor": "mixkit", "tipo": "video", "id": vid, "mime": "video/mp4",
                    "w": ALVO_W if vertical else None, "h": ALVO_H if vertical else None,
                    "dur": dur, "autor": "Mixkit/Envato",
                    "pagina": "https://mixkit.co" + caminho, "thumb": thumb,
                    "download": f"https://assets.mixkit.co/videos/{vid}/{vid}-1080.mp4",
                    "licenca": "Mixkit Stock Video Free License — comercial livre, sublicenciável",
                    "exige_atribuicao": False})
    return out, None


# 📐 A resolução-alvo do candidato vertical vem do perfil de peça (SPEC-00): o
# Mixkit não expõe w/h no HTML, então o script anota o alvo da PEÇA. Cravar
# 1080x1920 fazia o candidato mentir a dimensão numa peça 16:9.
# Preenchido em main(); FALLBACK (1080x1920) quando não há perfil.
ALVO_W, ALVO_H = 1080, 1920


# O eixo novo é o TIPO DE MÍDIA, e ele entra na tabela — não num script separado
# (que duplicaria HTTP, folha de contato, slug e o gate de licença).
PROVEDORES = {
    # nome            função      tipos aceitos
    "mixkit":    (mixkit,    {"video"}),
    "pexels":    (pexels,    {"video", "imagem"}),   # dois endpoints, uma função
    "pixabay":   (pixabay,   {"video"}),
    "wikimedia": (wikimedia, {"video", "imagem"}),
}
# Em vídeo o Wikimedia é plano C; em imagem é o primeiro degrau. Ver §3.1 da SPEC-29.
DEFAULT_POR_TIPO = {"video": "pexels,mixkit", "imagem": "wikimedia,pexels"}

AVISO_MARCA_PESSOA = (
    "⚠️ IMAGEM: duas travas que a busca por vídeo quase não exercita —\n"
    "   · MARCA registrada (logo, embalagem, fachada) não pode ser usada comercialmente\n"
    "     em relação a bens e serviços. O Commons é CHEIO de logo e a busca por marca\n"
    "     FUNCIONA. Para \"o McDonald's vende mais\", use hambúrguer genérico.\n"
    "   · PESSOA identificável: foto de pessoa pública em contexto editorial ≠ foto de\n"
    "     pessoa pública ao lado da sua oferta. A própria licença do Pexels proíbe\n"
    "     \"sugerir endosso\" e \"pessoa identificável em contexto negativo\".")


# ---------------------------------------------------------------- folha de contato
def folha(cands, destino):
    os.makedirs(destino, exist_ok=True)
    from PIL import Image, ImageDraw
    ims = []
    for i, c in enumerate(cands):
        if not c.get("thumb"):
            continue
        p = os.path.join(destino, f"t{i:02d}.jpg")
        try:
            if not os.path.exists(p):
                req = urllib.request.Request(c["thumb"], headers=UA)
                with urllib.request.urlopen(req, timeout=20) as r, open(p, "wb") as f:
                    f.write(r.read())
            im = Image.open(p).convert("RGB")
            im.thumbnail((320, 320))
            t = Image.new("RGB", (320, 260), "black")
            t.paste(im, ((320 - im.width) // 2, (200 - im.height) // 2 + 20))
            d = ImageDraw.Draw(t)
            # imagem não tem duração: no lugar dela vai o slug da licença, que é o
            # que decide se o candidato é usável (78% das imagens aprovadas exigem
            # crédito, contra 0 dos clipes de vídeo hoje na biblioteca).
            marca = (c.get("licenca_slug") or "?") if c.get("tipo") == "imagem" \
                else f"{c.get('dur') or '?'}s"
            d.text((5, 3), f"[{i}] {c['provedor']} {c.get('w')}x{c.get('h')} {marca}", fill="yellow")
            d.text((5, 232), (c.get("autor") or "")[:40], fill="#aaa")
            ims.append(t)
        except Exception as e:
            print(f"  miniatura {i} falhou: {e}", file=sys.stderr)
    if not ims:
        return None
    cols = min(5, len(ims))
    rows = (len(ims) + cols - 1) // cols
    out = Image.new("RGB", (cols * 324, rows * 264), "black")
    for i, im in enumerate(ims):
        out.paste(im, ((i % cols) * 324, (i // cols) * 264))
    cam = os.path.join(destino, "contato.png")
    out.save(cam)
    return cam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("termo", nargs="?")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--vertical", action="store_true")
    ap.add_argument("--dur-max", type=float, default=None)
    ap.add_argument("--tipo", choices=("video", "imagem"), default="video")
    ap.add_argument("--provedores", default=None,
                    help="default depende do --tipo: video → pexels,mixkit; imagem → wikimedia,pexels")
    ap.add_argument("--licencas", default=",".join(lic_mod.POLITICA_DEFAULT),
                    help="política de licença DE ARQUIVO (Wikimedia). Domínio fechado: "
                         + ", ".join(lic_mod.SLUGS_ARQUIVO))
    ap.add_argument("--rendition", choices=("original", "large2x", "large"), default="original",
                    help="tamanho da foto do Pexels. NUNCA portrait/landscape: são RECORTES")
    ap.add_argument("--checar-chaves", action="store_true")
    ap.add_argument("--perfil", help="dir da produção ou perfil.json — dá a resolução-alvo "
                                     "e a orientação (default: FALLBACK, 1080x1920)")
    a = ap.parse_args()

    global ALVO_W, ALVO_H
    P, _fonte_perfil = perfil_mod.carregar(
        a.perfil or os.environ.get("BENCH_PERFIL") or ".", quieto=False)
    ALVO_W, ALVO_H = int(P["video"]["largura"]), int(P["video"]["altura"])
    if not a.vertical and ALVO_H > ALVO_W:
        a.vertical = True    # a peça é vertical: buscar landscape é desperdiçar zoom

    if a.checar_chaves:
        for k, onde in [("PEXELS_API_KEY", "pexels.com/api"), ("PIXABAY_API_KEY", "pixabay.com/api/docs")]:
            print(f"{k:18s} {'OK' if os.environ.get(k) else 'FALTA — grátis em ' + onde}")
        print(f"{'wikimedia':18s} OK (não precisa de chave)")
        print(f"{'--tipo imagem':18s} OK sem chave nenhuma (wikimedia); "
              f"pexels de foto usa a MESMA PEXELS_API_KEY")
        print(f"\nBROLL_DIR = {RAIZ}")
        return
    if not a.termo:
        sys.exit("informe o termo de busca (ou --checar-chaves)")

    try:
        politica = lic_mod.validar_politica(a.licencas)
    except ValueError as e:
        sys.exit(str(e))
    if "cc-by-sa" in politica:
        print("⚠️ SA é viral: a obra derivada herda a licença — o vídeo inteiro entra "
              "no argumento. Ficará gravado `politica_licenca` em cada candidato.",
              file=sys.stderr)
    if a.tipo == "imagem":
        print(AVISO_MARCA_PESSOA, file=sys.stderr)

    import collections
    ctx = {"tipo": a.tipo, "politica": politica, "rendition": a.rendition,
           "vistos": 0, "aprovados": 0, "descartes": collections.Counter()}

    todos, avisos = [], []
    for nome in (a.provedores or DEFAULT_POR_TIPO[a.tipo]).split(","):
        nome = nome.strip()
        par = PROVEDORES.get(nome)
        if not par:
            avisos.append(f"provedor desconhecido: {nome}"); continue
        fn, tipos = par
        if a.tipo not in tipos:
            # pulado, nunca erro silencioso: é o mesmo padrão do aviso de chave.
            avisos.append(f"{nome}: não atende --tipo {a.tipo} (só {'/'.join(sorted(tipos))}) — pulado")
            continue
        try:
            r, aviso = fn(a.termo, a.n, a.vertical, a.dur_max, ctx)
            if aviso:
                avisos.append(f"{nome}: {aviso}")
            todos += r
            print(f"  {nome}: {len(r)} candidatos", file=sys.stderr)
        except Exception as e:
            avisos.append(f"{nome}: {type(e).__name__} {e}")

    # 2º cinto: TODO candidato passa pelo gate, inclusive os de provedor que já
    # carimbam a própria licença. Um provedor novo que esqueça de chamar o gate não
    # consegue vazar por aqui — e o `licenca_slug` fica gravado no candidato.
    filtrados = []
    for c in todos:
        cl = lic_mod.classificar(c.get("licenca", ""))
        c["licenca_slug"] = cl["slug"]
        if "cc-by-sa" in politica:
            c["politica_licenca"] = ",".join(politica)
        ok, motivo = lic_mod.aprovado(cl, politica)
        if not ok:
            ctx["descartes"][cl["slug"]] += 1
            print(f"  gate: descartado {c.get('id')} — {motivo}", file=sys.stderr)
            continue
        filtrados.append(c)
    todos = filtrados

    # ⚠️ imprima QUANTO o gate varreu: um gate que examinou 0 e aprovou 0 é
    # indistinguível de um quebrado. `vistos` só é contado onde a licença é DE
    # ARQUIVO (wikimedia) — nos outros o número honesto é o de aprovados.
    if ctx["vistos"] or ctx["descartes"]:
        print(f"  gate de licença: {len(todos)} aprovados"
              + (f" ({ctx['aprovados']} antes do corte por --n)"
                 if ctx["aprovados"] != len(todos) else "")
              + (f" de {ctx['vistos']} examinados" if ctx["vistos"] else "")
              + f" (política: {','.join(politica)}); descartes: "
              + f"{dict(ctx['descartes']) or 'nenhum'}", file=sys.stderr)

    for w in avisos:
        print(f"  ⚠️ {w}", file=sys.stderr)
    if not todos:
        print("\nNENHUM candidato. Caminhos:", file=sys.stderr)
        print("  1. configurar PEXELS_API_KEY (grátis, 2 min) — de longe o melhor acervo", file=sys.stderr)
        print("  2. gerar o plano com a skill `omni-insert` (funciona hoje, custa ~$0,8/8s)", file=sys.stderr)
        print("  3. filmar/usar acervo próprio", file=sys.stderr)
        sys.exit(2)

    destino = os.path.join(RAIZ, "busca-" + slug(a.termo))
    cam = folha(todos, destino)
    for i, c in enumerate(todos):
        c["i"] = i
    print(json.dumps(todos, ensure_ascii=False, indent=1))
    if cam:
        print(f"\nfolha de contato: {cam}  ← OLHE antes de escolher", file=sys.stderr)


if __name__ == "__main__":
    main()
