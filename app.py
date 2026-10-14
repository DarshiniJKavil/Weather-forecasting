"""Flask app: serves the UI and a JSON forecast API.

Forecast = live official forecast (real time)  +  ML correction learned from this
city's past forecast mistakes.  Models are trained once per city and cached; the live
data is re-fetched on every request so the page always shows current conditions.
"""
import time
from datetime import date, datetime

import requests
from flask import Flask, jsonify, render_template, request

from data_sources import (fetch_history, fetch_live, fetch_nwp_history, geocode,
                          synthetic_history)
from ml_model import MOSCorrector, WeatherForecaster, describe, describe_code

app = Flask(__name__)
MODEL_TTL, LIVE_TTL = 6 * 3600, 120  # seconds
MODELS, LIVE = {}, {}


class ServiceDown(Exception):
    pass


def get_bundle(city: str, demo: bool):
    key = (city.lower(), demo)
    hit = MODELS.get(key)
    if hit and time.time() - hit[0] < MODEL_TTL:
        return hit[1]

    loc = geocode(city)
    if not loc:
        raise LookupError("Couldn't find that place in India. Try another city name.")

    nwp = None
    if demo:
        actual = synthetic_history(loc["lat"], loc["lon"])
    else:
        try:
            actual = fetch_history(loc["lat"], loc["lon"])
        except (requests.RequestException, ValueError, KeyError) as e:
            raise ServiceDown("Couldn't download weather history. Check your internet connection.") from e
        try:
            nwp = fetch_nwp_history(loc["lat"], loc["lon"])
        except (requests.RequestException, ValueError, KeyError):
            nwp = None

    pattern = WeatherForecaster()
    pattern_metrics = pattern.fit(actual)

    mos = None
    if nwp is not None:
        joined = actual.join(nwp, how="inner")
        if len(joined) >= 150:
            mos = MOSCorrector()
            mos.fit(joined)

    bundle = {
        "loc": loc,
        "actual": actual,
        "pattern": pattern,
        "mos": mos,
        "demo": demo,
        "metrics": {**pattern_metrics, **(mos.metrics if mos else {})},
        "importance": mos.importance if mos else pattern.importance,
    }
    MODELS[key] = (time.time(), bundle)
    return bundle


def get_live(loc):
    key = (round(loc["lat"], 3), round(loc["lon"], 3))
    hit = LIVE.get(key)
    if hit and time.time() - hit[0] < LIVE_TTL:
        return hit[1]
    try:
        live = fetch_live(loc["lat"], loc["lon"])
    except (requests.RequestException, ValueError, KeyError) as e:
        raise ServiceDown("Couldn't reach the live weather service. Check your internet connection.") from e
    LIVE[key] = (time.time(), live)
    return live


def build_result(b, live):
    actual, pattern, mos = b["actual"], b["pattern"], b["mos"]
    today = date.fromisoformat(live["local_date"]) if live else date.today()
    gap = max((today - actual.index[-1].date()).days, 0)
    pat = {d["date"]: d for d in pattern.forecast(actual, steps=gap + 10)}

    days = []
    if live:
        for h, ds in enumerate(sorted(live["daily"])[:10]):
            n, p = live["daily"][ds], pat.get(ds)
            if mos:
                d = mos.predict_day(n["tmax"], n["tmin"], n["precip"], n["rain_prob"], date.fromisoformat(ds), h)
            else:  # history download worked but past-forecast data did not: blend instead
                w = 0.3 if p else 0.0
                hi = (1 - w) * n["tmax"] + w * (p["tmax"] if p else 0)
                lo = (1 - w) * n["tmin"] + w * (p["tmin"] if p else 0)
                pp = n["rain_prob"] if n["rain_prob"] is not None else 30
                pp = (1 - w) * pp + w * (p["rain_prob"] if p else 0)
                d = {"tmax": round(hi, 1), "tmin": round(lo, 1), "rain_mm": round(n["precip"], 1),
                     "rain_prob": round(pp), "band": round(b["pattern"].sigma * (1 + 0.15 * h), 1)}
            if h == 0:  # never forecast a high/low that today's readings already beat
                if live["obs_max"] is not None:
                    d["tmax"] = round(max(d["tmax"], live["obs_max"]), 1)
                if live["obs_min"] is not None:
                    d["tmin"] = round(min(d["tmin"], live["obs_min"]), 1)
            d["date"] = ds
            d["official"] = {"tmax": round(n["tmax"], 1), "tmin": round(n["tmin"], 1),
                             "rain_prob": n["rain_prob"]}
            if p:
                d["pattern"] = {"tmax": p["tmax"], "tmin": p["tmin"], "rain_prob": p["rain_prob"]}
            days.append(d)
    else:
        for ds in sorted(k for k in pat if k >= today.isoformat())[:10]:
            days.append(dict(pat[ds]))

    for d in days:
        d["label"], d["icon"], d["theme"] = describe(d["tmax"], d["rain_prob"])

    cur = None
    if live:
        c = live["current"]
        label, icon, theme = describe_code(c["code"], c["is_day"])
        cur = {**c, "label": label, "icon": icon, "theme": theme}

    return {
        "location": b["loc"],
        "mode": "demo" if b["demo"] else ("mos" if mos else "blend"),
        "live": cur,
        "hourly": live["hourly"] if live else [],
        "local_time": live["time"] if live else None,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "history": [
            {"date": i.date().isoformat(), "tmax": round(r.tmax, 1), "tmin": round(r.tmin, 1),
             "rain_mm": round(r.precip, 1)}
            for i, r in actual.tail(21).iterrows()
        ],
        "forecast": days,
        "metrics": b["metrics"],
        "importance": b["importance"],
        "data_points": int(len(actual)),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/forecast")
def api_forecast():
    city = (request.args.get("city") or "").strip()
    demo = request.args.get("demo") == "1"
    if not city:
        return jsonify(error="Please enter a city."), 400
    try:
        bundle = get_bundle(city, demo)
        live = None if demo else get_live(bundle["loc"])
        return jsonify(build_result(bundle, live))
    except LookupError as e:
        return jsonify(error=str(e)), 404
    except ServiceDown as e:
        return jsonify(error=str(e), can_demo=True), 503


if __name__ == "__main__":
    app.run(debug=True, port=5000)
