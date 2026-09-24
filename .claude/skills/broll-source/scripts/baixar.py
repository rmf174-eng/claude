#!/usr/bin/env python3
"""baixar — baixa um candidato escolhido, normaliza e registra na biblioteca com a LICENÇA.

A biblioteca é cumulativa: uma vez baixado, o clipe fica em `tools/broll-library/clips/`
(vídeo) ou `tools/broll-library/imagens/` (foto) e nunca é rebaixado. O `INDEX.json`
guarda de onde veio, sob que licença e com que termos foi achado — porque **licença sem
procedência é licença que ninguém consegue provar depois**.

Uso:
    baixar.py --json <candidatos.json> --i 3 [--tags "mcdonalds,fast-food"] [--nome mc-fachada]
    baixar.py --url <URL> [--tipo imagem] --provedor manual --licenca "CC0" --autor "..." [--nome x]
    baixar.py --listar [--tag fast-food] [--tipo imagem|video]
    baixar.py --creditos [--tag X | --nomes a,b,c] [--formato legenda|markdown]

Saída: caminho do artefato (stdout).

VÍDEO — normalização: `fps` do perfil de peça, sem áudio, H.264 CRF 18, tags de cor.
IMAGEM — **não passa por ffmpeg**: entra como veio, com a extensão vinda do MIME.
Re-encodar perderia qualidade e os metadados EXIF de autoria, que são justamente a
prova de procedência que o índice existe para guardar. Quem enquadra é o
`split-broll.py` / `imagem-clipe.py`, que sabem qual faixa do frame precisa cobrir.

🔴 VALIDAÇÃO DE BYTES (SPEC-29 §1.3). Antes desta spec, qualquer resposta HTTP 200
virava arquivo: um HTML de erro de 54 bytes era gravado como `.mp4.download`, o
ffmpeg falhava com "Invalid data found" (diagnóstico errado — a causa era uma
PÁGINA, não corrupção) e o `.download` FICAVA no disco, porque o `os.remove` estava
depois do `sys.exit`. Em imagem não há ffmpeg no caminho: sem validação, um HTML de
erro do thumb server do Commons viraria `imagens/cristo-redentor.jpg` com licença
registrada e tudo. Agora: Content-Type é AVISO (servidor mente nos dois sentidos), o
primeiro bloco é inspecionado (HTML/XML → aborta) e imagem ainda passa por magic
number. O parcial morre num `try/finally`.
"""
import argparse, hashlib, json, os, subprocess, sys, urllib.error, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import licenca as lic_mod   # noqa: E402

import perfil_do_bloco as perfil_mod   # noqa: E402  (SPEC-33 / achado A21)

RAIZ = os.environ.get("BROLL_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "tools", "broll-library")
RAIZ = os.path.abspath(RAIZ)
CLIPS = os.path.join(RAIZ, "clips")
# ⚠️ o .gitignore ignora o CONTEÚDO de tools/broll-library/, então um `.gitkeep` não
# sobrevive ao clone — e na máquina de quem instalar o produto nada disso existe.
# Quem cria o diretório é o script, sempre (FRONTEIRA.md, orientação 9).
IMAGENS = os.path.join(RAIZ, "imagens")
INDEX = os.path.join(RAIZ, "INDEX.json")
UA = {"User-Agent": "benchmark-system/1.0 (b-roll sourcing)"}

EXT_POR_MIME = {"image/jpeg": ".jpg", "image/png": ".png",
                "image/webp": ".webp", "image/gif": ".gif"}
API_COMMONS = "https://commons.wikimedia.org/w/api.php"


class ErroMidia(Exception):
    """O que voltou não é mídia (página de erro, bytes errados)."""


class GrandeDemais(Exception):
    def __init__(self, bytes_):
        super().__init__(bytes_)
        self.bytes = bytes_


def indice():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else []


def salvar(ix):
    os.makedirs(RAIZ, exist_ok=True)
    json.dump(ix, open(INDEX, "w"), ensure_ascii=False, indent=1)


def tipo_de(e):
    """Entrada antiga não tem `tipo` — ausente significa `video` (índice v1)."""
    return e.get("tipo", "video")


def mime_de(e):
    if e.get("mime"):
        return e["mime"]
    ext = os.path.splitext(e.get("arquivo", ""))[1].lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "video/mp4")


