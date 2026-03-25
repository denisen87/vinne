#!/usr/bin/env python3
"""
Simulerer at du spiller poker hender - oppdaterer current_game.json med ulike kort.
Brukes for å teste live polling og equity calculator.
"""

import json
import time
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

CURRENT_GAME_FILE = Path(__file__).parent / "current_game.json"

# Test hands - ulike kombinasjoner (bare gyldige kombinasjoner!)
TEST_HANDS = [
    {"hero": "As Ks", "board": "Qs Jd Ts"},         # AK high + draw to broadway
    {"hero": "Ah Kh", "board": "Qh Jd 2c"},         # AK with flush draw
    {"hero": "7c 7d", "board": "7h 2s Ac"},         # Trip sevens
    {"hero": "2h 3h", "board": "4h 5h 6c"},         # Straight + flush draw
    {"hero": "Tc 9c", "board": "8c 7d 6c Kh"},      # Flush draw + straight draw
    {"hero": "Qh Qd", "board": "Qs Kc Ad"},         # Trip queens
    {"hero": "Kh Kd", "board": "Ac Kc 2d"},         # Trip kings
    {"hero": "9h 9c", "board": "9d 8h 7c"},         # Trip nines
    {"hero": "Ah Ad", "board": "As 2c 3d"},         # Trip aces
    {"hero": "5h 5d", "board": "5c 4c 3h"},         # Trip fives
]

def update_game(hero: str, board: str):
    """Oppdater current_game.json med nye kort (atomic write for å unngå lock issues)"""
    data = {
        "hero": hero,
        "board": board,
        "updated_at": datetime.now().isoformat()
    }
    
    try:
        # Bruk temp file + atomic rename for å unngå locks
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', dir=CURRENT_GAME_FILE.parent, delete=False) as tmp:
            json.dump(data, tmp, indent=2)
            tmp_path = tmp.name
        
        # Atomic rename (erstatt hvis finnes)
        shutil.move(tmp_path, str(CURRENT_GAME_FILE))
        print(f"✅ Updated: hero={hero}, board={board}")
    except Exception as e:
        print(f"⚠️  Failed to write game state: {e}")
        try:
            Path(tmp_path).unlink()  # clean up temp file
        except:
            pass

def main():
    print("🎮 Starting hand simulator...")
    print(f"📝 Will update: {CURRENT_GAME_FILE}")
    print("Press Ctrl+C to stop\n")
    
    hand_index = 0
    
    try:
        while True:
            hand = TEST_HANDS[hand_index % len(TEST_HANDS)]
            update_game(hand["hero"], hand["board"])
            
            hand_index += 1
            time.sleep(5)  # Update every 5 seconds
            
    except KeyboardInterrupt:
        print("\n\n👋 Simulator stopped")

if __name__ == "__main__":
    main()
