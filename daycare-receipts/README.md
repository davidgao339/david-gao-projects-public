# Daycare Receipt Tracker

A local web app for tracking home daycare expenses. Upload a photo of a receipt
(Dollarama, Walmart, ...), the app reads it with OCR, pre-fills store / date / total,
and files it under a CRA-allowed home daycare expense category. Every entry stays
traceable to its receipt image, the purchase date on the receipt, and the upload time.

Expense categories are based on the CRA's official list for home daycare providers:
[Daycare in your home — Deducting your business expenses](https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/daycare-your-home/deducting-your-business-expenses.html)
(reported on Form T2125). You can add, rename, or hide categories in the app.

## One-time setup

1. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Install Tesseract OCR (used to read receipt photos locally — nothing is sent online):
   ```
   winget install UB-Mannheim.TesseractOCR
   ```
   If you skip this, the app still works — you just type the receipt details in yourself.

## Run

Double-click `run.bat` (or run `streamlit run app.py`). The app opens at
http://localhost:8501.

## Usage

- **New Entry** — upload one or more receipt photos (jpg/png/webp) at once. Each
  receipt gets its own review card with OCR-prefilled store, date, and total;
  review, pick a category, save, and move to the next. You can also create entries
  manually without a photo. Uploading the same image twice shows a duplicate warning.
- **Browse & Edit** — filter by category, date range, or vendor; edit entries inline
  (including re-categorizing) or mark them for deletion; view the stored receipt
  image for any entry.
- **Summary & Export** — totals per category for a date range (defaults to the
  current year), plus a CSV download for tax time.

## Where your data lives

Everything is stored in the `data\` folder next to the app:

- `data\receipts.db` — the expense entries (SQLite)
- `data\receipts\` — the receipt images, named by content hash

**Back up the `data\` folder and you've backed up everything.** It is excluded from git.

Tip: iPhone HEIC photos aren't supported directly — export/share them as JPG first
(or `pip install pillow-heif` and add a registration call if you want native support).
