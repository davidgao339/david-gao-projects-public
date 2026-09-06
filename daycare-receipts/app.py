"""Local receipt tracker for home daycare expenses (CRA categories).

Run with: streamlit run app.py  (or run.bat)
"""

import hashlib
import sqlite3
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

import ocr

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RECEIPTS_DIR = DATA_DIR / "receipts"
DB_PATH = DATA_DIR / "receipts.db"

# Allowed home-daycare expense categories per CRA "Daycare in your home":
# https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/daycare-your-home/deducting-your-business-expenses.html
SEED_CATEGORIES = [
    "Food & beverages for children",
    "Toys, books, arts & crafts",
    "Household supplies (diapers, cleaning, blankets)",
    "Field trips",
    "Office stationery & supplies",
    "Motor vehicle expenses",
    "Advertising",
    "Insurance",
    "Business-use-of-home",
    "Capital items (furniture, equipment)",
    "Salaries & wages",
    "Other",
]


# ---------------------------------------------------------------- database

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id         INTEGER PRIMARY KEY,
                name       TEXT NOT NULL UNIQUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                active     INTEGER NOT NULL DEFAULT 1
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id            INTEGER PRIMARY KEY,
                vendor        TEXT NOT NULL DEFAULT '',
                purchase_date TEXT,
                total_cents   INTEGER NOT NULL,
                category_id   INTEGER NOT NULL REFERENCES categories(id),
                notes         TEXT NOT NULL DEFAULT '',
                image_sha256  TEXT,
                image_path    TEXT,
                uploaded_at   TEXT,
                ocr_text      TEXT,
                created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at    TEXT
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(purchase_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_cat ON entries(category_id)")
        for i, name in enumerate(SEED_CATEGORIES):
            conn.execute(
                "INSERT OR IGNORE INTO categories(name, sort_order) VALUES (?, ?)", (name, i)
            )


def load_categories(active_only=True):
    with get_conn() as conn:
        where = "WHERE active = 1" if active_only else ""
        return pd.read_sql(
            f"SELECT id, name, active FROM categories {where} ORDER BY sort_order, name", conn
        )


def insert_entry(vendor, purchase_date, total_cents, category_id, notes,
                 image_sha256=None, image_path=None, uploaded_at=None, ocr_text=None):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO entries
               (vendor, purchase_date, total_cents, category_id, notes,
                image_sha256, image_path, uploaded_at, ocr_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vendor, purchase_date, total_cents, category_id, notes,
             image_sha256, image_path, uploaded_at, ocr_text),
        )
        return cur.lastrowid


def load_entries(category_ids=None, start=None, end=None, vendor_search=""):
    query = """
        SELECT e.id, e.purchase_date, e.vendor, e.total_cents, c.name AS category,
               e.notes, e.image_path, e.uploaded_at, e.ocr_text
        FROM entries e JOIN categories c ON c.id = e.category_id
        WHERE 1=1
    """
    params = []
    if category_ids:
        query += f" AND e.category_id IN ({','.join('?' * len(category_ids))})"
        params.extend(category_ids)
    if start:
        query += " AND e.purchase_date >= ?"
        params.append(start.isoformat())
    if end:
        query += " AND e.purchase_date <= ?"
        params.append(end.isoformat())
    if vendor_search:
        query += " AND e.vendor LIKE ?"
        params.append(f"%{vendor_search}%")
    query += " ORDER BY e.purchase_date DESC, e.id DESC"
    with get_conn() as conn:
        return pd.read_sql(query, conn, params=params)


@st.cache_resource
def tesseract_path():
    return ocr.find_tesseract()


def upright_image_bytes(image_bytes, ext, rotation=0):
    """Apply the EXIF orientation tag plus a manual rotation (degrees clockwise).

    Phone cameras store rotation as an EXIF tag instead of rotating the pixels;
    Streamlit strips that tag when displaying, so we bake the rotation into the
    pixels. Returns the original bytes untouched when no correction is needed.
    """
    img = Image.open(BytesIO(image_bytes))
    exif_orientation = img.getexif().get(0x0112, 1)
    if exif_orientation == 1 and rotation == 0:
        return image_bytes
    img = ImageOps.exif_transpose(img)
    if rotation:
        img = img.rotate(-rotation, expand=True)
    fmt = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}.get(ext, "PNG")
    if fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def reocr(cache, sha, image_bytes):
    """Re-run OCR (e.g. after a manual rotation) and refresh the cached parse."""
    with st.spinner("Re-reading receipt..."):
        text = ocr.extract_text(image_bytes)
    cache[sha] = {"text": text, "parsed": ocr.parse_receipt(text)}


# ---------------------------------------------------------------- UI helpers

