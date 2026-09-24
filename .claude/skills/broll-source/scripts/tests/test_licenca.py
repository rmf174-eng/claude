#!/usr/bin/env python3
"""test_licenca — a tabela do gate, mais o acervo REAL medido no Commons.

Roda sozinho (`python3 tests/test_licenca.py`), sem pytest e SEM REDE: as 24 strings
de licença abaixo são as que a API do Commons devolveu em 2026-08-08 para duas
consultas (`filetype:bitmap Cristo Redentor` e `filetype:bitmap Neymar`, 12 cada).
Ficam aqui como fixture para o teste continuar valendo quando o acervo mudar.

O que ele prova, nesta ordem:
  1. `licenca.autoteste()` passa (a tabela de 21 casos + os dois controles negativos);
  2. sobre o acervo real, o gate CONSERTADO aprova 11 de 24 e reprova os 13 `CC BY-SA`;
  3. sobre o mesmo acervo, o predicado de HOJE (`any(t in lic.lower() for t in
     ("cc0","public domain","cc by"))`, que é literalmente `buscar.py:124` antes desta
     spec) aprova **24 de 24** — inclusive os 13 BY-SA que o comentário ao lado dele
     promete cortar. É o defeito §1.2 da SPEC-29, executável.

Se (3) parar de vazar, o teste sai 1: significa que a fixture deixou de cobrir o
defeito que a spec conserta, e um verde aqui não valeria nada.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import licenca as L   # noqa: E402

# --- acervo REAL, 24 respostas (2026-08-08) --------------------------------
# Cristo Redentor: CC BY 3.0 ×2 · CC BY 4.0 ×2 · CC BY-SA 3.0 de ×1 · CC BY-SA 4.0 ×7
# Neymar:          CC0 ×1 · Public domain ×1 · CC BY 2.0 ×3 · CC BY 3.0 ×1 ·
#                  CC BY 4.0 ×1 · CC BY-SA 2.0 ×2 · CC BY-SA 4.0 ×3
ACERVO = (["CC BY 3.0"] * 2 + ["CC BY 4.0"] * 2 + ["CC BY-SA 3.0 de"] + ["CC BY-SA 4.0"] * 7
          + ["CC0", "Public domain"] + ["CC BY 2.0"] * 3 + ["CC BY 3.0", "CC BY 4.0"]
          + ["CC BY-SA 2.0"] * 2 + ["CC BY-SA 4.0"] * 3)

APROVADOS_ESPERADOS = 11      # 3×BY3.0 + 3×BY4.0 + 3×BY2.0 + CC0 + PD
BYSA_ESPERADOS = 13


def predicado_de_hoje(lic):
    """buscar.py:124 antes da SPEC-29 — substring de FAMÍLIA, e é o bug."""
    return any(t in lic.lower() for t in ("cc0", "public domain", "cc by"))


def main():
    falhas = []
    print("— tabela do gate —")
    if L.autoteste() != 0:
        falhas.append("licenca.autoteste() saiu 1")

    print(f"\n— acervo real: {len(ACERVO)} licenças —")
    aprovados = [l for l in ACERVO if L.aprovado(L.classificar(l))[0]]
    bysa = [l for l in ACERVO if L.classificar(l)["slug"] == "cc-by-sa"]
    vazam_hoje = [l for l in ACERVO if predicado_de_hoje(l)]
    print(f"gate consertado:  {len(aprovados)}/{len(ACERVO)} aprovados")
    print(f"cláusula SA:      {len(bysa)}/{len(ACERVO)} reprovados por viralidade")
    print(f"predicado de HOJE:{len(vazam_hoje)}/{len(ACERVO)} aprovados  ← o defeito")

    if len(ACERVO) != 24:
        falhas.append(f"fixture com {len(ACERVO)} entradas, esperava 24")
    if len(aprovados) != APROVADOS_ESPERADOS:
        falhas.append(f"aprovados={len(aprovados)}, esperava {APROVADOS_ESPERADOS}")
    if len(bysa) != BYSA_ESPERADOS:
        falhas.append(f"cc-by-sa={len(bysa)}, esperava {BYSA_ESPERADOS}")
    if len(vazam_hoje) != len(ACERVO):
        falhas.append(f"CONTROLE SEM DENTES: o predicado de hoje aprovou "
                      f"{len(vazam_hoje)}/{len(ACERVO)} — a fixture deixou de cobrir o defeito")
    # nenhum aprovado pode ser viral, em nenhuma circunstância
    for l in aprovados:
        if L.classificar(l)["viral"]:
            falhas.append(f"licença viral aprovada: {l!r}")

    if falhas:
        print(f"\n{len(falhas)} FALHA(S):")
        for f in falhas:
            print("  ✗ " + f)
        return 1
    print("\ntest_licenca: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
