// Tema por creator — TODA cor/fonte dos módulos do MotionKit vem daqui.
// Os componentes nunca hardcodam cor: trocar de creator = trocar o theme.

export type Theme = {
  ink: string; // texto manuscrito, setas, traços
  inkShadow: string; // sombra/glow do manuscrito (legibilidade sobre vídeo)
  highlight: string; // cor de destaque universal (título de passo, palavra ativa)
  stepText: string; // texto do título de passo (sobre highlight)
  postits: Record<string, string>; // paleta SEMÂNTICA: cor = categoria
  cardText: string; // texto dentro de post-its/cartões
  panelBg: string; // painel semi-transparente
  captionBase: string;
  captionActive: string;
};

// Neutro (default dos módulos) — placeholder pra qualquer creator novo.
export const neutralTheme: Theme = {
  ink: "#1A1A1A",
  inkShadow: "rgba(255,255,255,0.55)",
  highlight: "#F0E14A",
  stepText: "#1A1A1A",
  postits: {
    a: "#F9EFC9",
    b: "#C4E4E1",
    c: "#FADADD",
    d: "#D8D3EF",
    e: "#C9E2F7",
  },
  cardText: "#2B2B2B",
  panelBg: "rgba(255,255,255,0.93)",
  captionBase: "#FFFFFF",
  captionActive: "#F0E14A",
};

// creator-2 (creator-2) — tinta BRANCA porque os overlays vivem sobre vídeo
// (luminância medida dos bolsos dela: esquerdo 43–57, direito 90–119 → branco
// com sombra escura tem contraste de sobra). Destaque = rosé da linha editorial.
export const temaRoseSobreVideo: Theme = {
  ink: "#FFFFFF",
  inkShadow: "rgba(0,0,0,0.85)",
  highlight: "#FF8FA3",
  stepText: "#FFFFFF",
  postits: {
    papel: "#FFF8F0", // papelaria creme aprovada na peca-04
    nota: "#FDF1E3",
  },
  cardText: "#3D2B2F",
  panelBg: "rgba(255,248,240,0.96)",
  captionBase: "#FFFFFF",
  captionActive: "#FF8FA3",
};

// ref-C em modo OFERTA (post-ref-C-2, medido 2026-07-29). O amarelo aqui é
// #FCED65 — mais limão e mais claro que o #F0E14A dos vídeos educativos dela.
// Sem paleta semântica de post-it: em vídeo de oferta ela não usa post-it nenhum.
// ⚠️ Esse amarelo único só governa porque a cena dela é ACROMÁTICA (parede
// #cfcfcf, blusa #0f0f2f). Em cenário com cor, remedir com `som-e-cor.py paleta`.
export const temaAmareloOferta: Theme = {
  ...neutralTheme,
  ink: "#111111",
  highlight: "#FCED65",
  captionActive: "#FCED65",
  captionBase: "#FCED65", // a legenda dela é uma palavra por vez, toda em amarelo
};

// Tema do estudo de referência ref-C — hexes medidos na modelagem.
export const temaEstudoOferta: Theme = {
  ...neutralTheme,
  ink: "#141414",
  highlight: "#F0E14A",
  postits: {
    rotina: "#F9EFC9",
    autoridade: "#C4E4E1",
    leve: "#FADADD",
    bastidores: "#D8D3EF",
    denso: "#C9E2F7",
  },
};
