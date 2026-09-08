import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export const PY = "/home/z/.venv/bin/python3";
export const BRIDGE = "/home/z/my-project/scripts/bridge.py";
export const FLAGS_DIR = "/home/z/my-project/scripts/flags";

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
