"""
Ранковий health-брифінг: генерує AI-текст і статуси (сон/відновлення/готовність)
на основі сьогоднішніх Garmin-метрик, поточної погоди і вчорашньої вечірньої
рефлексії, і зберігає результат у сьогоднішній рядок Notion.

Запускається після sync.py (дані за сьогодні вже мають бути в Notion).

Потрібні secrets (env vars):
  NOTION_TOKEN, NOTION_DATABASE_ID, ANTHROPIC_API_KEY, OPENWEATHER_API_KEY
"""

import datetime
import json
import os
import re

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OPENWEATHER_API_KEY = os.environ["OPENWEATHER_API_KEY"]

KYIV_LAT = 50.4501
KYIV_LON = 30.5234
MODEL = "claude-sonnet-4-6"

# Персональний одноосібний проєкт — профіль просто хардкодиться, а не збирається
# від користувача (генерація тепер відбувається тут, а не в браузері).
USER_NAME = "Юрій"
USER_WORK_TYPE = "сидяча"
USER_AGE = 38
USER_GOAL = "здоров'я"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def num(props: dict, name: str):
    p = props.get(name)
    return p.get("number") if p else None


def text(props: dict, name: str):
    p = props.get(name)
    if not p:
        return None
    if p.get("rich_text"):
        return "".join(t["plain_text"] for t in p["rich_text"]) or None
    if p.get("title"):
        return "".join(t["plain_text"] for t in p["title"]) or None
    return None


def fetch_recent_rows(limit: int = 3) -> list[dict]:
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"sorts": [{"property": "Day", "direction": "descending"}], "page_size": limit}
    resp = requests.post(url, headers=NOTION_HEADERS, json=payload)
    resp.raise_for_status()
    pages = resp.json().get("results", [])

    rows = []
    for page in pages:
        props = page["properties"]
        rows.append({
            "page_id": page["id"],
            "date": props["Day"]["date"]["start"] if props.get("Day", {}).get("date") else None,
            "sleep_score": num(props, "Sleep score"),
            "sleep_hours": num(props, "Sleep hours"),
            "hrv_avg": num(props, "HRV avg"),
            "hrv_status": text(props, "HRV status"),
            "body_battery_high": num(props, "Body Battery high"),
            "body_battery_low": num(props, "Body Battery low"),
            "resting_hr": num(props, "Resting HR"),
            "deep_sleep_min": num(props, "Deep sleep min"),
            "rem_sleep_min": num(props, "REM sleep min"),
            "light_sleep_min": num(props, "Light sleep min"),
            "spo2_avg": num(props, "SpO2 avg"),
            "spo2_low": num(props, "SpO2 low"),
            "stress_avg": num(props, "Stress avg"),
            "activities": text(props, "Activities"),
            "evening_note": text(props, "Evening note"),
            "tomorrow_intention": text(props, "Tomorrow intention"),
        })
    return rows


def get_current_weather() -> dict:
    url = (
        "https://api.openweathermap.org/data/2.5/weather?lat=" + str(KYIV_LAT) +
        "&lon=" + str(KYIV_LON) + "&appid=" + OPENWEATHER_API_KEY + "&units=metric&lang=ua"
    )
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    return {
        "temp": data.get("main", {}).get("temp"),
        "feels_like": data.get("main", {}).get("feels_like"),
        "condition": (data.get("weather") or [{}])[0].get("description"),
        "humidity": data.get("main", {}).get("humidity"),
    }


def get_yesterday_evening_weather():
    # Історія доступна лише на платному One Call 3.0 — якщо ключ без підписки,
    # тихо пропускаємо і працюємо тільки з поточною погодою.
    yesterday = (
        datetime.datetime.now().replace(hour=22, minute=0, second=0, microsecond=0)
        - datetime.timedelta(days=1)
    )
    dt = int(yesterday.timestamp())
    url = (
        "https://api.openweathermap.org/data/3.0/onecall/timemachine?lat=" + str(KYIV_LAT) +
        "&lon=" + str(KYIV_LON) + "&dt=" + str(dt) + "&appid=" + OPENWEATHER_API_KEY +
        "&units=metric&lang=ua"
    )
    try:
        resp = requests.get(url)
        if not resp.ok:
            return None
        point = (resp.json().get("data") or [None])[0]
        if not point:
            return None
        return {
            "temp": point.get("temp"),
            "condition": (point.get("weather") or [{}])[0].get("description"),
        }
    except requests.RequestException:
        return None


