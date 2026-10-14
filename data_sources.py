"""Data access: geocoding, historical weather, reference forecast, and an offline fallback."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# India only. Used if the geocoding service cannot be reached.
BUILTIN_CITIES = {
    "bengaluru": (12.9716, 77.5946, "Bengaluru", "India"),
    "mumbai": (19.076, 72.8777, "Mumbai", "India"),
    "delhi": (28.6139, 77.209, "Delhi", "India"),
    "chennai": (13.0827, 80.2707, "Chennai", "India"),
    "hyderabad": (17.385, 78.4867, "Hyderabad", "India"),
    "kolkata": (22.5726, 88.3639, "Kolkata", "India"),
    "pune": (18.5204, 73.8567, "Pune", "India"),
    "ahmedabad": (23.0225, 72.5714, "Ahmedabad", "India"),
    "jaipur": (26.9124, 75.7873, "Jaipur", "India"),
    "lucknow": (26.8467, 80.9462, "Lucknow", "India"),
    "kochi": (9.9312, 76.2673, "Kochi", "India"),
    "thiruvananthapuram": (8.5241, 76.9366, "Thiruvananthapuram", "India"),
    "mysuru": (12.2958, 76.6394, "Mysuru", "India"),
    "coimbatore": (11.0168, 76.9558, "Coimbatore", "India"),
    "visakhapatnam": (17.6868, 83.2185, "Visakhapatnam", "India"),
    "bhubaneswar": (20.2961, 85.8245, "Bhubaneswar", "India"),
    "patna": (25.5941, 85.1376, "Patna", "India"),
    "bhopal": (23.2599, 77.4126, "Bhopal", "India"),
    "nagpur": (21.1458, 79.0882, "Nagpur", "India"),
    "chandigarh": (30.7333, 76.7794, "Chandigarh", "India"),
    "guwahati": (26.1445, 91.7362, "Guwahati", "India"),
    "goa": (15.4909, 73.8278, "Goa", "India"),
    "shimla": (31.1048, 77.1734, "Shimla", "India"),
    "srinagar": (34.0837, 74.7973, "Srinagar", "India"),
    "varanasi": (25.3176, 82.9739, "Varanasi", "India"),
    "surat": (21.1702, 72.8311, "Surat", "India"),
    "indore": (22.7196, 75.8577, "Indore", "India"),
    "mangaluru": (12.9141, 74.856, "Mangaluru", "India"),
    "dehradun": (30.3165, 78.0322, "Dehradun", "India"),
    "ranchi": (23.3441, 85.3096, "Ranchi", "India"),
}
INDIAN_CITY_NAMES = [c[0] for c in [('Bengaluru', 12.9716, 77.5946), ('Mumbai', 19.076, 72.8777), ('Delhi', 28.6139, 77.209), ('Chennai', 13.0827, 80.2707), ('Hyderabad', 17.385, 78.4867), ('Kolkata', 22.5726, 88.3639), ('Pune', 18.5204, 73.8567), ('Ahmedabad', 23.0225, 72.5714), ('Jaipur', 26.9124, 75.7873), ('Lucknow', 26.8467, 80.9462), ('Kochi', 9.9312, 76.2673), ('Thiruvananthapuram', 8.5241, 76.9366), ('Mysuru', 12.2958, 76.6394), ('Coimbatore', 11.0168, 76.9558), ('Visakhapatnam', 17.6868, 83.2185), ('Bhubaneswar', 20.2961, 85.8245), ('Patna', 25.5941, 85.1376), ('Bhopal', 23.2599, 77.4126), ('Nagpur', 21.1458, 79.0882), ('Chandigarh', 30.7333, 76.7794), ('Guwahati', 26.1445, 91.7362), ('Goa', 15.4909, 73.8278), ('Shimla', 31.1048, 77.1734), ('Srinagar', 34.0837, 74.7973), ('Varanasi', 25.3176, 82.9739), ('Surat', 21.1702, 72.8311), ('Indore', 22.7196, 75.8577), ('Mangaluru', 12.9141, 74.856), ('Dehradun', 30.3165, 78.0322), ('Ranchi', 23.3441, 85.3096)]]


def geocode(city: str):
    """Return dict(name, country, lat, lon) for a place in India, or None."""
    try:
        r = requests.get(GEO_URL, params={"name": city, "count": 1, "countryCode": "IN"}, timeout=8)
        r.raise_for_status()
        results = r.json().get("results")
        if results:
            x = results[0]
            return {
                "name": x["name"],
                "country": x.get("country", ""),
                "lat": x["latitude"],
                "lon": x["longitude"],
            }
    except (requests.RequestException, ValueError, KeyError):
        pass
    b = BUILTIN_CITIES.get(city.strip().lower())
    if b:
        return {"lat": b[0], "lon": b[1], "name": b[2], "country": b[3]}
    return None


def fetch_history(lat: float, lon: float, days: int = 900) -> pd.DataFrame:
    """Daily tmax / tmin / precipitation from Open-Meteo's archive (raises on failure)."""
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    r = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
        },
        timeout=20,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    df = pd.DataFrame(
        {
            "tmax": d["temperature_2m_max"],
            "tmin": d["temperature_2m_min"],
            "precip": d["precipitation_sum"],
        },
        index=pd.to_datetime(d["time"]),
    )
    df = df.dropna()
    if len(df) < 200:
        raise ValueError("Not enough historical data for this location")
    return df


