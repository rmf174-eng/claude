import React, { useMemo } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";
import { loadFont as loadPlayfair } from "@remotion/google-fonts/PlayfairDisplay";
import { ajustarUmaLinha } from "./texto/medida";

/**
 * HookTitle — gancho tipográfico de abertura: uma linha de GROTESCA PESADA
 * CONDENSADA em caps que se DIGITA (com cursor), e uma linha de SERIF ITÁLICA
 * colorida que entra em POP SECO logo depois, sobrepondo a primeira.
 *
 * Medido no ref-D (data/adhoc/modelagem-edicao/RECEITA-EDICAO.md):
 *   linha 1  Anton-like, caps, #fdfbf8, caixa ~95px (font ~130px), y 223–318, centrada
 *            type-on de 18 chars em ~0,65s (≈1,1 frame por char) com cursor "|" visível
 *   linha 2  Playfair Display Italic, #c0603c, y 332–460, POP SECO em t≈1,25s (sem fade)
 *   ambas    drop shadow escuro forte; morrem no corte (não animam a saída)
 *
 * ⚠️ Zona de UI: na referência o título fica em y 223–460, ou seja INVADE a faixa
 * y<290 que a nossa regra reserva (o corte 4:5 do feed come o topo). Em Reel de tela
 * cheia funciona; se o vídeo também for pro feed, empurre `y` pra >=300.
 *
 * 🎨 A cor de destaque da referência é a PAREDE dele mais clara e mais saturada
 * (parede #6e4227 → destaque #c0603c, mesma família de matiz). Use
 * `scripts/cor-da-cena.py` pra amostrar do próprio frame em vez de chutar.
 */

const anton = loadAnton();
const playfair = loadPlayfair("italic", { weights: ["700"], subsets: ["latin"] });

export type HookTitleProps = {
  linha1: string;
  linha2?: string;
  /** quando o type-on começa, em segundos do vídeo */
  startS?: number;
  /** frames por caractere digitado (1.1 = ritmo da referência) */
  fpc?: number;
  /** quando a linha 2 entra (segundos absolutos). default: fim da digitação + 0.4s */
  linha2AtS?: number;
  y?: number;
  fontSize1?: number;
  fontSize2?: number;
  cor1?: string;
  cor2?: string;
  /** deslocamento vertical da linha 2 em relação ao fim da linha 1 (px, pode ser negativo p/ sobrepor) */
  gap2?: number;
  /**
   * Alinhamento da linha 2. Na referência ela é **alinhada à DIREITA** com a linha 1
   * (as duas terminam em x≈940) — o degrau assimétrico é o que dá o ar de "assinatura"
   * manuscrita. Centralizar as duas linhas achata o efeito.
   */
  align2?: "center" | "right" | "left";
  /** margem lateral da linha 2 quando align2 != center (px). 140 = borda direita da linha 1 na referência */
  inset2?: number;
  sombra?: string;
  /**
   * SPEC-13 §3.7 — OPT-IN, default `false`. Com `ajustar`, `fontSize1` e
   * `fontSize2` deixam de ser tamanho fixo e viram TETO: cada linha passa por
   * `ajustarUmaLinha` com a SUA medida (linha 1 Anton caps com `letterSpacing`
   * +1; linha 2 Playfair 700 ITÁLICO), e um gancho longo demais encolhe em vez
   * de transbordar.
   *
   * ⚠️ Quem liga isto tem que garantir que as fontes já carregaram — a medição
   * usa `validateFontIsLoaded: true` e LANÇA se o browser ainda estiver no
   * fallback. Com `ajustar={false}` (o default) nada é medido e a saída é a
   * mesma de sempre.
   *
   * ❌ `duasLinhas` NÃO é aplicado aqui, de propósito: equilibrar largura entre
   * uma grotesca caps e uma serif itálica destrói o degrau assimétrico descrito
   * no comentário de `align2`, e as duas linhas do gancho são semanticamente
   * diferentes (afirmação + assinatura), não uma frase quebrada.
   */
  ajustar?: boolean;
  /** fração da largura do canvas que serve de orçamento para cada linha */
  orcamentoPct?: number;
  /** piso do ajuste, como fração do teto — impede o gancho de virar corpo de texto */
  pisoPct?: number;
};

export const writeSeconds = (texto: string, fpc = 1.1, fps = 30) =>
  (texto.length * fpc) / fps;

