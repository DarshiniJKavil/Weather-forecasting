"""Machine-learning forecaster.

Predicts tomorrow's max temp, min temp and rainfall from the last 7 days of weather
plus the time of year, then rolls forward day by day for a multi-day forecast.
"""
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

LAGS = 7
RAIN_MM = 1.0  # a day counts as "rainy" at or above this much precipitation


def feature_row(tmax, tmin, pr, d):
    """Features for predicting day `d` from the previous LAGS days (oldest -> newest)."""
    tmax, tmin, pr = (np.asarray(a[-LAGS:], dtype=float) for a in (tmax, tmin, pr))
    ang = 2 * np.pi * d.timetuple().tm_yday / 365.25
    return np.concatenate(
        [
            tmax[::-1],
            tmin[::-1],
            pr[::-1],
            [tmax[-3:].mean(), tmax.mean(), tmin.mean(), pr.sum(), np.sin(ang), np.cos(ang)],
        ]
    )


def importance_groups(imp):
    """Collapse 27 feature importances into 4 human-readable groups (sums to 1)."""
    imp = np.asarray(imp)
    last_day = imp[[0, LAGS, 2 * LAGS]].sum()
    older = imp[: 3 * LAGS].sum() - last_day
    rolling = imp[3 * LAGS : 3 * LAGS + 4].sum()
    season = imp[3 * LAGS + 4 :].sum()
    return {
        "Yesterday's weather": float(last_day),
        "Earlier in the week": float(older),
        "Weekly averages": float(rolling),
        "Time of year": float(season),
    }


class WeatherForecaster:
    def __init__(self, n_estimators=150, seed=42):
        kw = dict(n_estimators=n_estimators, min_samples_leaf=3, n_jobs=-1, random_state=seed)
        self.temp_model = RandomForestRegressor(**kw)
        self.rain_amount_model = RandomForestRegressor(**kw)
        self.rain_clf = RandomForestClassifier(class_weight="balanced", **kw)
        self._const_rain = None
        self.sigma = 1.5
        self.metrics = {}
        self.importance = {}

    @staticmethod
    def _dataset(df):
        tmax, tmin, pr = df["tmax"].values, df["tmin"].values, df["precip"].values
        dates = list(df.index)
        X, y = [], []
        for i in range(LAGS, len(df)):
            sl = slice(i - LAGS, i)
            X.append(feature_row(tmax[sl], tmin[sl], pr[sl], dates[i]))
            y.append([tmax[i], tmin[i], pr[i]])
        return np.array(X), np.array(y)

    def _fit_models(self, X, y):
        self.temp_model.fit(X, y[:, :2])
        self.rain_amount_model.fit(X, y[:, 2])
        wet = (y[:, 2] >= RAIN_MM).astype(int)
        if wet.min() == wet.max():
            self._const_rain = float(wet[0])
        else:
            self._const_rain = None
            self.rain_clf.fit(X, wet)

    def _rain_prob(self, X):
        if self._const_rain is not None:
            return np.full(len(X), self._const_rain)
        p = self.rain_clf.predict_proba(X)
        return p[:, list(self.rain_clf.classes_).index(1)]

    def fit(self, df: pd.DataFrame, holdout: int = 60):
        """Train, scoring on the most recent `holdout` days, then refit on everything."""
        X, y = self._dataset(df)
        Xtr, ytr, Xte, yte = X[:-holdout], y[:-holdout], X[-holdout:], y[-holdout:]
        self._fit_models(Xtr, ytr)

        tp = self.temp_model.predict(Xte)
        err_max, err_min = tp[:, 0] - yte[:, 0], tp[:, 1] - yte[:, 1]
        persist = np.abs(Xte[:, 0] - yte[:, 0]).mean()  # "tomorrow = today" baseline
        wet_true = yte[:, 2] >= RAIN_MM
        wet_pred = self._rain_prob(Xte) >= 0.5
        self.sigma = float(max(np.std(err_max), 0.5))
        self.metrics = {
            "mae_tmax": round(float(np.abs(err_max).mean()), 2),
            "mae_tmin": round(float(np.abs(err_min).mean()), 2),
            "baseline_mae_tmax": round(float(persist), 2),
            "rain_accuracy": round(float((wet_true == wet_pred).mean() * 100), 1),
            "train_days": int(len(Xtr)),
            "test_days": int(holdout),
        }

        self._fit_models(X, y)  # final model uses all the data
        self.importance = importance_groups(self.temp_model.feature_importances_)
        return self.metrics

    def forecast(self, df: pd.DataFrame, steps: int):
        tmax, tmin, pr = list(df["tmax"]), list(df["tmin"]), list(df["precip"])
        day = df.index[-1]
        out = []
        for h in range(1, steps + 1):
            day = day + timedelta(days=1)
            x = feature_row(tmax, tmin, pr, day).reshape(1, -1)
            hi, lo = self.temp_model.predict(x)[0]
            lo = min(lo, hi - 1.0)
            amount = max(float(self.rain_amount_model.predict(x)[0]), 0.0)
            prob = float(self._rain_prob(x)[0])
            tmax.append(hi), tmin.append(lo), pr.append(amount)
            band = self.sigma * (h ** 0.4)  # uncertainty widens with lead time
            out.append(
                {
                    "date": day.date().isoformat(),
                    "tmax": round(float(hi), 1),
                    "tmin": round(float(lo), 1),
                    "rain_mm": round(amount, 1),
                    "rain_prob": round(prob * 100),
                    "band": round(float(band), 1),
                }
            )
        return out


