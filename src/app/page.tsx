"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Bot,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Globe,
  Keyboard,
  MessageSquare,
  MonitorPlay,
  RotateCw,
  Send,
  User,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

interface TabInfo {
  id: string;
  title: string;
  url: string;
}

interface StatusInfo {
  ok?: boolean;
  xvfb?: boolean;
  chrome?: boolean;
  dev?: boolean;
  targetUrl?: string;
  tabCount?: number;
  active?: { id: string; title: string; url: string } | null;
  login?: string;
  account?: string | null;
  chatInput?: boolean;
  agentActiveAgo?: number | null;
  watcherActiveAgo?: number | null;
  operatorMessages?: number;
  agentMessages?: number;
}

interface ThreadMessage {
  ts: number;
  from: "operator" | "agent";
  text: string;
}

const FRAME_POLL_MS = 2500;
const TABS_POLL_MS = 5000;
const STATUS_POLL_MS = 5000;
const INBOX_POLL_MS = 4000;
const SCROLL_STEP = 400;

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url.slice(0, 24);
  }
}

function ageLabel(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "unknown";
  if (sec < 5) return `${sec}s ago`;
  if (sec < 90) return `${sec}s ago`;
  if (sec < 5400) return `${Math.round(sec / 60)}m ago`;
  return `${Math.round(sec / 3600)}h ago`;
}

