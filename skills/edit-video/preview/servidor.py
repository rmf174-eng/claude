#!/usr/bin/env python3
"""Servidor de preview da ilha de edição — stdlib pura, 127.0.0.1, um dir de produção.

Desenho derivado de helpers/preview_server.py de uma ferramenta de edição de terceiro.
 Nenhuma linha copiada literalmente: rotas, cache endereçado por conteúdo,
filmstrip por seek, limites de recurso e segurança são reescrita nossa.
Contrato e medições: docs/specs/SPEC-17-servidor-de-preview.md

Subcomandos:
    servidor.py sessao --dir D   escolhe porta+token e grava <dir>/.preview/servidor.json
    servidor.py servir --dir D   sobe o servidor (use com run_in_background)
    servidor.py parar  --dir D   SIGTERM no pid da sessão
    servidor.py status --dir D   diagnóstico em JSON

Regra dura: este processo NUNCA escreve fora de <dir>/.preview/.
"""

from __future__ import annotations

import argparse
import array
import errno
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from urllib.request import urlopen

VERSAO = "1"
BIND_HOST = "127.0.0.1"

# --- constantes de RESOLUÇÃO DE UI e de RECURSO ------------------------------
# Nenhuma delas é valor de formato de peça (largura/altura/aspecto/fps saem
# sempre do ffprobe do arquivo que está tocando). Ver SPEC-17 §7.10.
N_MIN = 24                 # nº mínimo de thumbs na faixa de filmstrip
N_MAX = 200                # nº máximo — o teto que torna o custo independente da duração
ALVO_S = 2.0               # intervalo alvo entre thumbs, quando cabe no teto
ALTURA_THUMB_PADRAO = 90   # altura do thumb em px; a LARGURA sai do aspecto real
BALDES_MAX = 20000         # nº máximo de baldes da waveform
PICOS_POR_S_MAX = 40.0     # resolução máxima da waveform
TAXA_AUDIO = 8000          # taxa de decode mono s16 para a waveform
TETO_POST = 1 << 20        # 1 MiB de corpo no POST
CHAVES_MANTIDAS = 3        # nº de chaves de cache guardadas por produção
PISO_ESTADO_S = 0.250      # piso de reavaliação do /api/estado
NONCE_APROVACAO_TTL_S = 10 * 60  # capacidade de UI: curta, mas cobre o diálogo
NONCES_APROVACAO_MAX = 128       # limite de memória para abas/refreshes abandonados
SESSAO_UI_TTL_S = 2 * 60 * 60    # cookie de sessão, sem persistência em disco
SESSOES_UI_MAX = 64
COOKIE_SESSAO_UI = "ilha_preview_ui"
# A app da SPEC-18, a que embarca ao lado deste arquivo. É a raiz do servidor por
# construção; `--app` monta OUTRA superfície, não substitui esta (H49-7).
APP_EMBARCADA = Path(__file__).resolve().parent / "app"
CACHE_SONDA_MAX = 64       # entradas do cache de ffprobe
OCIOSO_PADRAO_MIN = 120    # auto-desligamento por ociosidade
BLOCO_IO = 1 << 16         # 64 KiB por escrita no Range

CANDIDATOS_MIDIA = ("v-final.mp4", "v1-graded.mp4", "v1-sdr.mp4", "v1-montado.mp4")
OBSERVADOS = ("edl.json", "edl-audio.json", "captions.json", "planos.json",
              "janelas.json", "perfil.json")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".vtt": "text/vtt; charset=utf-8",
    ".srt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

# --- estado de processo ------------------------------------------------------
CFG: dict = {}
CONTADORES = {"sondas": 0, "req": 0}
_cont_lock = threading.Lock()

_sonda_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_sonda_lock = threading.Lock()

_gerando: dict = {}                 # (chave, tipo) -> {"feito","total","erro"}
_gen_lock = threading.Lock()

_estado_memo = {"t": 0.0, "obj": None, "rev": ""}
_estado_lock = threading.Lock()

# Capacidades de aprovação vivem somente neste processo. Não entram em
# servidor.json, estado.json nem no envelope append-only.
_nonces_aprovacao: "OrderedDict[str, dict]" = OrderedDict()
_nonces_aprovacao_lock = threading.Lock()
_sessoes_ui: "OrderedDict[str, dict]" = OrderedDict()
_sessoes_ui_lock = threading.Lock()

_ultima_req = {"t": time.time()}


def _carregar_adaptador_cloud():
    """Carrega o adaptador vizinho mesmo quando este arquivo entra via spec.

    Executado como script, o diretorio de ``servidor.py`` ja esta no sys.path.
    Os testes existentes importam o arquivo diretamente por ``importlib`` e nao
    criam pacote Python; resolver pelo caminho mantem as duas formas equivalentes.
    """
    caminho = Path(__file__).resolve().parent / "cloud_adapter.py"
    spec = importlib.util.spec_from_file_location("ilha_preview_cloud_adapter", caminho)
    if spec is None or spec.loader is None:
        raise RuntimeError("adaptador cloud indisponivel")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


CLOUD_ADAPTER = _carregar_adaptador_cloud()


# =============================================================================
# utilidades
# =============================================================================
def _agora_iso(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts if ts is not None else time.time()).astimezone()
    return dt.isoformat(timespec="seconds")


def _carimbo(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts if ts is not None else time.time())
    return dt.strftime("%Y%m%dT%H%M%S")


def _stat_par(p: Path) -> list | None:
    try:
        st = p.stat()
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size]


def _ler_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _escrever_json_atomico(destino: Path, obj) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")
    parcial.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(parcial, destino)


def sonda_de_escrita(raiz: Path) -> str | None:
    """Dá para escrever em `raiz`? Devolve `None` se sim, ou o REMÉDIO se não.

    🔴 O BURACO ERA NOSSO, e foi medido: `servidor.py sessao --dir` num
    diretório sem escrita estourava um traceback de `PermissionError` em
    `abrir_sessao` — `.preview/` é a PRIMEIRA coisa que o comando cria. Falhar
    alto e cedo já é melhor que subir e ficar numa tela de espera eterna, mas
    traceback não é remédio: quem lê não sabe se muda a permissão da pasta ou se
    pede acesso ao sistema.

    E os dois casos NÃO são o mesmo erro. No macOS o TCC nega `~/Desktop`,
    `~/Documents` e `~/Downloads` com **EPERM** mesmo com dono e modo perfeitos:
    a permissão que falta é do sistema, não do arquivo, e `chmod` não resolve.
    **EACCES** é o clássico: dono, grupo ou modo. Por isso duas mensagens.

    ⚠️ E a mensagem do EPERM não pode mentir fora do Mac: em Linux o TCC não
    existe, e ali EPERM costuma ser volume montado somente-leitura, sticky bit,
    contêiner sem a capability ou LSM (SELinux/AppArmor). Por isso o remédio do
    EPERM é escolhido por `sys.platform`, e não por adivinhação.
    """
    try:
        alvo = raiz / (".preview-sonda-%s" % secrets.token_hex(4))
        alvo.mkdir()
        alvo.rmdir()
        return None
    except FileExistsError:                                # improvável; não é falta de permissão
        return None
    except PermissionError as e:
        if e.errno == errno.EPERM and sys.platform == "darwin":
            return ("o macOS está negando o acesso ao conteúdo desta pasta "
                    "(EPERM/TCC) — não é dono nem `chmod`. Abra Ajustes do "
                    "Sistema → Privacidade e Segurança → Arquivos e Pastas (ou "
                    "Acesso Total ao Disco) e libere o app de onde você rodou "
                    "isto (Terminal, iTerm, VS Code…). Pastas como Desktop, "
                    "Documentos e Downloads são as que caem aqui.")
        if e.errno == errno.EPERM:
            return ("o sistema negou a operação nesta pasta (EPERM). Aqui isso "
                    "não é dono nem `chmod`: procure volume montado "
                    "somente-leitura, contêiner sem a capability de escrita, ou "
                    "política de LSM (SELinux/AppArmor) sobre este caminho.")
        return ("sem permissão de escrita nesta pasta (EACCES). Confira dono e "
                "modo — `ls -ld` no caminho acima — e rode de uma pasta sua, ou "
                "ajuste a permissão dela.")
    except OSError as e:
        if e.errno == errno.EROFS:
            return "esta pasta está num sistema de arquivos somente-leitura (EROFS)."
        return "não consegui criar arquivo nesta pasta: %s" % e


_ESTADO_MOD = {"m": None}


