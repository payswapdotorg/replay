"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Status = {
  ts: string;
  repo: string;
  browser_login: string;
  main_sha?: string;
  branches?: { name: string; sha: string }[];
  pulls?: { n: number; state: string; title: string }[];
};

type Tab = { id: string; title: string; url: string };
type TabsInfo = { active: string; new: string[]; tabs: Tab[] };
type Msg = { ts: number; from: "operator" | "agent"; text: string };
type Inbox = { thread: Msg[]; agent_heartbeat_ms: number; watcher_alive: boolean };

const CONSOLE_VERSION = "v6.1 · realtime drag";
const START_URL = "https://chat.z.ai/";
const FRAME_FAST_MS = 220; // while dragging / right after an event
const FRAME_IDLE_MS = 1300; // steady state
const MOVE_MIN_INTERVAL_MS = 45; // dragmove throttle
const DRAG_START_THRESHOLD = 0.004; // fraction of viewport before dragstart fires

function ago(ms: number): string {
  if (!ms) return "—";
  const s = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export default function Console() {
  const [frame, setFrame] = useState<string>("");
  const [status, setStatus] = useState<Status | null>(null);
  const [tabs, setTabs] = useState<TabsInfo>({ active: "", new: [], tabs: [] });
  const [inbox, setInbox] = useState<Inbox>({ thread: [], agent_heartbeat_ms: 0, watcher_alive: false });
  const [kb, setKb] = useState("");
  const [msg, setMsg] = useState("");
  const [tick, setTick] = useState(0);
  const [dragStart, setDragStart] = useState<{ fx: number; fy: number } | null>(null);
  const [dragCur, setDragCur] = useState<{ fx: number; fy: number } | null>(null);
  const [ripple, setRipple] = useState<{ fx: number; fy: number; k: number } | null>(null);
  const [lastClick, setLastClick] = useState("");
  const [domMode, setDomMode] = useState(false);
  const [navUrl, setNavUrl] = useState("");
  const imgRef = useRef<HTMLImageElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const autoSelRef = useRef(false);
  const rippleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dragRef = useRef<{ fx: number; fy: number } | null>(null);
  const dragStartedRef = useRef(false);
  const lastMoveSentRef = useRef(0);
  const lastMovePosRef = useRef<{ fx: number; fy: number } | null>(null);
  const dragCountRef = useRef(0);
  const fastUntilRef = useRef(0);
  const queueRef = useRef<Promise<unknown>>(Promise.resolve());
  const domModeRef = useRef(false);
  domModeRef.current = domMode;
  const sendRef = useRef<
    ((p: Record<string, unknown>) => Promise<Record<string, unknown> | null>) | null
  >(null);
  const refreshRef = useRef<() => void>(() => {});

  const bumpFast = useCallback(() => {
    fastUntilRef.current = Date.now() + 1600;
  }, []);

  const refreshFrame = useCallback(async () => {
    try {
      const r = await fetch("/api/frame", { cache: "no-store" });
      if (!r.ok) return;
      const blob = await r.blob();
      setFrame((old) => {
        if (old) URL.revokeObjectURL(old);
        return URL.createObjectURL(blob);
      });
    } catch {
      /* keep last frame */
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const r = await fetch("/api/status", { cache: "no-store" });
      if (r.ok) setStatus(await r.json());
    } catch {
      /* ignore */
    }
  }, []);

  const refreshTabs = useCallback(async () => {
    try {
      const r = await fetch("/api/tabs", { cache: "no-store" });
      if (!r.ok) return;
      const d = (await r.json()) as TabsInfo;
      setTabs(d);
      // auto-focus newly opened tabs (login popups) so events follow them
      if (!autoSelRef.current && d.new && d.new.length > 0) {
        autoSelRef.current = true;
        const nid = d.new[0];
        await fetch("/api/tabs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: nid }),
        });
        d.active = nid;
        setTabs(d);
        bumpFast();
        setTimeout(() => {
          autoSelRef.current = false;
        }, 15000);
      }
    } catch {
      /* ignore */
    }
  }, [bumpFast]);

  const refreshInbox = useCallback(async () => {
    try {
      const r = await fetch("/api/inbox", { cache: "no-store" });
      if (r.ok) setInbox(await r.json());
    } catch {
      /* ignore */
    }
  }, []);

  // Adaptive frame loop: fast (~4.5fps) while dragging or right after an
  // event, relaxed otherwise. Sequential — no request pileup.
  useEffect(() => {
    let cancelled = false;
    const sleep = (ms: number) => new Promise<void>((res) => setTimeout(res, ms));
    (async () => {
      while (!cancelled) {
        await refreshFrame();
        const fast = dragRef.current !== null || fastUntilRef.current > Date.now();
        await sleep(fast ? FRAME_FAST_MS : FRAME_IDLE_MS);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshFrame]);

  useEffect(() => {
    refreshStatus();
    refreshTabs();
    refreshInbox();
    const st = setInterval(refreshStatus, 20000);
    const tb = setInterval(refreshTabs, 5000);
    const ib = setInterval(refreshInbox, 4000);
    const tk = setInterval(() => setTick((t) => t + 1), 10000);
    return () => {
      clearInterval(st);
      clearInterval(tb);
      clearInterval(ib);
      clearInterval(tk);
    };
  }, [refreshStatus, refreshTabs, refreshInbox]);

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [inbox.thread.length]);

  const sendEvent = useCallback(
    async (payload: Record<string, unknown>): Promise<Record<string, unknown> | null> => {
      bumpFast();
      try {
        const r = await fetch("/api/event", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        let j: Record<string, unknown> | null = null;
        try {
          j = await r.json();
        } catch {
          /* bridge may return plain ok */
        }
        setTimeout(refreshFrame, 350);
        return j;
      } catch {
        return null;
      }
    },
    [refreshFrame, bumpFast]
  );

  // Ordered fire-and-forget queue for streamed drag events. Strict ordering
  // (each request waits for the previous) so moves never arrive out of order.
  const queueEvent = useCallback((payload: Record<string, unknown>) => {
    bumpFast();
    queueRef.current = queueRef.current
      .then(async () => {
        try {
          await fetch("/api/event", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
        } catch {
          /* next event still queued */
        }
      })
      .catch(() => {});
  }, [bumpFast]);

  useEffect(() => {
    sendRef.current = sendEvent;
    refreshRef.current = refreshFrame;
  }, [sendEvent, refreshFrame]);

  // Native (non-React) pointer listeners on the replay image. React's
  // delegated handlers were proven NOT to fire on this <img> in some page
  // states — native listeners are immune to that. Pointer events also cover
  // touch. Drags STREAM live: dragstart on first real movement, dragmove
  // throttled, dragend with the exact final position.
  useEffect(() => {
    const fracFromEvent = (ev: { clientX: number; clientY: number }) => {
      const img = imgRef.current;
      if (!img) return null;
      const rect = img.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) return null;
      return {
        fx: Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width)),
        fy: Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height)),
      };
    };

    const onDown = (ev: PointerEvent) => {
      if (ev.pointerType === "mouse" && ev.button !== 0) return;
      const img = ev.currentTarget as HTMLElement | null;
      if (img && typeof img.setPointerCapture === "function") {
        try {
          img.setPointerCapture(ev.pointerId);
        } catch {
          /* capture best-effort */
        }
      }
      const p = fracFromEvent(ev);
      if (!p) return;
      ev.preventDefault();
      dragRef.current = p;
      dragStartedRef.current = false;
      lastMoveSentRef.current = 0;
      lastMovePosRef.current = null;
      dragCountRef.current = 0;
      setDragStart(p);
      setDragCur(p);
    };

    const onMove = (ev: PointerEvent) => {
      const start = dragRef.current;
      if (!start) return;
      const p = fracFromEvent(ev);
      if (!p) return;
      setDragCur(p);
      if (!dragStartedRef.current) {
        // only commit to a drag after real movement — clicks stay clicks
        const d = Math.hypot(p.fx - start.fx, p.fy - start.fy);
        if (d < DRAG_START_THRESHOLD) return;
        dragStartedRef.current = true;
        lastMovePosRef.current = p;
        lastMoveSentRef.current = performance.now();
        dragCountRef.current = 1;
        queueEvent({ type: "dragstart", fx: start.fx, fy: start.fy });
        queueEvent({ type: "dragmove", fx: p.fx, fy: p.fy });
        setLastClick("drag live — keep moving…");
        return;
      }
      const now = performance.now();
      const last = lastMovePosRef.current;
      const moved = last ? Math.hypot(p.fx - last.fx, p.fy - last.fy) : 1;
      if (now - lastMoveSentRef.current >= MOVE_MIN_INTERVAL_MS && moved >= 0.002) {
        lastMoveSentRef.current = now;
        lastMovePosRef.current = p;
        dragCountRef.current += 1;
        queueEvent({ type: "dragmove", fx: p.fx, fy: p.fy });
      }
    };

    const finishDrag = (end: { fx: number; fy: number }) => {
      queueEvent({ type: "dragmove", fx: end.fx, fy: end.fy }); // exact final pos
      queueEvent({ type: "dragend", fx: end.fx, fy: end.fy });
      setLastClick(`drag complete — ${dragCountRef.current} live moves sent`);
      setTimeout(() => refreshRef.current(), 400);
    };

    const onUp = (ev: PointerEvent) => {
      const start = dragRef.current;
      dragRef.current = null;
      setDragStart(null);
      setDragCur(null);
      if (!start) return;
      const end = fracFromEvent(ev) || start;
      if (dragStartedRef.current) {
        finishDrag(end);
        return;
      }
      // click path (unchanged semantics — no drag events were ever sent)
      if (rippleTimer.current) clearTimeout(rippleTimer.current);
      setRipple({ fx: end.fx, fy: end.fy, k: Date.now() });
      rippleTimer.current = setTimeout(() => setRipple(null), 900);
      const useDom = domModeRef.current;
      sendRef
        .current?.(useDom ? { type: "domclick", fx: end.fx, fy: end.fy } : { type: "click", fx: end.fx, fy: end.fy })
        .then((r) => {
          if (r && r.ok === false) {
            setLastClick(`event error: ${String(r.error ?? "unknown")} — retry`);
            return;
          }
          const t = (r?.target as { tag?: string; text?: string; dx?: number; dy?: number } | undefined) || undefined;
          const label = t
            ? t.text
              ? `${t.tag} "${t.text}"`
              : t.tag || "?"
            : "(no target info)";
          const off = t && (t.dx || t.dy) ? ` (+${Math.abs(t.dx!)}px,${Math.abs(t.dy!)}px)` : "";
          setLastClick(r ? `${useDom ? "dom-click" : "clicked"} → ${label}${off}` : "event failed — retry");
        });
    };

    const onCancel = () => {
      const start = dragRef.current;
      dragRef.current = null;
      setDragStart(null);
      setDragCur(null);
      if (start && dragStartedRef.current) {
        const last = lastMovePosRef.current || start;
        queueEvent({ type: "dragend", fx: last.fx, fy: last.fy });
      }
    };

    const attach = () => {
      const img = imgRef.current;
      if (!img) return null;
      img.addEventListener("pointerdown", onDown);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onCancel);
      return () => {
        img.removeEventListener("pointerdown", onDown);
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onCancel);
      };
    };

    let detach = attach();
    // if the <img> isn't mounted yet, retry briefly until it appears
    const retry = setInterval(() => {
      if (!detach) {
        detach = attach();
        if (detach) clearInterval(retry);
      }
    }, 500);
    return () => {
      clearInterval(retry);
      detach?.();
    };
  }, [queueEvent]);

  // Type text into the page WITHOUT auto-Enter (auto-Enter submits login
  // forms mid-typing). Enter is a separate explicit button. The daemon
  // auto-focuses the first visible input if none is focused.
  const sendKeys = () => {
    if (!kb.trim()) return;
    const n = kb.length;
    sendEvent({ type: "type", text: kb }).then((r) => {
      const focus = r && typeof r.focus === "string" ? r.focus : "";
      setLastClick(`typed ${n} chars${focus ? ` · ${focus}` : ""}`);
    });
    setKb("");
  };

  const sendMsg = async () => {
    const text = msg.trim();
    if (!text) return;
    setMsg("");
    try {
      await fetch("/api/inbox", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      setTimeout(refreshInbox, 500);
    } catch {
      /* ignore */
    }
  };

  const selectTab = async (id: string) => {
    autoSelRef.current = true;
    try {
      await fetch("/api/tabs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      setTabs((t) => ({ ...t, active: id }));
      bumpFast();
      setTimeout(() => refreshRef.current(), 300);
    } finally {
      setTimeout(() => {
        autoSelRef.current = false;
      }, 5000);
    }
  };

  const doNav = () => {
    let u = navUrl.trim();
    if (!u) return;
    if (!/^https?:\/\//i.test(u)) u = "https://" + u;
    setNavUrl("");
    sendEvent({ type: "nav", url: u });
  };

  const loginColor =
    (status?.browser_login ?? "").startsWith("logged-in")
      ? "text-emerald-700 bg-emerald-50 border-emerald-200"
      : (status?.browser_login ?? "") === "logged-out"
        ? "text-red-700 bg-red-50 border-red-200"
        : "text-amber-700 bg-amber-50 border-amber-200";

  const activeTab = tabs.tabs.find((t) => t.id === tabs.active);
  const lastAgent = inbox.thread.filter((m) => m.from === "agent").slice(-1)[0];

  return (
    <main className="min-h-screen flex flex-col bg-neutral-50 text-neutral-900">
      <header className="border-b border-neutral-200 bg-white px-4 py-3">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold tracking-tight">Replay Console</h1>
          <span className="text-[10px] text-neutral-400 font-mono border border-neutral-200 rounded px-1.5 py-0.5">
            {CONSOLE_VERSION}
          </span>
          <span className="text-xs text-neutral-500">
            browser session {status?.ts ? `· ${status.ts}` : ""}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <span
              className={`px-2 py-1 rounded-md border text-xs font-medium ${
                inbox.watcher_alive
                  ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                  : "text-red-700 bg-red-50 border-red-200"
              }`}
            >
              watcher {inbox.watcher_alive ? "alive" : "down"}
            </span>
            <span className={`px-2 py-1 rounded-md border text-xs font-medium ${loginColor}`}>
              browser: {status?.browser_login ?? "…"}
            </span>
          </div>
        </div>
      </header>

      <section className="flex-1 max-w-7xl w-full mx-auto px-4 py-4 grid gap-4 lg:grid-cols-[1fr_380px]">
        <div className="flex flex-col gap-3">
          <div className="border border-neutral-200 rounded-lg bg-white p-3">
            <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
              <h2 className="text-sm font-semibold">Browser replay (click / drag live)</h2>
              <div className="flex gap-1 items-center">
                <div className="flex rounded border border-neutral-300 overflow-hidden" title="click mode: real mouse events vs direct DOM .click()">
                  <button
                    className={`px-2 py-1 text-xs ${!domMode ? "bg-neutral-900 text-white" : "bg-white text-neutral-600 hover:bg-neutral-100"}`}
                    onClick={() => setDomMode(false)}
                  >
                    Mouse
                  </button>
                  <button
                    className={`px-2 py-1 text-xs ${domMode ? "bg-neutral-900 text-white" : "bg-white text-neutral-600 hover:bg-neutral-100"}`}
                    onClick={() => setDomMode(true)}
                  >
                    DOM click
                  </button>
                </div>
                <button
                  className="px-2 py-1 text-xs border border-neutral-300 rounded hover:bg-neutral-100"
                  onClick={() => sendEvent({ type: "nav", url: START_URL })}
                >
                  chat.z.ai
                </button>
                <button
                  className="px-2 py-1 text-xs border border-neutral-300 rounded hover:bg-neutral-100"
                  onClick={() => sendEvent({ type: "reload" })}
                  title="reload page"
                >
                  ⟳
                </button>
                <button
                  className="px-2 py-1 text-xs border border-neutral-300 rounded hover:bg-neutral-100"
                  onClick={() => sendEvent({ type: "scroll", deltaY: 300, fx: 0.5, fy: 0.5 })}
                >
                  ↓
                </button>
                <button
                  className="px-2 py-1 text-xs border border-neutral-300 rounded hover:bg-neutral-100"
                  onClick={() => sendEvent({ type: "scroll", deltaY: -300, fx: 0.5, fy: 0.5 })}
                >
                  ↑
                </button>
              </div>
            </div>

            {/* Tab bar — events + frame follow the selected tab */}
            {tabs.tabs.length > 0 && (
              <div className="flex gap-1 flex-wrap mb-2">
                {tabs.tabs.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => selectTab(t.id)}
                    title={t.url}
                    className={`px-2 py-1 text-[11px] rounded border max-w-[220px] truncate ${
                      t.id === tabs.active
                        ? "bg-neutral-900 text-white border-neutral-900"
                        : "bg-white text-neutral-600 border-neutral-300 hover:bg-neutral-100"
                    } ${tabs.new?.includes(t.id) ? "ring-2 ring-amber-400" : ""}`}
                  >
                    {tabs.new?.includes(t.id) ? "✦ " : ""}
                    {t.title || t.url}
                  </button>
                ))}
              </div>
            )}

            <div className="relative rounded-md overflow-hidden bg-neutral-900 flex items-center justify-center">
              {frame ? (
                <img
                  ref={imgRef}
                  src={frame}
                  alt="live browser view"
                  className="max-w-full max-h-[62vh] cursor-pointer select-none touch-none"
                  draggable={false}
                />
              ) : (
                <div className="text-neutral-400 text-sm py-24">connecting to browser…</div>
              )}
              {dragStart && dragCur && (
                <svg
                  className="pointer-events-none absolute inset-0 w-full h-full"
                  aria-hidden="true"
                >
                  <line
                    x1={`${dragStart.fx * 100}%`}
                    y1={`${dragStart.fy * 100}%`}
                    x2={`${dragCur.fx * 100}%`}
                    y2={`${dragCur.fy * 100}%`}
                    stroke="#f59e0b"
                    strokeWidth="3"
                    strokeDasharray="8 4"
                  />
                  <circle cx={`${dragStart.fx * 100}%`} cy={`${dragStart.fy * 100}%`} r="6" fill="#f59e0b" />
                  <circle cx={`${dragCur.fx * 100}%`} cy={`${dragCur.fy * 100}%`} r="6" fill="#ef4444" />
                </svg>
              )}
              {ripple && (
                <div
                  key={ripple.k}
                  className="pointer-events-none absolute"
                  style={{
                    left: `${ripple.fx * 100}%`,
                    top: `${ripple.fy * 100}%`,
                    transform: "translate(-50%, -50%)",
                  }}
                >
                  <div className="w-6 h-6 rounded-full border-2 border-emerald-400 animate-ping" />
                </div>
              )}
              {dragStart && (
                <div className="absolute top-2 left-2 bg-amber-500/90 text-white text-[10px] px-2 py-1 rounded pointer-events-none">
                  drag streaming live — release to complete
                </div>
              )}
            </div>
            <div className="mt-1 text-[11px] text-neutral-400 truncate" aria-live="polite">
              {activeTab ? `${activeTab.title} — ${activeTab.url}` : ""}
            </div>
            <div
              className="mt-1 text-[11px] text-neutral-600 font-medium truncate"
              aria-live="polite"
            >
              {lastClick || "click feedback appears here (target element + offsets)"}
            </div>
            <div className="mt-2 flex gap-2">
              <input
                className="flex-1 border border-neutral-300 rounded px-2 py-1.5 text-sm"
                placeholder="type into the browser page (auto-focuses the first field)"
                value={kb}
                onChange={(e) => setKb(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendKeys()}
                aria-label="keyboard input for browser page"
              />
              <button
                className="px-3 py-1.5 text-sm bg-neutral-900 text-white rounded hover:bg-neutral-700"
                onClick={sendKeys}
              >
                Type
              </button>
              <button
                className="px-3 py-1.5 text-sm border border-neutral-300 rounded hover:bg-neutral-100"
                onClick={() => sendEvent({ type: "enter" })}
                title="press Enter in the page"
              >
                ↵
              </button>
            </div>
            <div className="mt-2 flex gap-2">
              <input
                className="flex-1 border border-neutral-300 rounded px-2 py-1.5 text-sm"
                placeholder="navigate to URL…"
                value={navUrl}
                onChange={(e) => setNavUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && doNav()}
                aria-label="navigate the browser to a URL"
              />
              <button
                className="px-3 py-1.5 text-sm border border-neutral-300 rounded hover:bg-neutral-100"
                onClick={doNav}
              >
                Go
              </button>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-3">
          {/* Operator ⇄ agent thread */}
          <div className="border border-neutral-200 rounded-lg bg-white p-4 flex flex-col">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold">Message the agent</h2>
              <span className="text-[11px] text-neutral-400">
                agent active {tick ? "" : ""}{ago(inbox.agent_heartbeat_ms || 0)}
              </span>
            </div>
            <div
              ref={threadRef}
              className="max-h-64 overflow-y-auto space-y-2 pr-1 mb-2 text-sm"
              aria-label="message thread"
            >
              {inbox.thread.length === 0 && (
                <p className="text-xs text-neutral-400 py-4 text-center">
                  No messages yet — send one below; the resident agent reads and answers
                  from this thread.
                </p>
              )}
              {inbox.thread.map((m, i) => (
                <div
                  key={`${m.ts}-${i}`}
                  className={`rounded-lg px-3 py-2 max-w-[90%] ${
                    m.from === "operator"
                      ? "ml-auto bg-neutral-900 text-white"
                      : "bg-neutral-100 text-neutral-800"
                  }`}
                >
                  <div className="text-[10px] opacity-60 mb-0.5">
                    {m.from === "operator" ? "you" : "agent"} ·{" "}
                    {new Date(m.ts).toLocaleTimeString()}
                  </div>
                  <div className="whitespace-pre-wrap break-words">{m.text}</div>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                className="flex-1 border border-neutral-300 rounded px-2 py-1.5 text-sm"
                placeholder="message the agent…"
                value={msg}
                onChange={(e) => setMsg(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendMsg()}
                aria-label="message to the agent"
              />
              <button
                className="px-3 py-1.5 text-sm bg-neutral-900 text-white rounded hover:bg-neutral-700"
                onClick={sendMsg}
              >
                Send
              </button>
            </div>
            {lastAgent && (
              <div className="mt-1 text-[11px] text-neutral-400 truncate">
                last reply: {lastAgent.text.slice(0, 80)}
              </div>
            )}
          </div>

          {/* Remote repo summary — only when REPO is configured in scripts/env.sh */}
          {status?.repo && (
            <div className="border border-neutral-200 rounded-lg bg-white p-4 text-xs space-y-1">
              <div className="flex justify-between">
                <span className="text-neutral-500">repo</span>
                <span className="font-mono">{status.repo}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">main</span>
                <span className="font-mono">{status.main_sha ?? "…"}</span>
              </div>
              {status.pulls && status.pulls.length > 0 && (
                <div className="flex justify-between">
                  <span className="text-neutral-500">pulls</span>
                  <span className="font-mono">
                    {status.pulls.filter((p) => p.state === "open").length} open /{" "}
                    {status.pulls.length} total
                  </span>
                </div>
              )}
              <div className="pt-1 border-t border-neutral-100 mt-1">
                <div className="text-neutral-500 mt-1">branches</div>
                <div className="max-h-40 overflow-y-auto">
                  {status?.branches?.map((b) => (
                    <div key={b.name} className="flex justify-between">
                      <span className="truncate">{b.name}</span>
                      <span className="font-mono text-neutral-500">{b.sha}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="border border-amber-200 bg-amber-50 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-amber-900 mb-2">Operator notes</h2>
            <ol className="list-decimal ml-4 text-xs text-amber-900 space-y-1.5">
              <li>
                <b>Site login (drags stream LIVE):</b> click &quot;Sign in&quot; in the
                replay → <b>Continue with Email</b> → click the email field → type in
                the box below the replay (it auto-focuses the first input) → Continue →
                password the same way. Slider/captcha: <b>press on the slider handle
                and drag slowly</b> — the replay follows your drag in real time; release
                when aligned. If a click ever lands wrong, toggle <b>DOM click</b> mode.
              </li>
              <li>
                <b>Message the resident agent</b> through the textbox above — it reads
                and replies while working; no login needed.
              </li>
              <li>
                <b>Stale page?</b> Hard-refresh (Ctrl+Shift+R). The version badge
                top-left must match the expected console version.
              </li>
            </ol>
          </div>
        </div>
      </section>

      <footer className="mt-auto border-t border-neutral-200 bg-white px-4 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
        <div className="max-w-7xl mx-auto text-[11px] text-neutral-500 flex flex-wrap gap-x-4">
          <span>Replay console — remote browser control</span>
          <span className="ml-auto">deployed from the replay repository</span>
        </div>
      </footer>
    </main>
  );
}
