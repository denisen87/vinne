import time
import json
from pathlib import Path
import requests
import xml.etree.ElementTree as ET

from sqlalchemy import text
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIR = Path(r"C:\Users\denis\AppData\Local\Betsolid Poker\data\angryshark\History\Data\Tables")
API_URL = "http://127.0.0.1:8000/import/betsolid"
CURRENT_GAME_FILE = Path(__file__).parent / "current_game.json"

# Enkel debounce: ikke importer samme fil for ofte
LAST_SENT: dict[str, float] = {}
MIN_SECONDS_BETWEEN = 2.0

HERO_NAME = "angryshark"


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
                    board_cards = cards
        
        board_str = " ".join(board_cards) if board_cards else ""
        
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        
        return {
            "board": board_str,
            "updated_at": now,
        }
    except Exception as e:
        print(f"[PARSE_ERROR] {e}")
        return None


def save_current_game(state: dict) -> None:
    """Lagre current game state til JSON-fil."""
    try:
        CURRENT_GAME_FILE.write_text(json.dumps(state, indent=2))
        print(f"[SAVED] Board updated: {state['board']}")
    except Exception as e:
        print(f"[SAVE_ERROR] {e}")


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
        key = str(p.resolve())
        now = time.time()
        if key in LAST_SENT and (now - LAST_SENT[key]) < MIN_SECONDS_BETWEEN:
            return

        try:
            xml_text = p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return

        # Tillat at filer starter med f.eks. BOM eller <?xml ...?>
        if "<session" not in xml_text[:500]:
            return

        # 1) Ekstrahere current game state
        game_state = extract_game_state(xml_text)
        if game_state:
            save_current_game(game_state)

        # 2) Send til API for full import
        try:
            r = requests.post(API_URL, data=xml_text.encode("utf-8"), headers={"Content-Type": "text/plain"}, timeout=10)
            if r.status_code == 200:
                print(f"[OK] Imported {p.name}: {r.json()}")
            else:
                print(f"[FAIL] {p.name} -> {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[ERROR] {p.name}: {e}")

        LAST_SENT[key] = now


def main():
    if not WATCH_DIR.exists():
        raise SystemExit(f"Folder not found: {WATCH_DIR}")

    event_handler = Handler()
    observer = Observer()
    observer.schedule(event_handler, str(WATCH_DIR), recursive=False)
    observer.start()

    print(f"Watching: {WATCH_DIR}")
    print(f"Posting to: {API_URL}")
    print(f"Saving current game to: {CURRENT_GAME_FILE}")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