def _estado_mod():
    """`scripts/estado.py` importado sob demanda, pela mesma skill.

    Tardio de propósito: o servidor sobe em produção VAZIA (etapa 0) e não pode
    pagar o import de um módulo que só é usado quando alguém clica em APROVAR.
    Caminho relativo a ESTE arquivo, nunca contando níveis a partir da raiz —
    `preview/` e `scripts/` são irmãos dentro da skill (auditar-acoplamento
    classe A)."""
    if _ESTADO_MOD["m"] is None:
        import importlib.util
        alvo = Path(__file__).resolve().parent.parent / "scripts" / "estado.py"
        spec = importlib.util.spec_from_file_location("edit_video_estado", alvo)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ESTADO_MOD["m"] = mod
    return _ESTADO_MOD["m"]


def dir_preview(d: Path) -> Path:
    return d / ".preview"


def _contexto_aprovacao_do_estado(obj: dict) -> dict:
    """Snapshot canônico que a UI vê e que uma capacidade autoriza."""
    est = obj.get("estado") if isinstance(obj.get("estado"), dict) else {}
    midia = obj.get("midia") if isinstance(obj.get("midia"), dict) else {}
    plano = est.get("plano") if isinstance(est.get("plano"), dict) else {}
    try:
        fase = float(est.get("fase") if est.get("fase") is not None else 1)
    except (TypeError, ValueError):
        fase = 1
    return {
        "alvo": "fase-2" if fase >= 2 else "fase-1",
        "fingerprint_corte": est.get("fingerprint_corte"),
        "fingerprint_render": est.get("fingerprint_render"),
        "render_alvo": est.get("render_corrente") or midia.get("rel"),
        "plano_sha256": plano.get("sha256"),
    }


def _purgar_nonces_aprovacao(agora: float) -> None:
    """Chamado com `_nonces_aprovacao_lock` adquirido."""
    vencidos = [nonce for nonce, reg in _nonces_aprovacao.items()
                if agora - reg["emitido_em"] > NONCE_APROVACAO_TTL_S]
    for nonce in vencidos:
        _nonces_aprovacao.pop(nonce, None)
    while len(_nonces_aprovacao) >= NONCES_APROVACAO_MAX:
        _nonces_aprovacao.popitem(last=False)


def _emitir_sessao_ui() -> str:
    """Cria a capacidade-base somente quando o documento da UI é servido."""
    ident = secrets.token_urlsafe(32)
    agora = time.time()
    with _sessoes_ui_lock:
        vencidas = [sid for sid, reg in _sessoes_ui.items()
                    if agora - reg["emitido_em"] > SESSAO_UI_TTL_S]
        for sid in vencidas:
            _sessoes_ui.pop(sid, None)
        while len(_sessoes_ui) >= SESSOES_UI_MAX:
            _sessoes_ui.popitem(last=False)
        _sessoes_ui[ident] = {"emitido_em": agora, "token": str(CFG["token"])}
    return ident


def _sessao_ui_valida(ident) -> bool:
    if not isinstance(ident, str) or not ident:
        return False
    agora = time.time()
    with _sessoes_ui_lock:
        reg = _sessoes_ui.get(ident)
        if reg and agora - reg["emitido_em"] > SESSAO_UI_TTL_S:
            _sessoes_ui.pop(ident, None)
            reg = None
    return bool(reg and secrets.compare_digest(reg["token"], str(CFG["token"])))


def _emitir_nonce_aprovacao(obj: dict, sessao_ui: str) -> str:
    """Emite uma capacidade opaca, presa à sessão e ao snapshot da tela."""
    if not _sessao_ui_valida(sessao_ui):
        raise ValueError("sessão da UI ausente ou vencida")
    nonce = secrets.token_urlsafe(32)
    agora = time.time()
    reg = {"emitido_em": agora, "token": str(CFG["token"]),
           "sessao_ui": sessao_ui,
           "contexto": _contexto_aprovacao_do_estado(obj)}
    with _nonces_aprovacao_lock:
        _purgar_nonces_aprovacao(agora)
        _nonces_aprovacao[nonce] = reg
    return nonce


def _consumir_nonce_aprovacao(nonce, contexto: dict, sessao_ui) -> str | None:
    """Consome uma vez. Devolve o motivo da recusa, ou `None` se autorizou."""
    if not isinstance(nonce, str) or not nonce:
        return "aprovação sem nonce efêmero da UI"
    agora = time.time()
    with _nonces_aprovacao_lock:
        _purgar_nonces_aprovacao(agora)
        reg = _nonces_aprovacao.pop(nonce, None)
    if reg is None:
        return "nonce de aprovação inválido, vencido ou já consumido"
    if not secrets.compare_digest(reg["token"], str(CFG["token"])):
        return "nonce de aprovação pertence a outra sessão"
    if not _sessao_ui_valida(sessao_ui) \
            or not secrets.compare_digest(reg["sessao_ui"], str(sessao_ui)):
        return "nonce de aprovação pertence a outra sessão da UI"
    if reg["contexto"] != contexto:
        divergentes = [k for k in reg["contexto"]
                       if reg["contexto"].get(k) != contexto.get(k)]
        return "nonce de aprovação não corresponde ao contexto: %s" % ", ".join(divergentes)
    return None


def _evento_sem_nonce(corpo: dict) -> dict:
    """A capacidade autoriza o ato, mas nunca vira histórico persistido."""
    limpo = dict(corpo)
    payload = limpo.get("payload")
    if isinstance(payload, dict):
        payload = dict(payload)
        payload.pop("nonce_aprovacao", None)
        limpo["payload"] = payload
    return limpo


