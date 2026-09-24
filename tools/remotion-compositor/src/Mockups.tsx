import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FONTS } from "./MotionKit";
import { Theme, neutralTheme } from "./themes";

// ————————————————————————————————————————————————————————————————
// Mockups de UI (v2 — calibrados pela análise frame a frame da referência,
// estudos/edicao-ref-C/): janela estilo macOS com checkboxes que vão
// MARCANDO, lista estilo app de mensagens que entra vazia e POVOA, banner
// de ligação estilo iOS, card de evento, calendário fullscreen com pan.
// Conteúdo/timing via props; estética de sistema (SF-like via sans do kit).
// ————————————————————————————————————————————————————————————————

// ——— chrome de janela macOS (semáforo + toolbar fake) ————————————————
const TrafficLights: React.FC = () => (
  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
    {["#FF5F57", "#FEBC2E", "#28C840"].map((c) => (
      <div key={c} style={{ width: 14, height: 14, borderRadius: "50%", background: c }} />
    ))}
  </div>
);

export const MacWindow: React.FC<{
  delayS: number;
  x: number;
  y: number;
  w: number;
  enter?: "slide-right" | "slide-up" | "pop";
  children: React.ReactNode;
}> = ({ delayS, x, y, w, enter = "slide-right", children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - delayS * fps;
  const p = spring({ frame: t, fps, config: { damping: 15, stiffness: 170 } });
  const dx = enter === "slide-right" ? (1 - p) * 220 : 0;
  const dy = enter === "slide-up" ? (1 - p) * 160 : 0;
  const scale = enter === "pop" ? p : 1;
  return (
    <div
      style={{
        position: "absolute",
        left: x + dx,
        top: y + dy,
        width: w,
        transform: `scale(${scale})`,
        opacity: p,
        background: "white",
        borderRadius: 14,
        boxShadow: "0 16px 44px rgba(0,0,0,0.26)",
        overflow: "hidden",
        fontFamily: FONTS.sans,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "12px 16px 8px",
        }}
      >
        <TrafficLights />
        <div style={{ display: "flex", gap: 12, opacity: 0.45 }}>
          <IconShare />
          <IconDots />
        </div>
      </div>
      {children}
    </div>
  );
};

const IconShare: React.FC = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#666" strokeWidth="2">
    <path d="M12 3v12M8 7l4-4 4 4M5 12v7h14v-7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IconDots: React.FC = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="#666">
    <circle cx="5" cy="12" r="2" />
    <circle cx="12" cy="12" r="2" />
    <circle cx="19" cy="12" r="2" />
  </svg>
);

// ——— checklist estilo Reminders: checkboxes CIRCULARES marcando um a um ———
export const MacChecklistMock: React.FC<{
  delayS: number;
  x: number;
  y: number;
  w?: number;
  rows: string[];
  checksAtS?: number[]; // quando cada linha é MARCADA (rel. ao pai; ordem das rows)
  accent?: string; // azul sistema
  enter?: "slide-right" | "slide-up" | "pop";
}> = ({ delayS, x, y, w = 420, rows, checksAtS = [], accent = "#2F7CF6", enter = "slide-right" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <MacWindow delayS={delayS} x={x} y={y} w={w} enter={enter}>
      <div style={{ padding: "6px 20px 18px" }}>
        {rows.map((text, i) => {
          const checkAt = checksAtS[i];
          const c =
            checkAt != null
              ? spring({
                  frame: frame - checkAt * fps,
                  fps,
                  config: { damping: 11, stiffness: 260 },
                })
              : 0;
          const checked = c > 0.05;
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                padding: "11px 0",
                borderBottom: i < rows.length - 1 ? "1px solid #EFEFEF" : "none",
              }}
            >
              <div
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: "50%",
                  border: `2.5px solid ${checked ? accent : "#B9C0CB"}`,
                  background: checked ? accent : "white",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  transform: `scale(${checked ? 0.9 + 0.1 * c : 1})`,
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" style={{ opacity: c }}>
                  <path
                    d="M5 12.5l4.2 4L19 7"
                    fill="none"
                    stroke="white"
                    strokeWidth="3.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
              <div style={{ fontSize: 27, fontWeight: 500, color: "#3A3A3C" }}>{text}</div>
            </div>
          );
        })}
      </div>
    </MacWindow>
  );
};

