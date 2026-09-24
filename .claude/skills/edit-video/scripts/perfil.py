#!/usr/bin/env python3
"""perfil.py — a ÚNICA porta de entrada do formato de peça (SPEC-00).

Um *perfil de peça* é um documento JSON que descreve o TIPO DE PEÇA — reels, vsl,
longform, screencast — e não o creator nem a produção. A regra de ouro que toda
spec futura herda:

    Nenhum script pode conter um valor de formato. Se um número descreve COMO A
    PEÇA É (dimensão, fps, sample rate, pad, alvo de loudness, zona de UI), ele
    vem do perfil. Se descreve FÍSICA (o RMS é medido em janelas de 10 ms; o piso
    de silêncio é percentil 15 num raio de 0,6 s), pode ficar no script.

BIBLIOTECA (o que os outros scripts importam)
    carregar(dir_producao)          -> dict     lê <dir>/perfil.json ou o FALLBACK
    spf(p)                          -> int      amostras de áudio por frame de vídeo
    vf_montagem(p, seg, sw, sh)     -> str      o filtro de vídeo de um segmento
    janela_base(W, H, sw, sh, aj)   -> (w, h)   a janela do bruto com o aspecto do alvo
    guarda_aspecto(...)             -> float    a distância de aspecto; avisa ou aborta
    zonas_ui(p)                     -> dict|None zonas proibidas em PIXELS
    video_sha(p)                    -> str      8 hex do que decide o render do segmento
    resolver_completo(...)          -> (caminho, perfil, origem)   ver abaixo

CLI
    perfil.py resolver <dir> --perfil <n> [--creator <n>] [--set k.k2=v]...
                             [--usuario <u>] [--estilo <u>/<slug>[@vNNN]]
    perfil.py mostrar  <dir>
    perfil.py validar  <arquivo.json>
    perfil.py patch    --arquivo <p.json> --bloco <chave> --de <fragmento.json>
    perfil.py sh       <dir>                     (KEY=VALUE para o montar.sh)
    perfil.py vf       <dir> --sw N --sh N [--seg '<json do segmento>']
                             [--zoom Z --cx X --cy Y] [--quieto]
                             [--permitir-aspecto-agressivo]

CADEIA DE MERGE (do mais genérico ao mais específico, merge profundo por chave)
    perfis/_base.json
      └─ perfis/<nome>.json
           └─ <creators>/<creator>/perfil-overrides.json     (opcional)
                └─ camadas de ESTILO (SPEC-24: estilo do usuário, UI, pedido)
                     └─ --set k.k2=v
                          → <dir-producao>/perfil.json  (snapshot, com _procedencia)

Cada camada registra, POR FOLHA, quem a escreveu (`resolver_completo` devolve o
mapa `origem`). Isso não é enfeite: é a única forma de responder "por que a
legenda saiu a 79% e não a 75,5%" sem refazer o merge de cabeça — e ele é
produzido PELO PRÓPRIO MERGE, nunca reconstruído depois por adivinhação.

O snapshot fica gravado COM a produção: remontar em outubro dá o mesmo resultado
mesmo que o catálogo tenha mudado. É a mesma lógica do sidecar de procedência que
o montar.sh já tinha, um nível acima.

⚠️ PRODUTO, NÃO INSTALAÇÃO. Este módulo conhece dois caminhos e mais nenhum:
`<dir-producao>` (que chega por argumento) e `perfis/` (relativo a este arquivo).
A camada de creator é resolvida por $BENCH_CREATORS_DIR, é OPCIONAL, e a ausência
dela é SILÊNCIO — um cliente do produto tem perfis e não tem `creators/`.
Zero dependência externa de propósito (nem `jsonschema`): o validador mínimo do
fim deste arquivo cobre o subconjunto de JSON Schema que `_schema.json` usa.
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time

CONTRATO = "benchmark.perfil-peca/v1"

# diretório do catálogo: SEMPRE relativo a este arquivo, nunca absoluto no fonte.
# realpath resolve o symlink .claude/skills/edit-video → ilha/skills/edit-video.
DIR_SCRIPT = os.path.dirname(os.path.realpath(__file__))
DIR_PERFIS = os.environ.get("BENCH_PERFIS_DIR") or \
    os.path.join(os.path.dirname(DIR_SCRIPT), "perfis")

# ---------------------------------------------------------------------------
# 🔒 FALLBACK_REELS — os valores DE HOJE DO CÓDIGO, não os do catálogo.
#
# Produção SEM `perfil.json` tem que se comportar exatamente como se comportava
# antes desta spec, byte a byte. Por isso este bloco é uma CÓPIA CONGELADA DO
# PRESENTE e diverge do perfil `reels` do catálogo em três pontos, todos de
# propósito:
#
#   1. pads 0.02/0.06  — é o default que estava em bordas.py:196 (o ritmo
#      `dinamico` da creator-2). A SKILL.md:44 documenta 0.12/0.20 como `normal`, e o
#      perfil `reels` adota o da DOC. Unificar os dois faz toda produção antiga
#      remontada mudar de ritmo EM SILÊNCIO.
#   2. cor: tags bt2020/arib-std-b67/bt2020nc aplicadas por `opcoes-de-saida` —
#      é literalmente o que montar.sh:129 fazia. Sabemos que 2 das 3 flags são
#      silenciosamente ignoradas neste build (qc-cor.py:24-30); o perfil novo
#      corrige isso com `setparams`, o FALLBACK NÃO, porque corrigir aqui muda
#      os bytes de toda remontagem antiga.
#   3. canais 1 e fade_modo por-segmento — audio-exato.py:64-67 e :39.
#
# NÃO "conserte" nada aqui. Consertar é o bug.
# ---------------------------------------------------------------------------
FALLBACK_REELS = {
    "contrato": CONTRATO,
    "nome": "reels-fallback",
    "descricao": "FALLBACK: o comportamento de hoje do código, congelado. "
                 "Não é o perfil `reels` do catálogo — ver comentário em perfil.py.",
    "video": {
        "aspecto": "9:16", "largura": 1080, "altura": 1920, "fps": 30,  # FALLBACK
        "pix_fmt": "yuv420p", "crf": 16, "preset_x264": "medium",
        "escala_flags": None, "unsharp": None,
    },
    "cor": {
        "entrada_esperada": "hlg", "lut": "hlg2sdr.cube",
        "tags_saida": {"color_primaries": "bt2020", "color_trc": "arib-std-b67",
                       "colorspace": "bt2020nc"},
        "aplicar_tags_por": "opcoes-de-saida",
        "grade": None,
    },
    "ritmo": {
        "pads": {"pre": 0.02, "post": 0.06},
        "cap": 0.25, "rel": 0.0, "floor": -52.0,
        "gap_min": 0.35, "fade_borda_s": 0.015, "fade_modo": "por-segmento",
        "gramatica_plano": "fixa", "zoom_alternado": [1.0, 1.27], "plano_max_s": 8.0,
    },
    "audio": {
        "sr": 48000, "canais": 1,   # FALLBACK
        "loudness": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
        "passes_loudnorm": 2, "codec": "aac", "bitrate": "192k",
    },
    "legenda": {
        "ativa": True, "queimada": True, "max_palavras_pagina": 3,
        "y_pct": 0.755, "fonte_palavras": "edl-bruto", "suprimir_por": "intersecao",
    },
    "zonas_ui": {"topo_pct": 0.1510, "fundo_pct": 0.7813, "direita_pct": 0.8556},
    # SPEC-20: sem bloco `trilha` no perfil, produção antiga se comporta byte a
    # byte como antes — nenhuma trilha entra em lugar nenhum. `ativa` é a única
    # chave aqui de propósito: o resto dos números vive no catálogo, e o
    # `trilha.py` RECUSA rodar com bloco incompleto em vez de inventar default.
    "trilha": {"ativa": False},
    "estrutura": None,
    "entregaveis": ["v-final.mp4", "v-final-sem-filtro.mp4"],
    "qc": {
        "obrigatorios": ["qc-cor", "qc-fonemas", "qc-emendas-asr", "av-sync",
                         "varredura-alpha"],
        "av_sync_ms": 3.0,
        "amostras_cor_pct": [0.02, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9],
    },
}

# fps válidos: 48000 % fps TEM que ser inteiro, senão a deriva de A/V volta.
FPS_VALIDOS = [24, 25, 30, 32, 40, 48, 50, 60, 75, 80, 96, 100, 120]

# As cadências NTSC, pela forma decimal com que aparecem em perfil escrito à mão.
# Elas existem aqui só para a MENSAGEM: nenhuma é aceita (ver `_msg_fps`).
NTSC_DECIMAL = {23.976: "24000/1001", 29.97: "30000/1001", 47.952: "48000/1001",
                59.94: "60000/1001", 119.88: "120000/1001"}

# só estes prefixos podem vir de um creator-override. O perfil manda no FORMATO;
# o creator manda no LOOK e no RITMO dentro daquele formato. `video.*` vindo do
# creator é erro de validação — a creator-2 não "tem" 9:16, ela tem um ritmo e um grade.
CREATOR_PODE = ("ritmo", "cor.grade", "legenda", "audio.loudness", "trilha")


class ErroPerfil(Exception):
    pass


# ------------------------------------------- escopo das camadas de estilo (SPEC-24)
def _no_escopo(caminho, escopo):
    """`escopo` = {"permite": [prefixos], "nega": [caminhos exatos ou prefixos]}."""
    if any(caminho == n or caminho.startswith(n + ".") for n in escopo.get("nega", ())):
        return False
    return any(caminho == a or caminho.startswith(a + ".")
               for a in escopo.get("permite", ()))


def _msg_fora_do_escopo(fora, rotulo, escopo):
    """🔴 A mensagem É o produto aqui. Um erro que diz só "path não permitido"
    manda o usuário adivinhar; este diz de quem o path é e qual é o comando."""
    linhas = []
    for c in sorted(set(fora)):
        dono = next((d for d in escopo.get("nega", ()) if c == d or c.startswith(d + ".")),
                    None)
        if dono is None:
            dono = next((d for d in escopo.get("exclusivo_do_perfil", ())
                         if c == d or c.startswith(d + ".")), None)
        linhas.append("  %s  → é do PERFIL DE PEÇA%s" % (c, " (%s)" % dono if dono else ""))
    exemplo = sorted(set(fora))[0]
    return (
        "camada `%s` tentou escrever %d caminho(s) fora de estilos/_escopo.json:\n%s\n"
        "Formato não se negocia por estilo: o perfil manda no FORMATO, o estilo manda no "
        "LOOK e no RITMO dentro dele.\n"
        "Se você quer mesmo esse valor nesta peça, é escolha de PERFIL:\n"
        "  perfil.py resolver <dir> --perfil <nome> --set %s=<valor>\n"
        "(fica gravado em perfil.json._procedencia.overrides, visível). "
        "Gravável por estilo: %s."
        % (rotulo, len(set(fora)), "\n".join(linhas), exemplo,
           ", ".join(escopo.get("permite", ())))
    )


def _modulo_estilo():
    """Importa o estilo.py que está AO LADO deste arquivo, sem depender de sys.path
    nem de o repo estar no PYTHONPATH. Devolve None se ele não existir (a SPEC-24
    pode não ter pousado numa instalação antiga) — e aí `--estilo` é erro de uso,
    não crash de import."""
    import importlib.util
    alvo = os.path.join(DIR_SCRIPT, "estilo.py")
    if not os.path.isfile(alvo):
        return None
    spec = importlib.util.spec_from_file_location("_estilo_spec24", alvo)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _camada_estilo(ref, dir_producao=None):
    """(rotulo, perfil_overrides, sha256, escopo) do estilo `<u>/<slug>[@vNNN]`,
    já com a herança de 1 nível aplicada e JÁ CONFERIDO contra o escopo."""
    mod = _modulo_estilo()
    if mod is None:
        raise ErroPerfil("--estilo pedido, mas estilo.py não existe em %s "
                         "(a biblioteca de estilos é a SPEC-24)" % DIR_SCRIPT)
    return mod.camada_para_perfil(ref)


# ------------------------------------------------------------------ utilidades
def _ler(caminho):
    with open(caminho, encoding="utf-8") as fh:
        return json.load(fh)


def _mesclar(base, novo):
    """merge profundo: dict funde chave a chave, o resto substitui."""
    out = dict(base)
    for k, v in novo.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _mesclar(out[k], v)
        else:
            out[k] = v
    return out


def _achatar(d, prefixo=""):
    """{'a': {'b': 1}} -> [('a.b', 1)]"""
    for k, v in d.items():
        p = f"{prefixo}.{k}" if prefixo else k
        if isinstance(v, dict) and v:
            yield from _achatar(v, p)
        else:
            yield p, v


def _mesclar_rotulado(base, novo, rotulo, origem, prefixo=""):
    """`_mesclar`, com uma diferença: TODA folha escrita registra quem a escreveu.

    🔴 O `origem` é produzido pelo merge, não reconstruído depois. Um mapa
    montado por adivinhação a posteriori é indistinguível de um mapa certo até o
    dia em que alguém precisa dele — que é exatamente o dia em que ele mente."""
    out = dict(base)
    for k, v in novo.items():
        p = f"{prefixo}.{k}" if prefixo else k
        if isinstance(v, dict) and isinstance(out.get(k), dict) and v:
            out[k] = _mesclar_rotulado(out[k], v, rotulo, origem, p)
        else:
            _esquecer(origem, p)      # o que estava em `p` deixou de existir
            out[k] = v
            for folha, _val in _achatar({k: v}, prefixo):
                origem[folha] = rotulo
    return out


def _esquecer(origem, prefixo):
    """Tira do mapa a folha `prefixo` e tudo abaixo dela. Chamado quando uma
    camada substitui um bloco inteiro (o caso do `"ritmo": "colado"`): folha que
    sumiu do perfil e continua no mapa é resposta errada com cara de resposta."""
    for f in [f for f in origem if f == prefixo or f.startswith(prefixo + ".")]:
        del origem[f]


def _sem_comentarios(d):
    """Tira, em QUALQUER profundidade, as chaves começando com `_`. Elas existem
    para o humano documentar a calibração ao lado do valor (o grade da creator-2 tem 5
    linhas de porquê) e não podem contar como caminho escrito pelo creator."""
    if not isinstance(d, dict):
        return d
    return {k: _sem_comentarios(v) for k, v in d.items() if not k.startswith("_")}


def _no(d, caminho):
    """acessa por caminho pontilhado; devolve (existe, valor)."""
    cur = d
    for parte in caminho.split("."):
        if not isinstance(cur, dict) or parte not in cur:
            return False, None
        cur = cur[parte]
    return True, cur


def _canonico(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha8(obj):
    return hashlib.sha256(_canonico(obj).encode("utf-8")).hexdigest()[:8]


def _sha256_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 16), b""):
            h.update(bloco)
    return h.hexdigest()


# ------------------------------------------------------------------- biblioteca
_AVISOU_FALLBACK = set()


def _normalizar_fps(p):
    """`"fps": 30.0` vira `30` — a MESMA cadência escrita com casa decimal.

    Feito no ponto de entrada (leitura do disco e fim do merge) para que
    `video_sha`, `spf` e o `_num` do `vf` vejam sempre a mesma forma. Sem isso o
    `.0` de digitação abortava a montagem inteira, e `30.0` não é fps
    fracionário — é 30."""
    try:
        f = fps_inteiro(p["video"]["fps"])
    except (KeyError, TypeError):
        return p
    if f is not None:
        p["video"]["fps"] = f
    return p


def _dica_de_fragmento(p, alvo):
    """A dica que faltava quando alguém COPIA `perfis/reels.json` para perfil.json.

    🔴 H48-9 / A-12b, medido em campo (2026-08-12): copiar `perfis/reels.json`
    para `<dir>/perfil.json` — o gesto óbvio, e o que qualquer pessoa tenta antes
    de ler a doc — devolvia `falta a chave obrigatória 'sr'` e nada mais. Os
    arquivos de `perfis/` são FRAGMENTOS: eles só viram perfil depois de mesclados
    sobre `_base.json`, e nada dizia isso.

    O sinal de que é fragmento e não perfil quebrado: faltam blocos INTEIROS que o
    `_base.json` fornece, e existe um arquivo com o mesmo nome em `perfis/`."""
    tem = set(p) if isinstance(p, dict) else set()
    base_arq = os.path.join(DIR_PERFIS, "_base.json")
    if not os.path.isfile(base_arq):
        return ""
    do_base = set(_ler(base_arq)) - {"_comentario"}
    faltando = sorted(b for b in do_base if b not in tem)
    nome = p.get("nome") if isinstance(p, dict) else None
    irmao = os.path.isfile(os.path.join(DIR_PERFIS, "%s.json" % nome)) if nome else False
    if len(faltando) < 2 and not irmao:
        return ""
    return (
        "\n\n⚠️ Isto parece um FRAGMENTO de `perfis/`, não um perfil resolvido: "
        "faltam %d bloco(s) que o `_base.json` fornece (%s).\n"
        "Os arquivos de `perfis/` NÃO são perfis — são camadas. Copiar um deles "
        "para `perfil.json` sempre falha assim.\n"
        "O caminho é resolver:\n"
        "  python3 perfil.py resolver %s --perfil %s\n"
        "(e `--set chave.chave=valor` para os ajustes pontuais desta peça)."
        % (len(faltando), ", ".join(faltando[:6]),
           os.path.dirname(alvo) or ".", nome or "<nome>"))


def carregar(dir_producao, quieto=False):
    """Lê <dir>/perfil.json. Sem ele, devolve o FALLBACK (o comportamento de hoje)
    e avisa UMA vez no stderr. Valida contra o schema; erro é fatal."""
    alvo = os.path.join(dir_producao, "perfil.json") if os.path.isdir(dir_producao) \
        else str(dir_producao)
    if os.path.isfile(alvo) and alvo.endswith(".json"):
        p = _ler(alvo)
        _normalizar_fps(p)
        erros = validar(p)
        if erros:
            sys.exit("perfil.json inválido em %s:\n  %s%s"
                     % (alvo, "\n  ".join(erros), _dica_de_fragmento(p, alvo)))
        return p
    chave = os.path.abspath(dir_producao)
    if not quieto and chave not in _AVISOU_FALLBACK:
        _AVISOU_FALLBACK.add(chave)
        print("aviso: sem perfil.json — usando o FALLBACK (vertical a 30 fps, pads "
              "0.02/0.06, mono, tags HLG: o comportamento de antes da SPEC-00). "
              "`perfil.py resolver <dir> --perfil <n>` fixa um perfil.", file=sys.stderr)
    return json.loads(json.dumps(FALLBACK_REELS))   # cópia, ninguém muta o global


def fps_inteiro(fps):
    """A cadência como INTEIRO, ou None se ela não for uma cadência inteira.

    `30` e `30.0` são a MESMA cadência e as duas passam — um perfil escrito à
    mão com `"fps": 30.0` era rejeitado por `isinstance(fps, int)` mesmo sendo
    exatamente 30, e "decimal inteiro é erro" não é regra nenhuma: o que produz
    deriva é decimal com FRAÇÃO (29,97), não o `.0` de digitação.
    `bool` é `int` em Python e não é cadência: fica de fora explicitamente."""
    if isinstance(fps, bool):
        return None
    if isinstance(fps, int):
        return fps
    if isinstance(fps, float) and fps.is_integer():
        return int(fps)
    return None


def spf(p):
    """Amostras de áudio por frame de vídeo. Erro se sr % fps != 0.

    🔴 O invariante `soma_audio == soma_video` sobrevive à parametrização SÓ se
    esta divisão for exata. Arredondar/interpolar para "suportar 29,97" é o bug
    de deriva progressiva de 2026-07-25 voltando pela porta nova."""
    sr = int(p["audio"]["sr"])
    fps = fps_inteiro(p["video"]["fps"])
    if fps is None or sr % fps != 0:
        raise ErroPerfil(_msg_fps(p["video"]["fps"], sr))
    return sr // fps


def _ntsc(fps):
    """A fração exata que `fps` arredonda, quando ele é um decimal NTSC."""
    try:
        x = float(fps)
    except (TypeError, ValueError):
        return None
    for dec, frac in NTSC_DECIMAL.items():
        if abs(x - dec) < 0.005:
            return frac
    return None


def _msg_fps(fps, sr):
    validos = [f for f in FPS_VALIDOS if sr % f == 0]
    try:
        x = float(fps)
    except (TypeError, ValueError):
        x = 0.0
    abaixo = max([f for f in validos if f <= x], default=validos[0])
    acima = min([f for f in validos if f >= x], default=validos[-1])
    # 🔴 A parte que a mensagem PRECISA dizer quando o valor é NTSC: qual é a
    # fração que aquele decimal arredonda, e por que nem a fração serve aqui.
    # Sem isso o operador troca 29.97 por 29.98 e recebe o mesmo "REJEITADO"
    # sem entender que o problema não é a casa decimal — é a cadência.
    extra = ""
    frac = _ntsc(fps)
    if frac is not None:
        num, den = frac.split("/")
        spf_medio = sr * int(den) / int(num)
        extra = (" %s é a forma decimal ARREDONDADA de %s (%.6f). Decimal "
                 "arredondado é onde nasce deriva — mas a fração exata TAMBÉM é "
                 "recusada aqui: %d/(%s) = %.1f amostras por frame, e arredondar "
                 "isso por segmento acumula ao longo da peça (é o bug de "
                 "2026-07-25). Não existe cadência NTSC nesta ilha, por decisão "
                 "de projeto: rejeitar, nunca aproximar."
                 % (fps, frac, int(num) / int(den), sr, frac, spf_medio))
    elif fps_inteiro(fps) is None:
        extra = (" %s não é uma cadência inteira, e cadência fracionária não tem "
                 "spf exato." % fps)
    return ("fps %s REJEITADO: %d %% %s não é inteiro, e aproximar reintroduz a "
            "deriva progressiva de A/V (a regra é rejeitar o fps, nunca aproximar)."
            "%s"
            " Vizinhos suportados: %d (abaixo) e %d (acima). "
            "Válidos: %s." % (fps, sr, fps, extra, abaixo, acima,
                              ", ".join(str(f) for f in validos)))


msg_fps = _msg_fps          # nome público: audio-exato.py usa a mesma mensagem


# ─────────── formato de saída: a janela de aspecto que mata a anamorfose (SPEC-06)
#
# 🔴 O DEFEITO QUE ISTO FECHA, remedido em 2026-08-09 sobre o código da onda 4:
#     fonte 1280×720 no perfil `reels` → `scale=1080:1920` → o ffmpeg não deforma
#     o CONTEÚDO, ele compensa no SAR. O arquivo sai com 1080×1920 pixels e
#     `sample_aspect_ratio=256:81`, `display_aspect_ratio=16:9`. Todo o resto da
#     ilha assume pixel quadrado num quadro 1080×1920 (Root.tsx, split-broll.py,
#     as zonas de UI) e NENHUM QC deste repo mede SAR: verde em tudo, imagem
#     espremida. População medida hoje: 3 das 8 produções com `input/` no disco
#     têm fonte 16:9 e nenhuma delas tem `perfil.json`.
#
# A correção é de CONSTRUÇÃO, não de checagem: a janela do bruto passa a ter o
# aspecto do ALVO antes de qualquer escala, e `setsar=1` fecha a porta mesmo
# quando o arredondamento para pixel par deixa a janela 1 px fora do aspecto.
#
# ⚠️ `setsar=1` é byte-neutro no caminho canônico — medido: os md5 de
# `scale=1080:1920,fps=30` e de `scale=1080:1920,fps=30,setsar=1` sobre uma fonte
# 2160×3840 são IGUAIS (686358c8…). Ele só muda alguma coisa exatamente onde
# havia anamorfose para desfazer.
ASPECTO_SILENCIO = 1.15      # 9:16 → 9:16 e vizinhança: nada a dizer
ASPECTO_AVISO = 1.40         # dá para julgar olhando o % descartado
ASPECTO_LIMITE = 2.00        # acima disto o crop central é quase sempre errado
COR_PAD_FALLBACK = "black"   # `video.cor_pad` manda; isto é o default do default


def _par_piso(x, teto=None):
    """Maior inteiro PAR ≤ x (e ≤ teto). yuv420p exige dimensão par.

    ⚠️ É O ARREDONDAMENTO DO ZOOM, e ele é PISO por retrocompatibilidade, não
    por correção: `int(sw/z)//2*2` é literalmente a conta que o montar.sh fazia
    antes da SPEC-00, e trocá-la por "par mais próximo" mudaria o crop de
    produção existente (medido: 3840/1,27 dá 3022 no piso e 3024 no próximo — e
    3024 muda os bytes de toda remontagem com zoom 1,27, que é o default do
    `zoom_alternado`). Para a JANELA DE ASPECTO, que é código novo e sem
    passado, vale `_par_prox`, que erra no máximo 1 px."""
    n = int(x) // 2 * 2
    if teto is not None:
        n = min(n, int(teto) // 2 * 2)
    return max(2, n)


def _par_prox(x, teto=None):
    """Inteiro PAR mais próximo de x (meio para cima), limitado por `teto`.

    O piso erra até 1,999 px; este erra no máximo 1,0. Num alvo 16:9 a partir de
    9:16 a altura ideal é 1215 (ímpar) — o piso daria 1214 e este dá 1216, e é a
    diferença entre a janela ficar 1,78 px fora do aspecto e ficar 1,0."""
    n = int(math.floor(x / 2.0 + 0.5)) * 2
    if teto is not None:
        n = min(n, int(teto) // 2 * 2)
    return max(2, n)


def razao_aspecto(W, H, sw, sh):
    """Quantas vezes o aspecto da fonte está longe do aspecto do alvo (≥ 1,0)."""
    return max((W / H) / (sw / sh), (sw / sh) / (W / H))


def janela_base(W, H, sw, sh, ajuste="crop"):
    """A janela do BRUTO que já tem o aspecto do ALVO, antes do zoom.

    🔴 O produto cruzado é INTEIRO de propósito: `sw*H == sh*W` decide "mesmo
    aspecto" sem passar por float. Comparar `sw/sh` com `W/H` faria o caminho
    canônico 2160×3840 → 1080×1920 depender de arredondamento, e qualquer desvio
    ali insere um `crop=` onde hoje não há — mudando os bytes de toda produção
    existente ao remontar, que é exatamente o que esta spec não pode fazer."""
    if ajuste == "pad" or sw <= 0 or sh <= 0:
        return sw, sh
    if sw * H == sh * W:
        return sw, sh                        # mesmo aspecto: janela = quadro inteiro
    if sw * H > sh * W:                      # fonte mais LARGA → corta lateral
        return _par_prox(sh * W / H, teto=sw), sh
    return sw, _par_prox(sw * H / W, teto=sh)     # fonte mais ALTA → corta topo/base


def guarda_aspecto(W, H, sw, sh, ajuste="crop", seg=None, permitir=False):
    """A distância de aspecto vira aviso ou abort — nunca recorte silencioso.

    🔴 Lição literal do `edit-video/SKILL.md`: *clamp sem guarda transforma
    medição-lixo em recorte válido, em silêncio*. Os `min()/max()` do cálculo de
    `x`/`y` sempre devolvem uma janela LEGAL; o que eles não sabem dizer é que
    uma tira de 33% da largura de um vídeo vertical não é o enquadramento que
    alguém quis. Devolve a razão medida (None quando não houve sondagem)."""
    seg = seg or {}
    if sw <= 0 or sh <= 0:
        return None
    r = razao_aspecto(W, H, sw, sh)
    if r <= ASPECTO_SILENCIO:
        return r                             # o caso normal: silêncio total
    bw, bh = janela_base(W, H, sw, sh, ajuste)
    perdido = 100.0 * (1.0 - (bw * bh) / float(sw * sh))
    livres = [k for k in ("cx", "cy") if k not in seg]
    if ajuste == "pad":
        # com `pad` não se perde quadro nenhum — o custo é barra, não recorte.
        # Reportar "0% descartado" aqui seria verdade inútil; o que o operador
        # precisa saber é quanta tela vira barra preta.
        print("aviso: aspecto da fonte (%d×%d) × alvo (%d×%d): r = %.2f, e o "
              "perfil pede `pad` — o quadro entra INTEIRO e %.0f%% da tela vira "
              "barra." % (sw, sh, W, H, r, 100.0 * (1.0 - 1.0 / r)),
              file=sys.stderr)
        return r
    if r > ASPECTO_LIMITE and ajuste == "crop" and not permitir:
        raise ErroPerfil(
            "ASPECTO INCOMPATÍVEL: a fonte é %d×%d e o alvo é %d×%d — distância "
            "de aspecto r = %.2f (limite %.2f).\n"
            "Com `ajuste: \"crop\"` o recorte central seria %d×%d, ou seja %.0f%% "
            "do quadro DESCARTADO, e quase nunca é o enquadramento que alguém "
            "quis — é a tira do meio.\n"
            "As três saídas reais:\n"
            "  1. `\"ajuste\": \"pad\"` no perfil (cabe o quadro inteiro, com barras);\n"
            "  2. reenquadrar segmento a segmento com `cx`/`cy` explícitos na EDL "
            "e rodar com `--permitir-aspecto-agressivo`;\n"
            "  3. usar um perfil do aspecto da fonte (`perfil.py mostrar --perfil "
            "<nome>` lista o catálogo)."
            % (sw, sh, W, H, r, ASPECTO_LIMITE, bw, bh, perdido))
    if r <= ASPECTO_AVISO:
        print("aviso: aspecto da fonte (%d×%d) × alvo (%d×%d): r = %.2f — o crop "
              "de aspecto descarta %.0f%% do quadro."
              % (sw, sh, W, H, r, perdido), file=sys.stderr)
    else:
        print("AVISO ALTO: aspecto da fonte (%d×%d) × alvo (%d×%d): r = %.2f — o "
              "crop de aspecto descarta %.0f%% do quadro%s.\n"
              "  Num alvo bem mais estreito que a fonte, o centro geométrico cai "
              "no torso e decepa a cabeça: confira o enquadramento antes de "
              "aprovar."
              % (sw, sh, W, H, r, perdido,
                 " e este segmento está no default (%s ausente na EDL)"
                 % "/".join(livres) if livres else ""), file=sys.stderr)
    return r


def _conferir_sar_fonte(sar):
    """Avisa quando o bruto NÃO tem pixel quadrado.

    ⚠️ LIMITE CONHECIDO, declarado em vez de escondido: `janela_base` raciocina
    em ASPECTO DE PIXEL (`sw`×`sh`), não em aspecto de EXIBIÇÃO. Numa fonte
    anamórfica — 1440×1080 com SAR 4:3, que exibe 16:9 — o produto cruzado diria
    "fonte mais alta que o alvo" e cortaria topo e base de um quadro que já
    estava no aspecto certo: recorte plausível e errado, que é exatamente a
    classe de defeito que a guarda de aspecto existe para não deixar passar em
    silêncio. Medido em 2026-08-09: das 11 fontes em `input/` de produção deste
    repo, 11 têm SAR `1:1` ou ausente. Por isso aqui é AVISO e não abort — nunca
    vimos uma, e abortar em material que ninguém testou é pior que avisar."""
    if not sar:
        return
    s = str(sar).strip().rstrip(",")
    if s in ("", "N/A", "0:1", "1:1"):
        return
    print("AVISO: a fonte declara sample_aspect_ratio=%s (pixel NÃO quadrado). A "
          "janela de aspecto é calculada em pixels, então o recorte pode sair "
          "errado nesta fonte — confira o enquadramento antes de aprovar." % s,
          file=sys.stderr)


def vf_montagem(p, seg, sw, sh, permitir_aspecto_agressivo=False, sar=None):
    """A string de filtro de vídeo de UM segmento. Substitui montar.sh:112-124.

    Ordem: crop (aspecto do alvo ∩ zoom, UM só) → scale → unsharp (só quando há
    ampliação real) → setsar=1 → fps → setparams (se o perfil pedir tags por
    filtro).

    🔴 UM CROP SÓ, nunca dois. A janela de aspecto e o zoom se combinam numa
    única expressão `crop=`. Dois crops encadeados dobram o erro de
    arredondamento e reabrem a "transformação dupla" que já custou um ciclo de
    remontagem — é a mesma razão pela qual o punch-in é feito nos pixels do
    bruto, e nunca reescalando um 1080 já pronto.

    O unsharp é CONDICIONAL de propósito: ele compensa upscale
    (docs/EDICAO-CAPACIDADES.md:185-188); aplicado quando a janela já é maior que
    a saída, injeta halo."""
    v = p["video"]
    W, H = int(v["largura"]), int(v["altura"])
    ajuste = (v.get("ajuste") or "crop")
    if ajuste not in ("crop", "pad"):
        raise ErroPerfil("video.ajuste = %r: só `crop` (corta o bruto, default) "
                         "ou `pad` (cabe inteiro, com barras)." % ajuste)
    z = float(seg.get("zoom", 1) or 1)
    sw, sh = int(sw or 0), int(sh or 0)
    if sw <= 0 or sh <= 0:
        if z > 1.0001 or ajuste == "pad":
            raise ErroPerfil(
                "sem as dimensões da fonte (--sw/--sh) não dá para calcular a "
                "janela: zoom=%g, ajuste=%s. Quem chama tem que sondar o bruto."
                % (z, ajuste))
        # sem sondagem: só o caminho legado sem crop. Continua saindo `setsar=1`,
        # que é a linha que fecha a anamorfose mesmo sem saber o aspecto da fonte.
        print("aviso: `vf` pedido sem as dimensões da fonte — a guarda de "
              "aspecto NÃO rodou neste segmento.", file=sys.stderr)
    _conferir_sar_fonte(sar)
    guarda_aspecto(W, H, sw, sh, ajuste, seg, permitir=permitir_aspecto_agressivo)

    partes = []
    larg_janela = None
    if sw > 0 and sh > 0:
        bw, bh = janela_base(W, H, sw, sh, ajuste)
        if z > 1.0001:
            cw, ch = _par_piso(bw / z, teto=bw), _par_piso(bh / z, teto=bh)
        else:
            cw, ch = bw, bh
        larg_janela = cw
        if (cw, ch) != (sw, sh):
            cx, cy = float(seg.get("cx", 0.5)), float(seg.get("cy", 0.5))
            x = max(0, min(sw - cw, round(sw * cx - cw / 2)))
            y = max(0, min(sh - ch, round(sh * cy - ch / 2)))
            partes.append(f"crop={cw}:{ch}:{x}:{y}")
    flags = v.get("escala_flags")
    sufixo = f":flags={flags}" if flags else ""
    # a largura que a janela vai OCUPAR na saída. Em `crop` é o quadro inteiro;
    # em `pad` é o retângulo que o `force_original_aspect_ratio=decrease` deixa,
    # e é ele que decide se houve ampliação (o unsharp existe só para isso).
    larg_destino = W
    if ajuste == "pad":
        partes.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease{sufixo}")
        partes.append(f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:"
                      f"color={v.get('cor_pad') or COR_PAD_FALLBACK}")
        if sw > 0 and sh > 0:
            larg_destino = min(W, int(round(H * sw / sh)))
    else:
        partes.append(f"scale={W}:{H}{sufixo}")
    if v.get("unsharp") and (larg_janela is None or larg_janela < larg_destino):
        partes.append(v["unsharp"])
    partes.append("setsar=1")
    partes.append("fps=%s" % _num(v["fps"]))
    tags = _setparams(p)
    if tags:
        partes.append(tags)
    return ",".join(partes)


def _setparams(p):
    cor = p.get("cor") or {}
    if cor.get("aplicar_tags_por") != "setparams":
        return ""
    t = cor.get("tags_saida") or {}
    itens = [f"{k}={t[k]}" for k in ("color_primaries", "color_trc", "colorspace")
             if t.get(k)]
    return ("setparams=" + ":".join(itens)) if itens else ""


def opcoes_cor_saida(p):
    """As flags `-color_*` de SAÍDA. Lista VAZIA salvo no modo legado.

    🔴 Medido em qc-cor.py:24-30: neste build `-color_primaries` e `-color_trc`
    de saída são SILENCIOSAMENTE ignoradas (só `-colorspace` pega). Perfil novo
    usa `setparams`. Isto aqui existe só para o FALLBACK reproduzir o passado."""
    cor = p.get("cor") or {}
    if cor.get("aplicar_tags_por") != "opcoes-de-saida":
        return []
    t = cor.get("tags_saida") or {}
    out = []
    for flag, chave in (("-color_primaries", "color_primaries"),
                        ("-color_trc", "color_trc"),
                        ("-colorspace", "colorspace")):
        if t.get(chave):
            out += [flag, t[chave]]
    return out


def zonas_ui(p):
    """Zonas proibidas em PIXELS, derivadas das frações do perfil e da resolução.
    None quando a peça não toca em feed nenhum (player web, YouTube)."""
    z = p.get("zonas_ui")
    if not z:
        return None
    W, H = int(p["video"]["largura"]), int(p["video"]["altura"])
    return {"top": int(round(z["topo_pct"] * H)),
            "bottom": int(round(z["fundo_pct"] * H)),
            "right": int(round(z["direita_pct"] * W))}


def raster_de_medicao(p, altura=171):
    """Raster minúsculo para MEDIR diferença de frame (detecção de corte).

    A ALTURA é física — 171 px é o que basta para a média de |Δ| entre frames ser
    estável, e vale para qualquer peça. A LARGURA é formato: sai do aspecto do
    perfil. Em 9:16 devolve 96×171, que é exatamente o par histórico de
    cortes-do-bruto.py:36 e qc-fonemas.py:175; em 16:9 devolve 304×171.
    Os dois scripts têm que usar a MESMA função, senão os cortes que um acha não
    casam com os do outro — que é o teste do critério 6 da SPEC-00."""
    W, H = int(p["video"]["largura"]), int(p["video"]["altura"])
    larg = max(2, int(round(altura * W / H)) // 2 * 2)
    return larg, altura


def escala_amostragem(p, divisor=4):
    """Raster de amostragem de luminância (flicker-scan): a resolução da peça
    dividida por `divisor`, arredondada para par."""
    # procedência: em vertical Full HD isto devolve o par histórico de
    # flicker-scan.py:16 (a resolução da peça sobre 4), agora derivado.
    W, H = int(p["video"]["largura"]), int(p["video"]["altura"])
    return max(2, W // divisor // 2 * 2), max(2, H // divisor // 2 * 2)


def video_sha(p):
    """8 hex de TUDO que decide como um segmento é renderizado.

    🔴 POR QUE ISTO EXISTE (o risco mais alto da SPEC-00). O sidecar de
    procedência do montar.sh comparava só `src,start,end,zoom,cx,cy`. Agora que o
    perfil influencia o `vf` (fps, escala, unsharp, tags de cor) e o encode
    (crf, preset, pix_fmt), trocar de perfil REUSARIA segmento renderizado no
    formato anterior — o bug do segmento órfão (6,25 s de vídeo errado com TODOS
    os QCs verdes) com porta de entrada nova.

    Cobre mais que o bloco `video` de propósito: as tags de cor e o modo de
    aplicá-las também mudam os bytes do segmento. Errar para MAIS invalidação
    custa tempo de render; errar para menos entrega vídeo errado."""
    cor = p.get("cor") or {}
    return _sha8({
        "video": p.get("video"),
        "tags_saida": cor.get("tags_saida"),
        "aplicar_tags_por": cor.get("aplicar_tags_por"),
    })


def _num(x):
    """Inteiro em float vira inteiro na string. O filtro aceita a forma com
    casa decimal, mas ela muda a string do vf e, com ela, o md5 da regressão."""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


# ------------------------------------------------------ camada de creator (opcional)
def dir_creators(dir_producao=None):
    """$BENCH_CREATORS_DIR → ./creators → sobe a partir de <dir-producao>.
    Devolve None se não achar. AUSÊNCIA É SILÊNCIO: um cliente do produto não tem
    `creators/`, e um aviso na máquina dele é vazamento de arquitetura."""
    env = os.environ.get("BENCH_CREATORS_DIR")
    if env:
        return env if os.path.isdir(env) else None
    if os.path.isdir("creators"):
        return "creators"
    if dir_producao:
        d = os.path.abspath(dir_producao)
        while True:
            cand = os.path.join(d, "creators")
            if os.path.isdir(cand):
                return cand
            pai = os.path.dirname(d)
            if pai == d:
                break
            d = pai
    return None


def _override_de_creator(creator, dir_producao):
    base = dir_creators(dir_producao)
    if not base:
        return None, None          # produto sem instância: silêncio total
    caminho = os.path.join(base, creator, "perfil-overrides.json")
    if not os.path.isfile(caminho):
        # o diretório existe mas ESTE creator não: aqui um aviso é útil (typo),
        # e não vaza arquitetura nenhuma, porque só roda em quem tem creators/.
        print("aviso: --creator %s pedido, mas %s não existe — seguindo sem override"
              % (creator, caminho), file=sys.stderr)
        return None, None
    return _ler(caminho), caminho


def ritmos_nomeados():
    """O catálogo de ritmos nomeados (perfis/_ritmos.json). {} se não existir."""
    cat = os.path.join(DIR_PERFIS, "_ritmos.json")
    return _ler(cat) if os.path.isfile(cat) else {}


def _aplicar_ritmo_nomeado(p, origem=None, rotulo=None):
    """`"ritmo": "colado"` vira o dict de perfis/_ritmos.json mesclado no ritmo."""
    r = p.get("ritmo")
    if not isinstance(r, str):
        return p
    ritmos = ritmos_nomeados()
    if r not in ritmos:
        raise ErroPerfil("ritmo nomeado %r não existe em %s/_ritmos.json (tem: %s)"
                         % (r, DIR_PERFIS, ", ".join(k for k in ritmos if not k.startswith("_"))))
    p = dict(p)
    p["ritmo"] = _mesclar(FALLBACK_REELS["ritmo"], ritmos[r])
    if origem is not None:
        _esquecer(origem, "ritmo")
        for folha, _v in _achatar({"ritmo": p["ritmo"]}):
            origem[folha] = rotulo or "ritmo-nomeado:%s" % r
    return p


# ------------------------------------------------------------------- resolver
def resolver(dir_producao, nome, creator=None, sets=None, quieto=False, **kw):
    """Compatível byte a byte com o de antes da SPEC-24 quando não recebe camada
    nenhuma. Quem precisa do perfil resolvido e do mapa de origem chama
    `resolver_completo`."""
    return resolver_completo(dir_producao, nome, creator, sets, quieto, **kw)[0]


def resolver_completo(dir_producao, nome, creator=None, sets=None, quieto=False,
                      usuario=None, estilo=None, estilo_sha256=None, camadas=None,
                      escopo_camadas=None, escrever=True):
    """(caminho, perfil, origem).

    `escrever=False` resolve em memória e devolve `(None, perfil, origem)` — usado
    para calcular a linha de base "o que o ESTILO daria, sem as camadas pontuais",
    que é o que define uma correção. Sem essa forma, calcular a base exigiria
    resolver num diretório temporário só para jogar fora.

    `camadas` é a lista ORDENADA de camadas entre o creator e o `--set`, cada uma
    `(rotulo, dict)` — é por onde a SPEC-24 injeta o estilo do usuário, a escolha
    pontual da UI e o pedido compilado. Cada camada é conferida contra
    `escopo_camadas` (a allowlist de prefixos de `estilos/_escopo.json`) ANTES de
    mergear: formato não se negocia por estilo."""
    sets = sets or []
    camadas = list(camadas or [])
    origem = {}
    base_arq = os.path.join(DIR_PERFIS, "_base.json")
    perfil_arq = os.path.join(DIR_PERFIS, nome + ".json")
    if not os.path.isfile(perfil_arq):
        disponiveis = sorted(f[:-5] for f in os.listdir(DIR_PERFIS)
                             if f.endswith(".json") and not f.startswith("_"))
        raise ErroPerfil("perfil %r não existe em %s (tem: %s)"
                         % (nome, DIR_PERFIS, ", ".join(disponiveis)))

    shas = {}
    p = {}
    for arq in (base_arq, perfil_arq):
        if os.path.isfile(arq):
            camada = _ler(arq)
            camada.pop("_comentario", None)
            p = _mesclar_rotulado(p, camada, "perfil:%s" % nome, origem)
            shas[os.path.relpath(arq, os.path.dirname(DIR_PERFIS))] = _sha256_arquivo(arq)
    p = _aplicar_ritmo_nomeado(p, origem, "perfil:%s" % nome)

    # ---- camada de creator, OPCIONAL e restrita
    if creator:
        ov, caminho = _override_de_creator(creator, dir_producao)
        if ov:
            ov = _sem_comentarios(ov)
            proibidos = [c for c, _ in _achatar(ov)
                         if not any(c == a or c.startswith(a + ".") for a in CREATOR_PODE)]
            if proibidos:
                raise ErroPerfil(
                    "creator-override não pode escrever em: %s.\n"
                    "O perfil manda no FORMATO; o creator manda no look e no ritmo dentro "
                    "dele. Permitido: %s. (Formato de peça vira `--set` ou perfil novo.)"
                    % (", ".join(sorted(proibidos)), ", ".join(CREATOR_PODE)))
            rot = "creator:%s" % creator
            p = _mesclar_rotulado(p, ov, rot, origem)
            p = _aplicar_ritmo_nomeado(p, origem, rot)
            shas[caminho] = _sha256_arquivo(caminho)

    # ---- camadas 3/4/5 (SPEC-24): estilo do usuário, UI, pedido compilado
    for rotulo, ov in camadas:
        ov = _sem_comentarios(ov or {})
        if not ov:
            continue
        if escopo_camadas is not None:
            fora = [c for c, _ in _achatar(ov) if not _no_escopo(c, escopo_camadas)]
            if fora:
                raise ErroPerfil(_msg_fora_do_escopo(fora, rotulo, escopo_camadas))
        p = _mesclar_rotulado(p, ov, rotulo, origem)
        p = _aplicar_ritmo_nomeado(p, origem, rotulo)

    # ---- overrides pontuais desta produção
    for s in sets:
        if "=" not in s:
            raise ErroPerfil("--set espera chave.chave=valor, recebi %r" % s)
        k, _, v = s.partition("=")
        try:
            val = json.loads(v)
        except json.JSONDecodeError:
            val = v
        d = {}
        cur = d
        partes = k.strip().split(".")
        for parte in partes[:-1]:
            cur[parte] = {}
            cur = cur[parte]
        cur[partes[-1]] = val
        p = _mesclar_rotulado(p, d, "set:%s" % k.strip(), origem)
        # 🔴 EXPANDE O RITMO NOMEADO A CADA `--set`, não só no fim (2026-08-12,
        # H48-8/A-12). Medido em campo:
        #     --perfil reels --set ritmo=dinamico --set ritmo.gramatica_plano=alternada
        #     → "ritmo: falta a chave obrigatória 'pads'"
        # A mecânica: o primeiro `--set` põe a STRING "dinamico" em `ritmo`; o
        # segundo mergeia `{"ritmo": {"gramatica_plano": …}}` em cima de uma
        # string, e o merge substitui — sobra um `ritmo` com UMA chave. A expansão
        # rodava depois do laço, quando `ritmo` já não era mais string, então ela
        # não fazia nada e o `pads` do ritmo nomeado nunca chegava.
        # O `_ritmos.json` DOCUMENTA a composição como suportada; agora ela é.
        # As camadas 3/4/5 já expandiam a cada camada — este laço era a exceção.
        p = _aplicar_ritmo_nomeado(p, origem, "set:%s" % k.strip())
    p = _aplicar_ritmo_nomeado(p, origem, "set:ritmo")

    p["nome"] = nome
    p["contrato"] = CONTRATO
    origem["nome"] = origem["contrato"] = "perfil:%s" % nome

    # ---- fps: rejeitar NTSC fracionário AQUI, não depois de 40 min de render
    fps_bruto = p["video"]["fps"]
    _normalizar_fps(p)                       # 30.0 é 30; 29.97 continua 29.97
    fps = fps_inteiro(fps_bruto)
    if fps is None or int(p["audio"]["sr"]) % fps != 0:
        raise ErroPerfil(_msg_fps(fps_bruto, int(p["audio"]["sr"])))

    # ---- procedência: o QC precisa poder provar o que foi usado
    p["_procedencia"] = {
        "resolvido_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "perfil": nome,
        "creator": creator,
        "sha256": shas,
        "overrides": list(sets),
    }
    # ⚠️ ADITIVO e SÓ quando há estilo: `perfil.json` sem estes campos continua
    # válido e significa "resolvido sem estilo". Escrevê-los sempre (com `null`)
    # mudaria os bytes de toda produção que não usa estilo — e o aceite §7.9
    # desta spec é exatamente um md5 dizendo que isso não pode acontecer.
    if usuario or estilo or camadas:
        if usuario:
            p["_procedencia"]["usuario"] = usuario
        if estilo:
            p["_procedencia"]["estilo"] = estilo
            if estilo_sha256:
                p["_procedencia"]["estilo_sha256"] = estilo_sha256
        p["_procedencia"]["camadas"] = ["perfil:%s" % nome] + \
            (["creator:%s" % creator] if creator else []) + \
            [r for r, _ov in camadas]
    dur = _duracao_montado(dir_producao) if escrever else None
    p["_producao"] = {"duracao_s": dur} if dur else None

    erros = validar(p)
    if erros:
        raise ErroPerfil("perfil resolvido não valida:\n  " + "\n  ".join(erros))

    if not escrever:
        return None, p, origem

    os.makedirs(dir_producao, exist_ok=True)
    destino = os.path.join(dir_producao, "perfil.json")
    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(p, fh, indent=1, ensure_ascii=False)
        fh.write("\n")

    _gravar_no_workspace(p, dir_producao, quieto=quieto)
    return os.path.abspath(destino), p, origem


def _duracao_montado(d):
    v = os.path.join(d, "v1-montado.mp4")
    if not os.path.isfile(v):
        return None
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", v], capture_output=True, text=True).stdout.strip()
    try:
        return round(float(out), 4)
    except ValueError:
        return None


# 🔴 `_dir_remotion()` MORREU AQUI (achado R-20e, 2026-08-11). Ela existia para
# achar o projeto Remotion e escrever `src/data/perfil.json` — e a SPEC-31 (A6)
# tirou essa escrita: o snapshot passou a ir para `<dir-producao>/remotion/`, que
# é o workspace da peça. Sem chamador, ela ficou como código morto que ENSINA o
# caminho errado: dois comentários de outros scripts a citavam como "o mecanismo
# de referência", e o mecanismo dela era `join(..,"..","..","..")`, que é classe A
# do auditor. Quem precisa do diretório hoje usa `BENCH_REMOTION_DIR` com o
# marcador, como `previews-peca.py:dir_remotion()` faz.


def _gravar_no_workspace(p, dir_producao, quieto=False):
    """O snapshot que o Remotion da PRODUÇÃO lê — `<dir>/remotion/perfil.json`.

    🔴 ATÉ 2026-08-10 ISTO ESCREVIA EM `src/data/perfil.json`, DENTRO DA FONTE DO
    PRODUTO, e o efeito colateral era global de propósito: "o projeto Remotion é
    UM só, então o arquivo é sempre a última produção resolvida". Três coisas
    quebraram nessa aposta e estão medidas na auditoria de 2026-08-10 (A6/A7):

      · com 8 agentes na mesma árvore, o arquivo mudou 3× durante uma spec
        (reels 1080×1920 → vsl 1920×1080 → reels → vsl) por ação de vizinho;
      · o `_procedencia` carrega `creator` e os sha por caminho ABSOLUTO, então
        a produção assinava caminho de máquina dentro do pacote — o portão 1 do
        exportador reprovou por isso, e nenhum export saía;
      · a calibração de UMA creator (grade, pads, fade_modo, palavras/página)
        virava o default embarcado do produto.

    Agora o snapshot mora na INSTÂNCIA: `<dir-producao>/remotion/perfil.json`, ao
    lado do `.tsx` da peça, que o importa direto. `src/data/perfil.json` voltou a
    ser o que o nome promete — a fixture do produto, estável, sem creator dentro.
    O canvas dos previews de estilo não vem mais de arquivo global: `previews-
    peca.py` passa largura/altura/fps por `inputProps` e CONFERE o que voltou.

    `BENCH_PERFIL_SEM_REMOTION=1` continua suprimindo a gravação, para teste que
    resolve perfil descartável. Ela é inócua hoje (grava dentro do próprio
    diretório resolvido), mas a variável está em uso e o contrato não muda.
    """
    if os.environ.get("BENCH_PERFIL_SEM_REMOTION") == "1":
        if not quieto:
            print("snapshot do Remotion NÃO gravado "
                  "(BENCH_PERFIL_SEM_REMOTION=1)", file=sys.stderr)
        return None
    dd = os.path.join(dir_producao, "remotion")
    os.makedirs(dd, exist_ok=True)
    destino = os.path.join(dd, "perfil.json")
    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(p, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    if not quieto:
        print("snapshot do Remotion: %s" % destino, file=sys.stderr)
    return destino


# ---------------------------------------------------------------------- patch
# ⚠️ LOCK POR `mkdir`, NÃO `flock`: macOS não traz flock(1) (é util-linux) e a
# ilha é o repositório de um produto que vai ser clonado em outras máquinas.
# `mkdir` é atômico em POSIX e existe em todo lugar. O PID vai dentro do lock
# para detectar lock órfão de processo morto. Mesmo mecanismo do
# ilha/scripts/commit-spec.sh (leia o cabeçalho dele).
def _tomar_lock(caminho, timeout_s=60):
    lock = caminho + ".lock"
    esperou = 0
    while True:
        try:
            os.mkdir(lock)
            with open(os.path.join(lock, "pid"), "w") as fh:
                fh.write(str(os.getpid()))
            return lock
        except FileExistsError:
            dono = None
            try:
                with open(os.path.join(lock, "pid")) as fh:
                    dono = int(fh.read().strip())
            except (OSError, ValueError):
                pass
            if dono is not None:
                try:
                    os.kill(dono, 0)
                except OSError:
                    print("aviso: lock órfão do pid %d — quebrando" % dono, file=sys.stderr)
                    _soltar_lock(lock)
                    continue
            if esperou >= timeout_s * 20:
                raise ErroPerfil("lock não obtido em %ds (%s, dono pid %s)"
                                 % (timeout_s, lock, dono))
            time.sleep(0.05)
            esperou += 1


def _soltar_lock(lock):
    try:
        os.remove(os.path.join(lock, "pid"))
    except OSError:
        pass
    try:
        os.rmdir(lock)
    except OSError:
        pass


def _mesclar_conferindo(atual, novo, prefixo, forcar=False):
    """merge profundo que RECUSA quando uma folha já existe com valor diferente.

    É a semântica que faz 7 specs escreverem blocos disjuntos do mesmo JSON sem
    fila: `ritmo.cauda_alvo_s` (SPEC-09) e `ritmo.pads` (SPEC-00) convivem, e dois
    agentes tentando gravar a MESMA folha com valores diferentes colidem em vez de
    um sobrescrever o outro em silêncio.

    ⚠️ `forcar` precisa chegar até AQUI. Sem ele, esta função registrava o conflito
    e mantinha o valor ANTIGO; o chamador então ignorava a lista de conflitos e
    gravava o dicionário inalterado — `--forcar` imprimia o caminho, saía 0 e não
    mudava nada. Medido em 2026-08-08 na troca de `legenda.max_palavras_pagina`
    (SPEC-13), e é a pior classe de defeito deste repo: sucesso silencioso."""
    conflitos = []
    out = dict(atual)
    for k, v in novo.items():
        p = f"{prefixo}.{k}" if prefixo else k
        if k in out:
            if isinstance(v, dict) and isinstance(out[k], dict):
                sub, c = _mesclar_conferindo(out[k], v, p, forcar)
                out[k] = sub
                conflitos += c
            elif _canonico(out[k]) != _canonico(v):
                conflitos.append((p, out[k], v))
                if forcar:
                    out[k] = v
        else:
            out[k] = v
    return out, conflitos


def patch(arquivo, bloco, fragmento, forcar=False):
    """read-modify-write de UM bloco de topo de um perfil, sob lock."""
    if not os.path.isfile(arquivo):
        raise ErroPerfil("arquivo não existe: %s" % arquivo)
    if not os.path.isfile(fragmento):
        raise ErroPerfil("fragmento não existe: %s" % fragmento)
    novo = _ler(fragmento)
    lock = _tomar_lock(arquivo)
    try:
        p = _ler(arquivo)
        atual = p.get(bloco)
        if isinstance(novo, dict) and isinstance(atual, dict):
            mesclado, conflitos = _mesclar_conferindo(atual, novo, bloco, forcar)
        elif bloco in p and _canonico(atual) != _canonico(novo):
            mesclado, conflitos = novo, [(bloco, atual, novo)]
        else:
            mesclado, conflitos = novo, []
        linhas = ["  %s: já vale %s, o fragmento quer %s"
                  % (c, _canonico(a), _canonico(b)) for c, a, b in conflitos]
        if conflitos and not forcar:
            raise ErroPerfil(
                "RECUSADO: %d folha(s) do bloco `%s` já existem com conteúdo diferente "
                "em %s:\n%s\n"
                "Isto é colisão de duas specs escrevendo a mesma chave — resolva no texto, "
                "não com --forcar."
                % (len(conflitos), bloco, arquivo, "\n".join(linhas)))
        if conflitos and forcar:
            # sobrescrever tem que ser BARULHENTO: quem lê o log precisa ver qual
            # folha de qual spec foi por cima, senão o --forcar vira o silêncio que
            # a recusa existe para impedir.
            print("--forcar: SOBRESCREVENDO %d folha(s) do bloco `%s` em %s:\n%s"
                  % (len(conflitos), bloco, arquivo, "\n".join(linhas)), file=sys.stderr)
        p[bloco] = mesclado
        erros = validar_arquivo(arquivo, p)
        if erros:
            raise ErroPerfil("patch deixaria %s inválido:\n  %s" % (arquivo, "\n  ".join(erros)))
        tmp = arquivo + ".tmp.%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(p, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, arquivo)     # troca atômica: ninguém lê arquivo pela metade
    finally:
        _soltar_lock(lock)
    return os.path.abspath(arquivo)


# ------------------------------------------------------- validador (sem dependência)
def _tipo_ok(v, t):
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "null":
        return v is None
    return True


_VISTOS = [0]


def _validar_no(v, esquema, caminho, erros):
    if not isinstance(esquema, dict):
        return
    _VISTOS[0] += 1
    if "const" in esquema and v != esquema["const"]:
        erros.append("%s: esperado %r, veio %r" % (caminho, esquema["const"], v))
        return
    if "enum" in esquema and v not in esquema["enum"]:
        erros.append("%s: %r não está em %s" % (caminho, v, esquema["enum"]))
        return
    if "anyOf" in esquema:
        for sub in esquema["anyOf"]:
            sub_erros = []
            _validar_no(v, sub, caminho, sub_erros)
            if not sub_erros:
                break
        else:
            erros.append("%s: %r não casa com nenhuma alternativa de anyOf" % (caminho, v))
        return
    t = esquema.get("type")
    if t is not None:
        tipos = t if isinstance(t, list) else [t]
        if not any(_tipo_ok(v, x) for x in tipos):
            erros.append("%s: tipo %s, esperado %s"
                         % (caminho, type(v).__name__, "|".join(tipos)))
            return
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in esquema and v < esquema["minimum"]:
            erros.append("%s: %r < mínimo %r" % (caminho, v, esquema["minimum"]))
        if "maximum" in esquema and v > esquema["maximum"]:
            erros.append("%s: %r > máximo %r" % (caminho, v, esquema["maximum"]))
    if isinstance(v, str) and "minLength" in esquema and len(v) < esquema["minLength"]:
        erros.append("%s: string vazia" % caminho)
    if isinstance(v, list):
        if "minItems" in esquema and len(v) < esquema["minItems"]:
            erros.append("%s: %d itens < mínimo %d" % (caminho, len(v), esquema["minItems"]))
        if "maxItems" in esquema and len(v) > esquema["maxItems"]:
            erros.append("%s: %d itens > máximo %d" % (caminho, len(v), esquema["maxItems"]))
        if "items" in esquema:
            for i, x in enumerate(v):
                _validar_no(x, esquema["items"], "%s[%d]" % (caminho, i), erros)
    if isinstance(v, dict):
        props = esquema.get("properties", {})
        for r in esquema.get("required", []):
            if r not in v:
                erros.append("%s: falta a chave obrigatória %r" % (caminho or "(raiz)", r))
        if esquema.get("additionalProperties") is False:
            for k in v:
                if k not in props:
                    erros.append("%s: chave desconhecida %r" % (caminho or "(raiz)", k))
        for k, sub in props.items():
            if k in v:
                _validar_no(v[k], sub, ("%s.%s" % (caminho, k)) if caminho else k, erros)


def e_camada_do_catalogo(caminho):
    """Um arquivo de perfis/ é uma CAMADA da cadeia de merge, não um perfil
    completo: `reels.json` não repete `audio.sr`, que vem de `_base.json`.
    Validar a camada isolada acusaria falta de chave obrigatória que existe."""
    try:
        return os.path.samefile(os.path.dirname(os.path.abspath(caminho)), DIR_PERFIS)
    except OSError:
        return False


def sobre_base(camada):
    """A camada mesclada sobre _base.json — o que o resolvedor de fato produz."""
    base_arq = os.path.join(DIR_PERFIS, "_base.json")
    p = _ler(base_arq) if os.path.isfile(base_arq) else {}
    p.pop("_comentario", None)
    c = dict(camada)
    c.pop("_comentario", None)
    return _aplicar_ritmo_nomeado(_mesclar(p, c))


def validar_arquivo(caminho, p=None):
    """Valida um ARQUIVO pelo que ele é: camada do catálogo (mesclada sobre
    `_base.json`) ou perfil completo. `p` permite validar um conteúdo em memória
    antes de gravá-lo."""
    p = _ler(caminho) if p is None else p
    if e_camada_do_catalogo(caminho) and not os.path.basename(caminho).startswith("_"):
        return validar(sobre_base(p))
    return validar(p)


def validar(p):
    """Devolve lista de erros ([] = válido). Valida contra perfis/_schema.json."""
    esquema_arq = os.path.join(DIR_PERFIS, "_schema.json")
    erros = []
    if not os.path.isfile(esquema_arq):
        return ["_schema.json não encontrado em %s" % DIR_PERFIS]
    _VISTOS[0] = 0
    _validar_no(p, _ler(esquema_arq), "", erros)
    # regra que o JSON Schema não expressa: sr % fps tem que ser inteiro.
    # ⚠️ o `enum` do schema também recusa 29,97, mas com a mensagem genérica
    # "não está em [24, 25, …]" — que não diz ao operador POR QUE o decimal dele
    # é o problema. Esta regra roda mesmo depois do enum e acrescenta a razão.
    try:
        sr = int(p["audio"]["sr"])
        fps = p["video"]["fps"]
        f = fps_inteiro(fps)
        if f is None or sr % f:
            erros.append("video.fps: " + _msg_fps(fps, sr))
    except (KeyError, TypeError, ValueError):
        pass
    return erros


# ------------------------------------------------------------------------ CLI
def _uso(code=64):
    saida = sys.stdout if code == 0 else sys.stderr
    print(__doc__.split("CADEIA DE MERGE")[0].strip(), file=saida)
    sys.exit(code)


def _flag(args, nome, default=None):
    if nome not in args:
        return default
    i = args.index(nome)
    if i + 1 >= len(args) or args[i + 1].startswith("--"):
        raise ErroPerfil("%s exige um valor" % nome)
    return args[i + 1]


def _cli():
    a = sys.argv[1:]
    if not a:
        print("erro: falta um comando (resolver, mostrar, validar, patch, sh ou vf).",
              file=sys.stderr)
        _uso()
    cmd, a = a[0], a[1:]
    if cmd in ("--help", "-h") or any(x in ("--help", "-h") for x in a):
        _uso(0)

    if cmd == "resolver":
        if not a or a[0].startswith("-"):
            _uso()
        d = a[0]
        nome = _flag(a, "--perfil")
        if not nome:
            print("erro: --perfil é obrigatório", file=sys.stderr)
            return 64
        sets = [a[i + 1] for i, x in enumerate(a) if x == "--set" and i + 1 < len(a)]
        ref, usuario = _flag(a, "--estilo"), _flag(a, "--usuario")
        extra = {}
        if ref:
            rot, ov, sha, escopo = _camada_estilo(ref, d)
            extra = {"usuario": usuario or rot.split(":", 1)[1].split("/")[0],
                     "estilo": rot.split(":", 1)[1], "estilo_sha256": sha,
                     "camadas": [(rot, ov)], "escopo_camadas": escopo}
        elif usuario:
            extra = {"usuario": usuario}
        caminho = resolver(d, nome, _flag(a, "--creator"), sets, **extra)
        print(caminho)
        return 0

    if cmd == "mostrar":
        nome = _flag(a, "--perfil")
        if nome:                       # catálogo, sem produção nenhuma no disco
            arq = os.path.join(DIR_PERFIS, nome + ".json")
            if not os.path.isfile(arq):
                print("erro: perfil %r não existe em %s" % (nome, DIR_PERFIS),
                      file=sys.stderr)
                return 1
            p = sobre_base(_ler(arq))
            p["nome"] = nome
        else:
            if a and not a[0].startswith("-") and not os.path.exists(a[0]):
                print("erro: caminho não existe: %s" % a[0], file=sys.stderr)
                return 66
            p = carregar(a[0] if a and not a[0].startswith("-") else ".")
        json.dump(p, sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if cmd == "validar":
        if not a:
            _uso()
        if not os.path.isfile(a[0]):
            print("erro: arquivo de perfil não existe: %s" % a[0], file=sys.stderr)
            return 66
        alvo = _ler(a[0])
        modo = ""
        if e_camada_do_catalogo(a[0]) and not os.path.basename(a[0]).startswith("_"):
            alvo = sobre_base(alvo)
            modo = "  (camada do catálogo, validada sobre _base.json)"
        erros = validar(alvo)
        # ⚠️ "quanto varreu" faz parte da saída de propósito: um validador que
        # confere 0 nós e sai 0 é indistinguível de um quebrado.
        if erros:
            print("%s: INVÁLIDO%s (%d nós conferidos)\n  %s"
                  % (a[0], modo, _VISTOS[0], "\n  ".join(erros)), file=sys.stderr)
            return 1
        print("%s: OK%s (%d nós conferidos)" % (a[0], modo, _VISTOS[0]))
        return 0

    if cmd == "patch":
        arq, bloco, frag = _flag(a, "--arquivo"), _flag(a, "--bloco"), _flag(a, "--de")
        if not (arq and bloco and frag):
            print("uso: perfil.py patch --arquivo <p.json> --bloco <chave-de-topo> "
                  "--de <fragmento.json> [--forcar]", file=sys.stderr)
            return 64
        print(patch(arq, bloco, frag, "--forcar" in a))
        return 0

    if cmd == "sh":
        d = a[0] if a else "."
        if a and not os.path.exists(d):
            print("erro: caminho não existe: %s" % d, file=sys.stderr)
            return 66
        p = carregar(d)
        v, au = p["video"], p["audio"]
        pares = [
            ("PERFIL_NOME", p.get("nome", "?")),
            ("PERFIL_W", _num(v["largura"])), ("PERFIL_H", _num(v["altura"])),
            ("PERFIL_FPS", _num(v["fps"])),
            ("PERFIL_CRF", _num(v.get("crf", 16))),
            ("PERFIL_PRESET", v.get("preset_x264", "medium")),
            ("PERFIL_PIXFMT", v.get("pix_fmt", "yuv420p")),
            ("PERFIL_COLOR_OPTS", " ".join(opcoes_cor_saida(p))),
            ("PERFIL_ACODEC", au.get("codec", "aac")),
            ("PERFIL_ABITRATE", au.get("bitrate", "192k")),
            ("PERFIL_SR", _num(au["sr"])),
            ("PERFIL_CANAIS", _num(au["canais"])),
            ("PERFIL_SPF", str(spf(p))),
            ("PERFIL_VIDEO_SHA", video_sha(p)),
        ]
        for k, val in pares:
            print("%s=%s" % (k, _aspas(str(val))))
        return 0

    if cmd == "vf":
        d = a[0] if a and not a[0].startswith("-") else "."
        if a and not a[0].startswith("-") and not os.path.exists(d):
            print("erro: caminho não existe: %s" % d, file=sys.stderr)
            return 66
        p = carregar(d, quieto="--quieto" in a)
        # `--seg` é a forma preferida: a linha da EDL inteira, para que a guarda
        # de aspecto saiba se `cx`/`cy` foram ESCRITOS ou são o default 0.5 — que
        # é a diferença entre "o operador enquadrou" e "ninguém olhou".
        bruto = _flag(a, "--seg")
        if bruto:
            seg = json.loads(bruto)
            if not isinstance(seg, dict):
                print("erro: --seg espera o objeto de UM segmento da EDL",
                      file=sys.stderr)
                return 64
        else:
            seg = {"zoom": float(_flag(a, "--zoom", 1))}
            for k in ("cx", "cy"):
                if "--" + k in a:
                    seg[k] = float(_flag(a, "--" + k))
        print(vf_montagem(p, seg, int(_flag(a, "--sw", 0)), int(_flag(a, "--sh", 0)),
                          permitir_aspecto_agressivo="--permitir-aspecto-agressivo" in a,
                          sar=_flag(a, "--sar")))
        return 0

    print("comando desconhecido: %s" % cmd, file=sys.stderr)
    _uso()


def _aspas(s):
    return s if re.fullmatch(r"[A-Za-z0-9_.:=/+-]*", s) else "'%s'" % s.replace("'", "'\\''")


if __name__ == "__main__":
    try:
        sys.exit(_cli())
    except ErroPerfil as e:
        print("ERRO: %s" % e, file=sys.stderr)
        sys.exit(1)
    except (OSError, json.JSONDecodeError) as e:
        print("ERRO: %s" % e, file=sys.stderr)
        sys.exit(1)
