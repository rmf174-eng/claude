#!/usr/bin/env python3
"""edl-do-par — descobre a EDL REAL de uma edição, comparando bruto ↔ editado.

Só roda quando existe o PAR (o creator publicou o bastidor, ou o creator-1 tem os dois).
É a medição mais valiosa da modelagem: revela quanto do bruto foi aproveitado,
onde o editor cortou, quanto de pausa/gagueira saiu e se houve speed ramp.

Como funciona: alinha as duas transcrições word-level (difflib) e declara um CORTE
onde o intervalo entre duas palavras consecutivas ENCOLHEU do bruto pro editado.
Palavras do bruto que não aparecem no editado (retake, gagueira) também fecham segmento.

Uso:
    edl-do-par.py <transcript-bruto.json> <transcript-editado.json> [saida.json]

⚠️ Tolerância de 0,12s: o Deepgram quantiza timestamps em 80ms — abaixo disso é ruído.
⚠️ Se o offset palavra a palavra DENTRO de um segmento não for constante, houve
   speed ramp (ou o áudio foi reprocessado). O script avisa.
"""
import difflib, json, sys, unicodedata

TOL = 0.12


def words(p):
    return json.load(open(p))["results"]["channels"][0]["alternatives"][0]["words"]


def norm(w):
    t = (w.get("punctuated_word") or w["word"]).lower()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return "".join(c for c in t if c.isalnum())


def main():
    raw, ed = words(sys.argv[1]), words(sys.argv[2])
    out_p = sys.argv[3] if len(sys.argv) > 3 else None
    R, E = [norm(w) for w in raw], [norm(w) for w in ed]

    pares = []
    for b in difflib.SequenceMatcher(None, R, E, autojunk=False).get_matching_blocks():
        pares += [(b.a + k, b.b + k) for k in range(b.size)]
    if not pares:
        sys.exit("nenhuma palavra em comum — os transcripts são de vídeos diferentes?")

    segs, cur = [], None
    for ri, ei in pares:
        if cur is None:
            cur = {"r": [ri, ri], "e": [ei, ei]}
            continue
        pr, pe = cur["r"][1], cur["e"][1]
        contiguo = ri == pr + 1 and ei == pe + 1
        gap_r = raw[ri]["start"] - raw[pr]["end"]
        gap_e = ed[ei]["start"] - ed[pe]["end"]
        if contiguo and (gap_r - gap_e) <= TOL:
            cur["r"][1], cur["e"][1] = ri, ei
        else:
            cur["motivo"] = "pausa cortada" if contiguo else "fala descartada"
            cur["removido_s"] = round(gap_r - gap_e, 3) if contiguo else None
            segs.append(cur)
            cur = {"r": [ri, ri], "e": [ei, ei]}
    cur["motivo"], cur["removido_s"] = "fim", None
    segs.append(cur)

    print(f"{'#':>2} | {'BRUTO':^15} | {'EDITADO':^15} | {'dur':>5} | {'removido':>8} | fala")
    print("-" * 116)
    out = []
    for i, s in enumerate(segs, 1):
        rb, re_ = raw[s["r"][0]], raw[s["r"][1]]
        eb, ee = ed[s["e"][0]], ed[s["e"][1]]
        txt = " ".join((w.get("punctuated_word") or w["word"]) for w in raw[s["r"][0]:s["r"][1] + 1])
        rem = f"{s['removido_s']:+.2f}s" if s["removido_s"] is not None else "   —   "
        print(f"{i:>2} | {rb['start']:6.2f}–{re_['end']:6.2f} | {eb['start']:6.2f}–{ee['end']:6.2f} |"
              f" {re_['end']-rb['start']:5.2f} | {rem:>8} | {txt[:52]}")
        out.append({"n": i, "raw_asr": [round(rb["start"], 3), round(re_["end"], 3)],
                    "ed_asr": [round(eb["start"], 3), round(ee["end"], 3)],
                    "removido_depois_s": s["removido_s"], "motivo_fim": s["motivo"], "fala": txt})

    print("\n--- FALA DO BRUTO QUE NÃO ENTROU (retake/gagueira/cauda) ---")
    usados = {p[0] for p in pares}
    run = []
    for i in range(len(raw) + 1):
        if i < len(raw) and i not in usados:
            run.append(i)
        elif run:
            print(f"  [{raw[run[0]]['start']:6.2f}–{raw[run[-1]]['end']:6.2f}] "
                  + " ".join((raw[j].get("punctuated_word") or raw[j]["word"]) for j in run))
            run = []

    # speed ramp? o offset dentro de cada segmento tem que ser constante
    alerta = []
    for s in segs:
        offs = []
        base = None
        for ri, ei in pares:
            if not (s["r"][0] <= ri <= s["r"][1]):
                continue
            if base is None:
                base = (raw[ri]["start"], ed[ei]["start"])
            offs.append((ed[ei]["start"] - base[1]) - (raw[ri]["start"] - base[0]))
        # ⚠️ limiar de 0,30s: o Deepgram quantiza timestamps em 80ms e o offset acumula
        # 2–3 quanta dentro de um segmento SEM que exista speed ramp nenhum (medido).
        # Com 0,16 este teste dava falso positivo em toda montagem normal.
        if offs and (max(offs) - min(offs)) > 0.30:
            alerta.append(round(max(offs) - min(offs), 3))
    print(f"\nspeed ramp: {'SUSPEITA — variação de offset ' + str(alerta) + ' (confirme comparando a duração das palavras)' if alerta else 'não (offset constante dentro dos segmentos, dentro da quantização de 80ms do ASR)'}")

    soma = sum(s["raw_asr"][1] - s["raw_asr"][0] for s in out)
    dur_raw = raw[-1]["end"]
    print(f"{len(out)} segmentos · {soma:.2f}s de fala útil · {soma/dur_raw*100:.0f}% do bruto aproveitado")
    if out_p:
        json.dump(out, open(out_p, "w"), ensure_ascii=False, indent=2)
        print(out_p)


if __name__ == "__main__":
    main()
