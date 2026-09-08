import { promises as fsp } from "fs";
import { join } from "path";
import { FLAGS, WATCHER_LOG } from "@/lib/replay";

const INBOX = join(FLAGS, "operator_inbox.jsonl");
const OUTBOX = join(FLAGS, "agent_outbox.jsonl");
const HEARTBEAT = join(FLAGS, "heartbeat");

type Msg = { ts: number; from: "operator" | "agent"; text: string };

async function readThread(): Promise<Msg[]> {
  const msgs: Msg[] = [];
  for (const [path, from] of [
    [INBOX, "operator"],
    [OUTBOX, "agent"],
  ] as const) {
    try {
      const raw = await fsp.readFile(path, "utf-8");
      for (const line of raw.split("\n")) {
        const t = line.trim();
        if (!t) continue;
        try {
          const d = JSON.parse(t);
          if (d && typeof d.text === "string") {
            msgs.push({ ts: Number(d.ts) || 0, from, text: String(d.text).slice(0, 2000) });
          }
        } catch {
          /* skip malformed line */
        }
      }
    } catch {
      /* file may not exist yet */
    }
  }
  msgs.sort((a, b) => a.ts - b.ts);
  return msgs;
}

export async function GET() {
  const msgs = await readThread();
  let agentHeartbeatMs = 0;
  let watcherAlive = false;
  try {
    const st = await fsp.stat(HEARTBEAT);
    agentHeartbeatMs = st.mtimeMs;
  } catch {
    /* no heartbeat yet */
  }
  try {
    const st = await fsp.stat(WATCHER_LOG);
    watcherAlive = Date.now() - st.mtimeMs < 300000;
  } catch {
    /* no watcher log */
  }
  return Response.json(
    {
      thread: msgs.slice(-100),
      agent_heartbeat_ms: agentHeartbeatMs,
      watcher_alive: watcherAlive,
    },
    { headers: { "Cache-Control": "no-store" } }
  );
}

export async function POST(req: Request) {
  try {
    const { text } = (await req.json()) as { text?: string };
    const clean = (text || "").trim().slice(0, 2000);
    if (!clean) {
      return Response.json({ ok: false, error: "empty" }, { status: 400 });
    }
    await fsp.mkdir(FLAGS, { recursive: true });
    const line = JSON.stringify({ ts: Date.now(), from: "operator", text: clean }) + "\n";
    await fsp.appendFile(INBOX, line, "utf-8");
    return Response.json({ ok: true });
  } catch (e) {
    return Response.json({ ok: false, error: String(e) }, { status: 500 });
  }
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
