"""
Garmin -> Notion daily sync.

Тягне за вчорашній день: сон, HRV, Body Battery, тренування, кроки, пульс спокою.
Пише один рядок у Notion-базу (по даті). Якщо рядок за цю дату вже є — оновлює його.

Потрібні secrets (env vars):
  GARMIN_EMAIL, GARMIN_PASSWORD
  NOTION_TOKEN, NOTION_DATABASE_ID
"""

import os
import sys
import datetime
import requests
from garminconnect import Garmin

GARMIN_EMAIL = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD = os.environ["GARMIN_PASSWORD"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def fetch_garmin_data(date_str: str) -> dict:
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()

    sleep = client.get_sleep_data(date_str) or {}
    hrv = client.get_hrv_data(date_str) or {}
    body_battery = client.get_body_battery(date_str, date_str) or []
    stats = client.get_stats(date_str) or {}
    activities = client.get_activities_by_date(date_str, date_str) or []

    sleep_dto = sleep.get("dailySleepDTO", {}) if isinstance(sleep, dict) else {}
    hrv_summary = hrv.get("hrvSummary", {}) if isinstance(hrv, dict) else {}

    bb_high = bb_low = None
    if body_battery and isinstance(body_battery, list):
        values = [v for entry in body_battery for v in entry.get("bodyBatteryValuesArray", [])]
        levels = [v[1] for v in values if isinstance(v, list) and len(v) > 1 and v[1] is not None]
        if levels:
            bb_high, bb_low = max(levels), min(levels)

    activity_names = ", ".join(a.get("activityName", "") for a in activities) if activities else ""

    return {
        "date": date_str,
        "sleep_score": sleep_dto.get("sleepScores", {}).get("overall", {}).get("value")
        if isinstance(sleep_dto.get("sleepScores"), dict) else None,
        "sleep_seconds": sleep_dto.get("sleepTimeSeconds"),
        "hrv_avg": hrv_summary.get("lastNightAvg"),
        "hrv_status": hrv_summary.get("status"),
        "body_battery_high": bb_high,
        "body_battery_low": bb_low,
        "resting_hr": stats.get("restingHeartRate"),
        "steps": stats.get("totalSteps"),
        "stress_avg": stats.get("averageStressLevel"),
        "activities": activity_names,
    }


def find_existing_page(date_str: str) -> str | None:
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"filter": {"property": "Day", "date": {"equals": date_str}}}
    resp = requests.post(url, headers=NOTION_HEADERS, json=payload)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None


def build_properties(data: dict) -> dict:
    def num(key):
        v = data.get(key)
        return {"number": v} if v is not None else {"number": None}

    return {
        "Name": {"title": [{"text": {"content": data["date"]}}]},
        "Day": {"date": {"start": data["date"]}},
        "Sleep score": num("sleep_score"),
        "Sleep hours": {"number": round(data["sleep_seconds"] / 3600, 2) if data.get("sleep_seconds") else None},
        "HRV avg": num("hrv_avg"),
        "HRV status": {"rich_text": [{"text": {"content": data.get("hrv_status") or ""}}]},
        "Body Battery high": num("body_battery_high"),
        "Body Battery low": num("body_battery_low"),
        "Resting HR": num("resting_hr"),
        "Steps": num("steps"),
        "Stress avg": num("stress_avg"),
        "Activities": {"rich_text": [{"text": {"content": data.get("activities") or ""}}]},
    }


def upsert_notion_row(data: dict):
    properties = build_properties(data)
    existing_id = find_existing_page(data["date"])

    if existing_id:
        url = f"https://api.notion.com/v1/pages/{existing_id}"
        resp = requests.patch(url, headers=NOTION_HEADERS, json={"properties": properties})
    else:
        url = "https://api.notion.com/v1/pages"
        payload = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties}
        resp = requests.post(url, headers=NOTION_HEADERS, json=payload)

    resp.raise_for_status()


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else (
        datetime.date.today() - datetime.timedelta(days=1)
    ).isoformat()

    data = fetch_garmin_data(target_date)
    upsert_notion_row(data)
    print(f"Synced {target_date}: {data}")


if __name__ == "__main__":
    main()
