#!/usr/bin/env python3
"""ritmo — perfil de MONTAGEM de um vídeo ao longo da timeline.

O cortes.py lista cada corte. Este agrega: quantos cortes por minuto em cada
trecho, quanto dura o plano médio, e onde a montagem acelera ou respira.

Numa VSL isso responde perguntas que o transcript não responde: a abertura é
cortada mais rápido que o corpo? o bloco de oferta desacelera pra dar peso ao
preço? o ritmo cai junto com a retenção?

Uso:
    ritmo.py <video> [--fps 8] [--janela 30] [--sigma 8] [--json]
    ritmo.py <video> --marcos 0:00-1:00=abertura 20:45-25:31=oferta

Saída: tabela de ritmo por janela + resumo. Com --json, dict serializável.
"""
import argparse
import json
import os
import re
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
LINHA = re.compile(r"^\s*([\d.]+)\s+\d+\s*\|(.+?)\|.*?(←\s*(.+))?$")


def duracao(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "format=duration", "-of", "csv=p=0", video],
        capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


def coleta_cortes(video, fps, sigma):
    """Roda cortes.py e devolve [(t, tipo), ...]."""
    r = subprocess.run(
        [sys.executable, os.path.join(AQUI, "cortes.py"), video,
         "--fps", str(fps), "--sigma", str(sigma)],
        capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"cortes.py falhou: {r.stderr[:400]}")
    cortes = []
    for ln in r.stdout.splitlines():
        if "←" not in ln:
            continue
        m = LINHA.match(ln)
        if m:
            cortes.append((float(m.group(1)), (m.group(4) or "").strip()))
    return cortes


def parse_marcos(specs, dur):
    """'0:00-1:00=abertura' -> (ini_s, fim_s, rotulo)"""
    def seg(t):
        p = [float(x) for x in t.split(":")]
        return p[0] * 60 + p[1] if len(p) == 2 else p[0]
    out = []
    for s in specs or []:
        faixa, _, rotulo = s.partition("=")
        ini, _, fim = faixa.partition("-")
        out.append((seg(ini), seg(fim) if fim else dur, rotulo or faixa))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--fps", type=int, default=8)
    ap.add_argument("--janela", type=float, default=30.0)
    ap.add_argument("--sigma", type=float, default=8.0)
    ap.add_argument("--marcos", nargs="*", default=[])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    dur = duracao(a.video)
    cortes = coleta_cortes(a.video, a.fps, a.sigma)
    ts = [t for t, _ in cortes]
    n = len(cortes)

    tipos = {}
    for _, tp in cortes:
        tipos[tp] = tipos.get(tp, 0) + 1

    # planos = intervalos entre cortes consecutivos
    planos = [b - x for x, b in zip(ts, ts[1:])] if n > 1 else []
    plano_medio = sum(planos) / len(planos) if planos else dur
    planos_ord = sorted(planos)
    mediana = planos_ord[len(planos_ord) // 2] if planos_ord else dur

    janelas = []
    t = 0.0
    while t < dur:
        fim = min(t + a.janela, dur)
        c = sum(1 for x in ts if t <= x < fim)
        janelas.append({"ini": t, "fim": fim, "cortes": c,
                        "por_min": c / ((fim - t) / 60) if fim > t else 0})
        t = fim

    marcos = []
    for ini, fim, rotulo in parse_marcos(a.marcos, dur):
        c = sum(1 for x in ts if ini <= x < fim)
        marcos.append({"rotulo": rotulo, "ini": ini, "fim": fim, "cortes": c,
                       "por_min": c / ((fim - ini) / 60) if fim > ini else 0,
                       "plano_medio": (fim - ini) / c if c else None})

    res = {
        "video": a.video, "duracao_s": round(dur, 1),
        "cortes": n, "cortes_por_min": round(n / (dur / 60), 1) if dur else 0,
        "plano_medio_s": round(plano_medio, 2), "plano_mediano_s": round(mediana, 2),
        "tipos": tipos, "janelas": janelas, "marcos": marcos,
        "fps_amostragem": a.fps,
    }

    if a.json:
        print(json.dumps(res, ensure_ascii=False))
        return

    print(f"{os.path.basename(os.path.dirname(a.video))}  {dur/60:.1f} min")
    print(f"  {n} cortes · {res['cortes_por_min']}/min · plano médio {plano_medio:.1f}s "
          f"(mediana {mediana:.1f}s)")
    print("  tipos: " + ", ".join(f"{v}x {k}" for k, v in
                                  sorted(tipos.items(), key=lambda x: -x[1])))
    if marcos:
        print("\n  trecho                   cortes   /min   plano")
        for m in marcos:
            pm = f"{m['plano_medio']:.1f}s" if m["plano_medio"] else "—"
            print(f"  {m['rotulo'][:22]:<22} {m['cortes']:>6} {m['por_min']:>6.1f} {pm:>7}")

    print("\n  perfil ao longo da peça (cada linha = "
          f"{a.janela:.0f}s, barra = cortes)")
    pico = max((j["cortes"] for j in janelas), default=1) or 1
    for j in janelas:
        barra = "█" * int(round(j["cortes"] / pico * 40))
        print(f"  {int(j['ini'])//60:02d}:{int(j['ini'])%60:02d} "
              f"{j['cortes']:>3} {barra}")


if __name__ == "__main__":
    main()
