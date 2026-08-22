import argparse, hashlib, json, time
from pathlib import Path
import httpx
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

MANIFEST = Path.home() / ".brain-sync.json"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf", ".txt", ".md"}


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


def sync_once(root: Path, client) -> int:
    m = _load()
    n = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXTS or p.parent == root:
            continue
        if p.name.startswith(".") or p.name.startswith("~$"):
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
    a = argparse.ArgumentParser()
    a.add_argument("--root", default=str(Path.home() / "Desktop" / "2ndBRAIN"))
    a.add_argument("--url", required=True)
    a.add_argument("--token", required=True)
    a.add_argument("--once", action="store_true")
    ns = a.parse_args()
    root, client = Path(ns.root), UploadClient(ns.url, ns.token)
    sync_once(root, client)
    if ns.once:
        return

    class H(FileSystemEventHandler):
        def on_any_event(self, e):
            time.sleep(2)
            sync_once(root, client)

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
