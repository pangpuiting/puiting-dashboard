# -*- coding: utf-8 -*-
"""抓取江门房产信息平台官方 API，输出结构化 data.json（纯标准库，无第三方依赖）。

用法: python scripts/fetch_data.py [--out data.json]
失败策略: 任一项目连续 3 次重试仍失败 -> 打印 ERROR 并以退出码 2 结束（不产出 data.json），
          上层 workflow 检测到失败即跳过 commit，保持上一次成功数据。
"""
import urllib.request
import re
import json
import sys
import time
from datetime import datetime, timezone, timedelta

JGID = "d111693f-6943-4f13-858a-cd61ff9184fd"
BASE = "http://jmzjj.jiangmen.cn:8085/public/web/Kfxm"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

CST = timezone(timedelta(hours=8))

# 官方项目 ID -> 工作台竞品名（保利西海岸 = 今古洲 + 御海 两项目之和）
PROJECTS = {
    "怡福·峰荟":     "2e94c442-0526-401a-bb7b-9d316ee3fc9b",
    "天悦骏汇花园":   "ab60e1d4-5e6d-419b-98dd-5abd691b59f9",
    "银海盛汇天际":   "791e9dfb-7da5-4553-89a8-ff1b69fefb59",
    "骏景湾天汇":     "1d5087ae-34c6-4928-9f8c-60497139379d",
    "怡福·博荟":     "7facbc62-b136-437c-9407-c3560d69f4d5",
    "朗廷云墅花园":   "753f571c-db5e-4e7a-aad4-12b2797212fc",
    "珑城半山":      "1704F62AD656456E9D05DF8CE8712007",
    "保利今古洲":     "63562FD72788441A9E2C3EFA2CB7D1A2",
    "保利御海":      "FBC3A6F01F4146EAA802850DC423DE89",
}


def clean(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


TIMEOUT = 60  # 御海(545KB) 实测需 ~29s，海外 IP 更慢，留足余量


def fetch_page(xmid: str, tries: int = 3) -> str:
    """抓取单项目页面。超时 60s，退避重试。"""
    url = f"{BASE}?xmid={xmid}&jgid={JGID}"
    last_err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"    retry {i + 1}/{tries} for {xmid[:8]}: {type(e).__name__}")
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"fetch failed after {tries} tries: {last_err}")


def parse_project(html: str) -> dict:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    table = {}
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        cells = [clean(c) for c in cells]
        if len(cells) >= 2 and cells[0]:
            table[cells[0]] = cells[1]

    def num(key: str) -> int:
        v = table.get(key, "")
        m = re.search(r"([\d,]+)", v.replace(",", ""))
        return int(m.group(1)) if m else -1

    def price(key: str):
        v = table.get(key, "")
        m = re.search(r"(\d+(?:\.\d+)?)", v)
        return float(m.group(1)) if m else None

    return {
        "备案名": table.get("项目名称：", ""),
        "sold": num("已售住宅套数："),
        "total": num("住宅套数："),
        "price": price("住宅均价："),
        "sold_non_res": num("已售非住宅套数："),
    }


def main() -> int:
    out_path = "data.json"
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]

    results: dict = {}
    failed: list = []

    # 并发抓取（3 路），总耗时约 1/3。串行 9 盘在海外 IP 上易触 CI 超时。
    def job(item):
        name, xmid = item
        return name, parse_project(fetch_page(xmid))

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(job, it): it[0] for it in PROJECTS.items()}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                n, info = fut.result()
                results[n] = info
                print(f"[OK] {n}: sold={info['sold']}/{info['total']} price={info['price']}")
            except Exception as e:  # noqa: BLE001
                failed.append(name)
                print(f"[ERROR] {name}: {e}")

    if failed:
        print(f"\nFAILED projects: {failed} — 不产出 data.json，保持上次数据")
        return 2

    # 保利西海岸 = 今古洲 + 御海
    try:
        jgz, yh = results["保利今古洲"], results["保利御海"]
        results["保利西海岸"] = {
            "备案名": "骏凯豪庭(今古洲+御海)",
            "sold": jgz["sold"] + yh["sold"],
            "total": jgz["total"] + yh["total"],
            "price": round(
                (jgz["price"] * jgz["sold"] + yh["price"] * yh["sold"])
                / (jgz["sold"] + yh["sold"]), 0
            ) if (jgz["price"] and yh["price"] and (jgz["sold"] + yh["sold"])) else None,
            "拆分": {"今古洲": jgz, "御海": yh},
        }
        print(f"[OK] 保利西海岸(合并): sold={results['保利西海岸']['sold']}/{results['保利西海岸']['total']}")
    except KeyError:
        print("[ERROR] 保利拆分项目缺失")
        return 2

    payload = {
        "fetched_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
        "source": "jmzjj.jiangmen.cn:8085 官方累计口径（延迟一天发布）",
        "projects": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nSaved -> {out_path} ({len(results)} projects)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
