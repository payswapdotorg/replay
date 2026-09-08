import { runBridgeBuffer } from "@/lib/bridge";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * GET /api/frame -> live JPEG screenshot of the active browser tab.
 * Binary-safe: buffer encoding end to end, no-store caching.
 */
export async function GET() {
  try {
    const buf = await runBridgeBuffer(["frame"]);
    if (!buf || buf.length < 100) {
      return new Response(null, { status: 502 });
    }
    return new Response(new Uint8Array(buf), {
      status: 200,
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return new Response(null, { status: 502 });
  }
}