export const HookTitle: React.FC<HookTitleProps> = ({
  linha1,
  linha2,
  startS = 0.2,
  fpc = 1.1,
  linha2AtS,
  y = 223,
  fontSize1 = 128,
  fontSize2 = 150,
  cor1 = "#fdfbf8",
  cor2 = "#c0603c",
  gap2 = -34,
  align2 = "right",
  inset2 = 140,
  sombra = "0 4px 9px rgba(0,0,0,0.85)",
  ajustar = false,
  orcamentoPct = 0.83,
  pisoPct = 0.4,
}) => {
  const frame = useCurrentFrame();
  // 📐 SPEC-00 §3.1: o `width: 1080` que estava cravado aqui era literal de
  // formato. A largura vem do CANVAS QUE ESTÁ SENDO RENDERIZADO, não de
  // `PERFIL.video.largura` — e a diferença não é acadêmica: `src/data/perfil.json`
  // é o snapshot da ÚLTIMA produção resolvida (hoje um longform 1920×1080),
  // enquanto `RefDGraphics` (Root.tsx:177-182) é 1080×1920. Ler o PERFIL aqui
  // colocaria um bloco de 1920 px dentro de um quadro de 1080.
  const { fps, width: larguraCanvas } = useVideoConfig();
  const t = frame / fps;

  const nChars = Math.max(
    0,
    Math.min(linha1.length, Math.floor(((t - startS) * fps) / fpc))
  );
  const digitando = t >= startS && nChars < linha1.length;
  // cursor pisca a ~3Hz enquanto digita e some quando a palavra fecha
  const cursorOn = digitando && Math.floor(t * 6) % 2 === 0;

  const fimDigitacao = startS + writeSeconds(linha1, fpc, fps);
  const t2 = linha2AtS ?? fimDigitacao + 0.4;
  const mostraL2 = linha2 !== undefined && t >= t2;

  /**
   * ⚠️ A medida é da STRING COMPLETA de `linha1`, nunca do prefixo do frame
   * corrente. Medir `linha1.slice(0, nChars)` faria a fonte CRESCER durante a
   * digitação. Por isso também está num `useMemo` que não depende de `frame`.
   */
  const [tam1, tam2] = useMemo<[number, number]>(() => {
    if (!ajustar) return [fontSize1, fontSize2];
    const orcamento = orcamentoPct * larguraCanvas;
    return [
      ajustarUmaLinha(
        linha1,
        { familia: anton.fontFamily, tamanho: fontSize1, entreletras: 1, caixa: "uppercase" },
        orcamento,
        fontSize1,
        Math.round(fontSize1 * pisoPct)
      ),
      linha2 === undefined
        ? fontSize2
        : ajustarUmaLinha(
            linha2,
            { familia: playfair.fontFamily, peso: 700, italico: true, tamanho: fontSize2 },
            orcamento,
            fontSize2,
            Math.round(fontSize2 * pisoPct)
          ),
    ];
  }, [ajustar, linha1, linha2, fontSize1, fontSize2, orcamentoPct, pisoPct, larguraCanvas]);

  if (t < startS) return null;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          top: y,
          left: 0,
          width: larguraCanvas,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontFamily: anton.fontFamily,
            fontSize: tam1,
            lineHeight: 0.98,
            color: cor1,
            letterSpacing: 1,
            textShadow: sombra,
            whiteSpace: "pre",
          }}
        >
          {linha1.slice(0, nChars)}
          {/* o cursor NÃO pode empurrar o texto: fica em posição absoluta */}
          <span style={{ position: "relative" }}>
            <span
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                opacity: cursorOn ? 1 : 0,
                fontWeight: 400,
              }}
            >
              |
            </span>
          </span>
        </div>
        {mostraL2 ? (
          <div
            style={{
              textAlign: align2,
              paddingRight: align2 === "right" ? inset2 : 0,
              paddingLeft: align2 === "left" ? inset2 : 0,
              marginTop: gap2,
              fontFamily: playfair.fontFamily,
              fontStyle: "italic",
              fontWeight: 700,
              fontSize: tam2,
              lineHeight: 1,
              color: cor2,
              textShadow: sombra,
            }}
          >
            {linha2}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

/** Variante que some com fade (quando NÃO há corte pra matar o título). */
export const HookTitleFade: React.FC<HookTitleProps & { fadeAtS: number }> = ({
  fadeAtS,
  ...p
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const op = interpolate(frame / fps, [fadeAtS, fadeAtS + 0.25], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ opacity: op }}>
      <HookTitle {...p} />
    </AbsoluteFill>
  );
};
