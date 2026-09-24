// As 4 PLACAS do preview do catálogo — fundos sintéticos, desenhados (SPEC-15 §3.6).
//
// 🔴 Nada de footage. Nem bruto de creator, nem `public/v1-montado.mp4`, nem
// `staticFile` de coisa nenhuma. Um preview de produto que carrega o rosto de
// uma creator vaza material de cliente para dentro do pacote — e nenhum detector
// de "mídia > 1 MB" acusaria 33 webm de 200 KB (FRONTEIRA §4).
//
// 📐 Nenhuma dimensão literal aqui: tudo sai de `PERFIL` (SPEC-00 §3.1).
// A placa é um FUNDO; o canvas é sempre o do perfil de peça.

import React from "react";
import { AbsoluteFill } from "remotion";
import { W, H } from "../perfil";
import type { Placa as TipoPlaca } from "./tipos";

/**
 * Rampa de luminância da placa `retrato`: o fundo vai de escuro (topo) a claro
 * (base) para a legenda ser julgada sobre os dois. Os extremos vêm da spec
 * (0,15 → 0,55 de luminância relativa).
 */
const LUM_TOPO = 0.15;
const LUM_BASE = 0.55;
const cinza = (l: number) => {
  const v = Math.round(l * 255);
  return `rgb(${v},${v},${v})`;
};

const PlacaVazia: React.FC = () => {
  /* A placa "não há cena aqui".
   *
   * Era um XADREZ de quadrados preenchidos (0,32 × 0,38 de luminância, 12
   * colunas) — exatamente o desenho que editor de imagem usa para dizer
   * "transparente". Medido na tela em 2026-08-11, no card `split-screen-esfumaçado`
   * (a única entrada que mostra esta placa NUA): o creator lê "esta metade está
   * vazia/quebrada", quando a frase é "aqui entra outro material".
   *
   * 🔴 O QUE NÃO PODE SE PERDER, e é por isso que isto não virou uma chapa lisa:
   * a decisão original está medida em `Preview.tsx:215-218` — com duas placas em
   * DEGRADÊ o split ficava invisível no card, porque a máscara corta justo na
   * faixa uniforme. A placa precisa continuar sendo outra COISA, não outro tom.
   *
   * Grade de LINHAS finas sobre chapa plana: mantém a diferença de caráter contra
   * qualquer degradê (é o que a medição pedia) e lê como espaço reservado, que é o
   * que ela é. Linha em vez de quadrado preenchido também tem menos borda, e
   * borda é o que pesa em VP9. */
  const passo = Math.round(W / 6);
  return (
    <AbsoluteFill style={{ background: cinza(0.3) }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <defs>
          <pattern
            id="grade-vazia"
            width={passo}
            height={passo}
            patternUnits="userSpaceOnUse"
          >
            <path
              d={`M ${passo} 0 L 0 0 0 ${passo}`}
              fill="none"
              stroke={cinza(0.4)}
              strokeWidth={Math.max(1, Math.round(W / 360))}
            />
          </pattern>
        </defs>
        <rect x={0} y={0} width={W} height={H} fill="url(#grade-vazia)" />
      </svg>
    </AbsoluteFill>
  );
};

const PlacaRetrato: React.FC = () => {
  // silhueta de meio-corpo centrada, do jeito que um talking-head ocupa o quadro
  const cx = W / 2;
  const rCabeca = W * 0.115;
  const yCabeca = H * 0.3;
  const yOmbro = yCabeca + rCabeca * 1.55;
  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, ${cinza(LUM_TOPO)} 0%, ${cinza(
          (LUM_TOPO + LUM_BASE) / 2
        )} 55%, ${cinza(LUM_BASE)} 100%)`,
      }}
    >
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <ellipse
          cx={cx}
          cy={yCabeca}
          rx={rCabeca}
          ry={rCabeca * 1.22}
          fill={cinza(0.62)}
        />
        <path
          d={`M ${cx - W * 0.28} ${H} C ${cx - W * 0.26} ${yOmbro} ${
            cx - W * 0.12
          } ${yOmbro - rCabeca * 0.2} ${cx} ${yOmbro - rCabeca * 0.25} C ${
            cx + W * 0.12
          } ${yOmbro - rCabeca * 0.2} ${cx + W * 0.26} ${yOmbro} ${
            cx + W * 0.28
          } ${H} Z`}
          fill={cinza(0.62)}
        />
      </svg>
    </AbsoluteFill>
  );
};

const PlacaPaisagem: React.FC = () => {
  const horizonte = H * 0.58;
  return (
    <AbsoluteFill style={{ background: cinza(0.2) }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <rect x={0} y={0} width={W} height={horizonte} fill={cinza(0.46)} />
        <rect
          x={0}
          y={horizonte}
          width={W}
          height={H - horizonte}
          fill={cinza(0.24)}
        />
        <path
          d={`M 0 ${horizonte} L ${W * 0.22} ${horizonte - H * 0.09} L ${
            W * 0.44
          } ${horizonte} Z`}
          fill={cinza(0.34)}
        />
        <path
          d={`M ${W * 0.34} ${horizonte} L ${W * 0.62} ${
            horizonte - H * 0.13
          } L ${W} ${horizonte} Z`}
          fill={cinza(0.3)}
        />
      </svg>
    </AbsoluteFill>
  );
};

const PlacaScreencast: React.FC = () => {
  const jx = W * 0.08;
  const jw = W * 0.84;
  const jy = H * 0.26;
  const jh = H * 0.42;
  const barra = jh * 0.11;
  return (
    <AbsoluteFill style={{ background: cinza(0.14) }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <rect
          x={jx}
          y={jy}
          width={jw}
          height={jh}
          rx={W * 0.02}
          fill={cinza(0.92)}
        />
        <rect
          x={jx}
          y={jy}
          width={jw}
          height={barra}
          rx={W * 0.02}
          fill={cinza(0.78)}
        />
        {[0, 1, 2].map((i) => (
          <circle
            key={i}
            cx={jx + barra * (0.55 + i * 0.5)}
            cy={jy + barra / 2}
            r={barra * 0.16}
            fill={cinza(0.55)}
          />
        ))}
        {[0, 1, 2, 3, 4].map((i) => (
          <rect
            key={i}
            x={jx + jw * 0.07}
            y={jy + barra + jh * (0.13 + i * 0.14)}
            width={jw * (i % 2 === 0 ? 0.7 : 0.48)}
            height={jh * 0.055}
            rx={jh * 0.027}
            fill={cinza(0.72)}
          />
        ))}
      </svg>
    </AbsoluteFill>
  );
};

export const Placa: React.FC<{ tipo: TipoPlaca }> = ({ tipo }) => {
  switch (tipo) {
    case "retrato":
      return <PlacaRetrato />;
    case "paisagem":
      return <PlacaPaisagem />;
    case "screencast":
      return <PlacaScreencast />;
    case "vazia":
    default:
      return <PlacaVazia />;
  }
};
