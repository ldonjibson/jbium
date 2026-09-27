"""
════════════════════════════════════════════════════════════
Diagnose: why is WebGL unavailable?
════════════════════════════════════════════════════════════

test_fingerprint.py reporting WebGL VERSION / vendor / renderer as None
means canvas.getContext('webgl') returned null -- the page has no WebGL
at all. Real Chrome on a desktop always has it (on a machine without a
usable GPU it falls back to the SwiftShader software renderer), so
"no WebGL" is itself a strong automation/VM tell.

This prints what's needed to find out why:
  1. The browser's own GPU report (CDP SystemInfo.getInfo): feature
     status per API (webgl / webgl2 / gpu_compositing ...), the GL
     implementation in use, and the GPU device it found.
  2. The actual WebGL/WebGL2 context-creation error message a page gets.
  3. Which graphics libraries sit next to the binary (SwiftShader /
     ANGLE / Vulkan ICD files the fallback needs).
  4. GPU/GL-related lines from the browser's own stderr.

Usage (same environment as test_fingerprint.py):
    export STEALTH_WEBSHARE_USERNAME=... STEALTH_WEBSHARE_PASSWORD=...
    python example/diagnose_webgl.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from driver.stealth_browser import Jbium, get_random_webshare_proxy
except ModuleNotFoundError:
    from jbium.stealth_browser import Jbium, get_random_webshare_proxy

PROBE_JS = """
(async () => {
    const probe = (type) => {
        const canvas = document.createElement('canvas');
        let error = null;
        canvas.addEventListener('webglcontextcreationerror',
                                e => { error = e.statusMessage || '(no statusMessage)'; });
        const gl = canvas.getContext(type);
        return { available: !!gl, creationError: error };
    };
    return {
        webgl: probe('webgl'),
        webgl2: probe('webgl2'),
        offscreenCanvas: typeof OffscreenCanvas !== 'undefined',
    };
})()
"""

GPU_LOG_WORDS = ("gpu", "gl_", "gles", "egl", "angle", "vulkan", "swiftshader", "webgl", "dri", "glx")


async def main():
    proxy_url = get_random_webshare_proxy()

    async with Jbium() as browser:
        await browser.launch(proxy_url=proxy_url, headless=False)

        print("\n=== 1. Browser GPU report (SystemInfo.getInfo) ===")
        try:
            info = await browser._cdp_command("SystemInfo.getInfo")
            gpu = info.get("gpu", {})
            print("featureStatus:")
            for feature, status in sorted(gpu.get("featureStatus", {}).items()):
                print(f"  {feature:40s} {status}")
            aux = gpu.get("auxAttributes", {})
            for key in ("glImplementationParts", "displayType", "glRenderer", "glVendor",
                        "glVersion", "sandboxed", "gpuCompositing", "skiaBackendType"):
                if key in aux:
                    print(f"{key}: {aux[key]}")
            for i, dev in enumerate(gpu.get("devices", [])):
                print(f"device[{i}]: {json.dumps(dev)}")
            if gpu.get("driverBugWorkarounds"):
                print(f"driverBugWorkarounds: {gpu['driverBugWorkarounds']}")
        except Exception as e:
            print(f"SystemInfo.getInfo failed: {e}")

        print("\n=== 2. WebGL context creation from a page ===")
        page = await browser.new_page()
        await page.goto("https://example.com/")
        print(json.dumps(await page.evaluate(PROBE_JS), indent=2))

        print("\n=== 3. Graphics libraries next to the binary ===")
        bin_dir = Path(browser.browser_path).parent
        print(f"binary dir: {bin_dir}")
        patterns = ("*swiftshader*", "*SwiftShader*", "libEGL*", "libGLESv2*", "libvulkan*",
                    "vk_swiftshader_icd.json")
        found = sorted({p for pattern in patterns for p in bin_dir.rglob(pattern)})
        for path in found:
            print(f"  {path.relative_to(bin_dir)}  ({path.stat().st_size} bytes)")
        if not found:
            print("  (none found -- the software-rendering fallback has nothing to load)")

        print("\n=== 4. GPU-related browser stderr lines ===")
        tail = list(getattr(browser, "_browser_stderr_tail", []))
        gpu_lines = [line for line in tail if any(w in line.lower() for w in GPU_LOG_WORDS)]
        for line in gpu_lines or ["(none in the captured tail)"]:
            print(f"  {line}")


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(main())
