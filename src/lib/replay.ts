import { execFile } from "child_process";
import { readFileSync } from "fs";
import { join } from "path";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

/**
 * Path + interpreter resolution for the replay stack.
 *
 * The Next.js dev server runs with cwd = repo root (launch_dev.py sets it),
 * so scripts/ sits at <root>/scripts. The python interpreter is resolved by
 * deploy.sh (it needs the `websocket` module) and recorded in
 * scripts/python_bin.txt; we read it once at module load.
 */
const ROOT = process.cwd();
export const SCRIPTS = join(ROOT, "scripts");
export const FLAGS = join(SCRIPTS, "flags");
export const BRIDGE = join(SCRIPTS, "bridge.py");
export const WATCHER_LOG = join(SCRIPTS, "watcher.log");
export const REPLAYD_URL =
  process.env.REPLAYD_URL || "http://127.0.0.1:3100";

function resolvePython(): string {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  try {
    const p = readFileSync(join(SCRIPTS, "python_bin.txt"), "utf-8").trim();
    if (p) return p;
  } catch {
    /* fall through */
  }
  return "python3";
}

/** Lazily resolved interpreter: deploy.sh may write python_bin.txt AFTER the
 * console is already running (e.g. a platform-managed dev server), so
 * resolving once at module load can pin a wrong "python3" fallback for the
 * whole server lifetime. */
export function pyBin(): string {
  return resolvePython();
}

/** Run bridge.py <cmd> and return stdout as Buffer (binary-safe). */
export function runBridge(cmd: string, arg?: string, timeoutMs = 25000) {
  const args = arg ? [BRIDGE, cmd, arg] : [BRIDGE, cmd];
  return execFileAsync(pyBin(), args, {
    timeout: timeoutMs,
    maxBuffer: 16 * 1024 * 1024,
    encoding: "buffer",
  });
}

/** Run bridge.py <cmd> and parse the last JSON line from stdout. */
export async function runBridgeJson(cmd: string, arg?: string, timeoutMs = 25000) {
  const { stdout } = await execFileAsync(pyBin(), arg ? [BRIDGE, cmd, arg] : [BRIDGE, cmd], {
    timeout: timeoutMs,
    maxBuffer: 4 * 1024 * 1024,
  });
  const text = stdout.toString("utf-8").trim().split("\n").pop() || "{}";
  return JSON.parse(text);
}

export function timeoutSignal(ms: number): AbortSignal {
  const ctl = new AbortController();
  setTimeout(() => ctl.abort(), ms);
  return ctl.signal;
}
