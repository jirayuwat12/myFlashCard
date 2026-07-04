"""Extract the Chinese–Thai vocabulary table from data/raw_pdf.pdf into JSON,
plus a PNG crop of each entry's rows so the extraction can be rechecked by eye.

No OCR: the PDF has a real text layer (embedded ToUnicode maps), so pdfplumber
reads the bordered table's cells directly. See the plan for why.
"""

import json
import re
from pathlib import Path

import pdfplumber

PDF = Path("data/raw_pdf.pdf")
OUT = Path("data/flashcards.json")
CROP_DIR = Path("data/crops")
NCOLS = 6  # no | 【word】 | pinyin | POS | Thai meaning | Chinese example
RES = 150  # crop render DPI
PAD = 4    # px padding around each crop

# Thai combining marks: U+0E31, U+0E34–U+0E3A, U+0E47–U+0E4E
COMB = "ัิ-ฺ็-๎"


def clean(t: str) -> str:
    """Fix pdfminer's Thai spacing/order artifacts and collapse whitespace."""
    if not t:
        return ""
    t = t.replace("\n", " ")
    t = re.sub(rf"\s+([{COMB}])", r"\1", t)  # drop stray space before a combining mark
    t = re.sub(rf"\.([{COMB}])", r"\1.", t)  # mark misplaced after '.' -> before it
    return re.sub(r"\s+", " ", t).strip()


def is_empty(c) -> bool:
    return not (c or "").strip()


def extract() -> list[dict]:
    # Pull every table row with its text, source page, and bounding box.
    rows: list[tuple] = []  # (cells, page_number, row_bbox)
    with pdfplumber.open(PDF) as pdf:
        for page in pdf.pages:
            for table in page.find_tables():
                cells = table.extract()
                for r, geom in zip(cells, table.rows):
                    if len(r) != NCOLS:
                        continue
                    if r[0] and "序号" in r[0]:  # column header row
                        continue
                    rows.append((r, page.page_number, geom.bbox))

    # Merged no/word/pinyin cells are empty on continuation rows (None or "").
    # Forward-fill across the whole stream — a single entry's senses can span a
    # page boundary, so filling must not reset per page.
    last_no = last_word = last_pin = None
    entries: list[dict] = []
    for (no, word, pin, pos, mean, ex), page_no, bbox in rows:
        if is_empty(no):
            no = last_no
        else:
            last_no = no
        if is_empty(word):
            word = last_word
        else:
            last_word = word
        if is_empty(pin):
            pin = last_pin
        else:
            last_pin = pin

        if not (no or "").strip().isdigit():
            continue  # junk before the first numbered entry

        sense = {
            "pos": clean(pos),
            "meaning_th": clean(mean),
            "examples": [clean(x) for x in (ex or "").split("\n") if x.strip()],
        }
        if entries and entries[-1]["no"] == int(no):
            entries[-1]["senses"].append(sense)
            entries[-1]["_boxes"].append((page_no, bbox))
        else:
            entries.append(
                {
                    "no": int(no),
                    "word": re.sub(r"[【】]", "", word or "").strip(),
                    "pinyin": (pin or "").strip(),
                    "page": page_no,
                    "senses": [sense],
                    "_boxes": [(page_no, bbox)],  # dropped after cropping
                }
            )
    return entries


def crop_entries(entries: list[dict]) -> None:
    """Save one PNG per entry (per page-segment) and set entry["images"]."""
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    scale = RES / 72.0

    # Assign filenames and index the crops needed on each page.
    by_page: dict[int, list[tuple[str, tuple]]] = {}  # page -> [(filename, pdf_bbox)]
    for e in entries:
        # group this entry's row boxes by page, preserving order
        segments: dict[int, list[tuple]] = {}
        for page_no, bbox in e.pop("_boxes"):
            segments.setdefault(page_no, []).append(bbox)
        images = []
        for i, (page_no, boxes) in enumerate(segments.items()):
            name = f"{e['no']:04d}.png" if i == 0 else f"{e['no']:04d}_{i + 1}.png"
            x0 = min(b[0] for b in boxes)
            top = min(b[1] for b in boxes)
            x1 = max(b[2] for b in boxes)
            bottom = max(b[3] for b in boxes)
            by_page.setdefault(page_no, []).append((name, (x0, top, x1, bottom)))
            images.append(f"{CROP_DIR.name}/{name}")
        e["images"] = images

    # Render each page once, then cut out every crop it holds.
    with pdfplumber.open(PDF) as pdf:
        for page_no, crops in by_page.items():
            im = pdf.pages[page_no - 1].to_image(resolution=RES).original
            W, H = im.size
            for name, (x0, top, x1, bottom) in crops:
                box = (
                    max(0, round(x0 * scale) - PAD),
                    max(0, round(top * scale) - PAD),
                    min(W, round(x1 * scale) + PAD),
                    min(H, round(bottom * scale) + PAD),
                )
                im.crop(box).save(CROP_DIR / name)


if __name__ == "__main__":
    entries = extract()
    crop_entries(entries)

    # Self-check: guards the merge/group + crop logic against a column/border shift.
    assert entries, "no entries extracted"
    assert all(e["word"] and e["pinyin"] for e in entries), "entry missing word/pinyin"
    nos = [e["no"] for e in entries]
    assert nos == sorted(nos) and len(nos) == len(set(nos)), "no not strictly increasing"
    by_no = {e["no"]: e for e in entries}
    assert len(by_no[15]["senses"]) == 3, f"的 should have 3 senses: {by_no[15]}"
    assert len(by_no[22]["senses"][0]["examples"]) == 2, f"读 should have 2 examples: {by_no[22]}"
    assert all(e["images"] for e in entries), "entry missing crop image"
    p15 = CROP_DIR / "0015.png"
    assert p15.exists() and p15.stat().st_size > 0, f"missing crop {p15}"

    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    n_crops = sum(len(e["images"]) for e in entries)
    print(f"wrote {len(entries)} entries (no 1..{nos[-1]}), {n_crops} crops -> {OUT}")
