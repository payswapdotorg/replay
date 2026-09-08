import { execFile } from "child_process";
import { join } from "path";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

/**
 * Environment overrides keep the console deployable outside the standard
 * z.ai sandbox layout (/home/z/my-project + /home/z/.venv):
 *   PYTHON_BIN  python interpreter with websocket-client installed
 *   PROJECT_ROOT absolute path of this repo checkout (defaults to cwd)
 */
const PROJECT_ROOT = process.env.PROJECT_ROOT ?? process.cwd();
export const PY = process.env.PYTHON_BIN ?? "/home/z/.venv/bin/python3";
export const BRIDGE = join(PROJECT_ROOT, "scripts", "bridge.py");
export const FLAGS_DIR = join(PROJECT_ROOT, "scripts", "flags");

/** Run bridge.py and return stdout as text (for tabs/status/event). */
export async function runBridge(args: string[]): Promise<string> {
  const { stdout } = await execFileAsync(PY, [BRIDGE, ...args], {
    timeout: 20_000,
    maxBuffer: 16 * 1024 * 1024,
  });
  return (stdout as unknown as string).trim();
}

/**
 * Run bridge.py and return stdout as a raw Buffer (for `frame`).
 * CRITICAL: screenshots must be routed as buffers — passing them through a
 * string (encoding: 'utf8') corrupts the JPEG bytes.
 */
export async function runBridgeBuffer(args: string[]): Promise<Buffer> {
  const { stdout } = (await execFileAsync(PY, [BRIDGE, ...args], {
    encoding: "buffer",
    timeout: 20_000,
    maxBuffer: 16 * 1024 * 1024,
  })) as unknown as { stdout: Buffer };
  return stdout;
}
