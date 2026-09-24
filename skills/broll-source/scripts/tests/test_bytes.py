#!/usr/bin/env python3
"""test_bytes — o servidor devolve HTTP 200 com uma PÁGINA; nada disso pode virar mídia.

Roda sozinho (`python3 tests/test_bytes.py`), sem pytest, sem rede externa: sobe um
`http.server` local numa porta efêmera e aponta o `baixar.py` para ele.

⚠️ Um portão que só testa o caso ruim é indistinguível de um `sys.exit(1)` no topo do
script. Por isso o CONTROLE POSITIVO é obrigatório aqui: o mesmo servidor serve uma
JPEG real de 1×1, e o `baixar.py` TEM que baixá-la, indexá-la e devolver 0. Sem essa
metade, "0 arquivos em imagens/" seria verde de graça.

Cobre o aceite 2 da SPEC-29 e o defeito E5 (o `.download` órfão).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
BAIXAR = os.path.join(AQUI, "..", "baixar.py")

# JPEG 1×1 de verdade (FFD8FF…), gerada uma vez e colada aqui em hex para o teste
# não depender de PIL nem de rede. Serve de CONTROLE POSITIVO.
JPEG_1X1 = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300ffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    "ffffffffffffffffffffffffffffffffffc2000b080001000101011100ffc40014000100000000"
    "00000000000000000000000900ffda0008010100000000013fffc40014100100000000000000000"
    "0000000000000002000ffda0008010100010500ffc40014110100000000000000000000000000000"
    "0002000ffda0008010301013f00ffc400141101000000000000000000000000000000200 0ffda000"
    "8010201013f00ffc40014100100000000000000000000000000000020 00ffda0008010100063f00"
    "ffc400141001000000000000000000000000000000200 0ffda0008010100013f10ffd9".replace(" ", ""))

HTML = b'<!doctype html><html><body>403 Forbidden</body></html>'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/ok"):
            corpo, ct = JPEG_1X1, "image/jpeg"
        else:
            # o caso que importa: 200 + Content-Type de imagem + corpo de PÁGINA.
            # É assim que o thumb server do Commons erra (ref-A, wikimedia_images.py:84-86).
            corpo, ct = HTML, "image/jpeg"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def conta(d):
    return len(os.listdir(d)) if os.path.isdir(d) else 0


def rodar(lib, *args):
    env = dict(os.environ, BROLL_DIR=lib)
    return subprocess.run([sys.executable, BAIXAR, *args], env=env,
                          capture_output=True, text=True)


def main():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    porta = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    lib = tempfile.mkdtemp(prefix="broll-teste-")
    falhas, checados = [], 0
    try:
        # índice legado, para provar que ele não é tocado por uma falha
        with open(os.path.join(lib, "INDEX.json"), "w") as f:
            json.dump([{"nome": "legado", "arquivo": "clips/legado.mp4", "provedor": "mixkit",
                        "id_origem": "1", "licenca": "Mixkit Stock Video Free License",
                        "exige_atribuicao": False, "autor": "Mixkit/Envato", "pagina": "",
                        "w": 1080, "h": 1920, "dur": 10.1, "tags": []}], f)
        antes = md5(os.path.join(lib, "INDEX.json"))

        for tipo, caminho in (("imagem", "x.jpg"), ("video", "x.mp4")):
            r = rodar(lib, "--url", f"http://127.0.0.1:{porta}/{caminho}",
                      "--tipo", tipo, "--provedor", "manual", "--licenca", "CC0",
                      "--autor", "teste")
            checados += 1
            saida = r.stdout + r.stderr
            if r.returncode == 0:
                falhas.append(f"{tipo}: exit 0 — a página virou mídia")
            if "página, não mídia" not in saida:
                falhas.append(f"{tipo}: mensagem não diz 'página, não mídia': {saida.strip()[:120]!r}")
            orfaos = [p for _, _, fs in os.walk(lib) for p in fs if p.endswith(".download")]
            if orfaos:
                falhas.append(f"{tipo}: sobrou parcial no disco: {orfaos}")
            if conta(os.path.join(lib, "imagens")) or conta(os.path.join(lib, "clips")):
                falhas.append(f"{tipo}: arquivo criado na biblioteca")
            if md5(os.path.join(lib, "INDEX.json")) != antes:
                falhas.append(f"{tipo}: INDEX.json foi alterado por um download que falhou")

        # ---- CONTROLE POSITIVO: sem ele, tudo acima é verde de graça ----------
        r = rodar(lib, "--url", f"http://127.0.0.1:{porta}/ok.jpg", "--tipo", "imagem",
                  "--provedor", "manual", "--licenca", "CC0", "--autor", "teste",
                  "--nome", "controle-positivo")
        checados += 1
        if r.returncode != 0:
            falhas.append(f"CONTROLE POSITIVO: imagem legítima foi recusada "
                          f"(exit {r.returncode}): {(r.stderr or '').strip()[-200:]}")
        elif conta(os.path.join(lib, "imagens")) != 1:
            falhas.append("CONTROLE POSITIVO: a imagem legítima não foi gravada")
        else:
            ix = json.load(open(os.path.join(lib, "INDEX.json")))
            e = [x for x in ix if x["nome"] == "controle-positivo"]
            if not e:
                falhas.append("CONTROLE POSITIVO: não entrou no INDEX.json")
            elif (e[0]["tipo"], e[0]["mime"], e[0]["dur"]) != ("imagem", "image/jpeg", None):
                falhas.append(f"CONTROLE POSITIVO: índice v2 errado: {e[0]}")
    finally:
        srv.shutdown()
        shutil.rmtree(lib, ignore_errors=True)

    print(f"casos varridos: {checados} (2 de página + 1 de controle positivo)")
    if falhas:
        print(f"{len(falhas)} FALHA(S):")
        for f in falhas:
            print("  ✗ " + f)
        return 1
    print("test_bytes: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
