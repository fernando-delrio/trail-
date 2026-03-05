import React, { useEffect, useRef, useState } from "react";
import { useUser } from "../context/UserContext";
import { session } from "../services/session";




const DEFAULT_MESSAGES = [
  {
    role: "assistant",
    content:
      "👋 Soy GASTACOBRE. Puedo ayudarte a elegir tu próxima bici o recomendarte rutas por zona y terreno (gravel, XC, trail, enduro, downhill, carretera). ¿Qué necesitas?",
  },
];

// Contexto inicial
const DEFAULT_CONTEXT = {
  mode: null,
  budget: null,
  budget_min: null,
  budget_max: null,
  exclude_modes: [],
  preferred_brands: [],
  excluded_brands: [],
  tags: [],
};

function normalize(str) {
  return (str || "").toLowerCase().trim();
}


function renderTextWithLinks(text) {
  if (!text) return null;

  const mdLink = new RegExp(String.raw`\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)`, "g");
  const urlRx = new RegExp(String.raw`(https?:\/\/[^\s]+)|(\bwww\.[^\s]+)`, "g");

  // 1) trocear por markdown links
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = mdLink.exec(text)) !== null) {
    const full = match[0];
    const label = match[1];
    const url = match[2];
    const start = match.index;

    if (start > lastIndex) {
      parts.push({ type: "text", value: text.slice(lastIndex, start) });
    }
    parts.push({ type: "link", label, url });
    lastIndex = start + full.length;
  }

  if (lastIndex < text.length) {
    parts.push({ type: "text", value: text.slice(lastIndex) });
  }

  // 2) dentro de cada "text", linkificar urls peladas
  const nodes = [];
  let key = 0;

  for (const p of parts) {
    if (p.type === "link") {
      nodes.push(
        <a
          key={`md-${key++}`}
          href={p.url}
          target="_blank"
          rel="noreferrer"
          className="gc-link"
        >
          {p.label}
        </a>
      );
      continue;
    }

    const chunk = p.value || "";
    if (!chunk) continue;

    let last = 0;
    let m;

    while ((m = urlRx.exec(chunk)) !== null) {
      const raw = m[0];
      const start = m.index;

      if (start > last) {
        nodes.push(<span key={`t-${key++}`}>{chunk.slice(last, start)}</span>);
      }

      const url = raw.startsWith("http") ? raw : `https://${raw}`;
      nodes.push(
        <a
          key={`u-${key++}`}
          href={url}
          target="_blank"
          rel="noreferrer"
          className="gc-link"
        >
          {raw}
        </a>
      );

      last = start + raw.length;
    }

    if (last < chunk.length) {
      nodes.push(<span key={`t-${key++}`}>{chunk.slice(last)}</span>);
    }
  }

  return nodes;
}


