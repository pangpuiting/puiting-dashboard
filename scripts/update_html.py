# -*- coding: utf-8 -*-
"""参数化工作台更新器：输入 data.json -> 差分更新 index.html。

只更新「官方 API 可直接驱动的确定性数字」：
  1. updatedAt
  2. mSnap（日期 + 各盘累计）
  3. 各竞品 sel: {sold, total, pct}
  4. 各竞品 m.sold（本月累计差分，同月累加 / 跨月重置）

不触碰（留给每周人工/Buddy 更新）：selNote、m.note、m.p、m.pw、
statusBar 文案、价格 fields、rankHist、policies、market。

防御策略：某盘数据异常（倒退>5 或单日增量>50）时跳过该盘（保持旧值），
其余照常更新；全部盘异常则退出码 2 不写文件。

用法: python scripts/update_html.py [--html index.html] [--data data.json] [--dry-run]
"""
import re
import json
import sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# 工作台竞品名 -> data.json 项目名（mSnap 中名称与 API 抓取名一致，直接映射）
API_KEYS = [
    "怡福·峰荟", "银海湾壹号", "天悦骏汇花园", "银海盛汇天际", "骏景湾天汇",
    "怡福·博荟", "珑城半山", "保利西海岸", "朗廷云墅花园",
]

# mSnap 内的行序（保持原格式写回）
MSNAP_ORDER = [
    "怡福·峰荟", "银海湾壹号", "天悦骏汇花园", "银海盛汇天际",
    "骏景湾天汇", "怡福·博荟", "珑城半山", "保利西海岸", "朗廷云墅花园", "外围改善组",
]

WARN_DELTA_MAX = 50      # 单日增量超过此值视为可疑
WARN_REGRESS_MAX = 5     # 累计倒退超过此值视为可疑


MSNAP_RE = r'mSnap: \{date:"(\d{4}-\d{2}-\d{2})", sold:\{(.*?)\n  \}\},'


def parse_msnap(html: str) -> dict:
    m = re.search(MSNAP_RE, html, re.S)
    if not m:
        raise ValueError("mSnap not found")
    sold = {}
    for name, val in re.findall(r'"([^"]+)":\s*(\d+)', m.group(2)):
        sold[name] = int(val)
    return {"date": m.group(1), "sold": sold, "block": m.group(0)}


def update_competitor(text: str, name: str, new_sold: int, new_total: int,
                      new_msold: int) -> tuple[str, bool]:
    """定位 name 的 competitor 对象，更新其 sel 与 m.sold。返回(新文本, 是否成功)。"""
    # 锚点：name: "X", 之后、下一个 name: 之前的窗口
    anchor = re.search(r'name: "' + re.escape(name) + r'",', text)
    if not anchor:
        return text, False
    start = anchor.end()
    nxt = re.search(r'\n    \{\n      name: "', text[start:])
    window_end = start + (nxt.start() if nxt else len(text))
    window = text[start:window_end]

    changed = False
    # sel: {sold: X, total: Y, pct: Z}
    def sel_repl(mo):
        nonlocal changed
        pct = round(new_sold / new_total * 100) if new_total else 0
        changed = True
        return f"sel: {{sold: {new_sold}, total: {new_total}, pct: {pct}}}"

    window, n1 = re.subn(r"sel: \{sold: \d+, total: \d+, pct: \d+\}", sel_repl, window, count=1)
    # m: {sold: N, ...
    window, n2 = re.subn(r"(m: \{sold: )\d+", lambda mo: mo.group(1) + str(new_msold), window, count=1)

    if n1 != 1 or n2 != 1 or not changed:
        return text, False
    return text[:start] + window + text[window_end:], True


