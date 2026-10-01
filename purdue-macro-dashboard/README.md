# Macro Facts: Purdue Dining

A dashboard that ranks Purdue's dining courts by how macro-friendly each meal is.
A GitHub Action pulls the menus and nutrition from Purdue Dining's public menu
feed every morning and republishes the page on GitHub Pages.

## Setup (about 10 minutes, one time)

1. Create a new **public** repository on GitHub (Pages is free for public repos).
2. Upload everything in this folder, keeping the `.github/workflows` folder.
   On the web: "Add file" > "Upload files", then drag the folder contents in.
   (Hidden `.github` folders sometimes get skipped by drag-and-drop; if so, create
   `.github/workflows/update.yml` with "Add file" > "Create new file" and paste it in.)
3. Go to **Settings > Pages** and set **Source** to **GitHub Actions**.
4. Go to **Actions**, click **Update dining data**, then **Run workflow**.
5. When it finishes (about 1–2 minutes), your dashboard is at
   `https://<your-username>.github.io/<repo-name>/`.

After that it updates on its own every morning, plus a midday refresh.

## Tuning the targets

All thresholds are in the `RULES` block at the top of `scripts/build_data.py`
(calories per gram of protein/carbs, minimum grams per serving, sodium and sugar limits).
Edit the numbers on GitHub and commit; the page rebuilds automatically.

## Good to know

- GitHub pauses scheduled workflows in repos with no activity for 60 days.
  If that happens you'll get an email; click "Enable workflow" in the Actions tab.
- Scheduled runs can start a little late when GitHub is busy.
- If a run fails (for example, Purdue's feed is down), GitHub emails you and the
  previous day's page stays up.

## Run locally

    python3 scripts/build_data.py --out site/data.json
    cp web/index.html site/
    cd site && python3 -m http.server 8000   # open http://localhost:8000
