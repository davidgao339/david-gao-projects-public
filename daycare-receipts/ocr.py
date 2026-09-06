"""OCR and receipt parsing for the daycare receipt tracker.

Importable without Streamlit. Run standalone to tune the parser:
    python ocr.py path\\to\\receipt.jpg
"""

import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from io import BytesIO

from PIL import Image, ImageFilter, ImageOps

try:
    import pytesseract
except ImportError:
    pytesseract = None

# Known Canadian stores: OCR-text keyword -> canonical vendor name.
KNOWN_STORES = {
    "dollarama": "Dollarama",
    "walmart": "Walmart",
    "wal-mart": "Walmart",
    "costco": "Costco",
    "superstore": "Real Canadian Superstore",
    "no frills": "No Frills",
    "nofrills": "No Frills",
    "frills": "No Frills",  # OCR often misreads "NO" (e.g. "N0")
    "shoppers drug": "Shoppers Drug Mart",
    "canadian tire": "Canadian Tire",
    "sobeys": "Sobeys",
    "metro": "Metro",
    "loblaws": "Loblaws",
    "freshco": "FreshCo",
    "food basics": "Food Basics",
    "giant tiger": "Giant Tiger",
    "michaels": "Michaels",
    "staples": "Staples",
    "winners": "Winners",
    "dollar tree": "Dollar Tree",
    "home depot": "Home Depot",
    "amazon": "Amazon",
    "indigo": "Indigo",
    "ikea": "IKEA",
    "toys r us": "Toys R Us",
    "toysrus": "Toys R Us",
}

WINDOWS_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]


def find_tesseract():
    """Locate the tesseract binary. Returns its path, or None if not installed."""
    if pytesseract is None:
        return None
    found = shutil.which("tesseract")
    if not found:
        for candidate in WINDOWS_TESSERACT_PATHS:
            if os.path.isfile(candidate):
                found = candidate
                break
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
    return found


def preprocess(img):
    """Light cleanup for phone photos of thermal receipts."""
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    longest = max(img.size)
    if longest < 1500:
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    elif longest > 4000:
        scale = 4000 / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.MedianFilter(3))
    return img


def extract_text(image_bytes):
    """OCR an image (raw bytes). Returns raw text, or '' on any failure."""
    if find_tesseract() is None:
        return ""
    try:
        img = preprocess(Image.open(BytesIO(image_bytes)))
        text = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
        if len(text.strip()) < 20:
            text = pytesseract.image_to_string(img, lang="eng")
        return text
    except Exception:
        return ""


MONEY_RE = re.compile(r"\$?\s*(\d{1,5})[.,](\d{2})\b")
# Lines that contain "total" but are not the grand total.
NOT_GRAND_TOTAL_RE = re.compile(
    r"(?i)sub\s*-?\s*total|total\s+(savings|tax|items?|discount|points|qty)"
)

MONTHS = {m.lower(): i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
)}
DATE_ISO_RE = re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})")
DATE_MONTHNAME_RE = re.compile(
    r"(\d{1,2})[ \-/]?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[ \-/,.]+(\d{2,4})"
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[ \-/,.]+(\d{1,2})[ \-/,.]+(\d{2,4})",
    re.IGNORECASE,
)
DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b")


def _plausible(d):
    return d is not None and 2015 <= d.year and d <= date.today() + timedelta(days=1)


def _make_date(year, month, day):
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_total(text):
    """Grand total in cents, or None."""
    candidates = []
    for line in text.splitlines():
        if re.search(r"(?i)\btotal\b", line) and not NOT_GRAND_TOTAL_RE.search(line):
            amounts = MONEY_RE.findall(line)
            if amounts:
                dollars, cents = amounts[-1]
                candidates.append(int(dollars) * 100 + int(cents))
    if candidates:
        return candidates[-1]  # grand total prints below subtotal
    all_amounts = [int(d) * 100 + int(c) for d, c in MONEY_RE.findall(text)]
    return max(all_amounts) if all_amounts else None


def parse_date(text):
    """Purchase date, or None."""
    for m in DATE_ISO_RE.finditer(text):
        d = _make_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if _plausible(d):
            return d
    for m in DATE_MONTHNAME_RE.finditer(text):
        if m.group(1):  # "05 Jan 2026"
            day, mon, year = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
        else:  # "Jan 5, 2026"
            mon, day, year = MONTHS[m.group(4).lower()], int(m.group(5)), int(m.group(6))
        d = _make_date(year, mon, day)
        if _plausible(d):
            return d
    for m in DATE_NUMERIC_RE.finditer(text):
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            month, day = b, a
        else:  # MM/DD is what most Canadian POS systems print
            month, day = a, b
        d = _make_date(year, month, day)
        if _plausible(d):
            return d
    return None


def parse_vendor(text):
    """Store name, or None."""
    lowered = text.lower()
    for keyword, name in KNOWN_STORES.items():
        if keyword in lowered:
            return name
    for line in text.splitlines():
        stripped = line.strip()
        if sum(ch.isalpha() for ch in stripped) >= 3:
            return stripped.title()[:40]
    return None


def parse_receipt(text):
    """Parse raw OCR text into {vendor, date, total_cents}; every value may be None."""
    if not text or not text.strip():
        return {"vendor": None, "date": None, "total_cents": None}
    return {
        "vendor": parse_vendor(text),
        "date": parse_date(text),
        "total_cents": parse_total(text),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python ocr.py <receipt-image>")
        sys.exit(1)
    print(f"tesseract: {find_tesseract() or 'NOT FOUND'}")
    with open(sys.argv[1], "rb") as f:
        raw = extract_text(f.read())
    print("---- raw OCR text ----")
    print(raw)
    print("---- parsed ----")
    parsed = parse_receipt(raw)
    print(f"vendor: {parsed['vendor']}")
    print(f"date:   {parsed['date']}")
    total = parsed["total_cents"]
    print(f"total:  {'$%.2f' % (total / 100) if total is not None else None}")
