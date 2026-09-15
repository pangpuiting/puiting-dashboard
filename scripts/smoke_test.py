# -*- coding: utf-8 -*-
"""冒烟测试：验证 index.html 数据结构完整性与一致性（纯标准库）。

用法: python scripts/smoke_test.py [--html index.html]
"""
import re
import sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
API_KEYS = ["怡福·峰荟", "天悦骏汇花园", "银海盛汇天际", "骏景湾天汇",
            "怡福·博荟", "珑城半山", "保利西海岸", "朗廷云墅花园"]

fails = []


def check(cond, msg):
    print(("  [PASS] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


def main() -> int:
    html_path = "index.html"
    if "--html" in sys.argv:
        html_path = sys.argv[sys.argv.index("--html") + 1]
    html = open(html_path, encoding="utf-8").read()

    print("== 1. 结构完整性 ==")
    check(html.count("<script>") >= 1 and html.count("</script>") >= 1, "script 标签配对")
    check(html.count("{") == html.count("}"), "大括号平衡 (%d/%d)" % (html.count("{"), html.count("}")))
    check(html.count("(") == html.count(")"), "小括号平衡 (%d/%d)" % (html.count("("), html.count(")")))
    check(",," not in html, "无连续逗号（格式崩坏检查）")
    check('const D' in html or 'D = {' in html or 'var D' in html, "数据对象 D 存在")

    print("== 2. 关键字段 ==")
    mo = re.search(r'updatedAt: "(\d{4}-\d{2}-\d{2})', html)
    check(bool(mo), "updatedAt 存在")
    if mo:
        d = datetime.strptime(mo.group(1), "%Y-%m-%d").date()
        today = datetime.now(CST).date()
        check((today - d).days <= 3, f"updatedAt 距今 {(today - d).days} 天（<=3）")

    print("== 3. mSnap 一致性 ==")
    m = re.search(r'mSnap: \{date:"(\d{4}-\d{2}-\d{2})", sold:\{(.*?)\n  \}\}', html, re.S)
    check(bool(m), "mSnap 存在")
    snap = {}
    if m:
        for name, val in re.findall(r'"([^"]+)":\s*(\d+)', m.group(2)):
            snap[name] = int(val)
        check(snap.get("怡福·峰荟", -1) > 0, "峰荟快照有值")
        check(snap.get("外围改善组") == 0, "外围改善组=0")

    print("== 4. 各盘 sel == mSnap ==")
    for key in API_KEYS:
        anchor = re.search(r'name: "' + re.escape(key) + r'",', html)
        if not anchor:
            check(False, f"{key}: 竞品对象缺失")
            continue
        win = html[anchor.end():anchor.end() + 4000]
        ms = re.search(r"sel: \{sold: (\d+), total: (\d+), pct: (\d+)\}", win)
        check(bool(ms), f"{key}: sel 存在")
        if ms and key in snap:
            sold = int(ms.group(1))
            check(sold == snap[key], f"{key}: sel.sold({sold}) == mSnap({snap[key]})")
            total = int(ms.group(2))
            pct = int(ms.group(3))
            check(abs(pct - round(sold / total * 100)) <= 1, f"{key}: pct 合理")

    print("== 5. 不变量 ==")
    check("rankHist" in html and "2026-08" in html, "rankHist 历史月保留")
    check(len(re.findall(r'policies:', html)) == 1, "policies 数组唯一")
    check(html.count("怡福·峰荟") >= 3, "峰荟至少出现 3 处（卡片/排名/mSnap）")

    print()
    if fails:
        print(f"FAILED: {len(fails)} 项未通过")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
