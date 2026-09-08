import { BRIDGE, REPLAYD_URL, runBridgeJson, timeoutSignal } from "@/lib/replay";

export async function POST(req: Request) {
  const payload = await req.json();
  // hot path: persistent replay daemon — streamed drag events land in ~5ms
  try {
    const r = await fetch(`${REPLAYD_URL}/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: timeoutSignal(9000),
    });
    if (r.ok) {
      return Response.json(await r.json());
    }
  } catch {
    /* daemon unavailable — legacy spawn fallback below */
  }
  try {
    const result = await runBridgeJson("event", JSON.stringify(payload), 20000);
    return Response.json(result);
  } catch (e) {
    return Response.json({ ok: false, error: String(e) }, { status: 500 });
  }
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
