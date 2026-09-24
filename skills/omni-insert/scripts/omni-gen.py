#!/usr/bin/env python3
"""Cliente mínimo do Gemini Omni Flash (geração/edição de vídeo) — stdlib only.

Uso:
  omni-gen.py gen   "<prompt>" <saida.mp4> [--ar 9:16]
  omni-gen.py edit  <video.mp4> "<prompt>" <saida.mp4>

⚠️ `edit` aceita até ~4s de input (5s+ é bloqueado) e o trecho precisa ir COM ÁUDIO:
com a trilha na entrada o modelo preserva a voz do creator e o lip sync; mandando
vídeo mudo (`-an`) ele sintetiza uma voz nova. Ver SKILL.md.

Loga no stderr, imprime o caminho do artefato final no stdout.
"""
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com"
KEY = os.environ.get("GEMINI_API_KEY")
MODEL = os.environ.get("BENCH_OMNI_MODEL", "gemini-omni-flash-preview")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _req(url, data=None, headers=None, method=None, raw=False):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=1800) as resp:
            payload = resp.read()
            return (payload, dict(resp.headers)) if raw else json.loads(payload or b"{}")
    except urllib.error.HTTPError as e:
        log(f"HTTP {e.code}: {e.read().decode()[:2000]}")
        raise


def upload(path):
    """Files API, protocolo resumable (o multipart simples não é aceito pra vídeo)."""
    size = os.path.getsize(path)
    mime = mimetypes.guess_type(path)[0] or "video/mp4"
    log(f"[upload] {path} ({size/1e6:.1f} MB, {mime})")
    _, headers = _req(
        f"{API}/upload/v1beta/files?key={KEY}",
        {"file": {"display_name": os.path.basename(path)}},
        {
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime,
        },
        raw=True,
    )
    up = headers.get("X-Goog-Upload-URL") or headers.get("x-goog-upload-url")
    with open(path, "rb") as f:
        info = _req(
            up,
            f.read(),
            {
                "Content-Length": str(size),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
                "Content-Type": mime,
            },
        )
    name = info["file"]["name"]
    # vídeo passa por PROCESSING antes de ficar utilizável
    for _ in range(120):
        st = _req(f"{API}/v1beta/{name}?key={KEY}")
        if st.get("state") == "ACTIVE":
            log(f"[upload] ok → {name}")
            return name, st.get("uri")
        if st.get("state") == "FAILED":
            raise RuntimeError(f"upload FAILED: {st}")
        time.sleep(3)
    raise TimeoutError("upload não ficou ACTIVE")


def interaction(payload):
    t0 = time.time()
    log(f"[omni] enviando ({MODEL})…")
    out = _req(f"{API}/v1beta/interactions?key={KEY}", payload)
    log(f"[omni] resposta em {time.time()-t0:.0f}s")
    return out


def find_video_uri(resp):
    """A resposta é uma lista de steps com content; acha o primeiro item de vídeo."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            uri = node.get("uri") or node.get("file_uri") or node.get("fileUri")
            if uri and isinstance(uri, str) and "files/" in uri:
                found.append(uri)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(resp)
    return found


def download(uri, dest):
    # a uri de saída vem como .../files/<id>:download?alt=media
    fid = uri.split("files/")[1].split(":")[0].split("?")[0]
    for _ in range(240):
        st = _req(f"{API}/v1beta/files/{fid}?key={KEY}")
        if st.get("state") == "ACTIVE":
            break
        if st.get("state") == "FAILED":
            raise RuntimeError(f"geração FAILED: {st}")
        time.sleep(5)
    data, _ = _req(f"{API}/v1beta/files/{fid}:download?alt=media&key={KEY}", raw=True)
    with open(dest, "wb") as f:
        f.write(data)
    log(f"[download] {dest} ({len(data)/1e6:.1f} MB)")
    return dest


def main():
    if not KEY:
        sys.exit("GEMINI_API_KEY ausente")
    mode = sys.argv[1]
    if mode == "edit":
        video, prompt, dest = sys.argv[2], sys.argv[3], sys.argv[4]
        _, uri = upload(video)
        payload = {
            "model": MODEL,
            "input": [
                {"type": "video", "uri": uri},
                {"type": "text", "text": prompt},
            ],
            "generation_config": {"video_config": {"task": "edit"}},
            "response_format": {"type": "video", "delivery": "uri"},
        }
    elif mode == "anim":
        # image_to_video: parte de uma IMAGEM (ex.: recorte do cenário real do
        # creator, sem ninguém em quadro) e anima — continuidade de cenário em
        # vez de cena inventada.
        img, prompt, dest = sys.argv[2], sys.argv[3], sys.argv[4]
        ar = sys.argv[sys.argv.index("--ar") + 1] if "--ar" in sys.argv else "9:16"
        _, uri = upload(img)
        payload = {
            "model": MODEL,
            "input": [
                {"type": "image", "uri": uri},
                {"type": "text", "text": prompt},
            ],
            "generation_config": {"video_config": {"task": "image_to_video"}},
            "response_format": {"type": "video", "aspect_ratio": ar, "delivery": "uri"},
        }
    else:
        prompt, dest = sys.argv[2], sys.argv[3]
        ar = sys.argv[sys.argv.index("--ar") + 1] if "--ar" in sys.argv else "9:16"
        payload = {
            "model": MODEL,
            "input": prompt,
            "response_format": {"type": "video", "aspect_ratio": ar, "delivery": "uri"},
        }

    resp = interaction(payload)
    with open(dest + ".response.json", "w") as f:
        json.dump(resp, f, indent=2, ensure_ascii=False)
    uris = find_video_uri(resp)
    log(f"[omni] uris na resposta: {uris}")
    if not uris:
        sys.exit(f"nenhum vídeo na resposta — ver {dest}.response.json")
    print(download(uris[-1], dest))


if __name__ == "__main__":
    main()
