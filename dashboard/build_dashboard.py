#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
趋势看板生成器 v2.0（纪律 v2.0 · 骄阳定制）
三区结构：我的持有 / 机会监测 / 每日推荐（温转热榜单九条件筛选）
仓位建议规则：危险信号→清仓；温转平→清仓；温转热·热→全仓；温转热·沸→半仓（止盈）
"""
import json, pathlib, datetime, sys

BASE = pathlib.Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
DIST_DIR = BASE / "dist"
DIST_DIR.mkdir(exist_ok=True)
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
F = CFG["filters"]

TEMP_COLOR = {"沸": "#ff2e4d", "热": "#ff7a45", "温": "#ffa940", "平": "#8a8f98",
              "凉": "#40a9ff", "寒": "#2f81f7", "冻": "#a371f7"}
POS_META = {"清仓": ("#ff4d4f", "pos-clear"), "全仓": ("#3fb950", "pos-full"),
            "半仓（止盈）": ("#d29922", "pos-half")}
BASE_SIGNAL = {"hold": ("继续持有", "#2f81f7"), "watch": ("观望", "#8a8f98"),
               "avoid": ("回避", "#6e7681")}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pct(v):
    if v is None:
        return '<span class="na">—</span>'
    p = v * 100
    cls = "up" if p > 0 else ("dn" if p < 0 else "fl")
    return '<span class="%s">%s%.2f%%</span>' % (cls, "+" if p > 0 else "", p)


def position_advice(r):
    """纪律：仓位建议。返回 (文案, 依据) 或 (None, None)。"""
    if r.get("stopwinFlagByDangerSignal"):
        return "清仓", "触发危险信号，按纪律立即清仓"
    prev, curr = r.get("trendTemperaturePrev"), r.get("trendTemperatureCurr")
    if prev == "温" and curr == "平":
        return "清仓", "温度由温转平，趋势动能消退，按纪律清仓"
    if prev == "温" and curr == "热":
        return "全仓", "温度由温转热（当前为热），触发全仓信号"
    if prev == "温" and curr == "沸":
        return "半仓（止盈）", "温度由温转沸，拥挤度过高，半仓止盈"
    return None, None


def base_signal(r):
    """无仓位触发时的基础信号（右侧/温度判定）。"""
    temp = r.get("trendTemperatureCurr") or ""
    if r.get("isTrendRightSide"):
        note = "右侧趋势中（节气%s）" % (r.get("trendPhaseCurr") or "—")
        note += "，温度偏热，勿追高" if temp == "热" else "，温度%s" % (temp or "—")
        return "hold", note
    s = r.get("trendStrengthLocalCurr")
    if s is not None and s >= 70 and temp in ("温", "平"):
        return "watch", "趋势左侧，但强度%.0f已临近右侧，密切关注转右信号（分析判断）" % s
    return "avoid", "趋势左侧（温度%s），不抄底、不补仓" % (temp or "—")


def candidate_check(r):
    """纪律v2.2 §三：九条件筛选（两段式后验证）。返回 (是否入选, 未满足原因列表)。
    注意：粗筛已过滤温度/强度/节气，此处验证剩余条件。"""
    fails = []
    name = r.get("tickerName", "")
    sym = r.get("tickerSymbol") or ""
    # 粗筛已保证 prev=温 curr=热 强度>95 节气∈phases，此处复核
    if not (r.get("trendTemperaturePrev") == "温" and r.get("trendTemperatureCurr") == "热"):
        fails.append("非温转热·热")
    if (r.get("trendStrengthLocalCurr") or 0) <= F["strengthMin"]:
        fails.append("强度%s≤95" % ("%.0f" % (r.get("trendStrengthLocalCurr") or 0)))
    if (r.get("trendPhaseCurr") or "") not in F["phases"]:
        fails.append("节气%s" % (r.get("trendPhaseCurr") or "缺失"))
    # 二段验证：行业温度/市值/成交额/价格
    if r.get("industryTrendTemperatureCurr") not in F["industryTempAllowed"]:
        v = r.get("industryTrendTemperatureCurr")
        fails.append("行业温度%s" % (v if v else "缺失"))
    mc = r.get("marketCap")
    if mc is None or mc <= F["marketCapMin"]:
        fails.append("市值%s" % ("缺失" if mc is None else "%.0f亿≤100" % mc))
    am = r.get("amount1d")
    if am is None or am <= F["amount1dMin"]:
        fails.append("日成交额%s" % ("缺失" if am is None else "%.1f亿≤2" % am))
    px = r.get("priceIndex")
    if px is None or px > F["priceMax"]:
        fails.append("股价%s" % ("缺失" if px is None else "%.1f>500" % px))
    if F["excludeST"] and "ST" in name.upper():
        fails.append("ST剔除")
    if F["excludeBJ"] and sym.endswith(".BJ"):
        fails.append("北交所剔除")
    return (len(fails) == 0), fails


def card(r, sig_label, sig_color, note, pos=None, pos_note=None, src=None):
    temp = r.get("trendTemperatureCurr") or ""
    prev = r.get("trendTemperaturePrev") or ""
    tc = TEMP_COLOR.get(temp, "#8a8f98")
    temp_html = ('<span class="temp" style="background:%s">%s</span>' % (tc, esc(temp))) if temp else ""
    trans_html = ""
    if prev and prev != temp:
        pc = TEMP_COLOR.get(prev, "#8a8f98")
        trans_html = '<span class="trans"><i style="background:%s">%s</i>→</span>' % (pc, esc(prev))
    phase = r.get("trendPhaseCurr") or ""
    phase_html = '<span class="phase">%s</span>' % esc(phase) if phase else ""
    days = r.get("daysSinceTrendEntry")
    days_html = ""
    if r.get("isTrendRightSide") and isinstance(days, (int, float)) and days > 0:
        days_html = '<span class="days">右侧%d天</span>' % days
    src_html = ""
    if src:
        src_html = "".join('<span class="src">%s</span>' % esc(s) for s in src)
    labels = r.get("tickerLabels") or ""
    labels_html = ""
    if labels:
        tags = [t for t in labels.split(";") if t.strip()]
        labels_html = "".join('<span class="tag">%s</span>' % esc(t) for t in tags)
    # 推荐卡片：方案C已砍 daysSinceTrendEntry/tickerLabels/stopwinFlagByBoilingTemperature
    # 仓位判定：危险信号→清仓；温转平→清仓；温转热·热→全仓；温转热·沸→半仓（温度字段已含沸）
    if r.get("stopwinFlagByDangerSignal"):
        labels_html += '<span class="tag danger">危险信号</span>'
    strength = r.get("trendStrengthLocalCurr")
    s_html = ""
    if strength is not None:
        s_html = ('<div class="sbar"><div class="sfill" style="width:%.0f%%"></div></div>'
                  '<div class="sval">强度 <b>%.1f</b></div>') % (min(strength, 100), strength)
    pos_html = ""
    if pos:
        c = POS_META.get(pos, ("#8a8f98", ""))[0]
        pos_html = '<span class="pos" style="background:%s">%s</span>' % (c, pos)
    price = r.get("priceIndex")
    price_html = ("%.3f" % price).rstrip("0").rstrip(".") if isinstance(price, (int, float)) else "—"
    sym = r.get("tickerSymbol") or ""
    return """
      <div class="card" style="border-left-color:%s">
        <div class="crow1"><span class="name">%s</span><span class="asset">%s %s</span></div>
        <div class="crow2"><span class="price">%s</span>
          <span class="rets">日 %s · 周 %s · 月 %s</span>%s</div>
        <div class="crow3">%s%s%s%s%s%s</div>
        %s
        <div class="crow4"><div class="sigtag" style="color:%s">仓位建议：%s</div><div class="note">%s</div></div>
      </div>""" % (sig_color, esc(r.get("tickerName", "?")), esc(r.get("asset", "")), esc(sym),
                    price_html, pct(r.get("return1d")), pct(r.get("return1w")), pct(r.get("return1m")),
                    pos_html, trans_html, temp_html, phase_html, days_html, labels_html, src_html,
                    s_html,
                    sig_color, esc(sig_label), esc(pos_note or note))


def section(title, color, cards_html, extra=""):
    if not cards_html:
        return ""
    return """
    <div class="ghead" style="color:%s">%s%s</div>
    %s""" % (color, title, extra, cards_html)


def main():
    files = sorted(f for f in DATA_DIR.glob("*.json") if not f.name.startswith("_"))
    if not files:
        sys.exit("no data files")
    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    as_of = payload.get("asOfDate", "—")
    held_ids = payload.get("heldIds", CFG["held"])
    watch_ids = CFG.get("watch", [])  # 监测池以config为准；v2.1已下线（不显示）
    pools = payload.get("pools", [])
    cands = payload.get("candidates", [])
    sources = payload.get("sources", {})

    meta = {}
    mf = BASE / "meta.json"
    if mf.exists():
        meta = json.loads(mf.read_text(encoding="utf-8"))
    generated_at = meta.get("generatedAt") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    cost = meta.get("cost", "—")
    balance = meta.get("balance", "—")

    held_rows = [r for r in pools if r.get("tmId") in held_ids]
    watch_rows = [r for r in pools if r.get("tmId") in watch_ids]

    # ---- 持有/监测池：仓位建议 + 基础信号
    clear_list, full_list, half_list = [], [], []
    def render_pool(rows):
        cards = []
        for r in sorted(rows, key=lambda x: -(x.get("trendStrengthLocalCurr") or -1)):
            pos, pnote = position_advice(r)
            if pos == "清仓":
                clear_list.append(r.get("tickerName"))
            elif pos == "全仓":
                full_list.append(r.get("tickerName"))
            elif pos == "半仓（止盈）":
                half_list.append(r.get("tickerName"))
            if pos:
                label, color = pos, POS_META[pos][0]
                cards.append(card(r, label, color, pnote, pos, pnote))
            else:
                sig, note = base_signal(r)
                label, color = BASE_SIGNAL[sig]
                cards.append(card(r, label, color, note))
        return "\n".join(cards)

    held_html = render_pool(held_rows)
    watch_html = render_pool(watch_rows)

    # ---- 推荐模块：九条件筛选
    picks, rejects = [], []
    for r in cands:
        ok, fails = candidate_check(r)
        (picks if ok else rejects).append((r, fails))
    pick_html = ""
    for r, _ in sorted(picks, key=lambda x: -(x[0].get("trendStrengthLocalCurr") or 0)):
        pos, pnote = position_advice(r)
        label = pos or "入选"
        color = POS_META.get(pos, ("#3fb950",))[0] if pos else "#3fb950"
        full_note = (pnote + "；九条件全满足") if pnote else "九条件全满足"
        pick_html += card(r, label, color, full_note, pos, full_note,
                          src=sources.get(str(r.get("tmId"))))
    reject_summary = ""
    if rejects:
        reject_summary = '<div class="rej">未入选 %d 只：%s</div>' % (
            len(rejects),
            "、".join('%s(%s)' % (esc(r.get("tickerName", "?")), esc(fails[0])) for r, fails in rejects[:8])
            + (" 等" if len(rejects) > 8 else ""))

    # ---- 今日建议操作
    parts = []
    if clear_list:
        parts.append('<div class="aline" style="color:#ff4d4f">🔴 清仓信号：%s —— 危险信号或温转平触发，按纪律执行。</div>' % "、".join(map(esc, clear_list)))
    if full_list:
        parts.append('<div class="aline" style="color:#3fb950">🟢 全仓信号：%s —— 温转热·热触发。</div>' % "、".join(map(esc, full_list)))
    if half_list:
        parts.append('<div class="aline" style="color:#d29922">🟡 半仓止盈：%s —— 温转热·沸触发。</div>' % "、".join(map(esc, half_list)))
    if picks:
        parts.append('<div class="aline" style="color:#3fb950">✨ 今日推荐关注 %d 只：%s（九条件全满足，详见推荐区）。</div>' % (len(picks), "、".join(esc(r.get("tickerName", "?")) for r, _ in picks)))
    if not parts:
        parts.append('<div class="aline">今日无清仓/全仓/推荐关注触发：持仓按现有仓位运行，左侧品种不抄底。</div>')
    advice_html = "\n".join(parts)

    n_right = sum(1 for r in held_rows if r.get("isTrendRightSide"))

    sections = (
        section("📌 我的持仓（%d）" % len(held_rows), "#e6edf3", held_html) +
        section("👁 机会监测（%d）" % len(watch_rows), "#e3b341", watch_html) +
        section("✨ 今日推荐关注（多榜单·九条件筛选，入选 %d/%d）" % (len(picks), len(cands)),
                "#3fb950", pick_html, "") +
        reject_summary
    )

    html_doc = TEMPLATE.replace("%%AS_OF%%", esc(as_of)) \
        .replace("%%GENERATED_AT%%", esc(generated_at)) \
        .replace("%%DISC%%", esc(CFG.get("disciplineVersion", "v2.1"))) \
        .replace("%%ADVICE%%", advice_html) \
        .replace("%%N_RIGHT%%", str(n_right)) \
        .replace("%%N_HELD%%", str(len(held_rows))) \
        .replace("%%N_PICKS%%", str(len(picks))) \
        .replace("%%N_CANDS%%", str(len(cands))) \
        .replace("%%SECTIONS%%", sections) \
        .replace("%%COST%%", esc(str(cost))) \
        .replace("%%BALANCE%%", esc(str(balance)))

    out = DIST_DIR / "index.html"
    out.write_text(html_doc, encoding="utf-8")
    print("built %s asOf=%s held=%d watch=%d cand=%d picks=%d"
          % (out, as_of, len(held_rows), len(watch_rows), len(cands), len(picks)))


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="format-detection" content="telephone=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="趋势看板">
<link rel="apple-touch-icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180' viewBox='0 0 180 180'><rect width='180' height='180' rx='32' fill='%230d1117'/><text x='90' y='118' text-anchor='middle' font-size='96'>📈</text></svg>">
<title>趋势看板 · %%AS_OF%%</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { background:#0d1117; color:#e6edf3; font-family:-apple-system,"PingFang SC","Helvetica Neue",sans-serif;
         font-size:15px; line-height:1.5; padding-bottom:40px; }
  .wrap { max-width:520px; margin:0 auto; padding:14px 14px 0; }
  header { padding:10px 2px 14px; }
  h1 { font-size:21px; font-weight:700; letter-spacing:1px; }
  .hsub { color:#8b949e; font-size:12.5px; margin-top:4px; }
  .advice { background:linear-gradient(135deg,#1c2333,#161b27); border:1px solid #2d333f;
            border-radius:14px; padding:16px 15px; margin-bottom:8px; }
  .atitle { font-size:13px; color:#8b949e; letter-spacing:2px; margin-bottom:10px; }
  .aline { font-size:15px; font-weight:600; line-height:1.6; margin-bottom:6px; }
  .stats { display:flex; gap:8px; margin:12px 0 4px; }
  .stat { flex:1; background:#161b22; border:1px solid #262b33; border-radius:10px;
          padding:9px 4px; text-align:center; }
  .stat b { display:block; font-size:17px; }
  .stat span { font-size:11px; color:#8b949e; }
  .ghead { font-size:14.5px; font-weight:700; margin:20px 2px 9px; letter-spacing:1px; }
  .card { background:#161b22; border:1px solid #262b33; border-left:3px solid #444;
          border-radius:12px; padding:12px 13px; margin-bottom:9px; }
  .crow1 { display:flex; justify-content:space-between; align-items:baseline; }
  .name { font-size:16px; font-weight:600; }
  .asset { font-size:11px; color:#8b949e; }
  .crow2 { margin-top:5px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .price { font-size:15px; font-weight:600; color:#c9d1d9; font-variant-numeric:tabular-nums; }
  .rets { font-size:12.5px; font-variant-numeric:tabular-nums; }
  .up { color:#f85149; } .dn { color:#3fb950; } .fl { color:#8b949e; } .na { color:#565d66; }
  .pos { color:#0d1117; font-size:12px; font-weight:700; border-radius:5px; padding:1px 8px; margin-left:auto; }
  .crow3 { margin-top:8px; display:flex; align-items:center; gap:5px; flex-wrap:wrap; }
  .temp { color:#0d1117; font-size:11.5px; font-weight:700; border-radius:5px; padding:1px 7px; }
  .trans i { font-style:normal; color:#0d1117; font-size:10.5px; border-radius:4px; padding:0 4px; opacity:.75; }
  .trans { font-size:11px; color:#8b949e; }
  .phase { font-size:11.5px; color:#c9a86a; border:1px solid #4d4028; border-radius:5px; padding:0 6px; }
  .days { font-size:11.5px; color:#58a6ff; border:1px solid #1f3a5f; border-radius:5px; padding:1px 6px; }
  .tag { font-size:12px; color:#d2a8ff; border:1px solid #3d2d52; border-radius:5px; padding:1px 6px; }
  .tag.danger { color:#ff7b72; border-color:#5a2d2a; font-weight:700; }
  .src { font-size:10.5px; color:#7ee787; border:1px solid #1f4630; border-radius:5px; padding:0 5px; }
  .sbar { height:7px; background:#262b33; border-radius:4px; margin-top:10px; overflow:hidden; }
  .sfill { height:100%; background:linear-gradient(90deg,#2f81f7,#a371f7); border-radius:4px; }
  .sval { font-size:16px; color:#8b949e; margin-top:4px; text-align:right; }
  .sval b { font-size:19px; color:#e6edf3; font-variant-numeric:tabular-nums; }
  .crow4 { margin-top:10px; padding-top:10px; border-top:1px dashed #2d333f; }
  .sigtag { font-size:17px; font-weight:700; display:block; letter-spacing:.5px; }
  .note { font-size:13.5px; color:#c9d1d9; display:block; margin-top:4px; line-height:1.55; }
  .rej { color:#6e7681; font-size:12px; margin:6px 2px 0; line-height:1.7; }
  footer { margin-top:26px; padding:14px 4px 0; border-top:1px solid #21262d;
           color:#6e7681; font-size:11.5px; line-height:1.8; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>📈 趋势看板</h1>
    <div class="hsub">数据日期 %%AS_OF%% · 生成于 %%GENERATED_AT%% · 纪律 %%DISC%%</div>
  </header>

  <section class="advice">
    <div class="atitle">今日建议操作</div>
    %%ADVICE%%
  </section>

  <div class="stats">
    <div class="stat"><b>%%N_RIGHT%%/%%N_HELD%%</b><span>持有池右侧</span></div>
    <div class="stat"><b>%%N_PICKS%%/%%N_CANDS%%</b><span>推荐入选</span></div>
    <div class="stat"><b>¥%%COST%%</b><span>本次取数费</span></div>
    <div class="stat"><b>¥%%BALANCE%%</b><span>账户余额</span></div>
  </div>

  %%SECTIONS%%

  <footer>
    数据源：趋势动物 API。行情与趋势指标为接口直接返回；仓位建议按纪律 %%DISC%%（骄阳定制）机械判定：危险信号/温转平→清仓，温转热·热→全仓，温转热·沸→半仓止盈；推荐模块为温转热榜单成分经九条件筛选（行业温度≥温），未入选原因已标注。<br>
    趋势动物指标仅供趋势交易研究与纪律执行参考，不构成投资建议或收益承诺。市场有风险，盈亏自负。
  </footer>
</div>
</body>
</html>
"""

if __name__ == "__main__":
    main()
