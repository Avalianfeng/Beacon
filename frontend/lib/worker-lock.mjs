/**
 * 探测输出目录是否被 .beacon-worker.lock 占用。
 * 与 Python RunLock 对齐：通过短生命周期子进程调用 is_locked。
 */
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { projectRoot } from "./shared.mjs";

/**
 * @param {string} outDir 已 resolve 的绝对路径
 * @param {object} [opts]
 * @param {() => NodeJS.ProcessEnv} [opts.buildChildEnv]
 * @returns {Promise<boolean>}
 */
export async function is_locked(outDir, opts = {}) {
  const pyCandidates = [
    resolve(projectRoot, ".venv/Scripts/python.exe"),
    resolve(projectRoot, ".venv/bin/python"),
    "python",
  ];
  const script =
    "from math_agent.run_lock import is_locked; import sys; "
    + `sys.exit(0 if is_locked(${JSON.stringify(outDir)}) else 1)`;

  for (const py of pyCandidates) {
    const busy = await new Promise((resolvePromise) => {
      let settled = false;
      const child = spawn(py, ["-c", script], {
        cwd: projectRoot,
        env: opts.buildChildEnv ? opts.buildChildEnv() : process.env,
        windowsHide: true,
      });
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        try { child.kill(); } catch {}
        resolvePromise(null);
      }, 5_000);
      child.on("error", () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolvePromise(null);
      });
      child.on("close", (code) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (code === 0) resolvePromise(true);
        else if (code === 1) resolvePromise(false);
        else resolvePromise(null);
      });
    });
    if (busy !== null) return busy;
  }

  // 无法探测时当作空闲，避免误挡「继续」
  return false;
}
