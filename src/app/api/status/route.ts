import { runBridge } from "@/lib/bridge";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * GET /api/status -> JSON status snapshot (processes, active tab, login
 * state, heartbeat ages) produced by `bridge.py status`.
 */
export async function GET() {
  try {
    const out = await runBridge(["status"]);
    const parsed = JSON.parse(out) as Record<string, unknown>;
    return Response.json({ ok: parsed.ok ?? true, ...parsed });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return Response.json({ ok: false, error: message }, { status: 502 });
  }
}
