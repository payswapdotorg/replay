import { promises as fs } from "fs";
import path from "path";
import { FLAGS_DIR } from "@/lib/bridge";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const OPERATOR_INBOX = path.join(FLAGS_DIR, "operator_inbox.jsonl");
const AGENT_OUTBOX = path.join(FLAGS_DIR, "agent_outbox.jsonl");

export interface ThreadMessage {
  ts: number;
  from: "operator" | "agent";
  text: string;
}

async function readJsonl(file: string): Promise<ThreadMessage[]> {
  try {
    const txt = await fs.readFile(file, "utf8");
    return txt
      .split("\n")
      .filter((l) => l.trim())
      .map((l) => {
        try {
          return JSON.parse(l) as ThreadMessage;
        } catch {
          return null;
        }
      })
      .filter((m): m is ThreadMessage => m !== null && typeof m.text === "string");
  } catch {
    return [];
  }
}

/** GET /api/inbox -> merged operator+agent message thread, sorted by ts. */
export async function GET() {
  const [operator, agent] = await Promise.all([
    readJsonl(OPERATOR_INBOX),
    readJsonl(AGENT_OUTBOX),
  ]);
  const messages = [...operator, ...agent].sort((a, b) => (a.ts || 0) - (b.ts || 0));
  return Response.json({ ok: true, messages });
}

/** POST /api/inbox {text} -> append operator message to operator_inbox.jsonl. */
export async function POST(req: Request) {
  let body: { text?: unknown };
  try {
    body = (await req.json()) as { text?: unknown };
  } catch {
    return Response.json({ ok: false, error: "invalid json" }, { status: 400 });
  }
  const text = typeof body.text === "string" ? body.text.trim().slice(0, 4000) : "";
  if (!text) {
    return Response.json({ ok: false, error: "empty text" }, { status: 400 });
  }
  const message: ThreadMessage = { ts: Date.now(), from: "operator", text };
  try {
    await fs.mkdir(FLAGS_DIR, { recursive: true });
    await fs.appendFile(OPERATOR_INBOX, JSON.stringify(message) + "\n", "utf8");
    return Response.json({ ok: true, message });
  } catch (e) {
    const message_ = e instanceof Error ? e.message : String(e);
    return Response.json({ ok: false, error: message_ }, { status: 500 });
  }
}
