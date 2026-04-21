# Deploy to GitHub + Render

## 1. Push to GitHub

In your project folder (e.g. `Poker - tracker`), run:

```bash
cd "/Users/tylertsay/Desktop/Poker - tracker"

# Initialize git (if not already)
git init

# Add everything (respects .gitignore)
git add .
git commit -m "Initial commit: Poker Tracker"

# Add your GitHub repo as remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/poker-tracker.git

# Push (main branch)
git branch -M main
git push -u origin main
```

If the repo already had a README and you get "failed to push (non-fast-forward)", either:

- **Force push** (only if no one else uses the repo):  
  `git push -u origin main --force`
- **Or pull first**:  
  `git pull origin main --allow-unrelated-histories`  
  then fix any conflicts, then `git push -u origin main`

---

## 2. Render: Database + Web Service

### Option A — Using the Blueprint (render.yaml)

1. Go to [Render Dashboard](https://dashboard.render.com).
2. **New** → **Blueprint**.
3. Connect your **GitHub** account and select the **poker-tracker** repo.
4. Render will read `render.yaml` and create:
   - A **PostgreSQL** database: `poker-tracker-db`
   - A **Web Service**: `poker-tracker` (builds and runs the app).
5. Add a **Secret** (Environment variable):
   - Key: `ADMIN_PASSWORD`  
   - Value: your chosen admin password (e.g. generate a strong one).
6. **Apply** the Blueprint. Render will build and deploy. The start command in `render.yaml` runs `stamp_alembic_if_needed.py` then `python -m alembic upgrade head`, so migrations run automatically.
7. Open the service URL (e.g. `https://poker-tracker-xxxx.onrender.com`) and log in with `ADMIN_PASSWORD`.

---

### Option B — Manual setup (no Blueprint)

#### Step 1: Create PostgreSQL database

1. [Render Dashboard](https://dashboard.render.com) → **New** → **PostgreSQL**.
2. Name: e.g. `poker-tracker-db`.
3. Region: choose one close to you.
4. Create. Wait until it’s **Available**.
5. Open the DB → **Info** (or **Connect**). Copy the **Internal Database URL** (use this for the web service).

#### Step 2: Create Web Service

1. **New** → **Web Service**.
2. Connect **GitHub** and select **poker-tracker**.
3. Settings:
   - **Name**: `poker-tracker` (or any name).
   - **Region**: same as DB if possible.
   - **Branch**: `main`.
   - **Runtime**: **Python 3**.
  - **Build Command**: `pip install -r requirements.txt`
  - **Start Command** (required — do not use only `uvicorn`):
    ```bash
    python stamp_alembic_if_needed.py && python -m alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT
    ```
    The stamp script fixes DBs that already have tables but no Alembic history (e.g. from an earlier deploy). Schema in production is managed only by Alembic.
4. **Environment** (Add Environment Variable):
   - `ADMIN_PASSWORD` = (your secret admin password)
   - `DATABASE_URL` = (paste the **Internal Database URL** from the PostgreSQL service)
     - Render often gives `postgres://...`; the app converts it to `postgresql://` automatically.
   - Optional: `PAYMENT_PASSWORD` = (separate password for ledger/payment actions; defaults to `ADMIN_PASSWORD`)
5. **Create Web Service**. Render will build and deploy. Migrations run as part of the start command.
6. Open the service URL and log in with `ADMIN_PASSWORD`.

---

## 3. After deploy

- **Login**: Go to your app URL → you’ll be redirected to `/login`. Use the `ADMIN_PASSWORD` you set.
- **First use**: Create players, then add a game (manual or upload).
- **Uploads**: Screenshot files are stored on the service disk; they can be lost on redeploy. For persistent uploads, use a Render **Disk** and point `UPLOADS_DIR` in code to that path, or add object storage later.
