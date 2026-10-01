# Macro Facts: Purdue Dining

Ranks Purdue's dining courts by how macro-friendly each meal is. A GitHub Action
pulls menus and nutrition every morning and republishes the page on GitHub Pages.

Files at the top level of the repo: `build_data.py`, `index.html`, `README.md`,
plus `.github/workflows/update.yml`.

Edit your targets in the `RULES` block at the top of `build_data.py`.
GitHub pauses scheduled workflows after 60 days with no repo activity; if you get
an email about it, click "Enable workflow" in the Actions tab.
