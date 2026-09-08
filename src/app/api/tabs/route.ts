import { promises as fs } from "fs";
import path from "path";
import { runBridge, FLAGS_DIR } from "@/lib/bridge";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const ACTIVE_TAB_FILE = path.join(FLAGS_DIR, "active_tab.txt");

interface TabInfo {
  id: string;
  title: string;
  url: string;
}

/** GET /api/tabs -> browser tab list + active tab id. */
export async function GET() {
  try {
    const out = await runBridge(["tabs"]);
    const parsed = JSON.parse(out) as { ok?: boolean; tabs?: TabInfo[]; active?: string | null };
    return Response.json(
      { ok: parsed.ok ?? false, tabs: parsed.tabs ?? [], active: parsed.active ?? null },
      { status: 200 },
    );
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return Response.json({ ok: false, tabs: [], active: null, error: message }, { status: 502 });
  }
}

/** POST /api/tabs {id} -> set the active tab (persisted to flags/active_tab.txt). */
export async function POST(req: Request) {
  let body: { id?: unknown };
  try {
    body = (await req.json()) as { id?: unknown };
  } catch {
    return Response.json({ ok: false, error: "invalid json" }, { status: 400 });
  }
  const id = typeof body.id === "string" ? body.id.trim() : "";
  if (!id) {
    return Response.json({ ok: false, error: "missing id" }, { status: 400 });
  }

  // verify the tab still exists
  try {
    const out = await runBridge(["tabs"]);
    const parsed = JSON.parse(out) as { tabs?: TabInfo[] };
    if (!(parsed.tabs ?? []).some((t) => t.id === id)) {
      return Response.json({ ok: false, error: "tab not found" }, { status: 404 });
    }
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return Response.json({ ok: false, error: message }, { status: 502 });
  }

  try {
    await fs.mkdir(FLAGS_DIR, { recursive: true });
    await fs.writeFile(ACTIVE_TAB_FILE, id, "utf8");
    return Response.json({ ok: true, id });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return Response.json({ ok: false, error: message }, { status: 500 });
  }
}
