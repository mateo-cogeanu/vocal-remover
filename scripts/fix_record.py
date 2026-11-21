"""Re-hash bundled native extensions in their dist-info RECORD.

PyInstaller re-signs every .so it bundles, which changes the bytes. mlx-audio-io
refuses to load if its extension no longer matches the hash pip recorded, so
we record the hash of the file as it now ships.
"""
import base64
import csv
import hashlib
import io
import sys
from pathlib import Path

app = Path(sys.argv[1])
res, fw = app / "Contents" / "Resources", app / "Contents" / "Frameworks"
for record in res.glob("*.dist-info/RECORD"):
    rows = list(csv.reader(io.StringIO(record.read_text())))
    changed = False
    for row in rows:
        if len(row) >= 2 and row[0].endswith((".so", ".dylib")) and row[1].startswith("sha256="):
            f = next((p for p in (fw / row[0], res / row[0]) if p.exists()), None)
            if f is None:
                continue
            h = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(f.read_bytes()).digest()).decode().rstrip("=")
            if h != row[1]:
                row[1], row[2] = h, str(f.stat().st_size)
                changed = True
    if changed:
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerows(rows)
        record.unlink()  # may be a symlink into Frameworks; replace with a real file
        record.write_text(out.getvalue())
        print(f"updated {record.parent.name}")