function updateContextFromUserText(prev, text) {
  const t = normalize(text);
  const next = { ...prev };

  const modes = [
    { key: "Carretera", rx: new RegExp(String.raw`\bcarretera\b|\broad\b|\basfalto\b`, "i") },
    { key: "Gravel", rx: new RegExp(String.raw`\bgravel\b`, "i") },
    { key: "XC", rx: new RegExp(String.raw`\bxc\b|\bcross\s*country\b`, "i") },
    { key: "Enduro", rx: new RegExp(String.raw`\benduro\b`, "i") },
    { key: "DH", rx: new RegExp(String.raw`\bdh\b|\bdownhill\b|\bbike\s*park\b|\bbikepark\b`, "i") },
    { key: "Trail", rx: new RegExp(String.raw`\btrail\b`, "i") },
  ];

  // excluir modo: "no quiero enduro", "no quiero una gravel", etc
  for (const m of modes) {
    const keyLower = m.key.toLowerCase();
    const noRx = new RegExp(String.raw`\bno\s+quiero\s+(una\s+)?` + keyLower + String.raw`\b`, "i");
    if (noRx.test(t)) {
      const set = new Set([...(next.exclude_modes || []), m.key]);
      next.exclude_modes = Array.from(set);
      if (next.mode === m.key) next.mode = null;
    }
  }

  // elegir modo si lo menciona
  for (const m of modes) {
    if (m.rx.test(t)) {
      if (!(next.exclude_modes || []).includes(m.key)) {
        next.mode = m.key;
      }
      break;
    }
  }

  // presupuesto: primer número (3-5 dígitos)
  const digits = String(text || "").replaceAll(".", "").replaceAll(",", "");
  const budgetMatch = digits.match(new RegExp(String.raw`\b(\d{3,5})\b`));
  if (budgetMatch) {
    const b = Number(budgetMatch[1]);
    if (!Number.isNaN(b)) next.budget = b;
  }

  // rango máximo: "menos de 2000", "máximo 2500", "por debajo de 1800"
  const maxMatch =
    t.match(new RegExp(String.raw`(menos de|maximo|máximo|por debajo de)\s*(\d{3,5})`, "i")) ||
    t.match(new RegExp(String.raw`(\d{3,5})\s*(€|eur)\s*(max|máx|maximo|máximo)`, "i"));
  if (maxMatch) {
    const num = Number(String(maxMatch[2] || maxMatch[1] || "").replace(/[^\d]/g, ""));
    if (!Number.isNaN(num)) next.budget_max = num;
  }

  // rango mínimo: "mínimo 1500", "a partir de 1200"
  const minMatch = t.match(new RegExp(String.raw`(minimo|mínimo|a partir de)\s*(\d{3,5})`, "i"));
  if (minMatch) {
    const num = Number(String(minMatch[2] || "").replace(/[^\d]/g, ""));
    if (!Number.isNaN(num)) next.budget_min = num;
  }

  // marca preferida: "quiero canyon", "me gusta trek"
  const wantBrand = t.match(new RegExp(String.raw`\b(quiero|prefiero|me gusta)\s+([a-z0-9\-]{3,20})\b`, "i"));
  if (wantBrand) {
    const brand = wantBrand[2].toLowerCase();
    const set = new Set([...(next.preferred_brands || []), brand]);
    next.preferred_brands = Array.from(set);
  }

  // excluir marca: "no quiero specialized"
  const noBrand = t.match(new RegExp(String.raw`\bno\s+quiero\s+([a-z0-9\-]{3,20})\b`, "i"));
  if (noBrand) {
    const brand = noBrand[1].toLowerCase();
    const set = new Set([...(next.excluded_brands || []), brand]);
    next.excluded_brands = Array.from(set);
  }

  return next;
}

