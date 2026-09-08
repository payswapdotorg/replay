import { runBridgeJson } from "@/lib/replay";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    // bridge.py status: {ts, repo, browser_login, main_sha?, branches?, pulls?}
    // repo is "" unless configured in scripts/env.sh — the console hides the
    // repo card in that case.
    const data = await runBridgeJson("status", undefined, 30000);
    return Response.json(data);
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