def fetch_reference(lat: float, lon: float):
    """Current conditions plus Open-Meteo's own numerical forecast, used as a comparison line."""
    try:
        r = requests.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": 10,
                "timezone": "auto",
            },
            timeout=10,
        )
        r.raise_for_status()
        j = r.json()
        daily = j["daily"]
        return {
            "current": {
                "temp": j["current"]["temperature_2m"],
                "humidity": j["current"]["relative_humidity_2m"],
                "wind": j["current"]["wind_speed_10m"],
            },
            "daily": {
                t: {"tmax": mx, "tmin": mn, "rain_prob": pp}
                for t, mx, mn, pp in zip(
                    daily["time"],
                    daily["temperature_2m_max"],
                    daily["temperature_2m_min"],
                    daily["precipitation_probability_max"],
                )
            },
        }
    except (requests.RequestException, ValueError, KeyError):
        return None


HIST_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"


def fetch_nwp_history(lat: float, lon: float, days: int = 730) -> pd.DataFrame:
    """What the official weather model *predicted* for past days (to learn its mistakes)."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)
    r = requests.get(
        HIST_FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
        },
        timeout=25,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    df = pd.DataFrame(
        {
            "nwp_tmax": d["temperature_2m_max"],
            "nwp_tmin": d["temperature_2m_min"],
            "nwp_precip": d["precipitation_sum"],
        },
        index=pd.to_datetime(d["time"]),
    ).dropna()
    return df


def fetch_live(lat: float, lon: float) -> dict:
    """Real-time conditions + the live 10-day official forecast (raises on failure)."""
    r = requests.get(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,is_day",
            "hourly": "temperature_2m,precipitation_probability",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
            "forecast_days": 10,
            "timezone": "auto",
        },
        timeout=12,
    )
    r.raise_for_status()
    j = r.json()
    cur = j["current"]
    now = cur["time"]  # local time at the place, e.g. "2026-10-12T10:15"
    local_date = now[:10]
    hours = [
        (t, tm, pp)
        for t, tm, pp in zip(
            j["hourly"]["time"], j["hourly"]["temperature_2m"], j["hourly"]["precipitation_probability"]
        )
        if tm is not None
    ]
    so_far = [tm for t, tm, _ in hours if t[:10] == local_date and t <= now]
    start_hour = now[:13] + ":00"
    daily = {}
    dd = j["daily"]
    for t, mx, mn, pr, pp in zip(
        dd["time"],
        dd["temperature_2m_max"],
        dd["temperature_2m_min"],
        dd["precipitation_sum"],
        dd["precipitation_probability_max"],
    ):
        if mx is None or mn is None:
            continue
        daily[t] = {"tmax": mx, "tmin": mn, "precip": pr or 0.0, "rain_prob": pp}
    if not daily:
        raise ValueError("Live forecast came back empty")
    return {
        "time": now,
        "local_date": local_date,
        "current": {
            "temp": cur["temperature_2m"],
            "feels": cur.get("apparent_temperature"),
            "humidity": cur["relative_humidity_2m"],
            "wind": cur["wind_speed_10m"],
            "code": cur.get("weather_code", 0),
            "is_day": cur.get("is_day", 1),
        },
        "hourly": [{"time": t, "temp": tm, "rain_prob": pp} for t, tm, pp in hours if t >= start_hour][:24],
        "obs_max": max(so_far) if so_far else None,
        "obs_min": min(so_far) if so_far else None,
        "daily": daily,
    }


def synthetic_history(lat: float, lon: float, days: int = 900) -> pd.DataFrame:
    """Offline demo data: a plausible seasonal climate for the given latitude."""
    rng = np.random.default_rng(int(abs(lat) * 1000 + abs(lon) * 10))
    end = pd.Timestamp(date.today() - timedelta(days=1))
    idx = pd.date_range(end=end, periods=days, freq="D")
    doy = idx.dayofyear.values
    hemi = 1 if lat >= 0 else -1
    mean_t = 31 - 0.38 * abs(lat)
    amp = 0.22 * abs(lat) + 1.5
    seasonal = mean_t + hemi * -amp * np.cos(2 * np.pi * (doy - 15) / 365.25)
    noise = np.zeros(days)
    for i in range(1, days):
        noise[i] = 0.7 * noise[i - 1] + rng.normal(0, 1.6)
    tmax = seasonal + noise
    tmin = tmax - (7 + rng.normal(0, 1.2, days))
    wet_season = 0.25 + 0.2 * np.sin(2 * np.pi * (doy - 150) / 365.25)
    rain_days = rng.random(days) < np.clip(wet_season, 0.05, 0.6)
    precip = np.where(rain_days, rng.gamma(1.4, 5.0, days), 0.0)
    tmax = tmax - np.where(rain_days, 2.5, 0)  # rainy days run cooler
    return pd.DataFrame({"tmax": tmax, "tmin": tmin, "precip": precip}, index=idx)