def mos_importance(imp):
    imp = np.asarray(imp)
    return {
        "Official forecast": float(imp[:3].sum()),
        "Time of year": float(imp[3:5].sum()),
        "Recent forecast errors": float(imp[5:7].sum()),
    }


class MOSCorrector:
    """Learns how the official weather model is usually wrong at THIS location and fixes it.

    Inputs: the official forecast for the target day, time of year, and how wrong the
    official model has been over the last 7 days. Output: corrected high/low and rain.
    """

    def __init__(self, seed=42):
        kw = dict(n_estimators=120, min_samples_leaf=5, n_jobs=-1, random_state=seed)
        self.res_model = RandomForestRegressor(**kw)
        self.amount = RandomForestRegressor(**kw)
        self.clf = RandomForestClassifier(class_weight="balanced", **kw)
        self._const = None
        self.sigma = 1.2
        self.b_max = self.b_min = 0.0
        self.metrics, self.importance = {}, {}

    @staticmethod
    def _row(n_max, n_min, n_pr, d, b_max, b_min):
        ang = 2 * np.pi * d.timetuple().tm_yday / 365.25
        return np.array([n_max, n_min, n_pr, np.sin(ang), np.cos(ang), b_max, b_min])

    @staticmethod
    def _dataset(df):
        n_max, n_min, n_pr = df["nwp_tmax"].values, df["nwp_tmin"].values, df["nwp_precip"].values
        e_max, e_min = df["tmax"].values - n_max, df["tmin"].values - n_min
        dates, X, y = list(df.index), [], []
        for i in range(7, len(df)):
            X.append(MOSCorrector._row(n_max[i], n_min[i], n_pr[i], dates[i],
                                       e_max[i - 7:i].mean(), e_min[i - 7:i].mean()))
            y.append([e_max[i], e_min[i], df["precip"].values[i]])
        return np.array(X), np.array(y)

    def _fit_models(self, X, y):
        self.res_model.fit(X, y[:, :2])
        self.amount.fit(X, y[:, 2])
        wet = (y[:, 2] >= RAIN_MM).astype(int)
        if wet.min() == wet.max():
            self._const = float(wet[0])
        else:
            self._const = None
            self.clf.fit(X, wet)

    def _prob(self, X):
        if self._const is not None:
            return np.full(len(X), self._const)
        return self.clf.predict_proba(X)[:, list(self.clf.classes_).index(1)]

    def fit(self, df, holdout=60):
        X, y = self._dataset(df)
        self._fit_models(X[:-holdout], y[:-holdout])
        Xte, yte = X[-holdout:], y[-holdout:]
        pred = self.res_model.predict(Xte)
        err = yte[:, :2] - pred  # remaining error after correction
        wet = yte[:, 2] >= RAIN_MM
        self.sigma = float(max(np.std(err[:, 0]), 0.4))
        self.metrics = {
            "raw_mae_tmax": round(float(np.abs(yte[:, 0]).mean()), 2),  # official model alone
            "mos_mae_tmax": round(float(np.abs(err[:, 0]).mean()), 2),
            "raw_mae_tmin": round(float(np.abs(yte[:, 1]).mean()), 2),
            "mos_mae_tmin": round(float(np.abs(err[:, 1]).mean()), 2),
            "raw_rain_acc": round(float(((Xte[:, 2] >= RAIN_MM) == wet).mean() * 100), 1),
            "mos_rain_acc": round(float(((self._prob(Xte) >= 0.5) == wet).mean() * 100), 1),
        }
        self._fit_models(X, y)
        e_max, e_min = df["tmax"].values - df["nwp_tmax"].values, df["tmin"].values - df["nwp_tmin"].values
        self.b_max, self.b_min = float(e_max[-7:].mean()), float(e_min[-7:].mean())
        self.importance = mos_importance(self.res_model.feature_importances_)
        return self.metrics

    def predict_day(self, n_max, n_min, n_pr, n_prob, d, lead):
        x = self._row(n_max, n_min, n_pr, d, self.b_max, self.b_min).reshape(1, -1)
        r = self.res_model.predict(x)[0]
        hi, lo = n_max + r[0], n_min + r[1]
        lo = min(lo, hi - 1.0)
        prob = float(self._prob(x)[0])
        if n_prob is not None:
            prob = 0.5 * prob + 0.5 * n_prob / 100.0
        mm = 0.5 * max(float(self.amount.predict(x)[0]), 0.0) + 0.5 * n_pr
        return {
            "tmax": round(float(hi), 1),
            "tmin": round(float(lo), 1),
            "rain_mm": round(float(mm), 1),
            "rain_prob": round(prob * 100),
            "band": round(self.sigma * (1 + 0.15 * lead), 1),
        }


