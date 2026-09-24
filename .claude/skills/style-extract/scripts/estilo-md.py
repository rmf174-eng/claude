#!/usr/bin/env python3
"""estilo-md — `estilo.json` → `ESTILO.md`, a ficha legível ao lado dele.

É a versão GERADA das fichas de `intelligence/edicao/`. Existe para uma razão
específica: `tools/remotion-compositor/src/vsl/estilos-medidos.ts` foi transcrito
À MÃO do JSON e pode divergir dele. Este não pode — a ficha é uma função do
artefato.

Seções fixas: veredito · corpus · o que É estilo (conf alta) · o que varia
(conf baixa, com o por_ref) · complexidade e variantes · por bloco · regras com
evidência · o que não foi medido · como reproduzir.

Uso:
    estilo-md.py <estilo.json> [--saida <arquivo.md>]

Saída: o caminho do .md no stdout.
"""
import argparse
import json
import os
import sys

MARCA = {"alta": "✅", "media": "🟡", "baixa": "⚠️"}


def fmt_v(v):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) or "—"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def disp_txt(p):
    d = p.get("disp") or {}
    if "cv" in d:
        return (f"p25 {fmt_v(d.get('p25'))} · p75 {fmt_v(d.get('p75'))} · "
                f"iqr {fmt_v(d.get('iqr'))} · cv {fmt_v(d.get('cv'))}")
    if "p10" in d:
        return f"faixa [{fmt_v(d.get('p10'))}, {fmt_v(d.get('p90'))}]"
    if "fracao_moda" in d:
        votos = ", ".join(f"{k}×{v}" for k, v in sorted((d.get("votos") or {}).items()))
        return f"moda {fmt_v(d.get('fracao_moda'))} ({votos})" if votos else "—"
    if "deltaE_mediano_ao_centro" in d:
        return f"ΔE mediano {fmt_v(d['deltaE_mediano_ao_centro'])} · máx {fmt_v(d.get('deltaE_max'))}"
    if "itens" in d:
        return " · ".join(f"{i['item']} {i['k']}/{i['de']}" for i in d["itens"][:8]) or "—"
    return "—"


def por_ref_txt(p):
    if not p.get("por_ref"):
        return "—"
    return " · ".join(f"{k}={fmt_v(v)}" for k, v in sorted(p["por_ref"].items()))


def linhas_params(eixos, filtro):
    out = []
    for grupo in sorted(eixos):
        for chave in sorted(eixos[grupo]):
            p = eixos[grupo][chave]
            if not isinstance(p, dict) or not filtro(p):
                continue
            out.append((f"{grupo}.{chave}", p))
    return out


