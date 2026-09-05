"""
Tests that all browser signals are internally consistent.
A "consistent" fingerprint means no signal contradicts another.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from driver.stealth_browser import Jbium, get_random_webshare_proxy


async def check_consistency(page) -> dict:
    """
    Check all fingerprint signals for internal consistency.
    Returns list of any inconsistencies found.
    """
    
    issues = []
    
    # Get all properties
    props = {
        "ua": await page.evaluate("navigator.userAgent"),
        "platform": await page.evaluate("navigator.platform"),
        "ua_data": await page.evaluate("""
            navigator.userAgentData ? JSON.stringify({
                platform: navigator.userAgentData.platform,
                mobile: navigator.userAgentData.mobile
            }) : 'null'
        """),
        "cores": await page.evaluate("navigator.hardwareConcurrency"),
        "memory": await page.evaluate("navigator.deviceMemory"),
        "screen_w": await page.evaluate("screen.width"),
        "screen_h": await page.evaluate("screen.height"),
        "dpr": await page.evaluate("window.devicePixelRatio"),
        "timezone": await page.evaluate(
            "Intl.DateTimeFormat().resolvedOptions().timeZone"
        ),
        "language": await page.evaluate("navigator.language"),
        "languages": await page.evaluate(
            "JSON.stringify(navigator.languages)"
        ),
        "touch": await page.evaluate("navigator.maxTouchPoints"),
        "plugins": await page.evaluate("navigator.plugins.length"),
        "webdriver": await page.evaluate("navigator.webdriver"),
    }
    
    # Parse UA data
    ua_data = json.loads(props["ua_data"]) if props["ua_data"] != "null" else {}
    
    # ── Consistency Checks ──
    
    # 1. UA should match platform
    if "Windows" in props["ua"]:
        if props["platform"] != "Win32":
            issues.append({
                "check": "ua_vs_platform",
                "expected": "Win32",
                "actual": props["platform"],
                "severity": "HIGH",
            })
    elif "Macintosh" in props["ua"]:
        if props["platform"] != "MacIntel":
            issues.append({
                "check": "ua_vs_platform",
                "expected": "MacIntel",
                "actual": props["platform"],
                "severity": "HIGH",
            })
    elif "Linux" in props["ua"] and "Android" not in props["ua"]:
        if "Linux" not in props["platform"]:
            issues.append({
                "check": "ua_vs_platform",
                "expected": "Linux x86_64",
                "actual": props["platform"],
                "severity": "HIGH",
            })
    
    # 2. UA Client Hints should match UA
    if ua_data:
        ua_platform = ua_data.get("platform", "")
        if "Windows" in props["ua"] and ua_platform != "Windows":
            issues.append({
                "check": "ua_vs_client_hints",
                "expected": "Windows",
                "actual": ua_platform,
                "severity": "HIGH",
            })
        elif "Macintosh" in props["ua"] and ua_platform != "macOS":
            issues.append({
                "check": "ua_vs_client_hints",
                "expected": "macOS",
                "actual": ua_platform,
                "severity": "HIGH",
            })
    
    # 3. Touch points should be 0 for desktop
    if props["touch"] > 0 and props["dpr"] < 1.5:
        issues.append({
            "check": "touch_vs_desktop",
            "expected": "0 touch points on desktop",
            "actual": str(props["touch"]),
            "severity": "MEDIUM",
        })
    
    # 4. Plugins should be 5 (Chrome-typical)
    if props["plugins"] == 0:
        issues.append({
            "check": "plugins_empty",
            "expected": "5 plugins",
            "actual": "0 plugins",
            "severity": "HIGH",
        })
    elif props["plugins"] != 5:
        issues.append({
            "check": "plugins_count",
            "expected": "5 plugins",
            "actual": str(props["plugins"]),
            "severity": "LOW",
        })
    
    # 5. webdriver must be false
    if props["webdriver"] == True:
        issues.append({
            "check": "webdriver_flag",
            "expected": "false",
            "actual": "true",
            "severity": "CRITICAL",
        })
    
    # 6. Language should not be empty
    if not props["language"]:
        issues.append({
            "check": "language_empty",
            "expected": "non-empty language",
            "actual": "empty",
            "severity": "HIGH",
        })
    
    # 7. Screen resolution should be reasonable
    if props["screen_w"] < 800 or props["screen_h"] < 600:
        issues.append({
            "check": "screen_too_small",
            "expected": "≥ 800x600",
            "actual": f"{props['screen_w']}x{props['screen_h']}",
            "severity": "MEDIUM",
        })
    
    # 8. DPR should be consistent with resolution
    # 4K screens usually have DPR 1.0 or 2.0
    # MacBook Retina has DPR 2.0
    # 1366x768 laptop has DPR 1.0
    if props["screen_w"] == 1366 and props["dpr"] != 1.0:
        issues.append({
            "check": "dpr_vs_resolution",
            "expected": "1.0 for 1366x768",
            "actual": str(props["dpr"]),
            "severity": "LOW",
        })
    
    return {
        "properties": props,
        "issues": issues,
        "consistent": len(issues) == 0,
        "critical_issues": [i for i in issues if i["severity"] == "CRITICAL"],
        "high_issues": [i for i in issues if i["severity"] == "HIGH"],
    }


async def main():
    proxy = get_random_webshare_proxy()
    print(f"Proxy: {proxy}\n")
    
    async with Jbium() as browser:
        session = await browser.launch(proxy_url=proxy, headless=False)
        page = await browser.new_page()
        
        # Wait a moment
        await asyncio.sleep(2)
        
        # Run consistency check
        result = await check_consistency(page)
        
        # Print results
        print("═" * 60)
        print("  CONSISTENCY CHECK RESULTS")
        print("═" * 60)
        
        print(f"\n  Overall: {'✅ CONSISTENT' if result['consistent'] else '❌ INCONSISTENT'}")
        print(f"  Issues found: {len(result['issues'])}")
        
        if result["critical_issues"]:
            print(f"\n  🔴 CRITICAL ISSUES ({len(result['critical_issues'])}):")
            for issue in result["critical_issues"]:
                print(f"     - {issue['check']}: {issue['actual']}")
        
        if result["high_issues"]:
            print(f"\n  🟠 HIGH ISSUES ({len(result['high_issues'])}):")
            for issue in result["high_issues"]:
                print(f"     - {issue['check']}: {issue['actual']}")
        
        if result["issues"] and not result["critical_issues"] and not result["high_issues"]:
            print(f"\n  🟡 OTHER ISSUES ({len(result['issues'])}):")
            for issue in result["issues"]:
                print(f"     - {issue['check']}: {issue['actual']}")
        
        # Print all properties
        print(f"\n  Browser Properties:")
        for key, value in result["properties"].items():
            print(f"    {key}: {value}")
        
        print("\n" + "═" * 60)
        
        # Save results
        with open("test_results/consistency.json", "w") as f:
            json.dump(result, f, indent=2)
        print(f"\n  Results saved: test_results/consistency.json")
        
        # Exit code
        if result["critical_issues"]:
            sys.exit(2)
        elif result["issues"]:
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