function timeLabel(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

async function postJSON(url: string, body: unknown): Promise<Response> {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export default function OperatorConsole() {
  // ---- replay state
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [frameOk, setFrameOk] = useState(false);
  const [frameTs, setFrameTs] = useState(0);
  const [frameErr, setFrameErr] = useState(false);
  const objectUrlRef = useRef<string | null>(null);
  const frameBusyRef = useRef(false);

  // ---- tabs / status / thread state
  const [tabs, setTabs] = useState<TabInfo[]>([]);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [msgInput, setMsgInput] = useState("");
  const [typeInput, setTypeInput] = useState("");
  const [lastAction, setLastAction] = useState("ready");
  const [sendingMsg, setSendingMsg] = useState(false);
  const threadRef = useRef<HTMLDivElement | null>(null);

  // ---- frame polling (blob URLs, revoke the old one, keep last frame on error)
  const refreshFrame = useCallback(async () => {
    if (frameBusyRef.current) return;
    frameBusyRef.current = true;
    try {
      const res = await fetch("/api/frame", { cache: "no-store" });
      if (!res.ok) {
        setFrameErr(true);
        return;
      }
      const blob = await res.blob();
      if (blob.size < 100) {
        setFrameErr(true);
        return;
      }
      const url = URL.createObjectURL(blob);
      const old = objectUrlRef.current;
      objectUrlRef.current = url;
      setFrameUrl(url);
      setFrameOk(true);
      setFrameErr(false);
      setFrameTs(Date.now());
      if (old) URL.revokeObjectURL(old);
    } catch {
      setFrameErr(true);
    } finally {
      frameBusyRef.current = false;
    }
  }, []);

  useEffect(() => {
    refreshFrame();
    const timer = setInterval(refreshFrame, FRAME_POLL_MS);
    return () => {
      clearInterval(timer);
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, [refreshFrame]);

  // ---- tabs polling
  const refreshTabs = useCallback(async () => {
    try {
      const res = await fetch("/api/tabs", { cache: "no-store" });
      if (!res.ok) return;
      const data = (await res.json()) as { tabs?: TabInfo[]; active?: string | null };
      setTabs(data.tabs ?? []);
      setActiveTab(data.active ?? null);
    } catch {
      /* keep last known tabs */
    }
  }, []);

  useEffect(() => {
    refreshTabs();
    const timer = setInterval(refreshTabs, TABS_POLL_MS);
    return () => clearInterval(timer);
  }, [refreshTabs]);

  // ---- status polling
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const res = await fetch("/api/status", { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as StatusInfo;
        if (alive) setStatus(data);
      } catch {
        /* keep last known status */
      }
    };
    poll();
    const timer = setInterval(poll, STATUS_POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  // ---- inbox polling + autoscroll
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const res = await fetch("/api/inbox", { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as { messages?: ThreadMessage[] };
        if (alive) setMessages(data.messages ?? []);
      } catch {
        /* keep last known thread */
      }
    };
    poll();
    const timer = setInterval(poll, INBOX_POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // ---- input events into the browser
  const sendEvent = useCallback(
    async (spec: Record<string, unknown>) => {
      setLastAction(`${String(spec.type)}…`);
      try {
        const res = await postJSON("/api/event", spec);
        const data = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string };
        setLastAction(
          data.ok === false ? `error: ${data.error ?? "unknown"}` : `${String(spec.type)} ok`,
        );
      } catch {
        setLastAction("error: network");
      }
      window.setTimeout(() => {
        refreshFrame();
      }, 350);
    },
    [refreshFrame],
  );

  /**
   * CRITICAL: click/drag coordinates are mapped with the image's
   * naturalWidth / naturalHeight — NEVER hardcoded viewport numbers. The real
   * viewport (e.g. 1439x756) differs from the requested window size (1440x900).
   * Press-drag-release sends a drag event (slider captchas); a press-release
   * under 6px sends a click.
   */
  const dragStartRef = useRef<{ vx: number; vy: number; cx: number; cy: number } | null>(null);

  const toViewport = (img: HTMLImageElement, e: React.MouseEvent<HTMLImageElement>) => ({
    x: Math.round(((e.clientX - img.getBoundingClientRect().left) / img.getBoundingClientRect().width) * img.naturalWidth),
    y: Math.round(((e.clientY - img.getBoundingClientRect().top) / img.getBoundingClientRect().height) * img.naturalHeight),
  });

  const onFrameMouseDown = (e: React.MouseEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    if (!img.naturalWidth || !img.naturalHeight) return;
    const v = toViewport(img, e);
    dragStartRef.current = { vx: v.x, vy: v.y, cx: e.clientX, cy: e.clientY };
  };

  const onFrameMouseUp = (e: React.MouseEvent<HTMLImageElement>) => {
    const start = dragStartRef.current;
    dragStartRef.current = null;
    if (!start) return;
    const img = e.currentTarget;
    if (!img.naturalWidth || !img.naturalHeight) return;
    const end = toViewport(img, e);
    const dist = Math.hypot(e.clientX - start.cx, e.clientY - start.cy);
    if (dist < 6) {
      sendEvent({ type: "click", x: end.x, y: end.y });
    } else {
      sendEvent({
        type: "drag",
        fromX: start.vx,
        fromY: start.vy,
        toX: end.x,
        toY: end.y,
      });
    }
  };

  const selectTab = useCallback(
    async (id: string) => {
      setLastAction("switching tab…");
      try {
        const res = await postJSON("/api/tabs", { id });
        const data = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string };
        if (data.ok === false) {
          setLastAction(`error: ${data.error ?? "tab switch failed"}`);
          return;
        }
        setActiveTab(id);
        setLastAction("tab switched");
        refreshTabs();
        refreshFrame();
      } catch {
        setLastAction("error: network");
      }
    },
    [refreshFrame, refreshTabs],
  );

  const sendMessage = useCallback(async () => {
    const text = msgInput.trim();
    if (!text || sendingMsg) return;
    setSendingMsg(true);
    setMsgInput("");
    try {
      const res = await postJSON("/api/inbox", { text });
      if (res.ok) {
        setLastAction("message sent to agent");
        const data = (await fetch("/api/inbox", { cache: "no-store" }).then((r) =>
          r.json(),
        )) as { messages?: ThreadMessage[] };
        setMessages(data.messages ?? []);
      } else {
        setLastAction("error: message failed");
      }
    } catch {
      setLastAction("error: network");
    } finally {
      setSendingMsg(false);
    }
  }, [msgInput, sendingMsg]);

  const typeAndEnter = useCallback(async () => {
    const text = typeInput;
    if (!text) return;
    setTypeInput("");
    setLastAction("typing into page…");
    try {
      await postJSON("/api/event", { type: "type", text });
      await postJSON("/api/event", { type: "enter" });
      setLastAction("typed + enter");
    } catch {
      setLastAction("error: network");
    }
    window.setTimeout(() => {
      refreshFrame();
    }, 350);
  }, [typeInput, refreshFrame]);

  const activeUrl = status?.active?.url ?? tabs.find((t) => t.id === activeTab)?.url ?? "";
  const targetUrl = status?.targetUrl || "https://chat.z.ai/";
  const targetHost = hostOf(targetUrl);
  const frameAge = frameTs ? Math.max(0, Math.round((Date.now() - frameTs) / 1000)) : null;
  const loginBadge =
    status?.login === "signed-in" ? (
      <Badge className="bg-emerald-600 hover:bg-emerald-600">Logged in</Badge>
    ) : status?.login === "signed-out" ? (
      <Badge className="bg-amber-600 hover:bg-amber-600">Not logged in</Badge>
    ) : (
      <Badge variant="secondary">Login state unknown</Badge>
    );

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
          <span className="relative flex h-2.5 w-2.5" aria-hidden="true">
            <span
              className={`absolute inline-flex h-full w-full rounded-full ${
                frameOk ? "animate-ping bg-emerald-500/60" : "bg-muted-foreground/40"
              }`}
            />
            <span
              className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
                frameOk ? "bg-emerald-600" : "bg-muted-foreground"
              }`}
            />
          </span>
          <div className="mr-auto min-w-0">
            <h1 className="truncate text-base font-semibold leading-tight sm:text-lg">
              Replay Console
            </h1>
            <p className="truncate text-xs text-muted-foreground">
              Live browser replay · click the screenshot to interact, drag for sliders · operator ⇄ agent thread
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {loginBadge}
            <Badge variant={status?.chrome ? "default" : "destructive"}>
              Chrome {status?.chrome ? "up" : "down"}
            </Badge>
            <Badge variant="outline">agent {ageLabel(status?.agentActiveAgo)}</Badge>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4 px-4 py-4 lg:flex-row">
        {/* -------- left: browser replay -------- */}
        <section className="min-w-0 flex-1" aria-label="Live browser replay">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-center gap-2">
                <MonitorPlay className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
                <CardTitle className="text-base">Browser replay</CardTitle>
                {frameOk ? (
                  <Badge className="bg-emerald-600 hover:bg-emerald-600">
                    live · {frameAge === null ? "" : `${frameAge}s old`}
                  </Badge>
                ) : (
                  <Badge variant="destructive">{frameErr ? "no signal" : "connecting"}</Badge>
                )}
                <span className="ml-auto truncate text-xs text-muted-foreground">
                  {activeUrl ? hostOf(activeUrl) : "no active tab"}
                </span>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {/* tab chips */}
              <nav aria-label="Browser tabs" className="thin-scroll -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
                {tabs.length === 0 && (
                  <span className="text-xs text-muted-foreground">no tabs</span>
                )}
                {tabs.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => selectTab(t.id)}
                    aria-pressed={t.id === activeTab}
                    className={`flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                      t.id === activeTab
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-muted text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        t.url.includes(targetHost) ? "bg-emerald-500" : "bg-muted-foreground/50"
                      }`}
                      aria-hidden="true"
                    />
                    <span className="max-w-36 truncate">{hostOf(t.url)}</span>
                    <span className="max-w-48 truncate opacity-70">{t.title}</span>
                  </button>
                ))}
              </nav>

              {/* live frame */}
              <div className="relative overflow-hidden rounded-md border bg-muted/60">
                {frameUrl ? (
                  <img
                    src={frameUrl}
                    alt="Live screenshot of the resident agent's browser"
                    onMouseDown={onFrameMouseDown}
                    onMouseUp={onFrameMouseUp}
                    onMouseLeave={() => {
                      dragStartRef.current = null;
                    }}
                    draggable={false}
                    className="block w-full cursor-crosshair select-none"
                    aria-label="Browser replay screenshot; click to interact, drag for sliders"
                  />
                ) : (
                  <Skeleton className="aspect-[1440/756] w-full" />
                )}
                {frameUrl && frameErr && (
                  <div className="absolute left-2 top-2 rounded bg-amber-600 px-2 py-0.5 text-xs font-medium text-white">
                    stale frame — keeping last image
                  </div>
                )}
              </div>

              {/* controls */}
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1" role="group" aria-label="Scroll the page">
                  <Button variant="outline" size="icon" className="h-10 w-10" aria-label="Scroll up" onClick={() => sendEvent({ type: "scroll", dy: -SCROLL_STEP })}>
                    <ChevronUp className="h-4 w-4" />
                  </Button>
                  <Button variant="outline" size="icon" className="h-10 w-10" aria-label="Scroll down" onClick={() => sendEvent({ type: "scroll", dy: SCROLL_STEP })}>
                    <ChevronDown className="h-4 w-4" />
                  </Button>
                  <Button variant="outline" size="icon" className="h-10 w-10" aria-label="Scroll left" onClick={() => sendEvent({ type: "scroll", dx: -SCROLL_STEP })}>
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <Button variant="outline" size="icon" className="h-10 w-10" aria-label="Scroll right" onClick={() => sendEvent({ type: "scroll", dx: SCROLL_STEP })}>
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
                <Button variant="outline" className="h-10" onClick={() => sendEvent({ type: "reload" })}>
                  <RotateCw className="mr-1.5 h-4 w-4" aria-hidden="true" /> Reload
                </Button>
                <Button variant="outline" className="h-10" onClick={() => sendEvent({ type: "nav", url: targetUrl })}>
                  <Globe className="mr-1.5 h-4 w-4" aria-hidden="true" /> {targetHost}
                </Button>
                <span className="ml-auto max-w-full truncate text-xs text-muted-foreground" aria-live="polite">
                  {lastAction}
                </span>
              </div>

              {/* keyboard box: type into the page */}
              <div className="flex items-center gap-2">
                <Keyboard className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <Input
                  value={typeInput}
                  onChange={(e) => setTypeInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") typeAndEnter();
                  }}
                  placeholder="Type into the page, then press Enter…"
                  aria-label="Type text into the browser page"
                  className="h-10"
                />
                <Button className="h-10 shrink-0" onClick={typeAndEnter} disabled={!typeInput}>
                  Type ↵
                </Button>
              </div>
            </CardContent>
          </Card>
        </section>

        {/* -------- right: status + operator⇄agent thread -------- */}
        <aside className="flex w-full flex-col gap-4 lg:w-[380px]" aria-label="Agent status and messages">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
                <CardTitle className="text-base">Status</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted-foreground">Display (Xvfb)</dt>
                <dd>{status?.xvfb ? "up" : "down"}</dd>
                <dt className="text-muted-foreground">Chrome (CDP)</dt>
                <dd>{status?.chrome ? "up" : "down"}</dd>
                <dt className="text-muted-foreground">Dev server</dt>
                <dd>{status?.dev ? "up" : "down"}</dd>
                <dt className="text-muted-foreground">Active tab</dt>
                <dd className="min-w-0 truncate" title={status?.active?.url ?? ""}>
                  {status?.active ? `${hostOf(status.active.url)} — ${status.active.title || "untitled"}` : "none"}
                </dd>
                <dt className="text-muted-foreground">Login</dt>
                <dd className="min-w-0 truncate">
                  {status?.login === "signed-in"
                    ? `signed in${status.account ? ` (${status.account})` : ""}`
                    : status?.login === "signed-out"
                      ? "not signed in — use Sign in → Continue with email"
                      : "unknown"}
                </dd>
                <dt className="text-muted-foreground">Browser tabs</dt>
                <dd>{status?.tabCount ?? tabs.length}</dd>
                <dt className="text-muted-foreground">Agent last active</dt>
                <dd>{ageLabel(status?.agentActiveAgo)}</dd>
                <dt className="text-muted-foreground">Watcher</dt>
                <dd>{ageLabel(status?.watcherActiveAgo)}</dd>
              </dl>
            </CardContent>
          </Card>

          <Card className="flex min-h-72 flex-col">
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <MessageSquare className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
                <CardTitle className="text-base">Operator ⇄ Agent</CardTitle>
                <Badge variant="outline" className="ml-auto">
                  {messages.length}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col gap-3">
              <div
                ref={threadRef}
                className="thin-scroll flex max-h-96 flex-1 flex-col gap-2 overflow-y-auto pr-1"
                role="log"
                aria-label="Message thread with the resident agent"
                aria-live="polite"
              >
                {messages.length === 0 && (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    No messages yet — say hello to the agent.
                  </p>
                )}
                {messages.map((m, i) => (
                  <div
                    key={`${m.ts}-${i}`}
                    className={`flex flex-col gap-0.5 ${m.from === "operator" ? "items-end" : "items-start"}`}
                  >
                    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      {m.from === "operator" ? (
                        <User className="h-3 w-3" aria-hidden="true" />
                      ) : (
                        <Bot className="h-3 w-3" aria-hidden="true" />
                      )}
                      <span>{m.from === "operator" ? "you" : "agent"}</span>
                      <span aria-hidden="true">·</span>
                      <time dateTime={new Date(m.ts).toISOString()}>{timeLabel(m.ts)}</time>
                    </div>
                    <div
                      className={`max-w-[85%] whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-sm leading-relaxed ${
                        m.from === "operator"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-foreground"
                      }`}
                    >
                      {m.text}
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2 border-t pt-3">
                <Input
                  value={msgInput}
                  onChange={(e) => setMsgInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") sendMessage();
                  }}
                  placeholder="Message the agent…"
                  aria-label="Message the resident agent"
                  className="h-11"
                />
                <Button className="h-11 shrink-0" onClick={sendMessage} disabled={!msgInput.trim() || sendingMsg}>
                  <Send className="mr-1.5 h-4 w-4" aria-hidden="true" />
                  Send
                </Button>
              </div>
            </CardContent>
          </Card>
        </aside>
      </main>

      <footer className="mt-auto border-t bg-card">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-xs text-muted-foreground">
          <span>
            replay {frameOk ? "live" : "down"} · frame {frameAge === null ? "—" : `${frameAge}s`} · poll{" "}
            {FRAME_POLL_MS / 1000}s
          </span>
          <span>{tabs.length} tab{tabs.length === 1 ? "" : "s"}</span>
          <span>agent active {ageLabel(status?.agentActiveAgo)}</span>
          <span className="ml-auto">clicks &amp; drags map via image natural size · never hardcoded</span>
        </div>
      </footer>
    </div>
  );
}
