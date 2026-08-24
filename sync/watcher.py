import argparse, fnmatch, hashlib, json, os, sys, time
from pathlib import Path
import httpx
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

MANIFEST = Path.home() / ".brain-sync.json"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf", ".txt", ".md", ".xlsx", ".csv", ".docx"}

# Top-level folders under the sync root that are never books: internal
# folders (_*), Clair's own photo folders (Clair*, Claire*) and the casting
# workspace. Matched case-sensitively against the first path segment.
DEFAULT_EXCLUDES = ["_*", "Clair*", "casting"]


class UploadClient:
    def __init__(self, url, token):
        self.url, self.token = url.rstrip("/"), token

    def upload(self, book: str, path: Path) -> None:
        with path.open("rb") as f:
            r = httpx.post(f"{self.url}/upload", headers={"X-Brain-Token": self.token},
                           data={"book": book}, files={"file": (path.name, f)}, timeout=120)
        r.raise_for_status()


def _load():
    return json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {}


def _sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def is_excluded(top: str, patterns=None) -> bool:
    """True when a top-level folder name matches any exclude glob."""
    pats = DEFAULT_EXCLUDES if patterns is None else patterns
    return any(fnmatch.fnmatchcase(top, pat) for pat in pats)


def sync_once(root: Path, client, excludes=None) -> int:
    m = _load()
    n = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXTS or p.parent == root:
            continue
        if p.name.startswith(".") or p.name.startswith("~$"):
            continue
        if is_excluded(p.relative_to(root).parts[0], excludes):
            continue
        key, sha = str(p), _sha(p)
        if m.get(key) == sha:
            continue
        client.upload(p.parent.name, p)
        m[key] = sha
        n += 1
        print(f"↑ {p.parent.name}/{p.name}")
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8")
    return n


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    a = argparse.ArgumentParser()
    a.add_argument("--root", default=str(Path.home() / "Desktop" / "2ndBRAIN"))
    a.add_argument("--url", required=True)
    a.add_argument("--token", default=None)
    a.add_argument("--once", action="store_true")
    a.add_argument("--exclude", action="append", default=None,
                   help="glob for top-level folders to skip (repeatable); "
                        f"default: {' '.join(DEFAULT_EXCLUDES)}")
    ns = a.parse_args()
    token = ns.token or os.environ.get("BRAIN_TOKEN")
    if not token:
        a.error("--token or BRAIN_TOKEN env var is required")
    excludes = ns.exclude if ns.exclude else list(DEFAULT_EXCLUDES)
    root, client = Path(ns.root), UploadClient(ns.url, token)
    sync_once(root, client, excludes)
    if ns.once:
        return

    class H(FileSystemEventHandler):
        def on_any_event(self, e):
            time.sleep(2)
            sync_once(root, client, excludes)

    o = Observer()
    o.schedule(H(), str(root), recursive=True)
    o.start()
    print("brain-sync watching", root)
    try:
        while True:
            time.sleep(60)
    finally:
        o.stop()
        o.join()


if __name__ == "__main__":
    main()
