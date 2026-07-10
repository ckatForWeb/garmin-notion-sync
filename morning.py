"""
Ранковий health-брифінг: рахує статуси (сон/відновлення/готовність)
детерміністично з порогів, генерує AI-текст поради на основі сьогоднішніх
Garmin-метрик, поточної погоди і вчорашньої вечірньої рефлексії, і зберігає
результат у сьогоднішній рядок Notion.

Запускається після sync.py (дані за сьогодні вже мають бути в Notion).

Потрібні secrets (env vars):
  NOTION_TOKEN, NOTION_DATABASE_ID, ANTHROPIC_API_KEY, OPENWEATHER_API_KEY
"""

import json
import os
import re

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OPENWEATHER_API_KEY = os.environ["OPENWEATHER_API_KEY"]

MODEL = "claude-sonnet-4-6"

# Персональний одноосібний проєкт — профіль просто хардкодиться, а не збирається
# від користувача (генерація тепер відбувається тут, а не в браузері).
USER_NAME = "Юрій"
USER_WORK_TYPE = "сидяча"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

SYSTEM_PROMPT = (
    "Ти персональний health-тренер. Говориш на 'ти', коротко і по суті, без медичного жаргону.\n"
    "Враховуй погоду (якщо спека — про воду і навантаження, якщо холод — про суглоби і розминку).\n"
    f"Враховуй тип роботи: {USER_WORK_TYPE} (нагадуй про рух і поставу).\n"
    "Якщо стрес > 50 два дні поспіль — окремо скажи про це.\n"
    "Якщо є вечірні нотатки вчора — враховуй їх у пораді.\n"
    "Відповідай одним абзацом, 3-4 речення максимум."
)


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
        "https://api.openweathermap.org/data/2.5/weather?q=Kyiv&appid=" +
        OPENWEATHER_API_KEY + "&units=metric&lang=ua"
    )
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    return {
        "temp": data.get("main", {}).get("temp"),
        "condition": (data.get("weather") or [{}])[0].get("description"),
    }


def has_elevated_stress_streak(rows: list[dict]) -> bool:
    streak = 0
    for row in rows:
        if row.get("stress_avg") is not None and row["stress_avg"] > 50:
            streak += 1
        else:
            break
    return streak >= 2


def compute_statuses(today: dict) -> dict:
    sleep_score = today.get("sleep_score")
    if sleep_score is not None and sleep_score >= 80:
        sleep_status = "green"
    elif sleep_score is not None and sleep_score >= 60:
        sleep_status = "yellow"
    else:
        sleep_status = "red"

    hrv_status = (today.get("hrv_status") or "").upper()
    if hrv_status == "BALANCED":
        recovery_status = "green"
    elif hrv_status == "LOW":
        recovery_status = "yellow"
    elif hrv_status == "POOR":
        recovery_status = "red"
    else:
        recovery_status = "yellow"

    bb_high = today.get("body_battery_high")
    if bb_high is not None and bb_high < 40:
        readiness_status = "red"
    elif bb_high is not None and bb_high >= 70 and sleep_status == "green":
        readiness_status = "green"
    else:
        readiness_status = "yellow"

    return {
        "sleep_status": sleep_status,
        "recovery_status": recovery_status,
        "readiness_status": readiness_status,
    }


def build_user_message(rows: list[dict], weather: dict) -> str:
    today = rows[0]
    yesterday = rows[1] if len(rows) > 1 else {}

    msg = "Дані Garmin за сьогодні:\n" + json.dumps(today, ensure_ascii=False) + "\n\n"
    msg += "Погода в Києві зараз:\n" + json.dumps(weather, ensure_ascii=False) + "\n"

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
            "max_tokens": 512,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_blocks).strip()


def save_to_notion(page_id: str, summary: str, statuses: dict, weather: dict):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    properties = {
        "Morning brief": {"rich_text": [{"text": {"content": summary[:1900]}}]},
        "Sleep status": {"rich_text": [{"text": {"content": statuses["sleep_status"]}}]},
        "Recovery status": {"rich_text": [{"text": {"content": statuses["recovery_status"]}}]},
        "Readiness status": {"rich_text": [{"text": {"content": statuses["readiness_status"]}}]},
        "Weather temp": {"number": weather.get("temp")},
        "Weather condition": {"rich_text": [{"text": {"content": weather.get("condition") or ""}}]},
    }
    resp = requests.patch(url, headers=NOTION_HEADERS, json={"properties": properties})
    resp.raise_for_status()


def main():
    rows = fetch_recent_rows(limit=3)
    if not rows:
        raise SystemExit("У базі немає жодного рядка — спершу запусти sync.py")

    weather = get_current_weather()
    statuses = compute_statuses(rows[0])

    user_message = build_user_message(rows, weather)
    summary = call_claude(SYSTEM_PROMPT, user_message)

    save_to_notion(rows[0]["page_id"], summary, statuses, weather)
    print(f"Morning brief saved for {rows[0]['date']}: {statuses} | {summary}")


if __name__ == "__main__":
    main()