def licenca_curta(txt):
    """"Wikimedia — CC BY 3.0" → "CC BY 3.0".

    ⚠️ NÃO corte no ponto: `"CC BY 3.0".split(".")[0]` devolve `"CC BY 3"` e o
    crédito passa a citar uma versão de licença que não existe.
    """
    t = (txt or "").split("—", 1)[-1].strip() if "—" in (txt or "") else (txt or "")
    return t.split(";")[0].strip()[:44]


# ------------------------------------------------------------------ download
def baixar_arquivo(url, destino, tipo, max_mb=None):
    """Baixa `url` em `destino`, recusando o que não é mídia. Nunca deixa parcial.

    Regra, escrita uma vez e valendo para os dois tipos:
      1. Content-Type é conferido contra o tipo esperado — AVISO, não veto. O
         Commons já serviu `application/octet-stream` para imagem boa e serve
         `text/html` para erro: vetar por Content-Type erra nos dois sentidos.
      2. O PRIMEIRO bloco lido é inspecionado. `<!doctype`/`<html`/`<?xml` → aborta.
      3. Imagem: além disso, magic number sobre o arquivo completo.
    """
    limite = int(max_mb * 1024 * 1024) if max_mb else None
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            ct = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            cl = r.headers.get("Content-Length")
            if limite and cl and cl.isdigit() and int(cl) > limite:
                raise GrandeDemais(int(cl))
            esperado = "image/" if tipo == "imagem" else "video/"
            if ct and not ct.startswith(esperado):
                print(f">> aviso: Content-Type {ct!r} não bate com o tipo {tipo} "
                      f"(aviso, não veto — quem decide são os bytes)", file=sys.stderr)
            total = 0
            with open(destino, "wb") as f:
                primeiro = r.read(1 << 20)
                if lic_mod.eh_pagina(primeiro):
                    raise ErroMidia(f"o servidor devolveu uma página, não mídia: {url}")
                while primeiro:
                    f.write(primeiro)
                    total += len(primeiro)
                    if limite and total > limite:
                        raise GrandeDemais(total)
                    primeiro = r.read(1 << 20)
        if tipo == "imagem":
            with open(destino, "rb") as f:
                cabeca = f.read(16)
            if not lic_mod.eh_imagem(cabeca):
                raise ErroMidia(f"os bytes não são de imagem (JPEG/PNG/GIF/WEBP): {url}")
        return total
    except BaseException:
        # E5: o parcial NUNCA sobrevive à falha. Antes, o `os.remove` estava depois
        # do `sys.exit` e o `.download` ficava no clips/ com nome de clipe bom.
        if os.path.exists(destino):
            os.remove(destino)
        raise


