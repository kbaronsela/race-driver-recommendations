# GitHub repo for your website

## You already have a repo

This project is already connected to:

**https://github.com/kbaronsela/race-driver-recommendations**

You can use that repo as-is for PythonAnywhere. On PythonAnywhere, clone it with:

```bash
git clone https://github.com/kbaronsela/race-driver-recommendations.git
```

---

## If you want a repo under your own GitHub account

1. **Create the repo on GitHub**
   - Go to [github.com](https://github.com) and sign in.
   - Click **+** → **New repository**.
   - Repository name: `race-driver-recommendations` (or any name you like).
   - Leave it empty (no README, no .gitignore).
   - Click **Create repository**.

2. **Push this project to your new repo**

   In your project folder (where `server.py` is), run:

   ```bash
   git remote add myorigin https://github.com/YOUR_GITHUB_USERNAME/race-driver-recommendations.git
   git push -u myorigin main
   ```

   Replace `YOUR_GITHUB_USERNAME` with your GitHub username.  
   If your default branch is `master` instead of `main`, use `git push -u myorigin master`.

   To use your repo as the main remote later:

   ```bash
   git remote remove origin
   git remote rename myorigin origin
   ```

3. **On PythonAnywhere**, clone using your repo URL:

   ```bash
   git clone https://github.com/YOUR_GITHUB_USERNAME/race-driver-recommendations.git
   cd race-driver-recommendations
   ```

---

## Files that must be in the repo (for the site to work)

| Path | Purpose |
|------|--------|
| `server.py` | Flask app and API |
| `wsgi.py` | PythonAnywhere entry point |
| `index.html` | Frontend |
| `requirements.txt` | Dependencies |
| `data/entries.json` | Contact list |
| `data/fields.json` | Field options for add/edit |
| `data/user_data.json` | Optional; created on first edit if missing |
| `assets/logo-moshav.png` | Moshav logo |
| `assets/logo-race-driver.png` | Race driver logo |
| `set_password.py` | Optional; for creating config locally |
| `config.json.example` | Optional; example for config |
| `DEPLOY_PYTHONANYWHERE.md` | Deployment steps for racedriver |

**Not in the repo** (in `.gitignore`): `config.json`, `venv/`, `__pycache__/`.  
On PythonAnywhere you set login via **Web** → **Environment variables**: `PYTHONANYWHERE_USER` and `PYTHONANYWHERE_PASSWORD`.

---

## One-time: make sure everything is committed

From the project folder:

```bash
git status
git add .
git status   # check that config.json is NOT listed (it's ignored)
git commit -m "Add all files for PythonAnywhere deployment"
git push origin main
```

Then on PythonAnywhere: `git pull` in the project folder and **Reload** the web app.
