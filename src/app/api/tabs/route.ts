import { promises as fsp } from "fs";
import { join } from "path";
import { REPLAYD_URL, FLAGS, runBridgeJson, timeoutSignal } from "@/lib/replay";

export async function GET() {
  // hot path: persistent replay daemon
  try {
    const r = await fetch(`${REPLAYD_URL}/tabs`, {
      cache: "no-store",
      signal: timeoutSignal(6000),
    });
    if (r.ok) {
      return Response.json(await r.json());
    }
  } catch {
    /* daemon unavailable — legacy spawn fallback below */
  }
  try {
    return Response.json(await runBridgeJson("tabs", undefined, 15000));
  } catch (e) {
    return Response.json({ active: "", new: [], tabs: [], error: String(e) }, { status: 500 });
  }
}

export async function POST(req: Request) {
  try {
    const { id } = (await req.json()) as { id?: string };
    if (!id || typeof id !== "string" || id.length > 64) {
      return Response.json({ ok: false, error: "bad id" }, { status: 400 });
    }
    // forward to the daemon (it persists the choice in its flags dir)
    try {
      const r = await fetch(`${REPLAYD_URL}/tabs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
        cache: "no-store",
        signal: timeoutSignal(5000),
      });
      if (r.ok) return Response.json(await r.json());
    } catch {
      /* daemon unavailable — write the flag file directly */
    }
    await fsp.mkdir(FLAGS, { recursive: true });
    await fsp.writeFile(join(FLAGS, "active_tab.txt"), id, "utf-8");
    return Response.json({ ok: true, id });
  } catch (e) {
    return Response.json({ ok: false, error: String(e) }, { status: 500 });
  }
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
