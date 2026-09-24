"""Contrato HTTP do nonce efêmero usado pelo gate de aprovação da UI."""

import importlib.util
import json
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen


SERVIDOR = Path(__file__).resolve().parents[1] / "servidor.py"


def _carregar_servidor():
    spec = importlib.util.spec_from_file_location("preview_servidor_nonce_test", SERVIDOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _json_get(url, headers=None):
    with urlopen(Request(url, headers=headers or {}), timeout=3) as resposta:
        return resposta.status, dict(resposta.headers), json.loads(resposta.read())


def _json_post(url, corpo, headers=None):
    cabecalhos = {"Content-Type": "application/json", "User-Agent": "teste-ui"}
    cabecalhos.update(headers or {})
    req = Request(url, data=json.dumps(corpo).encode("utf-8"), method="POST",
                  headers=cabecalhos)
    with urlopen(req, timeout=3) as resposta:
        return resposta.status, json.loads(resposta.read())


def _abrir_ui(url):
    with urlopen(url, timeout=3) as resposta:
        resposta.read()
        return resposta.headers.get("Set-Cookie").split(";", 1)[0]


def test_post_aprovacao_exige_nonce_contextual_e_consome_uma_vez(tmp_path):
    servidor = _carregar_servidor()
    (tmp_path / ".preview").mkdir()

    contexto = {
        "alvo": "fase-1",
        "fingerprint_corte": "sha1:" + "1" * 40,
        "fingerprint_render": "sha1:" + "2" * 40,
        "render_alvo": "v1-montado.mp4",
        "plano_sha256": "3" * 64,
    }
    estado = {
        "schema": "benchmark.preview-estado/v1",
        "sessao": {"token": "token-teste", "porta": 0, "pid": 123},
        "estado": {
            "fase": 1,
            "fingerprint_corte": contexto["fingerprint_corte"],
            "fingerprint_render": contexto["fingerprint_render"],
            "render_corrente": contexto["render_alvo"],
            "plano": {"sha256": contexto["plano_sha256"]},
        },
        "midia": {"rel": contexto["render_alvo"]},
    }
    chamadas = []

    def registrar_aprovacao(d, alvo, por, fonte, motivo, pid, esperado):
        chamadas.append({"d": d, "alvo": alvo, "por": por, "fonte": fonte,
                          "motivo": motivo, "pid": pid, "esperado": esperado})
        return {"alvo": alvo, "em": "2026-08-14T12:00:00-03:00",
                "fonte": fonte, "por": por}

    estado_mod_teste = SimpleNamespace(
        FONTE_UI="ui-save", registrar_aprovacao=registrar_aprovacao)

    estado_atual_original = servidor.estado_atual
    estado_mod_original = servidor._estado_mod
    servidor.estado_atual = lambda: (estado, "rev-fixture")
    servidor._estado_mod = lambda: estado_mod_teste

    httpd = servidor.ThreadingHTTPServer(("127.0.0.1", 0), servidor.Handler)
    porta = httpd.server_address[1]
    servidor.CFG.clear()
    servidor.CFG.update({
        "raiz": tmp_path,
        "token": "token-teste",
        "porta": porta,
        "app": tmp_path,
        "altura": 90,
        "desde": 0,
        "lock_evento": threading.Lock(),
    })
    with servidor._nonces_aprovacao_lock:
        servidor._nonces_aprovacao.clear()
    fio = threading.Thread(target=httpd.serve_forever, daemon=True)
    fio.start()
    base = "http://127.0.0.1:%d/token-teste/" % porta

    try:
        # O endpoint consultável sozinho não entrega a capacidade. Ela só é
        # emitida depois que o servidor entregou o documento da UI e criou a
        # sessão privada de browser correspondente.
        _, _, estado_sem_ui = _json_get(base + "api/estado")
        assert "nonce_aprovacao" not in estado_sem_ui["sessao"]
        cookie = _abrir_ui(base)
        cab_sessao = {"Cookie": cookie}

        status, headers, recebido = _json_get(base + "api/estado", cab_sessao)
        nonce = recebido["sessao"]["nonce_aprovacao"]
        assert status == 200
        assert headers["ETag"] == 'W/"rev-fixture"'
        assert recebido["estado"]["fingerprint_corte"] == contexto["fingerprint_corte"]
        assert recebido["estado"]["fingerprint_render"] == contexto["fingerprint_render"]
        assert "nonce_aprovacao" not in estado["sessao"]  # não contamina memo/ETag
        with servidor._nonces_aprovacao_lock:
            n_nonces_antes_304 = len(servidor._nonces_aprovacao)
        try:
            urlopen(Request(base + "api/estado", headers={
                **cab_sessao, "If-None-Match": headers["ETag"]}), timeout=3)
            resposta_304 = None
        except Exception as exc:                           # 304 vira exceção no urllib
            resposta_304 = exc
        assert getattr(resposta_304, "code", None) == 304
        with servidor._nonces_aprovacao_lock:
            assert len(servidor._nonces_aprovacao) == n_nonces_antes_304

        sem_nonce = {"tipo": "aprovacao", "payload": dict(contexto)}
        status, recusado = _json_post(base + "api/salvar", sem_nonce, cab_sessao)
        assert status == 200
        assert recusado["ok"] is False
        assert "sem nonce" in recusado["erro_aprovacao"]
        assert chamadas == []
        assert not list((tmp_path / ".preview").glob("pendentes/*.json"))

        com_nonce = {"tipo": "aprovacao",
                     "payload": {**contexto, "nonce_aprovacao": nonce,
                                 "por": "creator (UI)", "motivo": "ok"}}
        status, aceito = _json_post(base + "api/salvar", com_nonce, cab_sessao)
        assert status == 200 and aceito["ok"] is True
        assert aceito["aprovacao"]["fonte"] == "ui-save"
        assert len(chamadas) == 1
        assert chamadas[0]["esperado"] == contexto

        envelopes = list((tmp_path / ".preview").glob("pendentes/*.json"))
        assert len(envelopes) == 1
        gravado = json.loads(envelopes[0].read_text(encoding="utf-8"))
        assert "nonce_aprovacao" not in gravado["payload"]

        status, repetido = _json_post(base + "api/salvar", com_nonce, cab_sessao)
        assert status == 200
        assert repetido["ok"] is False
        assert "já consumido" in repetido["erro_aprovacao"]
        assert len(chamadas) == 1
        assert len(list((tmp_path / ".preview").glob("pendentes/*.json"))) == 1

        # Uma capacidade nova continua presa ao snapshot que a emitiu. Tentar
        # usá-la com fingerprints consultados/adulterados a consome e não grava.
        _, _, segundo_estado = _json_get(base + "api/estado", cab_sessao)
        nonce_contextual = segundo_estado["sessao"]["nonce_aprovacao"]
        adulterado = dict(contexto)
        adulterado["fingerprint_render"] = "sha1:" + "9" * 40
        _, fora_contexto = _json_post(
            base + "api/salvar",
            {"tipo": "aprovacao",
             "payload": {**adulterado, "nonce_aprovacao": nonce_contextual}},
            cab_sessao,
        )
        assert fora_contexto["ok"] is False
        assert "não corresponde ao contexto" in fora_contexto["erro_aprovacao"]
        _, repetido_depois_do_erro = _json_post(
            base + "api/salvar",
            {"tipo": "aprovacao",
             "payload": {**contexto, "nonce_aprovacao": nonce_contextual}},
            cab_sessao,
        )
        assert "já consumido" in repetido_depois_do_erro["erro_aprovacao"]
        assert len(chamadas) == 1

        # Mesmo contexto e mesmo token de URL não bastam: uma segunda carga do
        # documento abre outra sessão de UI e não pode reaproveitar a capacidade.
        _, _, terceiro_estado = _json_get(base + "api/estado", cab_sessao)
        nonce_da_primeira_ui = terceiro_estado["sessao"]["nonce_aprovacao"]
        cab_segunda_ui = {"Cookie": _abrir_ui(base)}
        _, outra_ui = _json_post(
            base + "api/salvar",
            {"tipo": "aprovacao",
             "payload": {**contexto, "nonce_aprovacao": nonce_da_primeira_ui}},
            cab_segunda_ui,
        )
        assert "outra sessão da UI" in outra_ui["erro_aprovacao"]
        _, consumido_por_outra_ui = _json_post(
            base + "api/salvar",
            {"tipo": "aprovacao",
             "payload": {**contexto, "nonce_aprovacao": nonce_da_primeira_ui}},
            cab_sessao,
        )
        assert "já consumido" in consumido_por_outra_ui["erro_aprovacao"]
        assert len(chamadas) == 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        fio.join(timeout=3)
        servidor.estado_atual = estado_atual_original
        servidor._estado_mod = estado_mod_original


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="preview-nonce-") as d:
        test_post_aprovacao_exige_nonce_contextual_e_consome_uma_vez(Path(d))
    print("1 caso verde: nonce contextual, obrigatório, efêmero e de uso único")