def porta_livre() -> int:
    """Porta efêmera do SO: bind em 0, lê getsockname, fecha. Nunca porta fixa."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((BIND_HOST, 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def _pid_vivo(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError, OSError):
        return False
    return True


# =============================================================================
# sonda (ffprobe cacheado por identidade de arquivo)
# =============================================================================
def _ffprobe(path: Path) -> dict | None:
    with _cont_lock:
        CONTADORES["sondas"] += 1
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        saida = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if saida.returncode != 0:
        return None
    try:
        return json.loads(saida.stdout or "{}")
    except ValueError:
        return None


def _fps_de(txt: str | None) -> float | None:
    if not txt or "/" not in txt:
        return None
    num, _, den = txt.partition("/")
    try:
        num_f, den_f = float(num), float(den)
    except ValueError:
        return None
    if den_f == 0:
        return None
    return num_f / den_f


def sonda(path: Path) -> dict:
    """{dur, w, h, fps, rot, tem_audio} — CACHEADO por (path, mtime_ns, size).

    Um ffprobe por VERSÃO do arquivo, não por requisição. É a primeira das três
    camadas de defesa do /api/estado (SPEC-17 §3.5).
    """
    try:
        st = path.stat()
    except OSError:
        return {"dur": None, "w": None, "h": None, "fps": None, "rot": 0,
                "tem_audio": False, "mtime_ns": None, "bytes": None}
    chave = (str(path), st.st_mtime_ns, st.st_size)
    with _sonda_lock:
        achado = _sonda_cache.get(chave)
        if achado is not None:
            _sonda_cache.move_to_end(chave)
            return dict(achado)

    bruto = _ffprobe(path) or {}
    fluxos = bruto.get("streams") or []
    v = next((f for f in fluxos if f.get("codec_type") == "video"), None)
    a = next((f for f in fluxos if f.get("codec_type") == "audio"), None)
    dur = None
    for cand in ((bruto.get("format") or {}).get("duration"),
                 (v or {}).get("duration"), (a or {}).get("duration")):
        try:
            dur = float(cand)
            break
        except (TypeError, ValueError):
            continue
    rot = 0
    if v:
        for sd in (v.get("side_data_list") or []):
            if "rotation" in sd:
                try:
                    rot = int(round(float(sd["rotation"])))
                except (TypeError, ValueError):
                    rot = 0
        if not rot:
            try:
                rot = int(round(float((v.get("tags") or {}).get("rotate", 0))))
            except (TypeError, ValueError):
                rot = 0
    val = {
        "dur": dur,
        "w": (v or {}).get("width"),
        "h": (v or {}).get("height"),
        "fps": _fps_de((v or {}).get("r_frame_rate")),
        "rot": rot % 360,
        "tem_audio": a is not None,
        "mtime_ns": st.st_mtime_ns,
        "bytes": st.st_size,
    }
    with _sonda_lock:
        _sonda_cache[chave] = val
        _sonda_cache.move_to_end(chave)
        while len(_sonda_cache) > CACHE_SONDA_MAX:
            _sonda_cache.popitem(last=False)
    return dict(val)


def dimensoes_exibidas(s: dict) -> tuple[int | None, int | None, float | None]:
    """Aplica a rotação do container. Nenhum número de formato é escrito aqui."""
    w, h = s.get("w"), s.get("h")
    if not w or not h:
        return None, None, None
    if s.get("rot", 0) % 180 == 90:
        w, h = h, w
    return w, h, (w / h if h else None)


# =============================================================================
# cache endereçado por conteúdo
# =============================================================================
def chave_midia(path: Path, n: int, altura: int) -> str:
    try:
        st = path.stat()
        ident = f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}|{n}|{altura}"
    except OSError:
        ident = f"{path}|0|0|{n}|{altura}"
    return hashlib.sha1(ident.encode("utf-8")).hexdigest()[:12]


def plano_strip(dur: float) -> tuple[int, float]:
    """Contagem limitada; intervalo derivado. O oposto do intervalo fixo do ref-A."""
    dur = max(float(dur or 0.0), 1e-6)
    n = min(N_MAX, max(N_MIN, int(round(dur / ALVO_S))))
    return n, dur / n


def _dir_cache(raiz: Path) -> Path:
    return dir_preview(raiz) / "cache"


def _limpar_parcial(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


def coletar_cache(raiz: Path, manter: int = CHAVES_MANTIDAS) -> int:
    """Coleta chaves velhas — só no FIM de uma geração, nunca durante o uso."""
    base = _dir_cache(raiz)
    if not base.is_dir():
        return 0
    chaves = [d for d in base.iterdir() if d.is_dir() and not d.name.endswith("-parcial")]
    chaves.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    removidas = 0
    for d in chaves[manter:]:
        shutil.rmtree(d, ignore_errors=True)
        removidas += 1
    return removidas


def gerar_strip(video: Path, destino: Path, n: int, intervalo: float,
                altura: int, fps: float | None, prog: dict) -> None:
    """Filmstrip por seek pontual em pool. Custo limitado por N_MAX, não pela duração.

    Escreve em <chave>.thumbs-parcial/ e só então faz os.replace para
    <chave>/thumbs/ — artefato só existe quando está completo (lição do
    segmento órfão, edit-video/SKILL.md:69).
    """
    parcial = destino.parent.with_name(destino.parent.name + ".thumbs-parcial")
    _limpar_parcial(parcial)
    parcial.mkdir(parents=True, exist_ok=True)
    passo_final = (1.0 / fps) if fps else 0.04
    dur_total = n * intervalo

    def um(k: int) -> bool:
        t = min((k + 0.5) * intervalo, max(0.0, dur_total - passo_final))
        alvo = parcial / f"{k + 1:04d}.jpg"
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.6f}", "-i", str(video),
               "-frames:v", "1", "-vf", f"scale=-2:{altura}", "-q:v", "6", "-y", str(alvo)]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0 and alvo.exists()

    trabalhadores = min(8, os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=trabalhadores) as pool:
        for ok in pool.map(um, range(n)):
            with _gen_lock:
                if ok:
                    prog["feito"] += 1

    largura = None
    primeiro = parcial / "0001.jpg"
    if primeiro.exists():
        s = _ffprobe(primeiro) or {}
        fl = (s.get("streams") or [{}])[0]
        largura = fl.get("width")

    meta = {
        "schema": "benchmark.preview-strip/v1",
        "n": n,
        "intervalo": round(intervalo, 6),
        "t0": round(intervalo / 2, 6),
        "altura": altura,
        "largura": largura,
        "dur": round(dur_total, 6),
        "src": video.name,
        "src_mtime_ns": video.stat().st_mtime_ns,
        "gerado_em": _agora_iso(),
    }
    (parcial / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        shutil.rmtree(parcial, ignore_errors=True)
        return
    os.replace(parcial, destino)


def gerar_waveform(video: Path, destino: Path, dur: float) -> None:
    """Decode mono s16 + min/max por balde, com teto de baldes (BALDES_MAX).

    Baldes de tamanho exato por divisão inteira — sem balde final ralo.
    """
    picos = min(PICOS_POR_S_MAX, BALDES_MAX / max(float(dur or 0.0), 1e-6))
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(video), "-vn",
           "-ac", "1", "-ar", str(TAXA_AUDIO), "-f", "s16le", "-"]
    bruto = subprocess.run(cmd, capture_output=True).stdout
    amostras = array.array("h")
    amostras.frombytes(bruto[: len(bruto) // 2 * 2])
    total = len(amostras)
    dur_audio = total / TAXA_AUDIO if total else 0.0
    n_baldes = max(1, min(BALDES_MAX, int(round(dur_audio * picos)))) if total else 0
    minimos: list[int] = []
    maximos: list[int] = []
    for b in range(n_baldes):
        i0 = b * total // n_baldes
        i1 = (b + 1) * total // n_baldes
        if i1 <= i0:
            i1 = i0 + 1
        pedaco = amostras[i0:i1]
        minimos.append(int(round(min(pedaco) / 32768 * 100)))
        maximos.append(int(round(max(pedaco) / 32768 * 100)))
    _escrever_json_atomico(destino, {
        "schema": "benchmark.preview-waveform/v1",
        "picosPorS": round(picos, 6),
        "dur": round(dur_audio, 6),
        "min": minimos,
        "max": maximos,
        "src_mtime_ns": video.stat().st_mtime_ns,
    })


def _iniciar(chave: str, tipo: str, total: int, alvo) -> dict:
    with _gen_lock:
        prog = _gerando.get((chave, tipo))
        if prog is not None and prog.get("estado") == "gerando":
            return prog
        prog = {"estado": "gerando", "feito": 0, "total": total, "erro": None}
        _gerando[(chave, tipo)] = prog

    def corpo():
        try:
            alvo(prog)
            with _gen_lock:
                prog["estado"] = "pronto"
        except Exception as exc:                      # noqa: BLE001 — reportado no estado
            with _gen_lock:
                prog["estado"] = "erro"
                prog["erro"] = f"{type(exc).__name__}: {exc}"
            print(f"[preview] falha gerando {tipo} {chave}: {exc}", file=sys.stderr, flush=True)

    threading.Thread(target=corpo, name=f"gen-{tipo}-{chave}", daemon=True).start()
    return prog


def garantir_midia(raiz: Path, video: Path, altura: int) -> dict:
    """Devolve o estado da mídia derivada, disparando geração em thread se faltar.

    NUNCA bloqueia a requisição: quem espera é o poll de /api/estado.
    """
    s = sonda(video)
    dur = s.get("dur") or 0.0
    n, intervalo = plano_strip(dur)
    chave = chave_midia(video, n, altura)
    base = _dir_cache(raiz) / chave
    thumbs = base / "thumbs"
    onda = base / "waveform.json"

    if (thumbs / "meta.json").exists():
        strip = {"estado": "pronto", "feito": n}
    elif not s.get("w"):
        strip = {"estado": "ausente", "feito": 0}
    else:
        prog = _iniciar(chave, "strip", n, lambda p: (
            gerar_strip(video, thumbs, n, intervalo, altura, s.get("fps"), p),
            coletar_cache(raiz)))
        strip = {"estado": prog["estado"], "feito": prog["feito"], "erro": prog.get("erro")}

    picos = min(PICOS_POR_S_MAX, BALDES_MAX / max(dur, 1e-6))
    if onda.exists():
        wf = {"estado": "pronto"}
    elif not s.get("tem_audio"):
        wf = {"estado": "ausente"}
    else:
        prog = _iniciar(chave, "waveform", 1,
                        lambda p: gerar_waveform(video, onda, dur))
        wf = {"estado": prog["estado"], "erro": prog.get("erro")}

    strip.update({"n": n, "intervalo": round(intervalo, 6), "altura": altura})
    wf["picosPorS"] = round(picos, 6)
    w, h, aspecto = dimensoes_exibidas(s)
    return {
        "chave": chave,
        "dur": s.get("dur"),
        "width": w,
        "height": h,
        "fps": s.get("fps"),
        "aspecto": round(aspecto, 6) if aspecto else None,
        "rot": s.get("rot", 0),
        "mtime_ns": s.get("mtime_ns"),
        "bytes": s.get("bytes"),
        "strip": strip,
        "waveform": wf,
    }


# =============================================================================
# escolha da mídia + montagem do estado
# =============================================================================
def _rel_lexicalmente_dentro(rel: str) -> bool:
    if not rel or rel.startswith("/") or "\x00" in rel:
        return False
    partes = PurePosixPath(rel).parts
    return ".." not in partes


def _rel_do_estado(est: dict) -> str | None:
    for campo in ("render", "entregavel", "video", "midia"):
        v = est.get(campo)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for sub in ("arquivo", "rel", "caminho", "path"):
                if isinstance(v.get(sub), str) and v[sub].strip():
                    return v[sub].strip()
    return None


def escolher_midia(raiz: Path, est: dict) -> tuple[Path, str] | None:
    rel = _rel_do_estado(est or {})
    candidatos = [rel] if rel else list(CANDIDATOS_MIDIA)
    for c in candidatos:
        if not c or not _rel_lexicalmente_dentro(c):
            continue
        p = raiz / c
        if p.is_file():
            return p, c
    return None


def resolver_sob(base: Path, rel: str) -> Path | None:
    """unquote → resolve → is_relative_to. Symlink que aponta para fora é BLOQUEADO."""
    rel = unquote(rel.split("?", 1)[0].split("#", 1)[0])
    if "\x00" in rel:
        return None
    p = (base / rel.lstrip("/")).resolve(strict=False)
    b = base.resolve(strict=False)
    return p if p == b or p.is_relative_to(b) else None


def _dir_publicado(raiz: Path) -> str:
    try:
        return str(raiz.relative_to(Path.cwd()))
    except ValueError:
        return str(raiz)


def montar_estado() -> tuple[dict, str]:
    raiz: Path = CFG["raiz"]
    prev = dir_preview(raiz)
    est = _ler_json(prev / "estado.json")
    if not isinstance(est, dict):
        est = {}

    arquivos: dict[str, list] = {}
    for nome in OBSERVADOS:
        par = _stat_par(raiz / nome)
        if par:
            arquivos[nome] = par
    par_est = _stat_par(prev / "estado.json")
    if par_est:
        arquivos[".preview/estado.json"] = par_est

    escolha = escolher_midia(raiz, est)
    midia = None
    if escolha:
        caminho, rel = escolha
        midia = garantir_midia(raiz, caminho, CFG["altura"])
        midia["rel"] = rel
        # Servível por /media/ só se a resolução estrita também aceitar. Um
        # input/ symlinkado para fora da produção gera filmstrip (leitura local
        # e deliberada, vinda do estado.json) mas NÃO é servido por HTTP.
        midia["servivel"] = resolver_sob(raiz, rel) is not None
        arquivos[rel] = [midia.get("mtime_ns"), midia.get("bytes")]

    edl = _ler_json(raiz / "edl.json")
    timeline = None
    if isinstance(edl, dict):
        timeline = edl.get("timeline_real")
    perfil = _ler_json(raiz / "perfil.json")

    pend = prev / "pendentes"
    try:
        n_pend = sum(1 for f in pend.glob("*.json"))
    except OSError:
        n_pend = 0
    # 🔴 H49-11 (achado F48-3, 2026-08-12): a marcação APLICADA continuava
    # desenhada na régua como se estivesse esperando. O dado existe desde a
    # SPEC-16 — o ACK é o MOVE para `aplicados/` — e a tela nunca soube dele: ela
    # só conhecia `enviada`, que quer dizer "o POST saiu", não "o agente aplicou".
    # Uma marca que diz "pendente" depois de aplicada é mentira visual, e o
    # creator remarca a mesma coisa duas vezes.
    #
    # O que viaja é o CONJUNTO de ids aplicados (não a contagem): a régua precisa
    # saber QUAL marca mudou de estado, e contagem não diz isso.
    apl_dir = prev / "aplicados"
    aplicados: list[str] = []
    try:
        for f in sorted(apl_dir.glob("*.json")):
            doc = _ler_json(f)
            for nota in ((doc or {}).get("notas") or []):
                ident = nota.get("id") or nota.get("marcacao_id")
                if ident:
                    aplicados.append(str(ident))
    except OSError:
        pass

    with _gen_lock:
        marca_gen = json.dumps(
            sorted((f"{k[0]}:{k[1]}", v.get("estado"), v.get("feito", 0))
                   for k, v in _gerando.items()))

    obj = {
        "schema": "benchmark.preview-estado/v1",
        "agora": round(time.time(), 3),
        "dir": _dir_publicado(raiz),
        "sessao": {"token": CFG["token"], "porta": CFG["porta"], "pid": os.getpid()},
        "estado": est,
        "midia": midia,
        "perfil": perfil,
        "edl": edl,
        "timeline_real": timeline,
        "timeline_real_ausente": timeline is None,
        "arquivos": arquivos,
        "pendentes": n_pend,
        "marcacoes_aplicadas": sorted(set(aplicados)),
    }
    marca = json.dumps([sorted(arquivos.items()), n_pend, marca_gen,
                        sorted(set(aplicados))], sort_keys=True)
    rev = hashlib.sha1(marca.encode("utf-8")).hexdigest()[:16]
    return obj, rev


def estado_atual() -> tuple[dict, str]:
    """Piso de reavaliação: várias abas batendo junto não multiplicam trabalho."""
    agora = time.time()
    with _estado_lock:
        if _estado_memo["obj"] is not None and agora - _estado_memo["t"] < PISO_ESTADO_S:
            return _estado_memo["obj"], _estado_memo["rev"]
    obj, rev = montar_estado()
    with _estado_lock:
        _estado_memo.update({"t": agora, "obj": obj, "rev": rev})
    return obj, rev


# =============================================================================
# página de diagnóstico embutida (só quando app/ não existe)
# =============================================================================
DIAG_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>preview — diagnóstico</title>
<style>
 :root{color-scheme:light dark}
 body{font:14px/1.5 ui-sans-serif,system-ui,sans-serif;margin:0;padding:24px;
      background:Canvas;color:CanvasText}
 h1{font-size:16px;margin:0 0 4px} h2{font-size:13px;margin:24px 0 8px;
      text-transform:uppercase;letter-spacing:.08em;opacity:.6}
 code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
 pre{background:color-mix(in srgb,CanvasText 6%,Canvas);padding:12px;border-radius:8px;
     overflow:auto;max-height:40vh;font-size:12px}
 video{max-width:100%;max-height:52vh;background:#000;border-radius:8px}
 #tira{display:flex;gap:2px;overflow-x:auto;padding-bottom:8px}
 #tira img{height:90px;border-radius:2px}
 canvas{width:100%;height:96px;background:color-mix(in srgb,CanvasText 6%,Canvas);
        border-radius:8px}
 table{border-collapse:collapse;font-size:12px} td{padding:2px 12px 2px 0}
 .aviso{padding:8px 12px;border-radius:8px;
        background:color-mix(in srgb,#e8a33d 22%,Canvas);font-size:12px}
</style></head><body>
<h1>preview — página de diagnóstico</h1>
<div id="sub">a app da SPEC-16/18 não está em <code>app/</code>; esta é a página embutida.</div>
<h2>rotas</h2>
<table><tbody>
<tr><td><code>api/estado</code></td><td>estado + mídia + edl (ETag/304)</td></tr>
<tr><td><code>api/saude</code></td><td>contadores</td></tr>
<tr><td><code>api/salvar</code></td><td>POST — fila append-only</td></tr>
<tr><td><code>media/&lt;rel&gt;</code></td><td>arquivo da produção, com Range</td></tr>
<tr><td><code>gen/&lt;chave&gt;/thumbs/NNNN.jpg</code></td><td>filmstrip (immutable)</td></tr>
<tr><td><code>gen/&lt;chave&gt;/waveform.json</code></td><td>picos min/max</td></tr>
</tbody></table>
<h2>render</h2>
<div id="video"></div>
<h2>waveform</h2>
<canvas id="onda" width="1600" height="192"></canvas>
<h2>filmstrip</h2>
<div id="tira"></div>
<h2>/api/estado</h2>
<pre id="dump">carregando…</pre>
<script>
let chaveVista=null, ondaVista=null, videoPosto=null;
function desenhar(w){
  const c=document.getElementById('onda'), g=c.getContext('2d');
  g.clearRect(0,0,c.width,c.height);
  const n=w.min.length, meio=c.height/2;
  g.fillStyle=getComputedStyle(document.body).color;
  for(let i=0;i<n;i++){
    const x=Math.floor(i*c.width/n), lg=Math.max(1,Math.ceil(c.width/n));
    const y0=meio-(w.max[i]/100)*meio, y1=meio-(w.min[i]/100)*meio;
    g.fillRect(x,y0,lg,Math.max(1,y1-y0));
  }
}
async function poll(){
  try{
    const r=await fetch('api/estado',{cache:'no-store'});
    const s=await r.json();
    document.getElementById('dump').textContent=JSON.stringify(s,null,1).slice(0,20000);
    const m=s.midia;
    if(m){
      if(m.rel!==videoPosto){
        videoPosto=m.rel;
        document.getElementById('video').innerHTML = m.servivel
          ? '<video controls preload="metadata" src="media/'+m.rel.split('/').map(encodeURIComponent).join('/')+'"></video>'
          : '<div class="aviso">'+m.rel+' resolve para fora da produção (symlink). '+
            'O filmstrip e a waveform são gerados, mas o arquivo não é servido por HTTP.</div>';
      }
      if(m.strip&&m.strip.estado==='pronto'&&m.chave!==chaveVista){
        chaveVista=m.chave;
        const t=document.getElementById('tira'); t.innerHTML='';
        for(let k=1;k<=m.strip.n;k++){
          const im=new Image(); im.loading='lazy';
          im.src='gen/'+m.chave+'/thumbs/'+String(k).padStart(4,'0')+'.jpg';
          im.title=((k-1)*m.strip.intervalo+m.strip.intervalo/2).toFixed(2)+'s';
          t.appendChild(im);
        }
      }
      if(m.waveform&&m.waveform.estado==='pronto'&&m.chave!==ondaVista){
        ondaVista=m.chave;
        const w=await (await fetch('gen/'+m.chave+'/waveform.json')).json();
        desenhar(w);
      }
    }else{
      document.getElementById('video').textContent='ainda não há render nesta produção.';
    }
  }catch(e){ document.getElementById('dump').textContent='erro: '+e; }
  setTimeout(poll,2000);
}
poll();
</script></body></html>
"""


