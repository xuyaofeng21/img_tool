from __future__ import annotations

import sys
import types
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "webview" not in sys.modules:
    fake_webview = types.SimpleNamespace(FOLDER_DIALOG=1)
    sys.modules["webview"] = fake_webview


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def]
    report_dir = ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "iteration_report.md"

    stats = session.config.pluginmanager.get_plugin("terminalreporter").stats  # type: ignore[union-attr]
    passed = len(stats.get("passed", []))
    failed = len(stats.get("failed", []))
    skipped = len(stats.get("skipped", []))
    total = session.testscollected

    failed_cases = []
    for item in stats.get("failed", []):
        nodeid = getattr(item, "nodeid", "")
        if nodeid:
            failed_cases.append(f"- `{nodeid}`")

    status = "通过" if exitstatus == 0 else "未通过"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# 迭代测试报告",
        "",
        f"- 生成时间：`{now}`",
        f"- 测试状态：**{status}**",
        f"- 总用例：`{total}`",
        f"- 通过：`{passed}`",
        f"- 失败：`{failed}`",
        f"- 跳过：`{skipped}`",
        "",
        "## 本轮结论",
        "- 已执行自动化回归，结果见上方统计。",
        "- 本报告为本地质量闭环产物，建议根据失败项优先修复再进入下一轮。",
        "",
        "## 失败清单",
    ]

    if failed_cases:
        lines.extend(failed_cases)
    else:
        lines.append("- 无失败用例")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