def gerar(est):
    L = []
    a = L.append
    a(f"# {est['nome']}")
    a("")
    a(f"> `{est['slug']}` · contrato `{est['contrato']}` · extrator v{est['versao_extrator']}")
    a(f"> gerado em {est['gerado_em']} por `{est['gerador']}`")
    a(f"> **estado: {est['estado'].upper()}** · {est['n_refs']} referências · "
      f"score de coerência {est['coerencia']['score']:.2f}")
    a("")
    a("## Veredito")
    a("")
    a(est["coerencia"]["veredito"])
    a("")
    if est["estado"] == "incoerente":
        a("🔴 **Estilo incoerente: `overlay_perfil` e `variantes` saem vazios de propósito.** "
          "O consumidor (SPEC-24) recusa aplicar. O que sobra de útil é o denominador comum "
          "abaixo.")
        a("")
    if est["avisos"]:
        a("### Avisos")
        a("")
        for av in est["avisos"]:
            a(f"- ⚠️ {av}")
        a("")

    a("## Corpus")
    a("")
    a("| ref | duração | objetivo | temperatura | cobertura semântica | medição |")
    a("|---|---|---|---|---|---|")
    for c in est["corpus"]:
        cob = "—" if c["cobertura_semantica_pct"] is None else f"{c['cobertura_semantica_pct']}%"
        a(f"| `{c['id']}` | {c['dur_s']/60:.1f} min | {c['objetivo']} | {c['temperatura']} "
          f"| {cob} | `{c['medicao']}` |")
    a("")
    fr = est["aplica_a"]["formato_das_refs"]
    a(f"Aplica a perfis de peça: {', '.join('`%s`' % p for p in est['aplica_a']['perfis'])} · "
      f"objetivo `{est['aplica_a']['objetivo']}` · temperatura `{est['aplica_a']['temperatura']}`. "
      f"As referências são {', '.join(fr['aspecto']) or '—'} e vão de {fr['dur_s']['min']:.0f}s "
      f"a {fr['dur_s']['max']:.0f}s — isso é **descritivo**: formato de peça vem do perfil "
      "(SPEC-00), nunca do estilo.")
    a("")

    if est["coerencia"]["clusters"]:
        a("### Como as referências se separam")
        a("")
        for c in est["coerencia"]["clusters"]:
            a(f"- **{', '.join(c['refs'])}** — separadas por `{c['separa_por']}`")
        a("")

    a("## O que É estilo (confiança alta ou média)")
    a("")
    a("Estes são os parâmetros que várias referências sustentam. Só eles entram em "
      "`overlay_perfil`.")
    a("")
    a("| parâmetro | valor | conf | n | dispersão | fonte |")
    a("|---|---|---|---|---|---|")
    for nome, p in linhas_params(est["eixos"], lambda p: p["conf"] in ("alta", "media")):
        a(f"| `{nome}` | **{fmt_v(p['v'])}** | {MARCA[p['conf']]} {p['conf']} | "
          f"{p['n']}/{p['n_total']} | {disp_txt(p)} | {p['fonte']} |")
    a("")

    a("## O que VARIA (confiança baixa — sugestão, nunca default)")
    a("")
    a("Um parâmetro daqui jamais vira default aplicado. Ele só entra num artefato "
      "executável com decisão humana registrada no `PLANO-EDICAO.md`.")
    a("")
    a("| parâmetro | mediana | n | por referência | por quê |")
    a("|---|---|---|---|---|")
    for nome, p in linhas_params(est["eixos"], lambda p: p["conf"] == "baixa"):
        motivo = p.get("nota") or ("n=%d" % p["n"] if p["n"] < 2 else disp_txt(p))
        a(f"| `{nome}` | {fmt_v(p['v'])} | {p['n']}/{p['n_total']} | {por_ref_txt(p)} "
          f"| {str(motivo)[:180]} |")
    a("")

    a("## Denominador comum")
    a("")
    if est["denominador_comum"]:
        for nome in sorted(est["denominador_comum"]):
            p = est["denominador_comum"][nome]
            a(f"- `{nome}` = **{fmt_v(p['v'])}** ({MARCA[p['conf']]} {p['conf']}, n={p['n']})")
    else:
        a("Nenhum parâmetro-núcleo fechou. As referências não têm denominador comum medido.")
    a("")

    c = est["complexidade"]
    a("## Complexidade e variantes")
    a("")
    a(f"**IC {c['ic'] if c['ic'] is not None else '—'}** "
      f"({c['faixa'] or 'indefinido'}) na escala v{c['versao_escala']}. "
      "IC é ordinal DENTRO da escala: dois estilos só se comparam com a mesma "
      "`versao_escala`, e não existe \"esta edição é 44% complexa\".")
    a("")
    if c.get("componentes_faltando"):
        a(f"⚠️ Sem IC agregado: faltam os componentes {', '.join(c['componentes_faltando'])}.")
        a("")
    a("| ref | IC |")
    a("|---|---|")
    for k in sorted(c["por_ref"]):
        a(f"| `{k}` | {c['por_ref'][k] if c['por_ref'][k] is not None else '—'} |")
    a("")
    if est["variantes"]:
        a("| variante | IC | recursos que sobrevivem |")
        a("|---|---|---|")
        for nome in ("enxuta", "padrao", "densa"):
            v = est["variantes"].get(nome)
            if not v:
                continue
            a(f"| `{nome}` | {v['ic'] if v['ic'] is not None else '—'} "
              f"| {', '.join(v['recursos']) or '—'} |")
        a("")
        a("A variante enxuta guarda os recursos presentes em quase todas as referências "
          "(os que de fato definem o estilo); a densa admite os que só uma ou duas usaram.")
        a("")

    a("## Por bloco")
    a("")
    if est["por_bloco"]:
        a("Um parâmetro só aparece aqui quando a variação POR BLOCO é maior que a variação "
          "ENTRE referências, e a direção é a mesma na maioria delas.")
        a("")
        a("| bloco | parâmetro | valor | conf | evidência |")
        a("|---|---|---|---|---|")
        for b in sorted(est["por_bloco"]):
            for k in sorted(est["por_bloco"][b]):
                p = est["por_bloco"][b][k]
                a(f"| `{b}` | `{k}` | {fmt_v(p['v'])} | {MARCA[p['conf']]} {p['conf']} "
                  f"| {p.get('nota') or '—'} |")
    else:
        a("Nenhum efeito de bloco sobreviveu ao critério: com este corpus, a diferença "
          "entre blocos é menor que a diferença entre referências. Reportar um efeito de "
          "bloco aqui seria repetir ruído de amostragem três vezes.")
    a("")

    a("## Regras em texto")
    a("")
    if est["regras"]:
        for r in est["regras"]:
            a(f"### `{r['id']}` · {r['tipo']} · suporte {r['suporte']}/{r['de']} "
              f"· {MARCA[r['conf']]} {r['conf']} · aplicável por `{r['aplicavel_por']}`")
            a("")
            a(f"> {r['texto']}")
            a("")
            for e in r["evidencia"]:
                a(f"- `{e['ref']}` em {e['t_s']:.1f}s — “{e['citacao']}”")
            a("")
    else:
        a("Nenhuma regra passou no portão de suporte (>= 2 referências com evidência "
          "timestampada em cada uma).")
        a("")
    if est["regras_candidatas"]:
        a(f"### Candidatas ({len(est['regras_candidatas'])}) — sugestões, não padrão")
        a("")
        for r in est["regras_candidatas"][:20]:
            a(f"- **{r['id']}** ({r['suporte']}/{r['de']}): {r['texto']}")
            if r.get("motivo"):
                a(f"  - por que não subiu: {r['motivo']}")
        a("")

    a("## O que NÃO foi medido")
    a("")
    for n in est["nao_medido"]:
        a(f"- {n}")
    a("")
    a("Campo faltando fica faltando. O modelo não preenche medida que o pixel não deu — "
      "o Gemini reportou legenda a 85% da altura onde o pixel mediu 56%, e destaque "
      "`#FFFF00` onde o pixel mediu `#F14418`.")
    a("")

    a("## Overlay de perfil proposto")
    a("")
    if est["overlay_perfil"]:
        a("Bloco pronto para virar um override de perfil de peça (SPEC-00 §3.2 autoriza "
          "`ritmo.*`, `legenda.*`, `audio.loudness` e `cor.grade`). **É proposta**: quem "
          "grava é a SPEC-24 ou um humano.")
        a("")
        a("```json")
        a(json.dumps(est["overlay_perfil"], ensure_ascii=False, indent=2))
        a("```")
    else:
        a("Vazio — o estado do estilo não autoriza default nenhum.")
    a("")

    a("## Como reproduzir a medição")
    a("")
    a("```bash")
    a("S=.claude/skills/style-extract/scripts")
    for c in est["corpus"]:
        a(f"python3 $S/medir-ref.py {c['fonte']} \\")
        a(f"  --id {c['id']} --objetivo {c['objetivo']} --temperatura {c['temperatura']} "
          f"--dir <corpus>")
    a(f"python3 $S/coerencia.py <corpus>")
    a(f"python3 $S/agregar.py <corpus> --slug {est['slug']} "
      f"--perfil {est['aplica_a']['perfis'][0]}")
    a("```")
    a("")
    a("Os `--marcos` e os `--deep-edit` de cada referência estão gravados na medição "
      "dela (`marcos[]` e `semantico.deep_edit[]`) — copie de lá para reproduzir a "
      "mesma estratificação e a mesma amostragem semântica, sem gastar Gemini de novo.")
    a("")
    return "\n".join(L) + "\n"