# =============================================================================
# handler
# =============================================================================
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "preview-ilha/" + VERSAO

    # ---- infraestrutura ----
    def log_message(self, formato: str, *args) -> None:  # noqa: A002
        try:
            codigo = str(args[1]) if len(args) > 1 else ""
        except Exception:                                 # noqa: BLE001
            codigo = ""
        if codigo in ("200", "206", "304") and "api/estado" in str(args[0]):
            return
        sys.stderr.write("[preview] %s %s\n" % (self.address_string(), formato % args))
        sys.stderr.flush()

    def _host_ok(self) -> bool:
        h = (self.headers.get("Host") or "").strip().lower()
        p = CFG["porta"]
        permitidos = {f"127.0.0.1:{p}", f"localhost:{p}", f"[::1]:{p}"}
        preview = CFG.get("preview") or {}
        if preview.get("modo") == "cloud" and preview.get("host_declarado"):
            cab = str(preview.get("host_header") or "").strip().lower()
            host = str(preview.get("host") or "").strip().lower()
            if cab:
                permitidos.add(cab)
            # Em HTTPS na porta default, navegadores e proxies podem omitir :443.
            if host and (cab == host or cab == host + ":443"):
                permitidos.update({host, host + ":443"})
        return h in permitidos

    def _cabecalho(self, code: int, ctype: str, length: int | None = None,
                   extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, obj, code: int = 200, cache: str = "no-store",
              extra: dict | None = None, so_cabecalho: bool = False) -> None:
        corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        cab = {"Cache-Control": cache}
        cab.update(extra or {})
        self._cabecalho(code, "application/json; charset=utf-8", len(corpo), cab)
        if not so_cabecalho:
            self._escrever(corpo)

    def _escrever(self, dados: bytes) -> None:
        try:
            self.wfile.write(dados)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _html(self, texto: str, so_cabecalho: bool = False,
              cabecalhos: dict | None = None) -> None:
        corpo = texto.encode("utf-8")
        extra = {"Cache-Control": "no-store"}
        extra.update(cabecalhos or {})
        self._cabecalho(200, "text/html; charset=utf-8", len(corpo),
                        extra)
        if not so_cabecalho:
            self._escrever(corpo)

    # ---- arquivo com Range ----
    def _arquivo(self, caminho: Path, cache: str = "no-cache",
                 so_cabecalho: bool = False,
                 cabecalhos: dict | None = None) -> None:
        if not caminho.is_file():
            self._json({"erro": "nao encontrado", "rel": caminho.name}, 404,
                       so_cabecalho=so_cabecalho)
            return
        st = caminho.stat()
        tamanho = st.st_size
        ctype = MIME.get(caminho.suffix.lower(), "application/octet-stream")
        etag = 'W/"%d-%d"' % (st.st_mtime_ns, tamanho)
        extra = {"Cache-Control": cache, "Accept-Ranges": "bytes", "ETag": etag}
        extra.update(cabecalhos or {})

        faixa = self.headers.get("Range")
        inicio, fim, codigo = 0, tamanho - 1, 200
        if faixa:
            m = re.match(r"^bytes=(\d*)-(\d*)$", faixa.strip())
            if m:
                if m.group(1):
                    inicio = int(m.group(1))
                    if m.group(2):
                        fim = min(int(m.group(2)), tamanho - 1)
                elif m.group(2):
                    inicio = max(0, tamanho - int(m.group(2)))
                if inicio >= tamanho or inicio > fim:
                    extra["Content-Range"] = f"bytes */{tamanho}"
                    self._cabecalho(416, ctype, 0, extra)
                    return
                codigo = 206
                extra["Content-Range"] = f"bytes {inicio}-{fim}/{tamanho}"

        comprimento = fim - inicio + 1
        self._cabecalho(codigo, ctype, comprimento, extra)
        if so_cabecalho:
            return
        with open(caminho, "rb") as f:
            f.seek(inicio)
            resta = comprimento
            while resta > 0:
                pedaco = f.read(min(BLOCO_IO, resta))
                if not pedaco:
                    break
                try:
                    self.wfile.write(pedaco)
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True
                    return
                resta -= len(pedaco)

    # ---- rotas ----
    def _prefixo(self) -> str | None:
        caminho = self.path.split("?", 1)[0].split("#", 1)[0]
        alvo = "/" + CFG["token"]
        if caminho == alvo:
            return ""
        if caminho.startswith(alvo + "/"):
            return caminho[len(alvo) + 1:]
        return None

    def _entrar(self) -> str | None:
        with _cont_lock:
            CONTADORES["req"] += 1
        _ultima_req["t"] = time.time()
        if not self._host_ok():
            self._json({"erro": "host nao autorizado"}, 403)
            return None
        resto = self._prefixo()
        if resto is None:
            self._json({"erro": "nao encontrado"}, 404)
            return None
        if cloud_expirada():
            self._json({"erro": "sessao expirada"}, 410)
            return None
        return resto

    def _sessao_ui(self) -> str | None:
        for trecho in (self.headers.get("Cookie") or "").split(";"):
            nome, separador, valor = trecho.strip().partition("=")
            if separador and nome == COOKIE_SESSAO_UI:
                return valor
        return None

    def _cookie_nova_sessao_ui(self) -> str:
        ident = _emitir_sessao_ui()
        seguro = "; secure" if (CFG.get("preview") or {}).get("modo") == "cloud" else ""
        return "%s=%s; path=/%s/; httponly; samesite=strict%s" \
            % (COOKIE_SESSAO_UI, ident, CFG["token"], seguro)

    def do_GET(self) -> None:                      # noqa: N802
        resto = self._entrar()
        if resto is None:
            return
        self._despachar(resto, so_cabecalho=False)

    def do_HEAD(self) -> None:                     # noqa: N802
        resto = self._entrar()
        if resto is None:
            return
        self._despachar(resto, so_cabecalho=True)

    def _despachar(self, resto: str, so_cabecalho: bool) -> None:
        raiz: Path = CFG["raiz"]
        if resto in ("", "index.html"):
            indice = CFG["app"] / "index.html"
            cabecalhos_ui = None if so_cabecalho else {
                "Set-Cookie": self._cookie_nova_sessao_ui()}
            # 🔴 H49-7 (achado A-9, 2026-08-12). `--app <pacote>` apontava a raiz
            # `/` para o diretório do PACOTE, que não tem `index.html` — então a
            # raiz caía na página de diagnóstico e **a timeline de aprovação
            # DESAPARECIA**. O ciclo documentado (`previews-peca.py --pacote` +
            # `servir --app <pacote>`) matava a única tela onde o corte se aprova,
            # e o contorno de quem tropeçou foi copiar `preview/app/.` para dentro
            # do pacote — trabalho manual para desfazer um dano nosso.
            #
            # A app da SPEC-18 é a raiz do servidor; um `--app` de terceiro é uma
            # SEGUNDA superfície, não um substituto. Quando ele não tem índice, a
            # raiz volta para a app embarcada e o `--app` continua alcançável em
            # `/app/` — que é onde a galeria do pacote já se serve.
            if not indice.is_file():
                embarcada = APP_EMBARCADA / "index.html"
                if embarcada.is_file():
                    self._arquivo(embarcada, cache="no-store",
                                  so_cabecalho=so_cabecalho,
                                  cabecalhos=cabecalhos_ui)
                    return
                self._html(DIAG_HTML, so_cabecalho=so_cabecalho)
                return
            self._arquivo(indice, cache="no-store", so_cabecalho=so_cabecalho,
                          cabecalhos=cabecalhos_ui)
            return
        if resto.startswith("app/"):
            p = resolver_sob(CFG["app"], resto[4:])
            if p is None:
                self._json({"erro": "fora da raiz"}, 403, so_cabecalho=so_cabecalho)
                return
            self._arquivo(p, cache="no-store", so_cabecalho=so_cabecalho)
            return
        if resto.startswith("media/"):
            p = resolver_sob(raiz, resto[6:])
            if p is None:
                self._json({"erro": "fora da raiz"}, 403, so_cabecalho=so_cabecalho)
                return
            if dir_preview(raiz) in p.parents:
                self._json({"erro": "fora da raiz"}, 403, so_cabecalho=so_cabecalho)
                return
            self._arquivo(p, cache="no-cache", so_cabecalho=so_cabecalho)
            return
        if resto.startswith("galeria/"):
            # A galeria de estilos (galeria.json + os previews .webm de nível 1)
            # mora em `<raiz>/.preview/estilos/`, e a rota `/media/` recusa TUDO
            # que está sob `.preview/` de propósito. Sem esta rota a aba Estilo
            # abre e 404 no primeiro fetch — que foi o estado até 2026-08-09.
            #
            # A ROTA se chama `galeria/` e o DIRETÓRIO `estilos/`, e isso é de
            # propósito: `estilos/` na raiz do repo é a biblioteca de estilos do
            # usuário (SPEC-24), coisa completamente diferente. Uma rota com o
            # mesmo nome fazia o auditor de acoplamento acusar — com razão, é
            # ambíguo para quem lê.
            base = dir_preview(raiz) / "estilos"
            p = resolver_sob(base, resto[8:])
            if p is None:
                self._json({"erro": "fora da raiz"}, 403, so_cabecalho=so_cabecalho)
                return
            if not p.is_file():
                self._json({"erro": "galeria não gerada nesta produção",
                            "como": "rode previews-peca.py no diretório dela"},
                           404, so_cabecalho=so_cabecalho)
                return
            self._arquivo(p, cache="no-cache", so_cabecalho=so_cabecalho)
            return
        if resto.startswith("gen/"):
            self._rota_gen(resto[4:], so_cabecalho)
            return
        if resto == "api/estado":
            self._rota_estado(so_cabecalho)
            return
        if resto == "api/saude":
            self._rota_saude(so_cabecalho)
            return
        self._json({"erro": "rota desconhecida"}, 404, so_cabecalho=so_cabecalho)

    def _rota_gen(self, resto: str, so_cabecalho: bool) -> None:
        base = _dir_cache(CFG["raiz"])
        p = resolver_sob(base, resto)
        if p is None:
            self._json({"erro": "fora da raiz"}, 403, so_cabecalho=so_cabecalho)
            return
        partes = PurePosixPath(unquote(resto)).parts
        if len(partes) >= 2 and partes[1] == "thumbs":
            if not (base / partes[0] / "thumbs" / "meta.json").exists():
                self._json({"erro": "em geracao"}, 404, so_cabecalho=so_cabecalho)
                return
        self._arquivo(p, cache="public, max-age=31536000, immutable",
                      so_cabecalho=so_cabecalho)

    def _rota_estado(self, so_cabecalho: bool) -> None:
        obj, rev = estado_atual()
        etag = 'W/"%s"' % rev
        recebido = self.headers.get("If-None-Match") or ""
        if etag in [x.strip() for x in recebido.split(",") if x.strip()]:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        resposta = obj
        sessao_ui = self._sessao_ui()
        if not so_cabecalho and _sessao_ui_valida(sessao_ui):
            # O nonce não participa de `rev`: é capacidade efêmera da resposta,
            # não estado/fingerprint da produção. Uma resposta 304 não emite.
            resposta = dict(obj)
            sessao = dict(obj.get("sessao") or {})
            sessao["nonce_aprovacao"] = _emitir_nonce_aprovacao(obj, sessao_ui)
            resposta["sessao"] = sessao
        self._json(resposta, 200, cache="no-store", extra={"ETag": etag},
                   so_cabecalho=so_cabecalho)

    def _rota_saude(self, so_cabecalho: bool) -> None:
        with _cont_lock:
            sondas, req = CONTADORES["sondas"], CONTADORES["req"]
        self._json({"ok": True, "dir": str(CFG["raiz"]), "pid": os.getpid(),
                    "versao": VERSAO, "desde": CFG["desde"],
                    "sondas": sondas, "req": req}, so_cabecalho=so_cabecalho)

    # ---- POST ----
    def do_POST(self) -> None:                     # noqa: N802
        resto = self._entrar()
        if resto is None:
            return
        if resto != "api/salvar":
            self._descartar_corpo()
            self._json({"erro": "rota desconhecida"}, 404)
            return
        try:
            comprimento = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            comprimento = -1
        if comprimento < 0:
            self._json({"erro": "Content-Length invalido"}, 400)
            return
        if comprimento > TETO_POST:
            self._descartar_corpo(comprimento)
            self._json({"erro": "corpo acima do teto", "teto": TETO_POST}, 413)
            return
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "json" not in ctype:
            self._descartar_corpo(comprimento)
            self._json({"erro": "Content-Type precisa ser JSON"}, 415)
            return
        bruto = self.rfile.read(comprimento) if comprimento else b""
        try:
            corpo = json.loads(bruto or b"{}")
        except ValueError:
            self._json({"erro": "JSON invalido"}, 400)
            return
        if not isinstance(corpo, dict) or not isinstance(corpo.get("tipo"), str) \
                or not corpo["tipo"].strip():
            self._json({"erro": "corpo precisa ser objeto com 'tipo' string"}, 400)
            return
        tipo = corpo["tipo"].strip().lower()
        if tipo == "aprovacao":
            # A aprovação é executável e pode ser recusada se o conteúdo mudou.
            # Só entra na fila append-only DEPOIS de registrada: um envelope
            # recusado em pendentes travaria ou confundiria o ACK do watcher.
            extra = self._efeito_do_evento(corpo)
            if extra.get("erro_aprovacao"):
                self._json({"ok": False, "arquivo": None, **extra})
                return
            alvo = self._gravar_evento(_evento_sem_nonce(corpo))
        else:
            alvo = self._gravar_evento(corpo)
            extra = {}
        self._json({"ok": True, "arquivo": str(alvo), **extra})

    def _efeito_do_evento(self, corpo: dict) -> dict:
        """O único evento que o SERVIDOR também executa: `aprovacao`.

        🔴 POR QUE ESTE É DIFERENTE DOS OUTROS (achado A10). Todo save da UI é
        append-only na fila `pendentes/`, e quem o transforma em trabalho é o
        agente — de propósito: ajuste de legenda e escolha de estilo têm que
        passar por validação de contrato antes de virar arquivo.

        A aprovação não. Ela é o ÚNICO ato do fluxo cuja autoria é o valor: se
        ela depender de um agente ler a fila, ela vira "o agente aprovou" de
        novo, que é exatamente o defeito. `ui-save` prova uma sessão ativa da UI,
        contexto fresco e capacidade consumida uma vez. Não é prova
        criptográfica de mão humana: um processo local com acesso ao token e à
        sessão consegue automatizar o mesmo protocolo. A fronteira restante é
        operacional, o agente não solicita nem envia esse nonce fora do app.
        """
        if (corpo.get("tipo") or "").strip().lower() != "aprovacao":
            return {}
        payload = corpo.get("payload") or {}
        if not isinstance(payload, dict):
            return {"aprovacao": None,
                    "erro_aprovacao": "payload de aprovação precisa ser objeto"}
        alvo = str(payload.get("alvo") or "fase-1")
        por = str(payload.get("por") or "creator (UI)")
        motivo = payload.get("motivo") or None
        campos_contexto = ("alvo", "fingerprint_corte", "fingerprint_render",
                           "render_alvo", "plano_sha256")
        faltando = [k for k in campos_contexto if k not in payload]
        if faltando:
            return {"aprovacao": None,
                    "erro_aprovacao": "aprovação sem contexto da tela: %s"
                    % ", ".join(faltando)}
        esperado = {k: payload.get(k) for k in campos_contexto}
        erro_nonce = _consumir_nonce_aprovacao(
            payload.get("nonce_aprovacao"), esperado, self._sessao_ui())
        if erro_nonce:
            return {"aprovacao": None, "erro_aprovacao": erro_nonce}
        try:
            est_mod = _estado_mod()
            reg = est_mod.registrar_aprovacao(
                str(CFG["raiz"]), alvo, por, fonte=est_mod.FONTE_UI,
                motivo=motivo, pid=os.getpid(), esperado=esperado)
        except KeyboardInterrupt:
            raise
        except BaseException as e:                   # noqa: BLE001
            # 🔴 `BaseException`, e não `Exception`. `estado.py` nasceu CLI e
            # aborta com `sys.exit(...)`; `SystemExit` atravessava o
            # `except Exception`, matava esta thread e fechava a conexão SEM
            # RESPOSTA. O browser via ERR_EMPTY_RESPONSE, tentava de novo, e um
            # clique virou 6 envelopes na fila. Medido na tela em 2026-08-10.
            # Falhar aqui não pode virar silêncio: o creator clicou.
            print("[preview] aprovacao NAO registrada: %s: %s"
                  % (type(e).__name__, e), file=sys.stderr, flush=True)
            return {"aprovacao": None, "erro_aprovacao": "%s: %s"
                    % (type(e).__name__, e)}
        print("[preview] aprovacao registrada pela UI: %s por %s"
              % (reg["alvo"], reg["por"]), file=sys.stderr, flush=True)
        return {"aprovacao": {"alvo": reg["alvo"], "em": reg["em"],
                              "fonte": reg["fonte"], "por": reg["por"]}}

    def _descartar_corpo(self, comprimento: int | None = None) -> None:
        if comprimento is None:
            try:
                comprimento = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                comprimento = 0
        resta = comprimento
        limite = 8 << 20
        if resta > limite:
            self.close_connection = True
            resta = min(resta, limite)
        while resta > 0:
            pedaco = self.rfile.read(min(BLOCO_IO, resta))
            if not pedaco:
                break
            resta -= len(pedaco)

    def _gravar_evento(self, corpo: dict) -> Path:
        raiz: Path = CFG["raiz"]
        pend = dir_preview(raiz) / "pendentes"
        pend.mkdir(parents=True, exist_ok=True)
        tipo_bruto = corpo["tipo"].strip().lower()
        tipo = re.sub(r"[^a-z0-9-]+", "-", tipo_bruto).strip("-") or "evento"
        envelope = {
            "schema": "benchmark.preview-evento/v1",
            "tipo": corpo["tipo"].strip(),
            "salvo_em": _agora_iso(),
            "origem": {"ua": self.headers.get("User-Agent") or "",
                       "token": CFG["token"]},
            "payload": corpo.get("payload"),
        }
        carimbo = _carimbo()
        with CFG["lock_evento"]:
            n = 1
            while (pend / f"{carimbo}-{tipo}-{n}.json").exists():
                n += 1
            alvo = pend / f"{carimbo}-{tipo}-{n}.json"
            _escrever_json_atomico(alvo, envelope)
        return alvo


