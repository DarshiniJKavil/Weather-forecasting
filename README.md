# SkyCast ML: weather forecasting with Python + machine learning

An interactive web app that trains a machine-learning model on real historical weather
for any city in India, then forecasts the next 3-10 days.

## Run it

```bash
cd weather_project
python -m venv venv
venv\Scripts\activate          # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser. The first search for a city takes a few
seconds because the model trains live. Repeat searches are cached for 30 minutes.

## How it works

1. **Live data** (`data_sources.py`): current conditions, the next 24 hours and the 10-day official
   forecast from the free Open-Meteo API (no key needed). The page refreshes itself every 5 minutes.
2. **Learning the official model's mistakes**: the app downloads what the official model *predicted*
   for the past ~2 years plus what actually happened, and trains Random Forests (`MOSCorrector` in
   `ml_model.py`) to learn how wrong it tends to be in your city: too warm, too cool, too wet.
3. **Corrected forecast**: today's live official forecast, adjusted by that learned correction and by
   how wrong the official model was over the last 7 days.
4. **Honest scoring**: the last 60 days are held back, and the page shows the official model's error next
   to the corrected error.
5. **Pattern-only model**: a second Random Forest (`WeatherForecaster`) forecasts from the last 7 days of
   weather alone. It is shown as a comparison and used as a fallback blend.
6. **No fake data**: if the live service can't be reached you get an error, not made-up numbers. Offline
   demo data only appears if you click the button, and is clearly labelled.

## Project layout

```
weather_project/
├── app.py            Flask server + /api/forecast
├── data_sources.py   geocoding, history, reference forecast, offline fallback
├── ml_model.py       feature engineering + Random Forest forecaster
├── requirements.txt
├── templates/index.html
└── static/ style.css, app.js
```

## Ideas to extend

- Add humidity, pressure and wind as input features
- Try gradient boosting or an LSTM and compare MAE
- Add hourly forecasts or weather alerts