def render_commons(titulo, largura):
    """Pede ao Commons um render JPEG de `largura` px do arquivo `File:…`.

    Serve a dois casos: original grande demais (`--max-mb`) e mime que a nossa
    lista de magic numbers não cobre (o `image/tiff` que a busca real devolveu —
    o TIFF cru seria rejeitado, com razão; o render vem JPEG e passa).
    """
    p = {"action": "query", "format": "json", "titles": titulo,
         "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": str(int(largura))}
    req = urllib.request.Request(API_COMMONS + "?" + urllib.parse.urlencode(p), headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    for pg in (d.get("query", {}).get("pages", {}) or {}).values():
        ii = (pg.get("imageinfo") or [{}])[0]
        if ii.get("thumburl"):
            return ii["thumburl"], "image/jpeg"
    return None, None


# ------------------------------------------------------------------ listagem
def listar(ix, tag=None, tipo=None):
    n = 0
    for e in ix:
        if tag and tag not in e.get("tags", []):
            continue
        if tipo and tipo_de(e) != tipo:
            continue
        atrib = "  ⚠️ EXIGE CRÉDITO" if e.get("exige_atribuicao") else ""
        d = e.get("dur", 0)
        # imagem não tem duração: `dur` é null no índice e a coluna vira `—`.
        # Nunca 0.04 — que é o que o ffprobe devolve numa JPEG (medido) e é um
        # índice que MENTE, pior que um índice incompleto.
        col = f"{d:5.1f}s" if isinstance(d, (int, float)) else f"{'—':>5} "
        print(f"{e['nome']:<28} {e.get('w')}x{e.get('h')} {col}  "
              f"{e['provedor']:<10} {e['licenca'][:34]:<34} [{','.join(e.get('tags',[]))}]{atrib}")
        n += 1
    if not n:
        print("(biblioteca vazia)" if not ix else "(nenhum item com esse filtro)")


def creditos(ix, tag=None, nomes=None, formato="legenda"):
    """O crédito sai do índice em formato COLÁVEL.

    Com 78% das imagens aprovadas exigindo atribuição (contra 0 dos 2 clipes de
    vídeo), registrar `exige_atribuicao` e nunca transformá-lo em texto é o mesmo
    que não atribuir. Item que não exige crédito NÃO entra (crédito desnecessário
    polui legenda); item que exige e não tem autor ABORTA — crédito obrigatório
    sem autor conhecido é um item que não deveria ter entrado na biblioteca.
    """
    alvo = []
    for e in ix:
        if tag and tag not in e.get("tags", []):
            continue
        if nomes and e["nome"] not in nomes:
            continue
        if not e.get("exige_atribuicao"):
            continue
        alvo.append(e)
    sem_autor = [e["nome"] for e in alvo if not (e.get("autor") or "").strip()]
    if sem_autor:
        print("ERRO: entrada exige crédito e não tem autor: " + ", ".join(sem_autor),
              file=sys.stderr)
        return 1
    if not alvo:
        print("(nenhum item do filtro exige crédito)", file=sys.stderr)
        return 0
    for e in alvo:
        rot = "Imagem" if tipo_de(e) == "imagem" else "Vídeo"
        lic = licenca_curta(e.get("licenca", ""))
        pag = (e.get("pagina") or "").replace("https://", "").replace("http://", "")
        if formato == "markdown":
            print(f"- {rot}: \"{e['nome']}\" por {e['autor']} "
                  f"([{lic}]({e.get('pagina','')}))")
        else:
            print(f"{rot}: \"{e['nome']}\" por {e['autor']} ({lic}) · {pag}")
    return 0


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json"); ap.add_argument("--i", type=int)
    ap.add_argument("--url"); ap.add_argument("--provedor"); ap.add_argument("--licenca")
    ap.add_argument("--autor", default=""); ap.add_argument("--pagina", default="")
    ap.add_argument("--exige-atribuicao", action="store_true")
    ap.add_argument("--tipo", choices=("video", "imagem"))
    ap.add_argument("--mime")
    ap.add_argument("--tags", default=""); ap.add_argument("--nome")
    ap.add_argument("--listar", action="store_true"); ap.add_argument("--tag")
    ap.add_argument("--creditos", action="store_true")
    ap.add_argument("--nomes", help="lista separada por vírgula, para --creditos")
    ap.add_argument("--formato", choices=("legenda", "markdown"), default="legenda")
    ap.add_argument("--max-mb", type=float, default=25.0,
                    help="teto do original; acima disso o Commons entrega um render de --largura")
    ap.add_argument("--largura", type=int, default=1600,
                    help="largura do render do Commons quando o original estoura --max-mb")
    ap.add_argument("--perfil", help="dir da produção ou perfil.json — dá o fps e as "
                                     "tags de cor da normalização (default: FALLBACK, fps 30)")
    a = ap.parse_args()

    ix = indice()
    if a.listar:
        listar(ix, a.tag, a.tipo)
        return 0
    if a.creditos:
        nomes = [n.strip() for n in (a.nomes or "").split(",") if n.strip()] or None
        return creditos(ix, a.tag, nomes, a.formato)

    if a.json is not None and a.i is not None:
        cands = json.load(open(a.json))
        if not 0 <= a.i < len(cands):
            sys.exit(f"índice {a.i} fora da faixa: o arquivo tem {len(cands)} candidatos (0–{len(cands)-1})")
        c = cands[a.i]
    elif a.url:
        c = {"provedor": a.provedor or "manual", "id": hashlib.sha1(a.url.encode()).hexdigest()[:8],
             "download": a.url, "licenca": a.licenca or "?", "autor": a.autor,
             "pagina": a.pagina, "exige_atribuicao": a.exige_atribuicao,
             "tipo": a.tipo or "video", "mime": a.mime}
    else:
        sys.exit("use --json/--i, --url, --listar ou --creditos")

    if c.get("licenca", "?") in ("?", "", None):
        sys.exit("ERRO: candidato sem licença declarada. Sem licença, não entra na biblioteca.")

    # o gate de licença vale também aqui: candidato de arquivo antigo, editado à
    # mão ou vindo de --url não pode entrar por uma porta que a busca já fecha.
    cl = lic_mod.classificar(c["licenca"])
    ok, motivo = lic_mod.aprovado(cl)
    if not ok:
        sys.exit(f"ERRO: licença reprovada pelo gate ({cl['slug']}): {motivo}\n"
                 f"  Se a decisão for consciente, refaça a busca com "
                 f"--licencas incluindo o slug — a decisão fica gravada no candidato.")

    tipo = a.tipo or c.get("tipo") or "video"
    nome = a.nome or f"{c['provedor']}-{c['id']}"
    nome = "".join(ch for ch in nome if ch.isalnum() or ch in "-_")

    mime = a.mime or c.get("mime") or ""
    rendition_forcada = None
    if tipo == "imagem" and not mime:
        # `--url` sem `--mime`: deriva da extensão da URL. Sem isto o caminho
        # manual abortaria ANTES do download, e a validação de bytes — que é a
        # razão de esta spec existir — nunca seria exercitada.
        ext_url = os.path.splitext(urllib.parse.urlparse(c["download"]).path)[1].lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif"}.get(ext_url, "")
    if tipo == "imagem":
        ext = EXT_POR_MIME.get(mime)
        url = c["download"]
        # mime fora da lista de magic numbers (image/tiff, p.ex.): o caminho é
        # SEMPRE o render do Commons, que vem JPEG. `.jpg` fixo para todo mime é o
        # que o ref-A faz — e a nossa própria consulta medida devolveu image/png.
        if ext is None:
            if c.get("provedor") == "wikimedia" and c.get("id"):
                url, mime = render_commons(c["id"], a.largura)
                if not url:
                    sys.exit(f"ERRO: mime {c.get('mime')!r} não suportado e o Commons não "
                             f"devolveu render de {c['id']}")
                ext = EXT_POR_MIME[mime]
                rendition_forcada = f"thumb-{a.largura}"
                print(f">> mime {c.get('mime')} não é JPEG/PNG/WEBP/GIF: usando render "
                      f"do Commons ({a.largura}px)", file=sys.stderr)
            else:
                sys.exit(f"ERRO: mime {mime!r} não suportado para imagem "
                         f"(JPEG/PNG/WEBP/GIF). Baixe manualmente e use --url --mime.")
        destino_dir, dest = IMAGENS, os.path.join(IMAGENS, nome + ext)
    else:
        url = c["download"]
        destino_dir, dest = CLIPS, os.path.join(CLIPS, nome + ".mp4")

    if any(e["nome"] == nome for e in ix) and os.path.exists(dest):
        print(">> já na biblioteca (não rebaixa)", file=sys.stderr)
        print(dest)
        return 0

    os.makedirs(destino_dir, exist_ok=True)
    bruto = dest + ".download"
    rendition = rendition_forcada or c.get("rendition")
    print(f">> baixando {url[:90]}", file=sys.stderr)
    try:
        try:
            baixar_arquivo(url, bruto, tipo, a.max_mb)
        except GrandeDemais as e:
            if tipo == "imagem" and c.get("provedor") == "wikimedia" and c.get("id"):
                print(f">> original tem {e.bytes/1e6:.1f} MB (> --max-mb {a.max_mb}): "
                      f"pedindo render de {a.largura}px ao Commons", file=sys.stderr)
                url, mime = render_commons(c["id"], a.largura)
                if not url:
                    sys.exit(f"ERRO: o Commons não devolveu render de {c['id']}")
                rendition = f"thumb-{a.largura}"
                baixar_arquivo(url, bruto, tipo, None)
            else:
                sys.exit(f"ERRO: {e.bytes/1e6:.1f} MB passa de --max-mb {a.max_mb}. "
                         f"Suba o teto se for consciente.")
        except ErroMidia as e:
            sys.exit(f"ERRO: {e}")
        except urllib.error.HTTPError as e:
            sys.exit(f"ERRO: HTTP {e.code} ({e.reason}) em {url}"
                     + ("\n  429 do upload.wikimedia.org é limite de taxa do servidor de "
                        "thumbnail: espere e repita." if e.code == 429 else ""))
        except urllib.error.URLError as e:
            sys.exit(f"ERRO: rede indisponível em {url}: {e.reason}")

        if tipo == "imagem":
            # 📷 SEM ffmpeg: a imagem entra como veio. Ver docstring.
            os.replace(bruto, dest)
            from PIL import Image
            with Image.open(dest) as im:
                w, h = im.size
            dur = None
            # o Commons entrega o thumbnail EXISTENTE mais próximo, não exatamente
            # a largura pedida (medido: --largura 800 → 960 px). O rótulo segue a
            # largura REAL, medida com PIL — rótulo que mente é o defeito favorito
            # deste repo.
            if rendition and str(rendition).startswith("thumb-"):
                rendition = f"thumb-{w}"
        else:
            # 📐 O fps de normalização vem do perfil de peça (SPEC-00): b-roll
            # normalizado a 30 entrando numa peça a 25 obriga o filtro a reamostrar
            # de novo na montagem. `--perfil <dir|arquivo.json>` ou $BENCH_PERFIL
            # apontam o perfil; sem nenhum dos dois vale o FALLBACK.
            P, _fonte_perfil = perfil_mod.carregar(
                a.perfil or os.environ.get("BENCH_PERFIL") or ".", quieto=False)
            FPS = P["video"]["fps"]
            t = (P.get("cor") or {}).get("tags_saida") or {}
            cp, ct_, cs = (t.get("color_primaries", "bt709"), t.get("color_trc", "bt709"),
                           t.get("colorspace", "bt709"))
            print(f">> normalizando (fps={FPS}, sem áudio, {cs})", file=sys.stderr)
            r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", bruto,
                                "-an", "-vf", f"fps={FPS},setparams="
                                f"color_primaries={cp}:color_trc={ct_}:colorspace={cs}",
                                "-c:v", "libx264", "-crf", "18",
                                "-preset", P["video"].get("preset_x264", "medium"),
                                "-pix_fmt", P["video"].get("pix_fmt", "yuv420p"),
                                dest], capture_output=True, text=True)
            if r.returncode:
                print(r.stderr[-1500:], file=sys.stderr)
                sys.exit(r.returncode)
            g = lambda k: subprocess.run(  # noqa: E731
                ["ffprobe", "-v", "error", "-select_streams", "v",
                 "-show_entries", f"stream={k}", "-of", "default=nk=1:nw=1", dest],
                capture_output=True, text=True).stdout.split()[0]
            w, h = int(g("width")), int(g("height"))
            dur = round(float(subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nk=1:nw=1", dest], capture_output=True, text=True).stdout), 2)
            if not mime:
                mime = "video/mp4"
    finally:
        if os.path.exists(bruto):
            os.remove(bruto)

    entrada = {"nome": nome, "arquivo": os.path.relpath(dest, RAIZ),
               "provedor": c["provedor"], "tipo": tipo, "mime": mime,
               "id_origem": c["id"],
               "licenca": c["licenca"], "licenca_slug": cl["slug"],
               "exige_atribuicao": bool(c.get("exige_atribuicao")),
               "autor": c.get("autor", ""), "pagina": c.get("pagina", ""),
               "w": w, "h": h, "dur": dur,
               "tags": [t.strip() for t in a.tags.split(",") if t.strip()]}
    if rendition:
        entrada["rendition"] = rendition
    ix.append(entrada)
    salvar(ix)
    if c.get("exige_atribuicao"):
        print(f"⚠️ ESTE CLIPE EXIGE CRÉDITO: \"{c.get('autor')}\" — o crédito TEM que entrar "
              f"na legenda do post. Registrado no INDEX.json; "
              f"`baixar.py --creditos` imprime a linha pronta.", file=sys.stderr)
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