def entry_form(prefill, categories, file_info, form_key="entry_form"):
    """Render the entry form; save on submit. `file_info` is None for manual entry.

    Returns the new entry id when saved, else None.
    """
    cat_names = categories["name"].tolist()
    default_cat = prefill.get("category") or "Other"
    cat_index = cat_names.index(default_cat) if default_cat in cat_names else len(cat_names) - 1

    with st.form(form_key, clear_on_submit=True):
        vendor = st.text_input("Store / vendor", value=prefill.get("vendor") or "")
        purchase_date = st.date_input("Purchase date (on receipt)",
                                      value=prefill.get("date") or date.today())
        total = st.number_input("Total ($)", min_value=0.0, step=0.01, format="%.2f",
                                value=prefill.get("total") or 0.0)
        category_name = st.selectbox("Category", cat_names, index=cat_index)
        notes = st.text_input("Notes (optional)")
        submitted = st.form_submit_button("Save entry", type="primary")

    if not submitted:
        return None
    if total <= 0:
        st.error("Total must be greater than $0.00.")
        return None

    category_id = int(categories.loc[categories["name"] == category_name, "id"].iloc[0])
    kwargs = {}
    if file_info:
        image_file = RECEIPTS_DIR / f"{file_info['sha']}.{file_info['ext']}"
        if not image_file.exists():
            image_file.write_bytes(file_info["bytes"])
        kwargs = {
            "image_sha256": file_info["sha"],
            "image_path": f"receipts/{image_file.name}",
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "ocr_text": file_info["ocr_text"],
        }
    entry_id = insert_entry(vendor.strip(), purchase_date.isoformat(),
                            round(total * 100), category_id, notes.strip(), **kwargs)
    st.success(f"Saved entry #{entry_id}: {vendor or '(no vendor)'} — "
               f"${total:.2f} — {category_name}")
    return entry_id


def new_entry_tab():
    categories = load_categories(active_only=True)

    if tesseract_path() is None:
        st.info(
            "**Tesseract OCR is not installed** — receipt text won't be read "
            "automatically, but you can still fill in entries manually.\n\n"
            "To enable OCR, run `winget install UB-Mannheim.TesseractOCR` "
            "in a terminal, then restart this app."
        )

    # The uploader is keyed by a generation counter: bumping it after a finished
    # batch clears the widget so the next batch can be uploaded without
    # removing the old files one by one.
    gen = st.session_state.setdefault("uploader_gen", 0)
    uploads = st.file_uploader("Upload one or more receipt photos",
                               type=["jpg", "jpeg", "png", "webp"],
                               accept_multiple_files=True,
                               key=f"uploader_{gen}")
    if not uploads:
        if st.session_state.get("last_batch_msg"):
            st.success(st.session_state["last_batch_msg"])
        st.caption("No receipts uploaded — you can also create an entry manually.")
        entry_form({}, categories, None, form_key="manual_entry")
        return
    st.session_state.pop("last_batch_msg", None)

    cache = st.session_state.setdefault("ocr_cache", {})
    saved = st.session_state.setdefault("batch_saved", {})
    files = [(f, hashlib.sha256(f.getvalue()).hexdigest()) for f in uploads]
    pending = sum(1 for _, sha in files if sha not in saved)
    if len(files) > 1:
        st.caption(f"{len(files)} receipts uploaded — {pending} left to review. "
                   "Save each one below.")

    if pending == 0:
        n = len({sha for _, sha in files})
        ids = ", ".join(f"#{i}" for i in dict.fromkeys(
            saved[sha] for _, sha in files))
        st.session_state["last_batch_msg"] = (
            f"All {n} receipt{'s' if n != 1 else ''} saved (entr"
            f"{'ies' if n != 1 else 'y'} {ids}). Ready for the next batch."
        )
        st.session_state["uploader_gen"] = gen + 1
        st.session_state["batch_saved"] = {}
        st.rerun()

    for i, (uploaded, sha) in enumerate(files):
        image_bytes = uploaded.getvalue()
        ext = uploaded.name.rsplit(".", 1)[-1].lower()

        if sha not in cache:
            with st.spinner(f"Reading {uploaded.name}..."):
                text = ocr.extract_text(image_bytes)
            cache[sha] = {"text": text, "parsed": ocr.parse_receipt(text)}
        text, parsed = cache[sha]["text"], cache[sha]["parsed"]
        total_cents = parsed["total_cents"]

        summary = " · ".join(str(x) for x in (
            parsed["vendor"], parsed["date"],
            f"${total_cents / 100:.2f}" if total_cents is not None else None,
        ) if x)
        label = uploaded.name + (f" — {summary}" if summary else "")
        if sha in saved:
            label = f"✅ {label} (saved as entry #{saved[sha]})"

        with st.expander(label, expanded=sha not in saved):
            if sha in saved:
                st.success(f"Saved as entry #{saved[sha]}.")
                continue

            with get_conn() as conn:
                dup = conn.execute(
                    "SELECT id, created_at FROM entries WHERE image_sha256 = ?", (sha,)
                ).fetchone()
            if dup:
                st.warning(f"This exact image was already saved as entry #{dup[0]} "
                           f"on {dup[1]}. You can still save it again if intended.")

            rotations = st.session_state.setdefault("rotations", {})
            rotation = rotations.get(sha, 0)
            display_bytes = upright_image_bytes(image_bytes, ext, rotation)

            # Saved image is the upright version; sha stays that of the original
            # upload so re-uploading the same photo is still detected as a duplicate.
            file_info = {"sha": sha, "ext": ext, "bytes": display_bytes, "ocr_text": text}
            prefill = {
                "vendor": parsed["vendor"],
                "date": parsed["date"],
                "total": total_cents / 100 if total_cents is not None else None,
            }

            left, right = st.columns([1, 1])
            with left:
                st.image(display_bytes, caption=uploaded.name, use_container_width=True)
                b1, b2, b3 = st.columns([1, 1, 2])
                if b1.button("⟲", key=f"rot_l_{i}_{sha[:8]}", help="Rotate left"):
                    rotations[sha] = (rotation - 90) % 360
                    reocr(cache, sha, upright_image_bytes(image_bytes, ext, rotations[sha]))
                    st.rerun()
                if b2.button("⟳", key=f"rot_r_{i}_{sha[:8]}", help="Rotate right"):
                    rotations[sha] = (rotation + 90) % 360
                    reocr(cache, sha, upright_image_bytes(image_bytes, ext, rotations[sha]))
                    st.rerun()
                with b3.popover("Raw OCR text"):
                    st.text(text or "(no text extracted)")
            with right:
                st.caption("Review the extracted details, fix anything wrong, then save.")
                entry_id = entry_form(prefill, categories, file_info,
                                      form_key=f"entry_{i}_{sha[:12]}")
                if entry_id:
                    saved[sha] = entry_id
                    st.rerun()


