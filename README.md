# Noah's Ark Fundraiser

Static public fundraiser page with a small Python/Flask admin API for safely adding and deleting donations in Supabase.

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

Open Supabase SQL Editor and run the SQL in `supabase-schema.sql`.

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
```

Default admin password: `uganda2026`.

## 5. Deploy free on Render

This project is ready for Render as one free Python web service. The public site and admin panel are served by the same Flask app.

1. Push this folder to a GitHub repository.
2. Go to Render and choose **New > Blueprint**.
3. Connect the repository and select `render.yaml`.
4. When Render asks for `SUPABASE_SERVICE_KEY`, paste your Supabase service role key.
5. After deploy, open the generated `https://...onrender.com` URL.

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
STRIPE_PUBLISHABLE_KEY=pk_test_your-publishable-key
STRIPE_SECRET_KEY=sk_test_your-secret-key
STRIPE_WEBHOOK_SECRET=whsec_your-webhook-secret
SITE_URL=https://your-render-url.onrender.com
```

Free Render services can sleep after inactivity. The first request after a quiet period can take about a minute.

## Stripe payments

Stripe Checkout is used for iDEAL/card donations. The browser sends the chosen amount to Flask, Flask creates a Checkout Session, and successful payments are verified server-side before a donation row is inserted in Supabase.

Do not commit Stripe secret keys. Put them in `.env` locally and Render environment variables in production. After adding `stripe_session_id` and `stripe_payment_intent`, re-run `supabase-schema.sql` in Supabase SQL Editor so paid Stripe sessions are recorded only once.

For webhook automation, add a Stripe webhook endpoint:

```text
https://your-domain.example/api/stripe/webhook
```

Listen for:

```text
checkout.session.completed
checkout.session.async_payment_succeeded
```