# =============================================================================
# subcomandos
# =============================================================================
def _url(porta: int, token: str) -> str:
    return f"http://{BIND_HOST}:{porta}/{token}/"


def contrato_preview(porta: int, token: str) -> dict:
    """Resolve a superficie configurada sem alterar o backend de loopback."""
    return CLOUD_ADAPTER.resolver(_url(porta, token), token, porta)


def cloud_expirada(agora: float | None = None) -> bool:
    """No modo cloud, a validade declarada limita tambem o servidor local."""
    preview = CFG.get("preview") or {}
    expira = preview.get("expira_epoch") if preview.get("modo") == "cloud" else None
    instante = time.time() if agora is None else float(agora)
    return bool(expira is not None and instante >= float(expira))


def sessao_viva(raiz: Path) -> dict | None:
    dados = _ler_json(dir_preview(raiz) / "servidor.json")
    if not isinstance(dados, dict):
        return None
    if not _pid_vivo(dados.get("pid")):
        return None
    try:
        url_local = dados.get("url_local") or dados["url"]
        with urlopen(url_local + "api/saude", timeout=2) as r:
            saude = json.loads(r.read().decode("utf-8"))
    except Exception:                                     # noqa: BLE001
        return None
    if not saude.get("ok") or str(saude.get("dir")) != str(raiz.resolve()):
        return None
    return dados