def has_elevated_stress_streak(rows: list[dict]) -> bool:
    streak = 0
    for row in rows:
        if row.get("stress_avg") is not None and row["stress_avg"] >= 50:
            streak += 1
        else:
            break
    return streak >= 2


def build_system_prompt() -> str:
    return (
        f"Ти персональний health-тренер користувача на ім'я {USER_NAME}. "
        "Говориш українською на 'ти', коротко і по суті, без медичного жаргону і без вибачень. "
        f"Користувач: вік {USER_AGE}, тип роботи — {USER_WORK_TYPE}, ціль — {USER_GOAL}. "
        "Враховуй погоду і тип роботи, коли даєш пораду. "
        "Стрес (stress_avg) інтерпретуй так: <25 — низький, все добре; 25-50 — середній, це норма; "
        "50+ — підвищений, обов'язково згадай це в пораді. "
        "Якщо передано elevated_stress_streak: true — це означає підвищений стрес (50+) два або "
        "більше днів поспіль; ОБОВ'ЯЗКОВО окремо наголоси в summary, що кілька днів поспіль "
        "підвищений стрес і сьогодні важливо не додавати навантаження. "
        "Якщо передано yesterday_evening_note або yesterday_tomorrow_intention — врахуй їх у "
        "пораді (наприклад, якщо вчора користувач писав що було важко на роботі, порадь не "
        "перевантажувати себе додатково сьогодні). "
        "Відповідай ЛИШЕ JSON без жодного тексту навколо у форматі: "
        '{"sleep_status": "green|yellow|red", "recovery_status": "green|yellow|red", '
        '"readiness_status": "green|yellow|red", "summary": "один абзац: що відбувається з тілом, '
        'чому (з урахуванням погоди), і одна конкретна порада на сьогодні"}'
    )


def build_user_message(rows: list[dict], current_weather: dict, yesterday_weather: dict | None) -> str:
    today = rows[0]
    yesterday = rows[1] if len(rows) > 1 else {}

    msg = "Дані Garmin за сьогодні:\n" + json.dumps(today, ensure_ascii=False) + "\n\n"
    msg += "Погода в Києві зараз:\n" + json.dumps(current_weather, ensure_ascii=False) + "\n"
    if yesterday_weather:
        msg += "Погода вчора о 22:00:\n" + json.dumps(yesterday_weather, ensure_ascii=False) + "\n"

    msg += "\nІсторія стресу (найсвіжіший перший):\n" + json.dumps(
        [{"date": r["date"], "stress_avg": r["stress_avg"]} for r in rows], ensure_ascii=False
    ) + "\n"
    msg += "elevated_stress_streak: " + str(has_elevated_stress_streak(rows)).lower() + "\n"

    if yesterday.get("evening_note"):
        msg += "yesterday_evening_note: " + json.dumps(yesterday["evening_note"], ensure_ascii=False) + "\n"
    if yesterday.get("tomorrow_intention"):
        msg += "yesterday_tomorrow_intention: " + json.dumps(yesterday["tomorrow_intention"], ensure_ascii=False) + "\n"

    return msg


def call_claude(system_prompt: str, user_message: str) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "content-type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": MODEL,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_blocks).strip()


def extract_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def save_to_notion(page_id: str, brief: dict):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    properties = {
        "Morning brief": {"rich_text": [{"text": {"content": brief["summary"][:1900]}}]},
        "Sleep status": {"rich_text": [{"text": {"content": brief["sleep_status"]}}]},
        "Recovery status": {"rich_text": [{"text": {"content": brief["recovery_status"]}}]},
        "Readiness status": {"rich_text": [{"text": {"content": brief["readiness_status"]}}]},
    }
    resp = requests.patch(url, headers=NOTION_HEADERS, json={"properties": properties})
    resp.raise_for_status()


def main():
    rows = fetch_recent_rows(limit=3)
    if not rows:
        raise SystemExit("У базі немає жодного рядка — спершу запусти sync.py")

    current_weather = get_current_weather()
    yesterday_weather = get_yesterday_evening_weather()

    user_message = build_user_message(rows, current_weather, yesterday_weather)
    raw = call_claude(build_system_prompt(), user_message)
    brief = extract_json(raw)

    save_to_notion(rows[0]["page_id"], brief)
    print(f"Morning brief saved for {rows[0]['date']}: {brief}")


if __name__ == "__main__":
    main()
