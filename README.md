# Noah's Ark Fundraiser

Static public fundraiser page with a small Python/Flask admin API for safely adding and deleting donations in Supabase. Large direct-transfer donations can generate a filled PDF form and are stored in a separate admin list.

## 1. Install Python

Install Python 3.11 or newer from python.org. On Windows, enable "Add python.exe to PATH" during installation.

If `python --version` still opens the Microsoft Store alias, disable the aliases in:

```text
Settings > Apps > Advanced app settings > App execution aliases
```

Turn off the `python.exe` and `python3.exe` aliases.

## 2. Install dependencies

From this project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill the real values. Never commit `.env`.

## 3. Create the Supabase table

Open Supabase SQL Editor and run the SQL in `supabase-schema.sql`. Re-run it after updates; it creates both `donations` and `large_donation_forms`.

The publishable key is already filled in. For admin add/delete, also fill this line in `.env`:

```text
SUPABASE_SERVICE_KEY=your-service-role-key
```

Do not put the service key in `config.js`.

## 4. Run locally

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

Open:

```text
http://localhost:5000/
http://localhost:5000/admin
http://localhost:5000/grote-donatie.html
```

Default admin password: `uganda2026`.

## 5. Deploy free on Render

This project is ready for Render as one free Python web service. The public site and admin panel are served by the same Flask app.

1. Push this folder to a GitHub repository.
2. Go to Render and choose **New > Blueprint**.
3. Connect the repository and select `render.yaml`.
4. When Render asks for `SUPABASE_SERVICE_KEY`, paste your Supabase service role key.
5. Make sure `supabase-schema.sql` has been run in Supabase.
6. After deploy, open the generated `https://...onrender.com` URL.

Render settings if you create the service manually instead of using the blueprint:

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
Plan: Free
```

Set these environment variables in Render:

```text
SUPABASE_URL=https://ipbfwummhkuflvqdomai.supabase.co
SUPABASE_KEY=sb_publishable_aQB7EjiqV_MLK_7UVTltiA_1vA2wvgC
SUPABASE_SERVICE_KEY=your-service-role-key
ADMIN_PASSWORD_HASH=0ba0d2c0160a5246cd62e302ccb7711cdac6808a965acf6f01a3a93ac6ab9a67
FLASK_SECRET_KEY=a-long-random-string
GOAL_EUR=10000
TARGET_DATE=2027-02-01
IBAN=your-iban
IBAN_NAME=your-account-name
TIKKIE_URL=your-tikkie-link
```

Free Render services can sleep after inactivity. The first request after a quiet period can take about a minute.

The large-donation form only records the submitted form and adds the amount to the counter after the user confirms they will transfer it themselves. It does not execute a bank payment.
