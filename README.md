# PEAC Compliment Tracker

Run the website and API together from this folder (Python 3.10+):

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python peac.py
```

Open http://127.0.0.1:5000 in your browser. Flask serves `index.html`, `style.css`, and `script.js`; the page loads real weekly totals from `/api/compliments`. `python_example.py` is a standalone sample and is not needed.

On first run the backend creates `data/compliments.csv` with `week,count` columns. Add weekly records there (dates in YYYY-MM-DD format), or use POST `/api/compliments`, then refresh the page. Charts display the recorded totals. Grade breakdowns are not collected by this backend. Report notes stay in your browser's local storage.

Optional: install scikit-learn to enable additional forecasting models.

The notes form adds each submission to the selected date’s totals. For example, 100 verified compliments followed by 230 produces 330. Trash counts also accumulate separately and do not contribute to the verified dashboard total. Enter only new counts on each submission.

Use **Reset graph** at the bottom of the reports page to clear all saved verified and trash counts after confirmation. This resets dashboard totals for everyone; browser notes are kept.