// ——— lista estilo app de mensagens: entra e POVOA row a row ————————————
export const MessengerListMock: React.FC<{
  delayS: number;
  x: number;
  y: number;
  w?: number;
  header?: string;
  headerColor?: string;
  rows: { name: string; preview?: string; badge?: number }[];
  rowsAtS?: number[]; // quando cada conversa APARECE (rel. ao pai)
}> = ({ delayS, x, y, w = 400, header = "Mensagens", headerColor = "#22B357", rows, rowsAtS = [] }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - delayS * fps;
  const p = spring({ frame: t, fps, config: { damping: 15, stiffness: 170 } });
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y + (1 - p) * 160,
        width: w,
        opacity: p,
        background: "white",
        borderRadius: 16,
        boxShadow: "0 16px 44px rgba(0,0,0,0.26)",
        overflow: "hidden",
        fontFamily: FONTS.sans,
      }}
    >
      <div
        style={{
          background: headerColor,
          color: "white",
          fontWeight: 700,
          fontSize: 26,
          padding: "12px 18px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>{header}</span>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.4">
          <circle cx="11" cy="11" r="7" />
          <path d="M16.5 16.5L21 21" strokeLinecap="round" />
        </svg>
      </div>
      <div style={{ padding: "4px 16px 10px" }}>
        {rows.map((r, i) => {
          const at = rowsAtS[i] ?? 0;
          const rp = spring({
            frame: frame - at * fps,
            fps,
            config: { damping: 13, stiffness: 240 },
          });
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 14,
                padding: "10px 0",
                borderBottom: i < rows.length - 1 ? "1px solid #F0F0F0" : "none",
                opacity: rp > 0.04 ? 1 : 0,
                transform: `translateY(${(1 - rp) * 14}px)`,
              }}
            >
              <div
                style={{
                  width: 52,
                  height: 52,
                  borderRadius: "50%",
                  background: "#D8DCE1",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <svg width="30" height="30" viewBox="0 0 24 24" fill="#9AA1A9">
                  <circle cx="12" cy="8.2" r="4.2" />
                  <path d="M4 20c1.4-3.6 4.4-5.4 8-5.4s6.6 1.8 8 5.4" />
                </svg>
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 25, fontWeight: 700, color: "#1C1C1E" }}>{r.name}</div>
                <div
                  style={{
                    fontSize: 20,
                    color: "#8E8E93",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {r.preview ?? "Enviou uma mensagem"}
                </div>
              </div>
              {r.badge ? (
                <div
                  style={{
                    background: headerColor,
                    color: "white",
                    borderRadius: 999,
                    minWidth: 30,
                    height: 30,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 18,
                    fontWeight: 800,
                    padding: "0 7px",
                  }}
                >
                  {r.badge}
                </div>
              ) : (
                <div
                  style={{ width: 14, height: 14, borderRadius: "50%", background: headerColor }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ——— banner de ligação estilo iOS ————————————————————————————————
// mode "incoming": botões circulares vermelho/verde; "missed": ícone
// vermelho + subtítulo "Ligação perdida".
const PhoneGlyph: React.FC<{ color?: string; down?: boolean }> = ({ color = "white", down }) => (
  <svg
    width="22"
    height="22"
    viewBox="0 0 24 24"
    style={down ? { transform: "rotate(135deg)" } : undefined}
  >
    <path
      d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.8 21 3 13.2 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.2.2 2.4.6 3.6.1.3 0 .7-.2 1l-2.3 2.2z"
      fill={color}
    />
  </svg>
);

export const CallBannerMock: React.FC<{
  delayS: number;
  x: number;
  y: number;
  w?: number;
  name: string;
  mode?: "incoming" | "missed";
  subtitle?: string;
}> = ({ delayS, x, y, w = 400, name, mode = "incoming", subtitle }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({
    frame: frame - delayS * fps,
    fps,
    config: { damping: 14, stiffness: 200 },
  });
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y + (1 - p) * 60,
        width: w,
        opacity: p,
        background: "white",
        borderRadius: 22,
        boxShadow: "0 14px 38px rgba(0,0,0,0.24)",
        padding: "14px 18px",
        display: "flex",
        alignItems: "center",
        gap: 14,
        fontFamily: FONTS.sans,
      }}
    >
      {mode === "missed" ? (
        <div
          style={{
            width: 46,
            height: 46,
            borderRadius: "50%",
            background: "#FCE8E6",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <PhoneGlyph color="#E0453A" down />
        </div>
      ) : (
        <div
          style={{
            width: 46,
            height: 46,
            borderRadius: "50%",
            background: "#D8DCE1",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <svg width="26" height="26" viewBox="0 0 24 24" fill="#9AA1A9">
            <circle cx="12" cy="8.2" r="4.2" />
            <path d="M4 20c1.4-3.6 4.4-5.4 8-5.4s6.6 1.8 8 5.4" />
          </svg>
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 25, fontWeight: 700, color: mode === "missed" ? "#E0453A" : "#1C1C1E" }}>
          {name}
        </div>
        <div style={{ fontSize: 19, color: "#8E8E93" }}>
          {subtitle ?? (mode === "missed" ? "Ligação perdida" : "Ligando…")}
        </div>
      </div>
      {mode === "incoming" ? (
        <div style={{ display: "flex", gap: 12 }}>
          <div
            style={{
              width: 46,
              height: 46,
              borderRadius: "50%",
              background: "#E0453A",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <PhoneGlyph down />
          </div>
          <div
            style={{
              width: 46,
              height: 46,
              borderRadius: "50%",
              background: "#34C759",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <PhoneGlyph />
          </div>
        </div>
      ) : null}
    </div>
  );
};

// ——— card de evento (calendário) ————————————————————————————————
export const EventCardMock: React.FC<{
  delayS: number;
  x: number;
  y: number;
  label: string;
  accent?: string;
}> = ({ delayS, x, y, label, accent = "#3478F6" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({
    frame: frame - delayS * fps,
    fps,
    config: { damping: 13, stiffness: 220 },
  });
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y + (1 - p) * 40,
        opacity: p,
        background: "white",
        borderRadius: 16,
        boxShadow: "0 12px 32px rgba(0,0,0,0.22)",
        padding: "12px 18px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        fontFamily: FONTS.sans,
      }}
    >
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: 10,
          background: accent,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2">
          <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" />
          <path d="M3.5 9.5h17M8 3v3.6M16 3v3.6" strokeLinecap="round" />
        </svg>
      </div>
      <div style={{ fontSize: 23, fontWeight: 700, color: "#1C1C1E" }}>{label}</div>
    </div>
  );
};

// ——— calendário FULLSCREEN semi-transparente com pan (painel do passo 1) ———
export const BigCalendarMock: React.FC<{
  delayS: number;
  panPx?: number; // deslocamento horizontal total durante a vida do painel
  opacity?: number;
  theme?: Theme;
}> = ({ delayS, panPx = 220, opacity = 0.88, theme = neutralTheme }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = frame - delayS * fps;
  const fade = interpolate(t, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const pan = interpolate(frame, [delayS * fps, durationInFrames], [0, -panPx], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const palette = Object.values(theme.postits);
  const DOW = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM", "SEG", "TER"];
  const LABELS = [
    "5 tipos de post que todo perfil precisa",
    "Rotina + dia de gravação em lote",
    "Bastidores da mesa de planejamento",
    "COLLAB: 3 mudanças no consumidor",
    "Tudo que você recebe no curso",
    "Respondendo a caixinha de ontem",
    "Case: de 0 a 10k com planejamento",
    "PUBLI: a ferramenta que organiza",
    "Quiz: você já criou sua estratégia?",
    "Dica rápida: onde buscar referências",
    "Depoimento real de quem aplicou",
    "Sábado leve: recarregar a criatividade",
    "Últimas vagas — link na bio",
    "Enquete: tema da próxima semana?",
    "Diário de uma segunda de criadora",
    "Como equilibrar denso e leve",
    "Testando formato novo no feed",
    "DESCANSO",
  ];
  const TAGS = ["DENSO", "LEVE"];
  return (
    <AbsoluteFill style={{ opacity: fade * opacity, fontFamily: FONTS.sans }}>
      <div
        style={{
          position: "absolute",
          inset: -40,
          background: "rgba(250,249,246,0.72)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          display: "flex",
          gap: 12,
          transform: `translateX(${pan}px)`,
          padding: "0 8px",
        }}
      >
        {DOW.map((dow, col) => (
          <div key={col} style={{ width: 200, flexShrink: 0 }}>
            <div
              style={{
                background: "#26262B",
                color: "white",
                borderRadius: 10,
                textAlign: "center",
                padding: "10px 0",
                fontWeight: 800,
                fontSize: 22,
                letterSpacing: 2,
                marginBottom: 10,
              }}
            >
              {dow} <span style={{ opacity: 0.55 }}>{String(col + 1).padStart(2, "0")}</span>
            </div>
            {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((row) => {
              const label = LABELS[(col * 5 + row * 3) % LABELS.length];
              const isRest = label === "DESCANSO";
              return (
                <div
                  key={row}
                  style={{
                    background: isRest ? "rgba(0,0,0,0.06)" : palette[(col + row) % palette.length],
                    borderRadius: 8,
                    padding: "9px 10px",
                    marginBottom: 8,
                    fontSize: 16.5,
                    fontWeight: 600,
                    color: isRest ? "#8A8A8E" : "#333",
                    lineHeight: 1.25,
                  }}
                >
                  {label}
                  {!isRest ? (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 11,
                        fontWeight: 800,
                        letterSpacing: 1.5,
                        color: "#5B5B60",
                      }}
                    >
                      ● {TAGS[(col + row) % 2]}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ——— calendário semanal compacto (conteúdo de PanelLite) ————————————
export const WeekCalendarMock: React.FC<{
  days: { name: string; cards?: { text: string; color?: string }[] }[];
  theme?: Theme;
}> = ({ days, theme = neutralTheme }) => {
  const palette = Object.values(theme.postits);
  return (
    <div style={{ display: "flex", gap: 14, height: "100%", fontFamily: FONTS.sans }}>
      {days.map((d, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            background: "rgba(0,0,0,0.045)",
            borderRadius: 14,
            padding: 10,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <div
            style={{
              textAlign: "center",
              fontWeight: 800,
              fontSize: 24,
              color: "#555",
              letterSpacing: 2,
            }}
          >
            {d.name}
          </div>
          {(d.cards ?? []).map((c, j) => (
            <div
              key={j}
              style={{
                background: c.color ?? palette[(i + j) % palette.length],
                borderRadius: 8,
                fontSize: 19,
                fontWeight: 700,
                color: "#333",
                padding: "8px 8px",
                textAlign: "center",
              }}
            >
              {c.text}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
};

// ——— folha de caderno pautado ————————————————————————————————————
export const NotebookPageMock: React.FC<{
  delayS: number;
  x: number;
  y: number;
  w: number;
  h: number;
  children?: React.ReactNode;
}> = ({ delayS, x, y, w, h, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({
    frame: frame - delayS * fps,
    fps,
    config: { damping: 17, stiffness: 150 },
  });
  return (
    <div
      style={{
        position: "absolute",
        left: x + (1 - p) * -120,
        top: y,
        width: w,
        height: h,
        opacity: p,
        background:
          "repeating-linear-gradient(180deg, #FDFCF8 0px, #FDFCF8 46px, #DDE7F0 47px)",
        borderRadius: 10,
        boxShadow: "0 12px 34px rgba(0,0,0,0.25)",
        borderLeft: "3px solid #F5B7B1",
        padding: "18px 22px 18px 34px",
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
};
