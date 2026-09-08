import { runBridge } from "@/lib/bridge";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const ALLOWED_TYPES = new Set([
  "click",
  "dblclick",
  "type",
  "key",
  "enter",
  "scroll",
  "nav",
  "reload",
]);

interface EventSpec {
  type: string;
  x?: number;
  y?: number;
  dx?: number;
  dy?: number;
  text?: string;
  key?: string;
  url?: string;
}

/**
 * POST /api/event {type: click|type|key|enter|scroll|nav|reload, ...}
 * -> dispatch input into the ACTIVE browser tab via bridge.py.
 */
export async function POST(req: Request) {
  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return Response.json({ ok: false, error: "invalid json" }, { status: 400 });
  }

  const type = typeof body.type === "string" ? body.type : "";
  if (!ALLOWED_TYPES.has(type)) {
    return Response.json(
      { ok: false, error: `bad type: ${type || "(none)"}` },
      { status: 400 },
    );
  }

  const spec: EventSpec = { type };
  for (const k of ["x", "y", "dx", "dy"] as const) {
    if (body[k] !== undefined && body[k] !== null && Number.isFinite(Number(body[k]))) {
      spec[k] = Math.round(Number(body[k]));
    }
  }
  if (body.text !== undefined && body.text !== null) {
    spec.text = String(body.text).slice(0, 5000);
  }
  if (body.key !== undefined && body.key !== null) {
    spec.key = String(body.key).slice(0, 32);
  }
  if (body.url !== undefined && body.url !== null) {
    const url = String(body.url).slice(0, 2000);
    if (!/^(https?:\/\/|file:\/\/)/i.test(url)) {
      return Response.json({ ok: false, error: "invalid url" }, { status: 400 });
    }
    spec.url = url;
  }

  try {
    const out = await runBridge(["event", JSON.stringify(spec)]);
    let parsed: { ok?: boolean; error?: string } = {};
    try {
      parsed = JSON.parse(out) as { ok?: boolean; error?: string };
    } catch {
      parsed = { ok: true };
    }
    return Response.json(parsed, {
      status: parsed.ok === false ? 502 : 200,
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return Response.json({ ok: false, error: message }, { status: 502 });
  }
}