def main() -> int:
    args = sys.argv[1:]
    html_path = "index.html"
    data_path = "data.json"
    dry = "--dry-run" in args
    if "--html" in args:
        html_path = args[args.index("--html") + 1]
    if "--data" in args:
        data_path = args[args.index("--data") + 1]

    html = open(html_path, encoding="utf-8").read()
    data = json.load(open(data_path, encoding="utf-8"))
    today = datetime.now(CST).strftime("%Y-%m-%d")

    snap = parse_msnap(html)
    snap_month = snap["date"][:7]
    today_month = today[:7]
    cross_month = snap_month != today_month

    warnings = []
    # 1) 计算每盘的新值
    plans = {}  # name -> (new_sold, new_total, new_msold)
    for key in API_KEYS:
        p = data["projects"].get(key)
        if not p or p["sold"] < 0:
            warnings.append(f"{key}: API 数据缺失/无效，跳过")
            continue
        old_sold = snap["sold"].get(key)
        if old_sold is None:
            warnings.append(f"{key}: mSnap 无此盘记录，跳过")
            continue
        delta = p["sold"] - old_sold
        if delta < -WARN_REGRESS_MAX:
            warnings.append(f"{key}: 累计倒退 {delta}（{old_sold}->{p['sold']}），可疑，跳过")
            continue
        if delta > WARN_DELTA_MAX:
            warnings.append(f"{key}: 单次增量 {delta} 超阈值 {WARN_DELTA_MAX}，可疑，跳过")
            continue
        plans[key] = (p["sold"], p["total"], delta)

    if not plans:
        print("ERROR: 无任何可更新盘")
        for w in warnings:
            print("  WARN:", w)
        return 2

    # 2) 各盘 m.sold 旧值（从 HTML 读）
    m_old = {}
    for key in plans:
        anchor = re.search(r'name: "' + re.escape(key) + r'",', html)
        if anchor:
            win = html[anchor.end():anchor.end() + 4000]
            mo = re.search(r"m: \{sold: (\d+)", win)
            m_old[key] = int(mo.group(1)) if mo else 0

    # 3) 更新各竞品 sel + m.sold
    ok, skip = 0, 0
    for key, (new_sold, new_total, delta) in plans.items():
        new_msold = delta if cross_month else m_old.get(key, 0) + delta
        html, success = update_competitor(html, key, new_sold, new_total, new_msold)
        if success:
            ok += 1
            print(f"[UPD] {key}: sold {snap['sold'][key]}->{new_sold} (+{delta}), m.sold -> {new_msold}")
        else:
            skip += 1
            warnings.append(f"{key}: sel/m 定位失败，保持旧值")

    # 4) 更新 mSnap 整块（跳过的盘保持旧值）
    new_snap_sold = dict(snap["sold"])
    for key, (new_sold, _, _) in plans.items():
        new_snap_sold[key] = new_sold
    # 换行位置对齐原格式（第一行 4 个、第二行 6 个），保持 diff 干净
    lines = ", ".join(f'"{n}":{new_snap_sold.get(n, 0)}' for n in MSNAP_ORDER[:4])
    lines2 = ", ".join(f'"{n}":{new_snap_sold.get(n, 0)}' for n in MSNAP_ORDER[4:])
    new_block = f'mSnap: {{date:"{today}", sold:{{\n    {lines},\n    {lines2}\n  }}}},'
    html, n = re.subn(re.escape(snap["block"]), new_block, html, count=1)
    if n != 1:
        print("ERROR: mSnap 替换失败")
        return 2

    # 5) updatedAt
    html, n = re.subn(r'updatedAt: "\d{4}-\d{2}-\d{2} \d{2}:\d{2}"',
                      f'updatedAt: "{today} 09:00"', html, count=1)
    if n != 1:
        print("ERROR: updatedAt 替换失败")
        return 2

    # 6) 自验证
    chk = parse_msnap(html)
    for key, (new_sold, _, _) in plans.items():
        assert chk["sold"][key] == new_sold, f"mSnap 校验失败: {key}"
        anchor = re.search(r'name: "' + re.escape(key) + r'",', html)
        win = html[anchor.end():anchor.end() + 4000]
        ms = re.search(r"sel: \{sold: (\d+)", win)
        assert int(ms.group(1)) == new_sold, f"sel 校验失败: {key}"
    if abs(len(html) - len(open(html_path, encoding='utf-8').read())) > 2000:
        print("ERROR: 文件长度异常变化")
        return 2

    # 7) 输出
    for w in warnings:
        print("  WARN:", w)
    if cross_month:
        print(f"  [跨月] {snap_month} -> {today_month}：m.sold 已重置，rankHist 归档需人工处理")
    print(f"\nOK: 更新 {ok} 盘，跳过 {skip} 盘；mSnap -> {today}")

    if not dry:
        with open(html_path, "w", encoding="utf-8", newline="") as f:
            f.write(html)
        print(f"Written -> {html_path}")
    else:
        print("(dry-run，未写文件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
