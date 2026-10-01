#!/usr/bin/env python3
"""
Fetch Purdue dining court menus + nutrition and tag macro-friendly items.

Writes site/data.json, which web/index.html reads. Standard library only,
so the GitHub Action needs no pip installs.

Usage:  python build_data.py [--days 3] [--out site/data.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# YOUR TARGETS. Edit these numbers to retune the highlighting.
# "ideal" = meets your targets, "close" = near-miss worth showing.
# Ratios are calories per gram (lower = leaner). Sodium in mg, per serving.
# ---------------------------------------------------------------------------
RULES = {
    "protein": {
        "ideal": {"max_cal_per_g": 15, "min_g": 10},
        "close": {"max_cal_per_g": 20, "min_g": 7},
    },
    "carb": {
        "ideal": {"max_cal_per_g": 10, "min_g": 15, "max_sugar_pct": 20,
                  "max_sodium": 350, "max_fat_pct": 30},
        "close": {"max_cal_per_g": 12.5, "min_g": 10, "max_sugar_pct": 35,
                  "max_sodium": 550, "max_fat_pct": 40},
    },
    # A "lean main" is a protein item that is also a real portion and not salty.
    "lean_main": {
        "ideal": {"min_protein_g": 15, "max_sodium": 600},
        "close": {"min_protein_g": 12, "max_sodium": 800},
    },
}

API = "https://api.hfs.purdue.edu/menus/v2"
DEFAULT_COURTS = ["Earhart", "Ford", "Hillenbrand", "Wiley", "Windsor"]
TZ = ZoneInfo("America/Indiana/Indianapolis")
UA = "purdue-macro-dashboard (personal, once-daily)"


def get_json(url: str, tries: int = 4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == tries - 1:
                raise
        time.sleep(1.5 * (attempt + 1))


def dining_courts() -> list[str]:
    try:
        data = get_json(f"{API}/locations") or {}
        names = [l["Name"] for l in data.get("Location", []) if l.get("Type") == "Dining Courts"]
        return names or DEFAULT_COURTS
    except Exception as e:  # noqa: BLE001
        print(f"warn: location list failed ({e}); using defaults", file=sys.stderr)
        return DEFAULT_COURTS


# ---------------------------------------------------------------- nutrition
def _num(entry: dict) -> float | None:
    v = entry.get("Value")
    if isinstance(v, (int, float)):
        return float(v)
    label = str(entry.get("LabelValue") or v or "")
    if label.strip().startswith("<"):
        return 0.5
    m = re.search(r"\d+(?:\.\d+)?", label)
    return float(m.group()) if m else None


def parse_nutrition(raw: dict | None) -> dict | None:
    if not raw or not raw.get("Nutrition"):
        return None
    out: dict = {}
    for n in raw["Nutrition"]:
        name = str(n.get("Name", "")).strip().lower()
        if name.startswith("serving"):
            out["serving"] = n.get("LabelValue")
            continue
        val = _num(n)
        if val is None:
            continue
        if name == "calories":
            out["cal"] = val
        elif name.startswith("protein"):
            out["p"] = val
        elif "carbohydrate" in name:
            out["c"] = val
        elif name in ("total fat", "fat") or name.startswith("total fat"):
            out["f"] = val
        elif name.startswith("sodium"):
            out["na"] = val
        elif "sugar" in name and "added" not in name:
            out["sugar"] = val
        elif "fiber" in name:
            out["fiber"] = val
    return out if "cal" in out else None


# ----------------------------------------------------------- classification
def classify(n: dict) -> dict:
    """Return tiers + human-readable reasons for near-misses."""
    cal = n.get("cal") or 0
    p, c, f = n.get("p") or 0, n.get("c") or 0, n.get("f") or 0
    na, sugar = n.get("na") or 0, n.get("sugar") or 0
    res = {"protein": None, "carb": None, "lean": None, "why": []}
    if cal <= 0:
        return res

    cpp = cal / p if p > 0 else None
    cpc = cal / c if c > 0 else None
    sugar_pct = 100 * sugar / c if c > 0 else 100
    fat_pct = 100 * 9 * f / cal

    # Protein
    R = RULES["protein"]
    if cpp is not None:
        if cpp <= R["ideal"]["max_cal_per_g"] and p >= R["ideal"]["min_g"]:
            res["protein"] = "ideal"
        elif cpp <= R["close"]["max_cal_per_g"] and p >= R["close"]["min_g"]:
            res["protein"] = "close"
            if cpp > R["ideal"]["max_cal_per_g"]:
                res["why"].append(f"{cpp:.1f} cal per g protein (target ≤{R['ideal']['max_cal_per_g']})")
            if p < R["ideal"]["min_g"]:
                res["why"].append(f"only {p:g} g protein per serving")

    # Carb (only if it isn't really a protein item)
    R = RULES["carb"]
    if cpc is not None and res["protein"] is None:
        def ok(t):
            return (cpc <= t["max_cal_per_g"] and c >= t["min_g"] and sugar_pct <= t["max_sugar_pct"]
                    and na <= t["max_sodium"] and fat_pct <= t["max_fat_pct"])
        if ok(R["ideal"]):
            res["carb"] = "ideal"
        elif ok(R["close"]):
            res["carb"] = "close"
            i = R["ideal"]
            if cpc > i["max_cal_per_g"]:
                res["why"].append(f"{cpc:.1f} cal per g carb (target ≤{i['max_cal_per_g']})")
            if c < i["min_g"]:
                res["why"].append(f"only {c:g} g carbs per serving")
            if sugar_pct > i["max_sugar_pct"]:
                res["why"].append(f"{sugar:g} g sugar")
            if na > i["max_sodium"]:
                res["why"].append(f"{na:g} mg sodium (target ≤{i['max_sodium']})")
            if fat_pct > i["max_fat_pct"]:
                res["why"].append(f"{fat_pct:.0f}% of calories from fat")

    # Lean main
    R = RULES["lean_main"]
    if res["protein"] == "ideal" and p >= R["ideal"]["min_protein_g"] and na <= R["ideal"]["max_sodium"]:
        res["lean"] = "ideal"
    elif res["protein"] in ("ideal", "close") and p >= R["close"]["min_protein_g"] and na <= R["close"]["max_sodium"]:
        res["lean"] = "close"
        if na > R["ideal"]["max_sodium"]:
            res["why"].append(f"{na:g} mg sodium (lean-main target ≤{R['ideal']['max_sodium']})")

    res["why"] = list(dict.fromkeys(res["why"]))
    return res


# ------------------------------------------------------------------- build
def slim_item(it: dict) -> dict:
    allergens = [a["Name"] for a in it.get("Allergens") or [] if a.get("Value")]
    return {
        "id": it["ID"],
        "name": it["Name"].strip(),
        "veg": bool(it.get("IsVegetarian")) or "Vegetarian" in allergens,
        "vegan": "Vegan" in allergens,
        "allergens": [a for a in allergens if a not in ("Vegetarian", "Vegan")],
        "ready": bool(it.get("NutritionReady")),
    }


def build(days: int) -> dict:
    today = datetime.now(TZ).date()
    dates = [(today + timedelta(d)).isoformat() for d in range(days)]
    courts = dining_courts()
    print(f"courts: {courts}; dates: {dates}")

    menus: dict = {}
    jobs = [(d, c) for d in dates for c in courts]
    with ThreadPoolExecutor(6) as ex:
        results = ex.map(lambda dc: (dc, _safe_menu(*dc)), jobs)
        for (d, c), m in results:
            menus.setdefault(d, {})[c] = m

    # Unique items that have nutrition
    ids = {it["ID"] for d in menus.values() for m in d.values() if m
           for meal in m.get("Meals") or [] for st in meal.get("Stations") or []
           for it in st.get("Items") or [] if it.get("NutritionReady")}
    print(f"fetching nutrition for {len(ids)} items")
    with ThreadPoolExecutor(8) as ex:
        nut = dict(ex.map(lambda i: (i, _safe_item(i)), sorted(ids)))

    out_days = {}
    for d in dates:
        day_courts = {}
        for c in courts:
            m = menus[d].get(c)
            if not m or not m.get("IsPublished") or not m.get("Meals"):
                day_courts[c] = {"published": False, "meals": []}
                continue
            meals = []
            for meal in sorted(m["Meals"], key=lambda x: x.get("Order", 0)):
                stations = []
                for st in meal.get("Stations") or []:
                    items = []
                    for it in st.get("Items") or []:
                        row = slim_item(it)
                        n = nut.get(it["ID"])
                        if n:
                            row["n"] = n
                            row.update(classify(n))
                        items.append(row)
                    if items:
                        stations.append({"name": st["Name"], "items": items})
                hours = meal.get("Hours") or {}
                meals.append({
                    "name": meal["Name"], "order": meal.get("Order", 0),
                    "status": meal.get("Status"),
                    "start": hours.get("StartTime"), "end": hours.get("EndTime"),
                    "stations": stations,
                })
            day_courts[c] = {"published": True, "meals": meals}
        out_days[d] = day_courts

    return {
        "generated": datetime.now(TZ).isoformat(timespec="minutes"),
        "rules": RULES,
        "courts": courts,
        "dates": dates,
        "days": out_days,
    }


def _safe_menu(date: str, court: str):
    try:
        return get_json(f"{API}/locations/{urllib.parse.quote(court)}/{date}")
    except Exception as e:  # noqa: BLE001
        print(f"warn: menu {court} {date}: {e}", file=sys.stderr)
        return None


def _safe_item(item_id: str):
    try:
        return parse_nutrition(get_json(f"{API}/items/{item_id}"))
    except Exception as e:  # noqa: BLE001
        print(f"warn: item {item_id}: {e}", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--out", default="site/data.json")
    a = ap.parse_args()
    data = build(a.days)
    total = sum(1 for d in data["days"].values() for c in d.values() for m in c["meals"]
                for s in m["stations"] for _ in s["items"])
    if total == 0:
        sys.exit("No menu items found for any court. Purdue's API may have changed or be down.")
    import os
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"wrote {a.out} ({total} item rows)")


if __name__ == "__main__":
    main()
