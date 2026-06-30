# Garmin → Notion sync

Щоденно тягне з Garmin Connect: сон (зокрема фази), HRV, Body Battery, пульс спокою, кроки, стрес, SpO2, тренування за вчора (з деталями) — і пише рядок у Notion-таблицю. Звідти я (Claude) можу читати дані через Notion MCP і робити аналітику/тренди в будь-який момент, без ручного експорту.

## Кроки налаштування

### 1. Створи Notion-базу (database)
Властивості (точні назви, тип):
- `Name` — Title (обов'язкове поле-заголовок для будь-якої Notion-бази)
- `Day` — Date
- `Sleep score` — Number
- `Sleep hours` — Number
- `Deep sleep min` — Number
- `Light sleep min` — Number
- `REM sleep min` — Number
- `Awake min` — Number
- `HRV avg` — Number
- `HRV status` — Text
- `Body Battery high` — Number
- `Body Battery low` — Number
- `Resting HR` — Number
- `Steps` — Number
- `Stress avg` — Number
- `Activities` — Text
- `Activity duration min` — Number
- `Activity avg HR` — Number
- `Activity max HR` — Number
- `Activity calories` — Number
- `Training effect` — Number
- `SpO2 avg` — Number
- `SpO2 low` — Number

Підключи цю базу до свого Notion-інтеграційного токена (Share → Connect → твоя інтеграція), скопіюй `database_id` з URL бази.

### 2. Створи GitHub-репозиторій
Заклинь у нього ці два файли (`sync.py` і `.github/workflows/sync.yml`), збережи структуру папок.

### 3. Додай secrets у репозиторії
Settings → Secrets and variables → Actions → New repository secret:
- `GARMIN_EMAIL`
- `GARMIN_PASSWORD`
- `NOTION_TOKEN` (Notion internal integration token, з notion.so/my-integrations)
- `NOTION_DATABASE_ID`

### 4. Перевір вручну
Actions → Garmin -> Notion sync → Run workflow (workflow_dispatch) — перший запуск варто зробити руками, щоб перевірити, що все під'єдналось і дані падають у таблицю правильно.

Далі воркфлоу ганяється сам щодня о ~6:00 за Києвом (cron `0 4 * * *`, UTC).

## Зауваження щодо нових полів
- Якщо за день кілька тренувань, `Activity duration min`/`calories` сумуються, `Activity avg HR` — середнє, `Activity max HR`/`Training effect` — максимум по тренуваннях.
- Точні ключі SpO2 у відповіді Garmin відрізняються залежно від моделі годинника — код пробує кілька варіантів (`get_spo2_data`, фолбек на `get_respiration_data`). Якщо в твоєї моделі немає SpO2-сенсора, поля просто будуть порожні.

## Зауваження щодо безпеки
- `garminconnect` логіниться напряму твоїми email/паролем (офіційного публічного OAuth API в Garmin для персонального використання немає) — тому пароль зберігається лише як GitHub secret, в коді ніде не світиться.
- Якщо в акаунті Garmin увімкнена 2FA — логін через бібліотеку може зламатись; тоді треба або вимкнути 2FA для Garmin Connect, або переходити на сесійні токени (`garminconnect` підтримує кешування сесії — можу доробити, якщо знадобиться).
- Раджу завести окремий Notion-токен з доступом лише до цієї бази, а не до всього воркспейсу.

## Що далі
Коли дані почнуть капати в Notion (хоча б тиждень), кинь мені посилання на базу — підключусь через Notion MCP і зроблю дашборд/аналіз трендів (сон vs HRV vs тренування, anomaly detection, кореляції з твоїм робочим навантаженням і т.д.).
