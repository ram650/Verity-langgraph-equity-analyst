# Deploying Verity

Frontend (static React) on **Vercel**, backend (FastAPI) on **Render**. Both deploy
from this GitHub repo. Your `backend/.env` is gitignored and never leaves your machine.

## 0. Push to GitHub
From the repo root (E:\Verity):

```
git init
git add .
git commit -m "Verity: verifiable multi-agent equity research"
```

Create an empty repo at github.com (no README), then:

```
git remote add origin https://github.com/<you>/verity.git
git branch -M main
git push -u origin main
```

Confirm `backend/.env` is NOT in the push (it's gitignored).

## 1. Backend on Render
- render.com -> New -> **Blueprint** -> pick this repo. `render.yaml` configures the
  service (root dir `backend`, install, and start command) automatically.
- Open the service -> **Environment** and set:
  - `ANTHROPIC_API_KEY` = your Anthropic key
  - `ALPHAVANTAGE_API_KEY` = your key (optional; only for the spin check)
  - `VERITY_CORS_ORIGINS` = `*` for now (tighten in step 3)
- Deploy. Note the URL, e.g. `https://verity-api.onrender.com`. Test `…/suggested`.

## 2. Frontend on Vercel
- vercel.com -> New Project -> import this repo.
- **Root Directory** = `frontend` (framework auto-detects as Vite).
- Add an Environment Variable:
  - `VITE_API_BASE` = your Render URL, e.g. `https://verity-api.onrender.com`
- Deploy. Note the URL, e.g. `https://verity.vercel.app`.

## 3. Lock down CORS
- Back in Render -> Environment, set `VERITY_CORS_ORIGINS` = your Vercel URL
  (e.g. `https://verity.vercel.app`) and redeploy. Now only your site can call the API.

## Notes
- Render's free tier sleeps after ~15 min idle; the first request after a nap wakes
  it (~30-60s). Fine for a portfolio demo.
- The report and logo caches live on disk and reset on redeploy — reports simply
  regenerate on next view (a few cents each). Cost guardrails: per-IP rate limit
  (`VERITY_RATE_PER_MIN`) and a daily cap on new analyses (`VERITY_DAILY_NEW_ANALYSES`).
- Never commit `backend/.env`. Rotate the key if it is ever exposed.
