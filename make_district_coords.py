# -*- coding: utf-8 -*-
"""生成全国区县坐标表 static/geo/district-coords.json（定位显示精确到区/县用）。

数据源：阿里 DataV 免费地理接口（geo.datav.aliyun.com，公开数据，无需 Key）。
结构：[{name: 区县名, city: 所属市, lng, lat}, ...]，生成后纯离线查表。
"""

import json
import time
import urllib.request

BASE = "https://geo.datav.aliyun.com/areas_v3/bound"


def fetch(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    provinces = fetch(f"{BASE}/100000_full.json")
    rows = []
    for p in provinces["features"]:
        pprop = p.get("properties") or {}
        pad, pname = pprop.get("adcode"), pprop.get("name")
        if not pad:
            continue
        time.sleep(0.05)
        try:
            pdata = fetch(f"{BASE}/{pad}_full.json")
        except Exception as e:
            print("跳过省:", pname, e)
            continue
        for c in pdata["features"]:
            cprop = c.get("properties") or {}
            cad, cname, clevel = cprop.get("adcode"), cprop.get("name"), cprop.get("level")
            ccenter = cprop.get("center") or cprop.get("centroid")
            # 直辖市/省直辖县：这一层就是区县，直接收录
            if clevel == "district" and ccenter:
                rows.append({"name": cname, "city": pname, "province": pname,
                             "lng": ccenter[0], "lat": ccenter[1]})
                continue
            if not cad:
                continue
            time.sleep(0.05)
            try:
                cdata = fetch(f"{BASE}/{cad}_full.json")
            except Exception:
                continue
            for d in cdata["features"]:
                dprop = d.get("properties") or {}
                dcenter = dprop.get("center") or dprop.get("centroid")
                if dcenter:
                    rows.append({"name": dprop.get("name"), "city": cname,
                                 "province": pname,
                                 "lng": dcenter[0], "lat": dcenter[1]})
            time.sleep(0.05)
        print(f"{pname}: 累计 {len(rows)}")

    out = "static/geo/district-coords.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print("完成，共", len(rows), "个区县 →", out)


if __name__ == "__main__":
    main()
