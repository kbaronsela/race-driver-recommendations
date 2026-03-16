# Deploy to PythonAnywhere (free)

Follow these steps to make your site available at **https://racedriver.pythonanywhere.com**.

## 1. Create an account

- Go to [pythonanywhere.com](https://www.pythonanywhere.com) and sign up for a **Beginner (free)** account (e.g. username **racedriver**).

## 2. Push your code to GitHub (if not already)

- Create a repo on GitHub (e.g. **race-driver-recommendations**) and push this project.
- **Include:** `data/`, `assets/`, `server.py`, `wsgi.py`, `index.html`, `requirements.txt`, `set_password.py`, `config.json.example`, `scripts/` (optional).
- **Do not** commit `config.json` (it’s in `.gitignore`). Set the login on PythonAnywhere with environment variables (step 6).

## 3. Clone the repo on PythonAnywhere

- Open the **Consoles** tab and start a **Bash** console.
- Run (use your actual GitHub repo URL):

```bash
cd ~
git clone https://github.com/YOUR_GITHUB_USERNAME/race-driver-recommendations.git
cd race-driver-recommendations
```

Example: if the repo is `https://github.com/kbaronsela/race-driver-recommendations.git`, use that URL.

## 4. Create a virtualenv and install dependencies

In the same Bash console:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Create the Web app

- Go to the **Web** tab.
- Click **Add a new web app** → Next → **Flask** → Next.
- Choose **Python 3.10** (or the version that matches your venv).
- **Project directory:** `/home/racedriver/race-driver-recommendations`
- **WSGI configuration file:** click the link and replace the file with:

```python
import sys
path = '/home/racedriver/race-driver-recommendations'
if path not in sys.path:
    sys.path.insert(0, path)

from server import app as application
```

- **Virtualenv:** `/home/racedriver/race-driver-recommendations/venv`
- Click the green **Reload** button for your web app.

## 6. Set your login (user + password)

You have two options.

**Option A – Environment variables (recommended)**  
- In the **Web** tab, find **Code** → **Environment variables** (or the section where you can add variables).  
- Add:
  - `PYTHONANYWHERE_USER` = your chosen login username  
  - `PYTHONANYWHERE_PASSWORD` = your chosen login password  

Then click **Reload** again.

**Option B – config.json**  
- In the Bash console, from the project directory, run:
  - `python set_password.py`
- Follow the script to create `config.json` with your user and password.  
- Reload the web app.

## 7. Ensure data and assets are present

- In the project folder on PythonAnywhere you must have:
  - `data/entries.json`
  - `data/fields.json`
  - `assets/` (with your logos)
- If you cloned from Git, they should already be there. If you created the repo without `data/` (e.g. for privacy), upload or recreate them in the same structure.

## 8. Open your site

- Your site will be at: **https://racedriver.pythonanywhere.com**
- Open it in a browser; you should see the main page and be able to log in with the user/password you set in step 6.

## Updating after changes

In a Bash console:

```bash
cd ~/race-driver-recommendations
git pull
source venv/bin/activate
pip install -r requirements.txt   # only if requirements changed
```

Then in the **Web** tab click **Reload** for your web app.

## Troubleshooting

- **502 Bad Gateway:** Check the **Web** tab → **Error log**. Often the cause is a wrong path, wrong virtualenv, or missing dependency; fix and Reload.
- **Static files (logos, CSS) not loading:** The app serves `index.html` and `/data/` and uses Flask’s static handling for files in the project directory; if something is missing, check that the path in the Web app points to the project that contains `index.html` and `assets/`.
- **Login not working:** Ensure `PYTHONANYWHERE_USER` and `PYTHONANYWHERE_PASSWORD` are set (and Reload was clicked) or that `config.json` exists and is readable by the app.
