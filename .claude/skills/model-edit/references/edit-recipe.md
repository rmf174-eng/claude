# Schema `benchmark.edit-recipe/v1`

Uma receita de edição modelada. Tudo em coordenadas **1080×1920** e segundos.
Campo ausente = não medido (≠ ausente no vídeo). Campo `null` = medido e ausente.

```jsonc
{
  "schema": "benchmark.edit-recipe/v1",
  "fonte": {
    "handle": "ref-D",
    "url": null,
    "tem_bruto": true,              // existe o par bastidor+editado?
    "dur_editado_s": 23.03,
    "dur_bruto_s": 41.50,
    "resolucao": "2160x3840@30"
  },

  "montagem": {
    "n_segmentos": 6,
    "pct_bruto_aproveitado": 33,
    "dur_media_plano_s": 3.3,
    "speed_ramp": false,
    "corte_encostado": true,        // o corte cai na fala, sem respiro
    "pads_estimados_s": {"pre": 0.02, "post": 0.02},
    "corta_dentro_da_palavra": true,// apara a soltura da última sílaba
    "segmentos": [
      {"n": 1, "raw_asr": [0.0, 2.08], "ed_asr": [0.08, 2.0],
       "removido_depois_s": 4.96, "motivo_fim": "pausa cortada",
       "fala": "Você pode parar de tentar ser o melhor."}
    ]
  },

  "planos": [
    {"n": "A", "janela_s": [0.0, 2.0], "zoom": 1.000, "cx": 0.50, "cy": 0.50,
     "nota": "nativo; título por cima"},
    {"n": "B", "janela_s": [2.0, 4.9], "zoom": 1.306, "cx": 0.411, "cy": 0.448}
  ],
  "gramatica_de_plano": "alterna nativo (1.00) e punch-in (1.22–1.31) a cada corte de frase",

  "camadas": [
    {"tipo": "split-screen", "janela_s": [4.9, 12.4],
     "fonte": "b-roll externo", "entrada": "corte seco", "saida": "corte seco",
     "geometria": {"base_desloca_pct": 25, "base_zoom": 1.03,
                   "overlay_opaco_ate_pct": 34, "overlay_fim_pct": 51,
                   "feather_pct": 17, "curva": "smooth"},
     "funcao": "prova visual + esconde 3 jump cuts do trecho mais remendado"}
  ],

  "tipografia": {
    "titulo": {
      "janela_s": [0.2, 2.0], "morre_em": "corte",
      "linhas": [
        {"texto": "PARE DE TENTAR SER", "familia": "grotesca pesada condensada (Anton)",
         "caps": true, "cor": "#fdfbf8", "bbox": [140, 223, 940, 318],
         "font_size": 105, "anim": "type-on com cursor", "fpc": 1.1},
        {"texto": "o melhor", "familia": "serif display itálica (Playfair Display)",
         "cor": "#c0603c", "bbox": [410, 330, 935, 435], "font_size": 130,
         "align": "right", "anim": "pop seco", "at_s": 1.25}
      ],
      "sombra": "0 4px 9px rgba(0,0,0,0.85)",
      "viola_zona_ui": "y<290 (corte 4:5 do feed)"
    },
    "legenda": {
      "familia": "grotesca neutra semibold", "font_size": 70, "cor": "#ffffff",
      "highlight_palavra_ativa": null,
      "y_centro_pct": 79, "palavras_por_pagina": [2, 4],
      "comeca_apos_titulo": true
    }
  },

  "audio": {
    "musica": null, "sfx": null,
    "lufs_integrado": -14.4,
    "piso_p5_db": -33.9, "fala_p80_db": -14.2, "dinamica_db": 19.7,
    "comprime": true,
    "cadeia_equivalente": "acompressor=threshold=-30dB:ratio=6:attack=5:release=150,acompressor=threshold=-30dB:ratio=4:attack=10:release=250,loudnorm=I=-14.4:TP=-1.5"
  },

  "cor": {
    "delta_lum_pct": -5, "delta_sat_pct": 18,
    "cadeia_equivalente": "eq=saturation=1.18:gamma=0.95",
    "cor_destaque_vem_da_cena": true
  },

  "densidade": {
    "cortes": 6, "blocos_broll": 1, "elementos_graficos": 2,
    "elementos_por_10s": 0.9,
    "nota": "muito mais econômico que o sistema ref-C (4–6/10s); a retenção vem do ritmo de corte"
  },

  "replicacao": {
    "feita": true,
    "pasta": "estudos/modelagem-ref-D/",
    "desvios": ["EDL 6% mais longa", "b-roll do teste é recorte da própria referência"]
  }
}
```

## Convenções

- `bbox`: `[x0, y0, x1, y1]` em 1080×1920.
- percentuais de geometria vertical sempre em **% da altura do frame** (portável entre resoluções).
- `null` em `musica`/`sfx`/`highlight_palavra_ativa` significa **medido e ausente** — é
  informação editorial forte ("o estilo dele é sem trilha"), não campo vazio.
- Nomes de fonte: descreva a **classe** ("grotesca pesada condensada") e, entre parênteses, o
  palpite de família. Identificação exata de fonte por imagem não é confiável — a classe é o que
  se reproduz.