export default function AiChatDialog({ floating = true, routeContext = null }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [userBikes, setUserBikes] = useState([]);

  const { user } = useUser();

  const backendUrl = (import.meta.env.VITE_BACKEND_URL || "").replace(/\/$/, "");

  useEffect(() => {
    const token = session.getToken();
    if (!token) return;
    fetch(`${backendUrl}/api/bikes`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (Array.isArray(data)) setUserBikes(data); })
      .catch(() => {});
  }, [backendUrl]);

  const [messages, setMessages] = useState(DEFAULT_MESSAGES);
  const [context, setContext] = useState(DEFAULT_CONTEXT);

  const listRef = useRef(null);
  const routeAnalysisSentRef = useRef(null);
  const pendingRouteMsg = useRef(null);

  // Cuando llega un routeContext nuevo, prepara el mensaje y abre el chat
  useEffect(() => {
    if (!routeContext) return;
    const { name, terrain, distance_km, gain_m, type } = routeContext;
    pendingRouteMsg.current = `Analiza esta ruta: "${name || "Sin nombre"}", tipo ${type || "—"}, terreno ${terrain || "—"}, ${Number(distance_km || 0).toFixed(2)} km, desnivel +${Math.round(gain_m || 0)} m. ¿Qué bici de mi garaje es la más adecuada para ella?`;
    routeAnalysisSentRef.current = null;
    setMessages(DEFAULT_MESSAGES);
    setContext(DEFAULT_CONTEXT);
    setInput("");
    setOpen(true);
  }, [routeContext]);

  // Auto-scroll
  useEffect(() => {
    if (!open) return;
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [open, messages, sending]);

  const toggleOpen = () => setOpen((v) => !v);

  const resetChat = () => {
    setMessages(DEFAULT_MESSAGES);
    setContext(DEFAULT_CONTEXT);
    setInput("");
  };

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;

    const updatedContext = updateContextFromUserText(context, text);
    setContext(updatedContext);

    const nextMessages = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setInput("");
    setSending(true);

    try {
      const resp = await fetch(`${backendUrl}/api/ai/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.getToken()}`,
        },
        body: JSON.stringify({
          messages: nextMessages,
          context: updatedContext,
          user_profile: buildUserProfile(),
          route_context: routeContext || undefined,
          terrain: routeContext?.terrain || undefined,
        }),
      });

      const data = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        setMessages((m) => [
          ...m,
          {
            role: "assistant",
            content: `⚠️ Error: ${data?.msg || data?.error || "algo falló en el servidor"}`,
          },
        ]);
        return;
      }

      // Mensaje principal
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: (data?.assistant_message || "").trim() || "OK",
        },
      ]);

      // Recomendaciones
      const recs = Array.isArray(data?.recommendations) ? data.recommendations : [];
      if (recs.length) {
        setMessages((m) => [...m, { role: "assistant", content: "__RECS_BLOCK__", recs }]);
      }

      // Chips de sugerencia (presupuesto / terreno)
      const chips = Array.isArray(data?.suggested_chips) ? data.suggested_chips : [];
      if (chips.length) {
        setMessages((m) => [...m, { role: "assistant", content: "__CHIPS__", chips }]);
      }

      // Preguntas de seguimiento
      const qs = Array.isArray(data?.next_questions) ? data.next_questions : [];
      if (qs.length) {
        setMessages((m) => [...m, { role: "assistant", content: "__QUESTIONS__", questions: qs }]);
      }
    } catch (e) {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `⚠️ Error de red/servidor: ${e?.message || "Failed to fetch"}`,
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  const sendQuestion = async (text) => {
    if (sending) return;
    const updatedContext = updateContextFromUserText(context, text);
    setContext(updatedContext);
    const nextMessages = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setSending(true);
    try {
      const resp = await fetch(`${backendUrl}/api/ai/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.getToken()}`,
        },
        body: JSON.stringify({ messages: nextMessages, context: updatedContext, user_profile: buildUserProfile(), route_context: routeContext || undefined, terrain: routeContext?.terrain || undefined }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setMessages((m) => [...m, { role: "assistant", content: `⚠️ ${data?.error || "error"}` }]);
        return;
      }
      setMessages((m) => [...m, { role: "assistant", content: (data?.assistant_message || "").trim() || "OK" }]);
      const recs = Array.isArray(data?.recommendations) ? data.recommendations : [];
      if (recs.length) setMessages((m) => [...m, { role: "assistant", content: "__RECS_BLOCK__", recs }]);
      const chips = Array.isArray(data?.suggested_chips) ? data.suggested_chips : [];
      if (chips.length) setMessages((m) => [...m, { role: "assistant", content: "__CHIPS__", chips }]);
      const qs = Array.isArray(data?.next_questions) ? data.next_questions : [];
      if (qs.length) setMessages((m) => [...m, { role: "assistant", content: "__QUESTIONS__", questions: qs }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠️ ${e?.message || "Failed to fetch"}` }]);
    } finally {
      setSending(false);
    }
  };

  const buildUserProfile = () => ({
    name: user?.name || null,
    location: user?.location || null,
    bikes: userBikes.map((b) => ({
      name: b.name,
      model: b.model,
      km: b.km_total,
      parts: (b.parts || []).map((p) => ({
        name: p.part_name,
        brand: p.brand,
        wear: p.wear_percentage,
        km_current: p.km_current,
        km_life: p.km_life,
      })),
    })),
  });

  // Dispara el auto-análisis de ruta tras abrir el chat y resetear mensajes
  useEffect(() => {
    if (!open || !pendingRouteMsg.current || sending) return;
    if (messages.length !== DEFAULT_MESSAGES.length) return;
    if (routeAnalysisSentRef.current) return;
    routeAnalysisSentRef.current = true;
    const msg = pendingRouteMsg.current;
    pendingRouteMsg.current = null;
    sendQuestion(msg);
  // sendQuestion es estable en este contexto; ignoramos exhaustive-deps
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sending, messages.length]);

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className={floating ? "gc-fab-wrap" : ""}>
      {floating && (
        <button
          type="button"
          className="gc-fab"
          onClick={toggleOpen}
          aria-label="Abrir GASTACOBRE"
        >
          <span className="gc-fab-icon">🤖</span>
          <span className="gc-fab-text">GASTACOBRE</span>
        </button>
      )}

      {open && (
        <div className="gc-overlay" onMouseDown={() => setOpen(false)}>
          <div className="gc-dialog" onMouseDown={(e) => e.stopPropagation()}>
            <div className="gc-header">
              <div>
                <div className="gc-title">GASTACOBRE</div>
                <div className="gc-subtitle">Asistente IA</div>
              </div>

              <div className="gc-header-actions">
                <button type="button" className="gc-reset" onClick={resetChat} title="Reset">
                  Reset
                </button>
                <button
                  type="button"
                  className="gc-close"
                  onClick={() => setOpen(false)}
                  aria-label="Cerrar"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="gc-messages" ref={listRef}>
              {messages.map((m, idx) => {
                const isUser = m.role === "user";

                // ignorar bloques huérfanos
                if (m.content === "__RECS_BLOCK__" && !Array.isArray(m.recs)) return null;
                if (m.content === "__QUESTIONS__" && !Array.isArray(m.questions)) return null;
                if (m.content === "__CHIPS__" && !Array.isArray(m.chips)) return null;

                // bloque recomendaciones
                if (m.content === "__RECS_BLOCK__" && Array.isArray(m.recs)) {
                  return (
                    <div
                      key={`recs-${idx}`}
                      className={`gc-bubble ${isUser ? "gc-bubble-user" : "gc-bubble-assistant"}`}
                    >
                      <div className="gc-recs-title">📌 Recomendaciones:</div>
                      <div className="gc-recs">
                        {m.recs.map((r, i) => {
                          const title = r.name || r.model || r.id || `Recomendación ${i + 1}`;
                          const price = r.price_eur ? `${r.price_eur}€` : "";
                          const why = r.why || r.reason || "";
                          const url = r.url || r.link || "";

                          return (
                            <div key={`rec-${idx}-${i}`} className="gc-rec">
                              <div className="gc-rec-top">
                                {url ? (
                                  <a className="gc-rec-link" href={url} target="_blank" rel="noreferrer">
                                    {title}
                                  </a>
                                ) : (
                                  <div className="gc-rec-name">{title}</div>
                                )}
                                {price && <div className="gc-rec-price">{price}</div>}
                              </div>

                              {why && <div className="gc-rec-why">{renderTextWithLinks(why)}</div>}

                              {url && (
                                <div className="gc-rec-url">
                                  <a href={url} target="_blank" rel="noreferrer">
                                    Ver producto
                                  </a>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                }

                // chips de sugerencia (presupuesto / terreno)
                if (m.content === "__CHIPS__" && Array.isArray(m.chips)) {
                  return (
                    <div key={`chips-${idx}`} className="gc-chips">
                      {m.chips.map((c, i) => (
                        <button
                          key={i}
                          type="button"
                          className="gc-chip-btn"
                          onClick={() => sendQuestion(c.value)}
                          disabled={sending}
                        >
                          {c.label}
                        </button>
                      ))}
                    </div>
                  );
                }

                // bloque preguntas de seguimiento
                if (m.content === "__QUESTIONS__" && Array.isArray(m.questions)) {
                  return (
                    <div key={`qs-${idx}`} className="gc-questions-block">
                      {m.questions.map((q, i) => {
                        const questionText = typeof q === "object" ? q.question : q;
                        const options = typeof q === "object" && Array.isArray(q.options) ? q.options : [];
                        return (
                          <div key={i} className="gc-question-item">
                            <div className="gc-question-text">{questionText}</div>
                            {options.length > 0 && (
                              <div className="gc-chips">
                                {options.map((opt, j) => (
                                  <button
                                    key={j}
                                    type="button"
                                    className="gc-chip-btn"
                                    onClick={() => sendQuestion(opt)}
                                    disabled={sending}
                                  >
                                    {opt}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  );
                }

                // mensaje normal
                return (
                  <div
                    key={idx}
                    className={`gc-bubble ${isUser ? "gc-bubble-user" : "gc-bubble-assistant"}`}
                  >
                    {renderTextWithLinks(m.content)}
                  </div>
                );
              })}

              {sending && (
                <div className="gc-bubble gc-bubble-assistant gc-typing">Escribiendo…</div>
              )}
            </div>

            <div className="gc-inputbar">
              <textarea
                className="gc-input"
                placeholder="Escribe aquí"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={2}
              />
              <button type="button" className="gc-send" onClick={send} disabled={sending}>
                {sending ? "..." : "Enviar"}
              </button>
            </div>

          </div>
        </div>
      )}

      {!floating && (
        <button type="button" className="gc-inline-btn" onClick={toggleOpen}>
          Abrir GASTACOBRE
        </button>
      )}
    </div>
  );
}
