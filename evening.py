"""
Вечірній health-брифінг: короткий підсумок дня на основі кроків, стресу і
динаміки Body Battery, плюс одна порада що зробити перед сном для кращого
відновлення. Зберігає результат у сьогоднішній рядок Notion.

Потрібні secrets (env vars):
  NOTION_TOKEN, NOTION_DATABASE_ID, ANTHROPIC_API_KEY
"""

import datetime
import json
import os

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
MODEL = "claude-sonnet-4-6"

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
    return None


def fetch_today_row() -> dict | None:
    today = datetime.date.today().isoformat()
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"filter": {"property": "Day", "date": {"equals": today}}}
    resp = requests.post(url, headers=NOTION_HEADERS, json=payload)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None

    page = results[0]
    props = page["properties"]
    return {
        "page_id": page["id"],
        "date": today,
        "steps": num(props, "Steps"),
        "stress_avg": num(props, "Stress avg"),
        "body_battery_high": num(props, "Body Battery high"),
        "body_battery_low": num(props, "Body Battery low"),
        "activities": text(props, "Activities"),
    }


SYSTEM_PROMPT = (
    "Коротко (2-3 речення) підсумуй день по даних і дай одну пораду що зробити перед сном "
    "для кращого відновлення. Говориш на 'ти', просто і по-людськи."
)


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


def save_to_notion(page_id: str, brief_text: str):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    properties = {"Evening brief": {"rich_text": [{"text": {"content": brief_text[:1900]}}]}}
    resp = requests.patch(url, headers=NOTION_HEADERS, json={"properties": properties})
    resp.raise_for_status()


def main():
    row = fetch_today_row()
    if not row:
        raise SystemExit("Немає рядка за сьогодні в Notion — спершу запусти sync.py")

    bb_swing = None
    if row["body_battery_high"] is not None and row["body_battery_low"] is not None:
        bb_swing = row["body_battery_high"] - row["body_battery_low"]

    user_message = json.dumps({
        "date": row["date"],
        "steps": row["steps"],
        "stress_avg": row["stress_avg"],
        "body_battery_high": row["body_battery_high"],
        "body_battery_low": row["body_battery_low"],
        "body_battery_swing": bb_swing,
        "activities": row["activities"],
    }, ensure_ascii=False)

    brief_text = call_claude(SYSTEM_PROMPT, user_message)
    save_to_notion(row["page_id"], brief_text)
    print(f"Evening brief saved for {row['date']}: {brief_text}")


if __name__ == "__main__":
    main()
