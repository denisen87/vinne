import os
import time
import hashlib
from pathlib import Path
import requests

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIR = Path(r"C:\Users\denis\AppData\Local\Betsolid Poker\data\angryshark\History\Data")
API_URL = os.getenv("BETSOLID_IMPORT_URL", "http://127.0.0.1:8010/import/betsolid")

# Enkel debounce: ikke importer samme uendrede fil for ofte
LAST_SENT: dict[str, tuple[float, str]] = {}
MIN_SECONDS_BETWEEN = 2.0

HERO_NAME = "angryshark"


def normal_card(card: str) -> str:
    raw = str(card or "").strip().upper()
    if len(raw) < 2:
        return ""
    suit_first = raw[0] in {"S", "H", "D", "C"}
    if suit_first:
        return raw[1:].replace("10", "T") + raw[0].lower()
    return raw[0].replace("10", "T") + raw[1].lower()


def extract_game_state(xml_text: str) -> dict | None:
    """
    Ekstrahere board fra siste game i XML.
    Hole cards må legges inn manuelt av brukeren siden BetSolid ikke eksporterer dem.
    Returnerer: {"board": "Qs Jd 2c", "updated_at": "2026-01-15T13:47:27"}
    """
    try:
        root = ET.fromstring(xml_text)
        if root.tag != "session":
            return None
        
        # Finn siste game
        games = root.findall("game")
        if not games:
            return None
        
        latest_game = games[-1]
        
        # Hent board fra siste <round> med cards
        board_cards = []
        for rnd in latest_game.findall("round"):
            cards_attr = rnd.attrib.get("cards")
            if cards_attr:
                cards = cards_attr.strip().split()
                if cards:
                    board_cards = [normal_card(c) for c in cards]
            for cards_node in rnd.findall("cards"):
                card_type = (cards_node.attrib.get("type") or "").lower()
                if card_type in {"flop", "turn", "river"}:
                    cards = (cards_node.text or "").strip().split()
                    if card_type == "flop":
                        board_cards = [normal_card(c) for c in cards]
                    else:
                        board_cards.extend(normal_card(c) for c in cards)
        
        board_str = " ".join(c for c in board_cards if c) if board_cards else ""
        
        general = latest_game.find("general")
        started_at = general.findtext("startdate") if general is not None else None
        
        return {
            "board": board_str,
            "updated_at": started_at or "",
            "gamecode": latest_game.attrib.get("gamecode") or "",
            "session_code": root.attrib.get("code") or root.attrib.get("sessioncode") or "",
        }
    except Exception as e:
        print(f"[PARSE_ERROR] {e}")
        return None


class Handler(FileSystemEventHandler):

    def on_modified(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def _handle(self, path_str: str):
        p = Path(path_str)
        print(f"[EVENT] {p.name} modified/created")

        if not p.exists():
            return

        # BetSolid-filer uten ending kan likevel være XML
        # Vi prøver bare å lese og sjekke om det starter med "<session"
        try:
            xml_text = p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return

        key = str(p.resolve())
        now = time.time()
        content_hash = hashlib.sha1(xml_text.encode("utf-8", errors="ignore")).hexdigest()
        last = LAST_SENT.get(key)
        if last and last[1] == content_hash and (now - last[0]) < MIN_SECONDS_BETWEEN:
            return

        # Tillat at filer starter med f.eks. BOM eller <?xml ...?>
        if "<session" not in xml_text[:500]:
            return

        # Send kun ferdig filhistorikk til API for full import.
        try:
            r = requests.post(API_URL, data=xml_text.encode("utf-8"), headers={"Content-Type": "text/plain"}, timeout=10)
            if r.status_code == 200:
                print(f"[OK] Imported {p.name}: {r.json()}")
            else:
                print(f"[FAIL] {p.name} -> {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[ERROR] {p.name}: {e}")

        LAST_SENT[key] = (now, content_hash)


def import_recent_existing_files(handler: Handler, limit: int = 80) -> None:
    files = [p for p in WATCH_DIR.rglob("*") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in reversed(files[:limit]):
        handler._handle(str(p))


def main():
    if not WATCH_DIR.exists():
        raise SystemExit(f"Folder not found: {WATCH_DIR}")

    event_handler = Handler()
    import_recent_existing_files(event_handler)
    observer = Observer()
    observer.schedule(event_handler, str(WATCH_DIR), recursive=True)
    observer.start()

    print(f"Watching: {WATCH_DIR}")
    print(f"Posting to: {API_URL}")
    print("Mode: file history only")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