def browse_tab():
    categories = load_categories(active_only=False)

    f1, f2, f3 = st.columns([2, 2, 1])
    with f1:
        selected_cats = st.multiselect("Category", categories["name"].tolist())
    with f2:
        date_range = st.date_input(
            "Purchase date range",
            value=(date(date.today().year, 1, 1), date.today()),
        )
    with f3:
        vendor_search = st.text_input("Vendor contains")

    start, end = (date_range if isinstance(date_range, tuple) and len(date_range) == 2
                  else (None, None))
    category_ids = categories.loc[
        categories["name"].isin(selected_cats), "id"].tolist() if selected_cats else None

    df = load_entries(category_ids, start, end, vendor_search.strip())
    if df.empty:
        st.info("No entries match these filters.")
        return

    display = df[["id", "purchase_date", "vendor", "total_cents",
                  "category", "notes", "uploaded_at"]].copy()
    display["purchase_date"] = pd.to_datetime(display["purchase_date"]).dt.date
    display["total"] = display.pop("total_cents") / 100
    display["delete"] = False
    display = display[["id", "purchase_date", "vendor", "total",
                       "category", "notes", "uploaded_at", "delete"]]

    edited = st.data_editor(
        display,
        hide_index=True,
        num_rows="fixed",
        disabled=["id", "uploaded_at"],
        column_config={
            "id": st.column_config.NumberColumn("ID"),
            "purchase_date": st.column_config.DateColumn("Purchase date"),
            "vendor": st.column_config.TextColumn("Vendor"),
            "total": st.column_config.NumberColumn("Total", format="$%.2f",
                                                   min_value=0.0, step=0.01),
            "category": st.column_config.SelectboxColumn(
                "Category", options=categories["name"].tolist(), required=True),
            "notes": st.column_config.TextColumn("Notes"),
            "uploaded_at": st.column_config.TextColumn("Uploaded"),
            "delete": st.column_config.CheckboxColumn("Delete?"),
        },
        key="entries_editor",
    )

    if st.button("Save changes", type="primary"):
        cat_ids = dict(zip(categories["name"], categories["id"]))
        now = datetime.now().isoformat(timespec="seconds")
        updates = deletes = 0
        with get_conn() as conn:
            for (_, orig), (_, new) in zip(display.iterrows(), edited.iterrows()):
                entry_id = int(orig["id"])
                if new["delete"]:
                    conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
                    deletes += 1
                    continue
                changed = (orig[["purchase_date", "vendor", "total", "category", "notes"]]
                           .tolist() !=
                           new[["purchase_date", "vendor", "total", "category", "notes"]]
                           .tolist())
                if changed:
                    pdate = new["purchase_date"]
                    conn.execute(
                        """UPDATE entries SET vendor=?, purchase_date=?, total_cents=?,
                           category_id=?, notes=?, updated_at=? WHERE id=?""",
                        (str(new["vendor"] or "").strip(),
                         pdate.isoformat() if pd.notna(pdate) else None,
                         round(float(new["total"]) * 100),
                         int(cat_ids[new["category"]]),
                         str(new["notes"] or "").strip(),
                         now, entry_id),
                    )
                    updates += 1
        st.session_state.pop("entries_editor", None)
        st.success(f"Updated {updates} and deleted {deletes} entries.")
        st.rerun()

    with_images = df[df["image_path"].notna()]
    if not with_images.empty:
        st.divider()
        options = {
            f"#{row.id} — {row.vendor or '(no vendor)'} — {row.purchase_date} — "
            f"${row.total_cents / 100:.2f}": row
            for row in with_images.itertuples()
        }
        choice = st.selectbox("View receipt for entry", list(options))
        row = options[choice]
        image_file = DATA_DIR / row.image_path
        if image_file.exists():
            img = ImageOps.exif_transpose(Image.open(image_file))
            st.image(img, width=450,
                     caption=f"Entry #{row.id} — uploaded {row.uploaded_at}")
        else:
            st.error(f"Image file missing: {image_file}")
        if row.ocr_text:
            with st.expander("Raw OCR text for this receipt"):
                st.text(row.ocr_text)