def abrir_sessao(raiz: Path, porta: int | None = None, altura: int | None = None) -> dict:
    viva = sessao_viva(raiz)
    if viva:
        return viva
    dir_preview(raiz).mkdir(parents=True, exist_ok=True)
    dados = {
        "url": "",
        "url_local": "",
        "porta": int(porta) if porta else porta_livre(),
        "token": secrets.token_hex(6),
        "dir": str(raiz.resolve()),
        "pid": None,
        "iniciado_em": _agora_iso(),
        "versao": VERSAO,
        "altura_thumb": int(altura or ALTURA_THUMB_PADRAO),
    }
    dados["url"] = _url(dados["porta"], dados["token"])
    dados["url_local"] = dados["url"]
    dados["preview"] = contrato_preview(dados["porta"], dados["token"])
    dados["url_preferida"] = dados["preview"]["url"]
    _escrever_json_atomico(dir_preview(raiz) / "servidor.json", dados)
    return dados


def _ocioso_vigia(httpd, minutos: int) -> None:
    preview = CFG.get("preview") or {}
    tem_expiracao = preview.get("modo") == "cloud" and preview.get("expira_epoch")
    if minutos <= 0 and not tem_expiracao:
        return
    limite = minutos * 60 if minutos > 0 else None

    def corpo():
        while True:
            time.sleep(5)
            if cloud_expirada():
                print("[preview] sessao cloud expirada; encerrando.",
                      file=sys.stderr, flush=True)
                threading.Thread(target=httpd.shutdown, daemon=True).start()
                return
            if limite is not None and time.time() - _ultima_req["t"] > limite:
                print(f"[preview] ocioso por {minutos} min — encerrando.",
                      file=sys.stderr, flush=True)
                threading.Thread(target=httpd.shutdown, daemon=True).start()
                return

    threading.Thread(target=corpo, name="ocioso", daemon=True).start()


