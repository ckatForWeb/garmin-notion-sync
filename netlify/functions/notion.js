// Проксі до Notion REST API. NOTION_TOKEN живе тільки тут (env var на Netlify),
// у браузер ніколи не потрапляє. GET — забрати останній рядок, POST — зберегти контекст.

const NOTION_DB_ID = "ae75f432-077f-4c9e-a62c-aa1a6ff51a0e";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function num(props, name) {
  const p = props[name];
  return p && p.number != null ? p.number : null;
}

function text(props, name) {
  const p = props[name];
  if (!p) return null;
  if (p.rich_text && p.rich_text.length) return p.rich_text.map((t) => t.plain_text).join("");
  if (p.title && p.title.length) return p.title.map((t) => t.plain_text).join("");
  return null;
}

exports.handler = async function (event) {
  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers: CORS_HEADERS, body: "" };
  }

  const NOTION_TOKEN = process.env.NOTION_TOKEN;
  if (!NOTION_TOKEN) {
    return {
      statusCode: 500,
      headers: CORS_HEADERS,
      body: JSON.stringify({ error: "NOTION_TOKEN не налаштовано на сервері (Netlify env var)" }),
    };
  }

  const notionHeaders = {
    Authorization: "Bearer " + NOTION_TOKEN,
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
  };

  try {
    if (event.httpMethod === "GET") {
      const resp = await fetch("https://api.notion.com/v1/databases/" + NOTION_DB_ID + "/query", {
        method: "POST",
        headers: notionHeaders,
        body: JSON.stringify({
          sorts: [{ property: "Day", direction: "descending" }],
          page_size: 1,
        }),
      });
      if (!resp.ok) {
        const t = await resp.text();
        return { statusCode: resp.status, headers: CORS_HEADERS, body: t };
      }
      const data = await resp.json();
      const page = data.results && data.results[0];
      if (!page) {
        return {
          statusCode: 404,
          headers: CORS_HEADERS,
          body: JSON.stringify({ error: "У базі ще немає жодного рядка" }),
        };
      }
      const props = page.properties;
      const row = {
        date: props["Day"] && props["Day"].date ? props["Day"].date.start : null,
        sleep_score: num(props, "Sleep score"),
        sleep_hours: num(props, "Sleep hours"),
        hrv_avg: num(props, "HRV avg"),
        hrv_status: text(props, "HRV status"),
        body_battery_high: num(props, "Body Battery high"),
        body_battery_low: num(props, "Body Battery low"),
        resting_hr: num(props, "Resting HR"),
        deep_sleep_min: num(props, "Deep sleep min"),
        rem_sleep_min: num(props, "REM sleep min"),
        light_sleep_min: num(props, "Light sleep min"),
        spo2_avg: num(props, "SpO2 avg"),
        spo2_low: num(props, "SpO2 low"),
        stress_avg: num(props, "Stress avg"),
        activities: text(props, "Activities"),
      };
      return { statusCode: 200, headers: CORS_HEADERS, body: JSON.stringify(row) };
    }

    if (event.httpMethod === "POST") {
      const payload = JSON.parse(event.body || "{}");
      const contextText = String(payload.contextText || "").slice(0, 1900);
      const today = new Date().toISOString().slice(0, 10);

      const queryResp = await fetch("https://api.notion.com/v1/databases/" + NOTION_DB_ID + "/query", {
        method: "POST",
        headers: notionHeaders,
        body: JSON.stringify({ filter: { property: "Day", date: { equals: today } } }),
      });
      if (!queryResp.ok) {
        const t = await queryResp.text();
        return { statusCode: queryResp.status, headers: CORS_HEADERS, body: t };
      }
      const queryData = await queryResp.json();
      const existing = queryData.results && queryData.results[0];

      const properties = {
        "Context notes": { rich_text: [{ text: { content: contextText } }] },
      };

      let saveResp;
      if (existing) {
        saveResp = await fetch("https://api.notion.com/v1/pages/" + existing.id, {
          method: "PATCH",
          headers: notionHeaders,
          body: JSON.stringify({ properties: properties }),
        });
      } else {
        saveResp = await fetch("https://api.notion.com/v1/pages", {
          method: "POST",
          headers: notionHeaders,
          body: JSON.stringify({
            parent: { database_id: NOTION_DB_ID },
            properties: Object.assign(
              {
                Name: { title: [{ text: { content: today } }] },
                Day: { date: { start: today } },
              },
              properties
            ),
          }),
        });
      }
      if (!saveResp.ok) {
        const t = await saveResp.text();
        return { statusCode: saveResp.status, headers: CORS_HEADERS, body: t };
      }
      return { statusCode: 200, headers: CORS_HEADERS, body: JSON.stringify({ ok: true }) };
    }

    return { statusCode: 405, headers: CORS_HEADERS, body: "Method not allowed" };
  } catch (err) {
    return { statusCode: 500, headers: CORS_HEADERS, body: JSON.stringify({ error: String(err) }) };
  }
};
