# 趋势看板

每日自动更新趋势动物数据，生成 H5 看板并部署到 GitHub Pages。

## 运行机制

- **定时触发**: 每日北京时间 20:00（UTC 12:00）
- **手动触发**: GitHub Actions → Update Trend Dashboard → Run workflow
- **部署地址**: GitHub Pages（首次运行后生成）

## 流水线

1. `fetch_dashboard_data.py` — 调用趋势动物 API 取数（持有池快照 + 榜单穿透 + 两段式筛选）
2. `build_dashboard.py` — 生成 H5 看板（dist/index.html）
3. 部署到 GitHub Pages

## 配置

- `dashboard/config.json` — 持有池、榜单、筛选条件（apiKey 留空，由 Secret 注入）
- GitHub Secret `TREND_API_KEY` — 趋势动物 API Key

## 本地运行

```bash
export TREND_API_KEY="sk-xxxx"
python dashboard/fetch_dashboard_data.py
python dashboard/build_dashboard.py
open dashboard/dist/index.html
```

## 免责

趋势动物数据仅供参考，不构成投资建议。