def cmd_servir(args) -> int:
    raiz = Path(args.dir).resolve()
    if not raiz.is_dir():
        print(f"erro: dir inexistente: {raiz}", file=sys.stderr)
        return 2
    dados = _ler_json(dir_preview(raiz) / "servidor.json") or {}
    porta = int(args.porta or dados.get("porta") or 0) or porta_livre()
    token = args.token or dados.get("token") or secrets.token_hex(6)
    altura = int(args.altura_thumb or dados.get("altura_thumb") or ALTURA_THUMB_PADRAO)
    app = Path(args.app).resolve() if args.app else APP_EMBARCADA
    preview = contrato_preview(porta, token)

    CFG.update({"raiz": raiz, "token": token, "porta": porta, "app": app,
                "altura": altura, "desde": time.time(),
                "preview": preview,
                "lock_evento": threading.Lock()})
    with _nonces_aprovacao_lock:
        _nonces_aprovacao.clear()
    with _sessoes_ui_lock:
        _sessoes_ui.clear()

    try:
        httpd = ThreadingHTTPServer((BIND_HOST, porta), Handler)
    except OSError as exc:
        print(f"erro: porta {porta} indisponível ({exc}). Rode 'sessao' de novo.",
              file=sys.stderr)
        return 2
    httpd.daemon_threads = True

    registro = {
        "url": _url(porta, token), "url_local": _url(porta, token),
        "url_preferida": preview["url"], "preview": preview,
        "porta": porta, "token": token,
        "dir": str(raiz), "pid": os.getpid(), "iniciado_em": _agora_iso(),
        "versao": VERSAO, "altura_thumb": altura,
    }
    _escrever_json_atomico(dir_preview(raiz) / "servidor.json", registro)
    print(json.dumps(registro, ensure_ascii=False), flush=True)
    print(f"[preview] servindo {raiz} em {registro['url_preferida']} "
          f"(app={'sim' if (app / 'index.html').is_file() else 'diagnóstico embutido'})",
          file=sys.stderr, flush=True)
    if getattr(args, "abrir", False):
        print("[preview] %s" % abrir_no_browser(registro["url_preferida"]),
              file=sys.stderr, flush=True)

    def encerrar(_sig, _frm):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, encerrar)
    signal.signal(signal.SIGINT, encerrar)
    _ocioso_vigia(httpd, int(args.ocioso))
    try:
        httpd.serve_forever(poll_interval=0.2)
    finally:
        httpd.server_close()
        atual = _ler_json(dir_preview(raiz) / "servidor.json")
        if isinstance(atual, dict) and atual.get("pid") == os.getpid():
            try:
                (dir_preview(raiz) / "servidor.json").unlink()
            except OSError:
                pass
        print("[preview] encerrado.", file=sys.stderr, flush=True)
    return 0


