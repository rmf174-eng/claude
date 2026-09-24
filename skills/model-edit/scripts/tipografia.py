#!/usr/bin/env python3
"""tipografia — mede a CAMADA DE TEXTO de um vídeo inteiro, não de um frame.

O grafismo.py isola um overlay comparando dois frames do mesmo plano. Serve pra
medir UM elemento. Este script responde as perguntas que só aparecem na peça
inteira, que são as que a gente precisa pra configurar o CaptionLayer:

  • em que faixa da altura vive a legenda, e o quanto ela é estável
  • qual a cor base e qual a cor de destaque
  • quantas palavras por página e de quantos em quantos segundos ela troca
  • quando entra texto GRANDE fora da faixa de legenda (a segunda camada)
  • como isso tudo varia ao longo da peça (a "dinâmica" que segura o lead)

Método: detecta pixels de texto por (luminância alta OU saturação alta) somada a
gradiente local forte — que é o que separa letra de parede clara. Projeta na
vertical pra achar as faixas, e acumula ao longo do tempo.

Uso:
    tipografia.py <video> [--fps 2] [--janela 30] [--json] [--dump-mascara dir/]

Saída: faixas de texto, cores, cadência, e a timeline de ocupação por região.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

W, H = 216, 384  # amostra vertical barata; medidas saem em % e em 1080x1920


def decodifica(video, fps):
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", video, "-vf",
         f"fps={fps},scale={W}:{H}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    n = len(raw) // (W * H * 3)
    if n < 2:
        sys.exit("vídeo curto demais ou ilegível")
    return np.frombuffer(raw, np.uint8)[:n * W * H * 3].reshape(n, H, W, 3)


def mascara_texto(fr, so_claro=False):
    """True onde é provável ser glifo: claro-ou-saturado E com borda forte."""
    f = fr.astype(np.float32)
    lum = f @ np.array([0.299, 0.587, 0.114], np.float32)
    mx, mn = f.max(axis=2), f.min(axis=2)
    sat = (mx - mn) / (mx + 1e-6)

    # gradiente (Sobel simplificado) — letra tem borda dura, pele/parede não
    gy = np.abs(np.diff(lum, axis=0, prepend=lum[:1]))
    gx = np.abs(np.diff(lum, axis=1, prepend=lum[:, :1]))
    borda = gx + gy

    claro = lum > 205
    if so_claro:
        # cenário quente e saturado (madeira, sofá colorido, luz âmbar) acende o
        # critério de cor e o detector elege o cenário. Aí só a luminância serve.
        return claro & (borda > 26)
    colorido = (sat > 0.55) & (lum > 90)
    return (claro | colorido) & (borda > 26)


def faixas_de(perfil, limiar):
    """Agrupa linhas contíguas acima do limiar em faixas (y0, y1, pico)."""
    out, ini = [], None
    for y, v in enumerate(perfil):
        if v >= limiar and ini is None:
            ini = y
        elif v < limiar and ini is not None:
            if y - ini >= 3:
                out.append((ini, y, float(perfil[ini:y].max())))
            ini = None
    if ini is not None and len(perfil) - ini >= 3:
        out.append((ini, len(perfil), float(perfil[ini:].max())))
    return out


def cor_dominante(px):
    """Duas cores principais dos pixels de texto, por quantização grosseira."""
    if len(px) < 40:
        return []
    q = (px // 40 * 40).astype(int)
    chaves, contagem = np.unique(q.reshape(-1, 3), axis=0, return_counts=True)
    ordem = np.argsort(-contagem)[:4]
    tot = contagem.sum()
    return [{"hex": "#%02X%02X%02X" % tuple(np.clip(chaves[i] + 20, 0, 255)),
             "pct": round(float(contagem[i] / tot) * 100, 1)}
            for i in ordem if contagem[i] / tot > 0.06]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--janela", type=float, default=30.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--so-claro", action="store_true",
                    help="ignora o critério de cor — use em cenário quente/saturado")
    a = ap.parse_args()

    fr = decodifica(a.video, a.fps)
    n = len(fr)
    dur = n / a.fps

    masks = np.stack([mascara_texto(f, a.so_claro) for f in fr])       # (n,H,W) bool
    ocup = masks.mean(axis=(1, 2))                          # ocupação por frame

    # ⚠️ o passo que separa texto de cenário claro: TEXTO PISCA.
    # Um teclado branco, uma parede clara ou uma camisa brilhante acendem a
    # máscara e ficam acesos; a legenda liga e desliga a cada página. Pesando
    # cada pixel pela taxa de alternância, o cenário sai e a tipografia fica.
    alternancia = np.abs(np.diff(masks.astype(np.int8), axis=0)).mean(axis=0)
    peso = masks.mean(axis=0) * alternancia                # (H,W)
    perfil = peso.mean(axis=1)
    perfil = perfil / (perfil.max() or 1) * 100            # normalizado 0–100

    limiar = max(perfil.max() * 0.35, 8.0)
    todas = faixas_de(perfil, limiar)

    # ⚠️ segundo discriminante, e ele é necessário: a alternância sozinha ainda
    # elege objeto claro que a pessoa MEXE. No caso medido era um teclado branco
    # na mesa — 26% de pixels claros no rodapé, e as mãos passando por cima
    # fazem a máscara piscar igual a uma legenda.
    # A legenda de VSL é CENTRALIZADA: o centro de massa horizontal fica em
    # ~50% e o teclado fica deslocado. Pontua por intensidade × centralidade.
    def centralidade(y0, y1):
        cols = peso[y0:y1].mean(axis=0)
        if cols.sum() <= 0:
            return 0.0, 0.5
        cx = float((cols * np.arange(W)).sum() / cols.sum() / W)
        return max(0.0, 1 - abs(cx - 0.5) / 0.25), cx

    marcadas = []
    for y0, y1, pico in todas:
        c, cx = centralidade(y0, y1)
        marcadas.append((y0, y1, pico, c, cx))
    legenda = max(marcadas, key=lambda f: f[2] * f[3], default=None)
    if legenda and legenda[2] * legenda[3] <= 0:
        legenda = None

    res = {"video": a.video, "duracao_s": round(dur, 1), "frames": n,
           # A base dos campos legados `*_1920`, como DADO. É o que permite a um
           # leitor converter sem saber de cor o canvas que estava no nome.
           "normalizacao": {"altura_px": 1920, "de": "y/H — a medição é relativa"},
           "faixas_de_texto": [], "legenda": None, "segunda_camada": None,
           "cadencia": {}, "timeline": []}

    for y0, y1, pico, c, cx in marcadas:
        res["faixas_de_texto"].append({
            "y0_pct": round(y0 / H * 100, 1), "y1_pct": round(y1 / H * 100, 1),
            "altura_pct": round((y1 - y0) / H * 100, 2),
            # 🔴 OS TRÊS ABAIXO SÃO LEGADO (SPEC-41). O nome carrega um canvas
            # (`1080x1920`) dentro de uma medição que já é relativa: os valores
            # nascem de `y/H`, então valem para qualquer resolução, e só o NOME
            # diz o contrário. Quem mede uma peça 16:9 lê "1920" num campo que
            # descreve a altura dela. Continuam gravados por compatibilidade —
            # o consumidor novo lê os `_pct` e a base declarada em `normalizacao`.
            "y0_1080x1920": int(y0 / H * 1920), "y1_1080x1920": int(y1 / H * 1920),
            "altura_px_1920": int((y1 - y0) / H * 1920),
            "intensidade_rel": round(pico, 1),
            "centro_x_pct": round(cx * 100, 1),
            "centralidade": round(c, 2),
            "eh_legenda": bool(legenda and y0 == legenda[0]),
        })

    if legenda:
        y0, y1 = legenda[0], legenda[1]
        # A faixa detectada é só o NÚCLEO (limiar de 35% do pico). Pra altura do
        # glifo — que é o que vira fontSize — expande enquanto houver 12% do
        # pico, senão o fontSize sai ~40% menor que o real.
        pk = perfil[y0:y1].max()
        ya, yb = y0, y1
        while ya > 0 and perfil[ya - 1] > pk * 0.12:
            ya -= 1
        while yb < H and perfil[yb] > pk * 0.12:
            yb += 1
        res_altura_glifo = int((yb - ya) / H * 1920)
        sub = masks[:, y0:y1, :]
        presente = sub.mean(axis=(1, 2)) > 0.004
        px = fr[:, y0:y1, :][sub]
        # largura ocupada quando presente
        cols = sub[presente].mean(axis=(0, 1)) if presente.any() else np.zeros(W)
        usadas = np.where(cols > cols.max() * 0.15)[0] if cols.max() > 0 else []
        res["legenda"] = {
            "y_centro_pct": round((ya + yb) / 2 / H * 100, 1),
            "y0_pct": round(y0 / H * 100, 1), "y1_pct": round(y1 / H * 100, 1),
            "altura_glifo_pct": round((yb - ya) / H * 100, 2),
            "altura_glifo_px_1920": res_altura_glifo,   # legado — ver `normalizacao`
            "faixa_total_pct": [round(ya / H * 100, 1), round(yb / H * 100, 1)],
            "presente_pct_do_tempo": round(float(presente.mean()) * 100, 1),
            "largura_usada_pct": round(
                float(len(usadas) / W * 100) if len(usadas) else 0, 1),
            "cores": cor_dominante(px),
        }
        # base x destaque: a legenda tem uma cor de corpo e uma da palavra ativa.
        # Separar por cromaticidade é mais confiável que clusterizar tudo junto —
        # o corpo é acromático (branco) e o destaque é saturado.
        fx = fr[:, y0:y1, :].astype(int)
        R, G, B = fx[..., 0], fx[..., 1], fx[..., 2]
        mx = fx.max(axis=3) if fx.ndim == 4 else np.max(fx, axis=-1)
        mn = np.min(fx, axis=-1)
        croma = mx - mn
        acro = sub & (mn > 200)                      # branco/cinza claro
        satur = sub & (croma > 70) & (mx > 120)      # palavra destacada
        def med(m, puro=None):
            """Cor do NÚCLEO do glifo, não a média da máscara.

            A média inclui os pixels de borda, que são mistura de letra com
            fundo e puxam o hex pro cenário: no caso medido a média deu #C94C2B
            e o núcleo, #E04219 (a mesma legenda, lida em resolução nativa).
            """
            if m.sum() < 60:
                return None
            if puro is not None:
                lim = np.percentile(puro[m], 75)
                m = m & (puro >= lim)
                if m.sum() < 20:
                    return None
            return "#%02X%02X%02X" % (int(R[m].mean()), int(G[m].mean()), int(B[m].mean()))
        res["legenda"]["cor_base"] = med(acro, mn)
        res["legenda"]["cor_destaque"] = med(satur, croma)
        res["legenda"]["frames_com_destaque_pct"] = round(
            float(satur.any(axis=(1, 2)).mean()) * 100, 1)

        # cadência: quantas VEZES o conteúdo da faixa muda de forma relevante
        dif = np.abs(np.diff(sub.astype(np.int8), axis=0)).mean(axis=(1, 2))
        trocas = int((dif > max(dif.mean() * 1.4, 0.004)).sum())
        res["cadencia"] = {
            "trocas_detectadas": trocas,
            "trocas_por_min": round(trocas / (dur / 60), 1),
            "s_por_pagina": round(dur / trocas, 2) if trocas else None,
            "nota": f"amostrado a {a.fps}fps — é piso, não teto",
        }
        # segunda camada = texto fora da faixa da legenda
        fora = masks.copy()
        fora[:, y0:y1, :] = False
        ocup_fora = fora.mean(axis=(1, 2))
        ativo = ocup_fora > max(ocup_fora.mean() + 2 * ocup_fora.std(), 0.006)
        res["segunda_camada"] = {
            "presente_pct_do_tempo": round(float(ativo.mean()) * 100, 1),
            "ocupacao_media_quando_ativa_pct": round(
                float(ocup_fora[ativo].mean() * 100) if ativo.any() else 0, 2),
            "cores": cor_dominante(fr[fora]) if fora.any() else [],
        }

    # timeline por janela: ocupação de texto e onde ela está
    passo = max(int(a.janela * a.fps), 1)
    for i in range(0, n, passo):
        bloco = masks[i:i + passo]
        if not len(bloco):
            continue
        topo = bloco[:, :int(H * .33), :].mean() * 100
        meio = bloco[:, int(H * .33):int(H * .66), :].mean() * 100
        base = bloco[:, int(H * .66):, :].mean() * 100
        res["timeline"].append({
            "t": round(i / a.fps, 1), "topo": round(topo, 2),
            "meio": round(meio, 2), "base": round(base, 2),
            "total": round(float(bloco.mean() * 100), 2)})

    if a.json:
        print(json.dumps(res, ensure_ascii=False))
        return

    L, S = res["legenda"], res["segunda_camada"]
    print(f"{os.path.basename(os.path.dirname(a.video))}  {dur/60:.1f} min · "
          f"{n} frames @ {a.fps}fps")
    print(f"\n  ocupação de texto: média {ocup.mean()*100:.2f}% · "
          f"pico {ocup.max()*100:.2f}%")
    print(f"\n  faixas de texto encontradas ({len(todas)}):")
    for f in res["faixas_de_texto"]:
        print(f"    y {f['y0_pct']:5.1f}%–{f['y1_pct']:5.1f}%  "
              f"(1920: {f['y0_1080x1920']:4d}–{f['y1_1080x1920']:4d}, "
              f"alt {f['altura_px_1920']:3d}px)  int. {f['intensidade_rel']:5.1f}")
    if L:
        print(f"\n  LEGENDA → centro em {L['y_centro_pct']}% da altura "
              f"(yPct do CaptionLayer)")
        print(f"    altura do glifo ~{L['altura_glifo_px_1920']}px em 1080x1920")
        print(f"    largura usada {L['largura_usada_pct']}% · "
              f"na tela {L['presente_pct_do_tempo']}% do tempo")
        print(f"    cor base {L.get('cor_base')} · destaque {L.get('cor_destaque')} "
              f"(em {L.get('frames_com_destaque_pct')}% dos frames)")
        c = res["cadencia"]
        print(f"    cadência: ~{c['trocas_por_min']}/min · "
              f"~{c['s_por_pagina']}s por página")
    if S:
        print(f"\n  SEGUNDA CAMADA (texto fora da faixa da legenda)")
        print(f"    ativa {S['presente_pct_do_tempo']}% do tempo · "
              f"ocupa {S['ocupacao_media_quando_ativa_pct']}% da tela quando entra")
        print(f"    cores: " + ", ".join(f"{c['hex']} ({c['pct']}%)" for c in S["cores"]))

    print(f"\n  timeline (cada linha = {a.janela:.0f}s · ocupação de texto %)")
    print("    t      topo  meio  base   total")
    pico = max((x["total"] for x in res["timeline"]), default=1) or 1
    for x in res["timeline"]:
        barra = "█" * int(round(x["total"] / pico * 26))
        print(f"    {int(x['t'])//60:02d}:{int(x['t'])%60:02d} "
              f"{x['topo']:5.2f} {x['meio']:5.2f} {x['base']:5.2f} "
              f"{x['total']:6.2f} {barra}")


if __name__ == "__main__":
    main()