def restricoes(est, conf_min=("alta", "media")):
    """As regras verificadas, no formato em que entram num `PLANO-EDICAO.md`.

    O SKILL desta skill já dizia que regra com `conf >= media` vira "restrição
    textual no prompt que gera o PLANO-EDICAO.md, com a evidência anexa" — e
    isso era uma frase, não um comando: alguém teria que reescrever as regras à
    mão, e uma regra reescrita à mão perde o suporte junto.

    Sai colável, com o suporte em cada linha, porque a restrição sem o número
    ao lado vira opinião no meio do plano. Uma referência por regra basta na
    lista; a evidência inteira está no `ESTILO.md`, citado no cabeçalho."""
    L = []
    boas = [r for r in est.get("regras") or [] if r.get("conf") in conf_min]
    L.append("## Restrições de estilo (medidas, não escolhidas)")
    L.append("")
    if not boas:
        L.append("Nenhuma regra do estilo extraído chegou a `conf >= media` — este plano "
                 "não recebe restrição de estilo, e isso é resultado, não omissão.")
        L.append("")
        return "\n".join(L) + "\n"
    L.append(f"De `{est.get('slug')}` ({est.get('n_refs')} referências, coerência "
             f"{(est.get('coerencia') or {}).get('estado')}). A evidência de cada uma "
             f"está no `ESTILO.md` ao lado do `estilo.json`.")
    L.append("")
    for r in boas:
        ev = (r.get("evidencia") or [{}])[0]
        L.append(f"- **{r['texto']}**")
        L.append(f"  - suporte {r['suporte']}/{r['de']} referências · conf {r['conf']} "
                 f"· aplicável por `{r['aplicavel_por']}` · id `{r['id']}`")
        if ev.get("ref"):
            L.append(f"  - ex.: `{ev['ref']}` em {ev.get('t_s', 0):.1f}s — {ev.get('citacao', '')}")
    L.append("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("estilo")
    ap.add_argument("--saida", default=None)
    ap.add_argument("--restricoes", action="store_true",
                    help="imprime só o bloco de restrições para colar no PLANO-EDICAO.md")
    a = ap.parse_args()
    with open(a.estilo, encoding="utf-8") as fh:
        est = json.load(fh)
    if not str(est.get("contrato", "")).startswith("benchmark.estilo-edicao"):
        sys.exit(f"contrato inesperado: {est.get('contrato')!r}")
    if a.restricoes:
        sys.stdout.write(restricoes(est))
        return
    destino = a.saida or os.path.join(os.path.dirname(os.path.abspath(a.estilo)), "ESTILO.md")
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(gerar(est))
    print(destino)


if __name__ == "__main__":
    main()
