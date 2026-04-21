# Weekly Poker Tracker (Home Game)

**Repository:** [https://github.com/ttsay10000/poker-tracker](https://github.com/ttsay10000/poker-tracker) — owner: `ttsay10000`

A small web app to track weekly poker results: add games (manual or screenshot), review and correct data, enforce balance (sum of net change = 0) with optional override, and track outstanding balances and settlements.

## Features

- **Dashboard**: Chart of cumulative net per player over time; filters (players, date range); table of totals, games played, avg/game, outstanding, and status (organizer owes / owes organizer / settled).
- **Games**: Add past games manually (date + grid) or via screenshot upload; review and edit grid (player mapping, buy-in, cashout, net change); confirm and save only on final save (no draft DB writes).
- **Balance rules**: Game must balance (sum of net change = 0 within ±$0.01) or admin must check “Force Save” and provide a reason.
- **Players**: Create, edit, deactivate (no hard delete); unique normalized names.
- **Settlements**: Record payments (I paid player = +amount, Player paid me = -amount); outstanding = lifetime net − settled.
- **Edit saved games**: Change date, player mapping, numbers; add/remove rows. If settlements exist, a warning is shown; outstanding updates automatically.

## Stack

- **Backend**: FastAPI + Jinja2 templates
- **DB**: PostgreSQL (Render) or SQLite (local)
- **ORM**: SQLModel
- **Migrations**: Alembic
- **Charts**: Chart.js (server-prepared JSON)

## Setup

### Local

1. Clone and create a virtualenv:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

2. Copy env and set admin password:
   ```bash
   cp .env.example .env
   # Edit .env: set ADMIN_PASSWORD=yourpassword
   ```

3. (Optional) Use PostgreSQL by setting `DATABASE_URL` in `.env`. If unset, SQLite is used (`poker.db` in project root).

4. Create tables (SQLite creates them on startup; for Alembic):
   ```bash
   python -m alembic upgrade head
   ```

5. Run the app:
   ```bash
   uvicorn main:app --reload
   ```
   Open http://127.0.0.1:8000 → redirects to `/dashboard` (login required).

### Deploy on Render

1. **New Web Service**; connect the repo.

2. **Build**:
   - Build command: `pip install -r requirements.txt`
   - No static build step required.

3. **Start**:
   - Start command: `python stamp_alembic_if_needed.py && python -m alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT`

4. **Environment**:
   - `ADMIN_PASSWORD`: required (admin login).
   - `DATABASE_URL`: from Render PostgreSQL (auto-set if you add a Postgres instance and link it).
   - Optional: `SECRET_KEY` for cookie signing (defaults to `ADMIN_PASSWORD`).
   - Optional: `PAYMENT_PASSWORD` for ledger/payment actions (defaults to `ADMIN_PASSWORD`).

5. **Persistent disk** (optional): If you use screenshot uploads and want them to survive deploys, add a disk and set `UPLOADS_DIR` to that path (or mount the disk and update `config.py` to use it). Otherwise uploads are stored in the app filesystem and may be lost on redeploy.

6. Migrations must run on every deploy before the app starts.
   The start command above handles this automatically. If you already created the
   web service with an older start command, update it in Render and redeploy.

## Auth

- All main routes are admin-only. Set `ADMIN_PASSWORD` in the environment; login at `/login`. Session is stored in a signed cookie.

## Data model (summary)

- **Player**: id, name, name_normalized (unique), is_active, created_at
- **Game**: id, played_at, source_image_path_or_url, created_at, updated_at
- **GameEntry**: game_id, player_id, raw_name, buyin, cashout, final_stack, net_change
- **Settlement**: player_id, settled_at, amount (>0 organizer paid player; <0 player paid organizer), note

Balance: `outstanding(player) = SUM(GameEntry.net_change) − SUM(Settlement.amount)`.

## License

Use as you like for home games.
