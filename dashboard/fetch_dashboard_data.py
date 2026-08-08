#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
看板数据流水线 v2.2
- 持有池快照（poolFields）
- 日频榜单：先穿透收集→合并去重→一次快照（享阶梯折扣，避免跨榜重复计费）
- 大集合两段式：>bigBoardThreshold 时先用 preFilterFields（强度+节气）粗筛，
  幸存者再补剩余字段（条件为合取式，粗筛只剔除必然不合格者，无漏判）
- 缓存榜（右侧基金）：本地缓存 boardCacheMaxAgeDays 天（默认14，双周报告），
  缓存到期才重新穿透；年龄驱动，漏跑自愈
输出: data/<asOfDate>.json（pools + candidates + sources + asOfDate）+ meta.json
余额不足或接口失败立即终止（不重试付费接口）。
"""
import json, pathlib, urllib.request, urllib.parse, datetime, sys, time, os

BASE = pathlib.Path(__file__).resolve().parent
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
API = "https://www.trendtrader.cn/apiData/data/"
KEY = os.environ.get("TREND_API_KEY") or CFG["apiKey"]
WEEK_CACHE = BASE / "data" / "_weekly_boards.json"


def call(endpoint, **params):
    qs = urllib.parse.urlencode({"apiKey": KEY, **params})
    req = urllib.request.Request(API + endpoint + "?" + qs,
                                 headers={"User-Agent": "trend-dashboard/2.2"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def must_ok(d, endpoint):
    if d.get("code") != "00000":
        msg = (d.get("msg") or "")
        if "余额" in msg or "balance" in msg.lower():
            print("INSUFFICIENT_BALANCE: %s" % msg)
        else:
            print("API_ERROR %s: %s" % (endpoint, msg))
        sys.exit(2)


def balance():
    d = call("getAccountBalance", viewLevel="summary")
    must_ok(d, "getAccountBalance")
    return float(d["data"][0]["balance"])


def snapshot(tmids, fields):
    if not tmids:
        return []
    d = call("getTickerSnapshot", tmIds=",".join(map(str, tmids)),
             fields=",".join(fields))
    must_ok(d, "getTickerSnapshot")
    return d.get("data", [])


def penetrate(board_id):
    d = call("getComponentTicker", tmId=board_id)
    must_ok(d, "getComponentTicker")
    return d.get("data", [])


def snapshot_smart(ids):
    """两段式筛选：先用 preFilterFields（温度前后+强度+节气）粗筛，
    幸存者再补 candidateFields（行业温度/市值/成交额/价格/右侧/危险信号）。
    合取条件，粗筛只剔除必然不合格者，无漏判。返回 {tmId: row}。"""
    if not ids:
        return {}
    pre = snapshot(ids, CFG["preFilterFields"])
    F = CFG["filters"]
    survivors = [r["tmId"] for r in pre
                 if (r.get("trendTemperaturePrev") == "温"
                     and r.get("trendTemperatureCurr") == "热"
                     and (r.get("trendStrengthLocalCurr") or 0) > F["strengthMin"]
                     and (r.get("trendPhaseCurr") or "") in F["phases"])]
    if not survivors:
        return {}
    pre_by_id = {r["tmId"]: r for r in pre}
    merged = {}
    for r in snapshot(survivors, CFG["candidateFields"]):
        m = dict(pre_by_id.get(r["tmId"], {}))
        m.update(r)
        merged[r["tmId"]] = m
    return merged


def main():
    held = CFG["held"]
    watch = CFG.get("watch", [])
    boards_daily = CFG.get("boardsDaily", CFG.get("leaderboards", []))
    boards_cached = CFG.get("boardsCached", CFG.get("boardsWeekly", []))
    board_names = CFG.get("boardNames", {})
    max_age = CFG.get("boardCacheMaxAgeDays", 14) * 86400

    (BASE / "data").mkdir(exist_ok=True)

    status = call("getUpdateStatus")
    must_ok(status, "getUpdateStatus")
    bal0 = balance()

    pools = snapshot(held + watch, CFG["poolFields"]) if (held or watch) else []

    # ---- 日频榜：穿透→合并去重→智能快照
    daily_ids, sources = [], {}
    for b in boards_daily:
        bname = board_names.get(str(b), str(b))
        for x in penetrate(b):
            tid = x["tmId"]
            if tid not in sources:
                daily_ids.append(tid)
                sources[str(tid)] = []
            if bname not in sources[str(tid)]:
                sources[str(tid)].append(bname)
    candidates = snapshot_smart(daily_ids)

    # ---- 缓存榜（双周）：年龄驱动刷新
    if boards_cached:
        cached_data, use_cache = None, False
        if WEEK_CACHE.exists():
            try:
                cached_data = json.loads(WEEK_CACHE.read_text(encoding="utf-8"))
                use_cache = (time.time() - cached_data.get("fetchedTs", 0)) < max_age
            except Exception:
                use_cache = False
        if not use_cache:
            cached_data = {"fetchedTs": time.time(), "rows": [], "sources": {}}
            cached_ids, cached_src = [], {}
            for b in boards_cached:
                bname = board_names.get(str(b), str(b))
                for x in penetrate(b):
                    tid = x["tmId"]
                    if tid not in cached_src:
                        cached_ids.append(tid)
                        cached_src[str(tid)] = []
                    if bname not in cached_src[str(tid)]:
                        cached_src[str(tid)].append(bname)
            for tid, row in snapshot_smart(cached_ids).items():
                cached_data["rows"].append(row)
            cached_data["sources"] = cached_src
            WEEK_CACHE.write_text(json.dumps(cached_data, ensure_ascii=False),
                                  encoding="utf-8")
        for row in cached_data.get("rows", []):
            tid = row.get("tmId")
            if tid is None:
                continue
            if tid not in candidates:
                candidates[tid] = row
            for nm in cached_data.get("sources", {}).get(str(tid), []):
                sources.setdefault(str(tid), [])
                if nm not in sources[str(tid)]:
                    sources[str(tid)].append(nm)

    bal1 = balance()
    cand_list = list(candidates.values())
    as_of = "unknown"
    for src in (pools, cand_list):
        if src and src[0].get("asOfDate"):
            as_of = src[0]["asOfDate"]
            break

    out = {"asOfDate": as_of, "discipline": CFG["disciplineVersion"],
           "heldIds": held, "watchIds": watch,
           "pools": pools, "candidates": cand_list, "sources": sources}
    (BASE / "data").mkdir(exist_ok=True)
    (BASE / "data" / ("%s.json" % as_of)).write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")

    meta = {"cost": round(bal0 - bal1, 3), "balance": round(bal1, 3),
            "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    (BASE / "meta.json").write_text(json.dumps(meta, ensure_ascii=False),
                                    encoding="utf-8")
    print("OK asOf=%s pools=%d cand=%d cost=%.3f bal=%.3f"
          % (as_of, len(pools), len(cand_list), meta["cost"], bal1))


if __name__ == "__main__":
    main()