def abrir_no_browser(url: str) -> str:
    """Abre a URL no browser padrão do SO. Devolve o que aconteceu, em prosa.

    🔴 ESTE É O CAMINHO AUTÔNOMO, e ele existe porque os outros dois podem não.
    Sem painel embutido (`preview_start`) e sem browser MCP, o que sobra é o
    creator abrir a URL na mão — e "copie este endereço e cole no navegador" é
    exatamente o passo em que uma sessão morre. Uma linha de `webbrowser.open`
    tira isso do caminho.

    Nunca é fatal: numa máquina sem ambiente gráfico (CI, servidor remoto) isto
    falha, e falhar aqui não pode derrubar um servidor que está no ar. O retorno
    é texto para o log, não exceção.
    """
    try:
        import webbrowser
        if webbrowser.open(url):
            return "aberto no browser padrão"
        return "browser padrão não respondeu — abra a URL à mão"
    except Exception as e:                                   # noqa: BLE001
        return "não consegui abrir o browser (%s) — abra a URL à mão" % type(e).__name__


def _apontar_launch(raiz: Path) -> str | None:
    """Reescreve o `--dir` do `.claude/launch.json` para a produção desta sessão.

    🔴 ACHADO A18. O painel do harness aponta para UMA produção, por um caminho
    escrito à mão dentro do `runtimeArgs`, e NADA o atualizava. Medido em
    2026-08-09: o arquivo apontava para uma produção antiga enquanto a sessão
    editava outra. Não deu erro — o painel simplesmente não chegou a ser aberto.
    Se tivesse sido, teria mostrado a produção errada com todos os QCs verdes.

    Quem sabe qual é a produção corrente é justamente quem abre a sessão. A
    escrita é conservadora: só troca o `--dir` de configurações cujo comando
    chama ESTE script, e só se o arquivo já existir. Ausência é silêncio — um
    cliente sem `.claude/launch.json` não é um erro (a régua de uma frase)."""
    raiz_repo = os.environ.get("BENCH_LAUNCH_JSON")
    arq = Path(raiz_repo) if raiz_repo else Path.cwd() / ".claude" / "launch.json"
    if not arq.is_file():
        return None
    dados = _ler_json(arq)
    if not isinstance(dados, dict) or not isinstance(dados.get("configurations"), list):
        return None
    # relativo só quando a produção está DENTRO da árvore que carrega o
    # launch.json; fora dela, `relpath` devolve uma escada de `..` que funciona
    # e não se lê. Caminho que sai da árvore vai absoluto.
    base = arq.parent.parent
    novo_dir = str(raiz)
    try:
        novo_dir = str(raiz.relative_to(base))
    except ValueError:
        pass
    mudou = False
    for cfg in dados["configurations"]:
        args_l = cfg.get("runtimeArgs")
        if not isinstance(args_l, list):
            continue
        for i, a in enumerate(args_l):
            if not isinstance(a, str) or "preview/servidor.py" not in a:
                continue
            trocado = re.sub(r"--dir\s+'[^']*'", "--dir '%s'" % novo_dir, a)
            if trocado != a:
                args_l[i] = trocado
                mudou = True
    if not mudou:
        return None
    _escrever_json_atomico(arq, dados)
    return str(arq)


def cmd_sessao(args) -> int:
    raiz = Path(args.dir).resolve()
    if not raiz.is_dir():
        print(f"erro: dir inexistente: {raiz}", file=sys.stderr)
        return 2
    # A sonda vem ANTES de `abrir_sessao`, que cria `.preview/` na primeira linha.
    remedio = sonda_de_escrita(raiz)
    if remedio:
        print("erro: não dá para abrir a sessão em %s\n       %s" % (raiz, remedio),
              file=sys.stderr)
        return 2
    dados = abrir_sessao(raiz, args.porta, args.altura_thumb)
    if dados.get("pid"):
        preview = dados.get("preview") or CLOUD_ADAPTER.resolver(
            dados.get("url_local") or dados["url"], str(dados["token"]),
            int(dados["porta"]), ambiente={})
    else:
        preview = contrato_preview(int(dados["porta"]), str(dados["token"]))
    # A configuracao de um processo vivo e imutavel. Para trocar de adaptador,
    # encerre a sessao e crie outra; assim URL e Host permitido nunca divergem.
    dados["preview"] = preview
    dados["url_local"] = dados.get("url_local") or dados["url"]
    dados["url_preferida"] = preview["url"]
    _escrever_json_atomico(dir_preview(raiz) / "servidor.json", dados)
    saida = {"url": preview["url"], "url_local": dados["url_local"],
             "preview": preview, "porta": dados["porta"],
             "token": dados["token"], "dir": dados["dir"],
             "pid": dados.get("pid")}
    alvo = _apontar_launch(raiz)
    if alvo:
        saida["launch"] = alvo
    if getattr(args, "abrir", False):
        saida["abertura"] = abrir_no_browser(preview["url"])
    print(json.dumps(saida, ensure_ascii=False), flush=True)
    return 0


def cmd_parar(args) -> int:
    raiz = Path(args.dir).resolve()
    arq = dir_preview(raiz) / "servidor.json"
    dados = _ler_json(arq) or {}
    pid = dados.get("pid")
    morto = False
    if _pid_vivo(pid):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
        for _ in range(50):
            if not _pid_vivo(pid):
                morto = True
                break
            time.sleep(0.1)
    try:
        arq.unlink()
    except OSError:
        pass
    print(json.dumps({"ok": True, "pid": pid, "encerrado": morto},
                     ensure_ascii=False), flush=True)
    return 0


def cmd_status(args) -> int:
    raiz = Path(args.dir).resolve()
    dados = _ler_json(dir_preview(raiz) / "servidor.json") or {}
    viva = sessao_viva(raiz) is not None
    if viva and dados.get("preview"):
        preview = dados["preview"]
    elif dados.get("porta") and dados.get("token"):
        preview = contrato_preview(int(dados["porta"]), str(dados["token"]))
    else:
        preview = dados.get("preview") or None
    base = _dir_cache(raiz)
    chaves, bytes_cache = [], 0
    if base.is_dir():
        for d in base.iterdir():
            if d.is_dir():
                chaves.append(d.name)
                for f in d.rglob("*"):
                    if f.is_file():
                        bytes_cache += f.stat().st_size
    pend = dir_preview(raiz) / "pendentes"
    apl = dir_preview(raiz) / "aplicados"
    print(json.dumps({
        "viva": viva,
        "url": (preview or {}).get("url") or dados.get("url"),
        "url_local": dados.get("url_local") or dados.get("url"),
        "preview": preview,
        "pid": dados.get("pid"),
        "dir": str(raiz),
        "cache": {"chaves": sorted(chaves), "bytes": bytes_cache},
        "pendentes": len(list(pend.glob("*.json"))) if pend.is_dir() else 0,
        "aplicados": len(list(apl.glob("*.json"))) if apl.is_dir() else 0,
    }, ensure_ascii=False), flush=True)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="servidor de preview da ilha de edição")
    sub = p.add_subparsers(dest="cmd", required=True)

    def comum(sp):
        sp.add_argument("--dir", required=True, help="diretório da produção")

    sp = sub.add_parser("sessao", help="escolhe porta e token; grava servidor.json")
    comum(sp)
    sp.add_argument("--abrir", action="store_true",
                    help="abre a URL no browser padrão do SO (caminho autônomo)")
    sp.add_argument("--porta", type=int, default=None)
    sp.add_argument("--altura-thumb", type=int, default=None, dest="altura_thumb")
    sp.set_defaults(func=cmd_sessao)

    sp = sub.add_parser("servir", help="sobe o servidor")
    comum(sp)
    sp.add_argument("--abrir", action="store_true",
                    help="abre a URL no browser padrão do SO (caminho autônomo)")
    sp.add_argument("--porta", type=int, default=None)
    sp.add_argument("--token", default=None)
    sp.add_argument("--app", default=None, help="dir da app (default: app/ ao lado)")
    sp.add_argument("--ocioso", type=int, default=OCIOSO_PADRAO_MIN,
                    help="minutos sem requisição até encerrar (0 desliga)")
    sp.add_argument("--altura-thumb", type=int, default=None, dest="altura_thumb")
    sp.set_defaults(func=cmd_servir)

    sp = sub.add_parser("parar", help="encerra a sessão viva")
    comum(sp)
    sp.set_defaults(func=cmd_parar)

    sp = sub.add_parser("status", help="diagnóstico em JSON")
    comum(sp)
    sp.set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