def summary_tab():
    c1, c2 = st.columns(2)
    with c1:
        start = st.date_input("From", value=date(date.today().year, 1, 1), key="sum_start")
    with c2:
        end = st.date_input("To", value=date.today(), key="sum_end")

    df = load_entries(start=start, end=end)
    if df.empty:
        st.info("No entries in this date range.")
    else:
        df["total"] = df["total_cents"] / 100
        by_cat = (df.groupby("category", as_index=False)["total"].sum()
                  .sort_values("total", ascending=False))
        st.metric("Grand total", f"${df['total'].sum():,.2f}",
                  help=f"{len(df)} entries from {start} to {end}")
        st.bar_chart(by_cat.set_index("category")["total"])
        st.dataframe(
            by_cat, hide_index=True,
            column_config={"total": st.column_config.NumberColumn("Total", format="$%.2f")},
        )

        export = df[["id", "purchase_date", "vendor", "category",
                     "total", "notes", "image_path", "uploaded_at"]].copy()
        export = export.rename(columns={"image_path": "image_file"})
        export = export.sort_values(["purchase_date", "id"])
        st.download_button(
            "Download CSV",
            export.to_csv(index=False),
            file_name=f"daycare_expenses_{start}_{end}.csv",
            mime="text/csv",
        )

    st.divider()
    with st.expander("Manage categories"):
        categories = load_categories(active_only=False)
        st.caption(
            "Based on CRA-allowed home daycare expenses: "
            "[Deducting your business expenses]"
            "(https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/"
            "daycare-your-home/deducting-your-business-expenses.html)"
        )

        new_name = st.text_input("Add category")
        if st.button("Add") and new_name.strip():
            with get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO categories(name, sort_order) VALUES (?, ?)",
                    (new_name.strip(), len(categories)),
                )
            st.rerun()

        r1, r2 = st.columns(2)
        with r1:
            rename_from = st.selectbox("Rename category", categories["name"].tolist())
        with r2:
            rename_to = st.text_input("New name")
        if st.button("Rename") and rename_to.strip():
            with get_conn() as conn:
                conn.execute("UPDATE categories SET name = ? WHERE name = ?",
                             (rename_to.strip(), rename_from))
            st.rerun()

        toggle_name = st.selectbox(
            "Show / hide category",
            [f"{row.name} ({'active' if row.active else 'hidden'})"
             for row in categories.itertuples()],
        )
        if st.button("Toggle active"):
            name = toggle_name.rsplit(" (", 1)[0]
            with get_conn() as conn:
                conn.execute("UPDATE categories SET active = 1 - active WHERE name = ?",
                             (name,))
            st.rerun()


# ---------------------------------------------------------------- main

st.set_page_config(page_title="Daycare Receipts", page_icon="🧾", layout="wide")
init_db()
st.title("🧾 Daycare Receipt Tracker")

tab_new, tab_browse, tab_summary = st.tabs(["New Entry", "Browse & Edit", "Summary & Export"])
with tab_new:
    new_entry_tab()
with tab_browse:
    browse_tab()
with tab_summary:
    summary_tab()
