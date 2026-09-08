import { BRIDGE, REPLAYD_URL, runBridge, timeoutSignal } from "@/lib/replay";

export async function GET() {
  // hot path: persistent replay daemon (~90ms frames, persistent CDP conns)
  try {
    const r = await fetch(`${REPLAYD_URL}/frame`, {
      cache: "no-store",
      signal: timeoutSignal(9000),
    });
    if (r.ok) {
      const buf = await r.arrayBuffer();
      if (buf.byteLength > 0) {
        return new Response(new Uint8Array(buf), {
          headers: {
            "Content-Type": "image/jpeg",
            "Cache-Control": "no-store, no-cache, must-revalidate",
          },
        });
      }
    }
  } catch {
    /* daemon unavailable — legacy spawn fallback below */
  }
  try {
    const { stdout } = await runBridge("frame");
    const buf = stdout as unknown as Buffer;
    if (!buf || buf.length === 0) {
      return new Response("", { status: 500 });
    }
    return new Response(new Uint8Array(buf), {
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": "no-store, no-cache, must-revalidate",
      },
    });
  } catch {
    return new Response("", { status: 500 });
  }
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