# WMO weather codes -> (label, emoji, night emoji, theme)
def describe_code(code, is_day=1):
    c = int(code or 0)
    if c == 0:
        return ("Clear sky", "☀️" if is_day else "🌙", "sunny" if is_day else "night")
    if c == 1:
        return ("Mostly clear", "🌤️" if is_day else "🌙", "sunny" if is_day else "night")
    if c == 2:
        return ("Partly cloudy", "⛅" if is_day else "☁️", "cloudy" if is_day else "night")
    if c == 3:
        return ("Overcast", "☁️", "cloudy")
    if c in (45, 48):
        return ("Foggy", "🌫️", "cloudy")
    if 51 <= c <= 57:
        return ("Drizzle", "🌦️", "rainy")
    if 61 <= c <= 67 or 80 <= c <= 82:
        return ("Rain", "🌧️", "rainy")
    if 71 <= c <= 77 or c in (85, 86):
        return ("Snow", "❄️", "cold")
    if c >= 95:
        return ("Thunderstorm", "⛈️", "rainy")
    return ("Cloudy", "☁️", "cloudy")


def describe(tmax, rain_prob):
    """Turn numbers into a label, emoji and theme used by the UI."""
    if rain_prob >= 65:
        return "Rainy", "🌧️", "rainy"
    if rain_prob >= 40:
        return "Showers likely", "🌦️", "rainy"
    if tmax >= 36:
        return "Very hot", "🔥", "hot"
    if rain_prob >= 22:
        return "Partly cloudy", "⛅", "cloudy"
    if tmax <= 8:
        return "Cold", "❄️", "cold"
    return "Sunny", "☀️", "sunny"
