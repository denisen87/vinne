#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import json
from pathlib import Path
from datetime import datetime

xml_file = Path(r"C:\Users\denis\AppData\Local\Betsolid Poker\data\angryshark\History\Data\Tables\8551647226.xml")
hero_name = "angryshark"

print(f"📖 Reading: {xml_file.name}")
xml_text = xml_file.read_text(encoding="utf-8", errors="ignore")
print(f"✅ File size: {len(xml_text)} bytes\n")

root = ET.fromstring(xml_text)
games = root.findall("game")
print(f"📊 Found {len(games)} games in session\n")

latest_game = games[-1] if games else None
if not latest_game:
    print("❌ No games found")
    exit(1)

print("=== Latest Game ===")

# Get hero cards
hero_cards = None
all_players = []
for p in latest_game.findall(".//player"):
    name = p.attrib.get("name")
    cards = p.attrib.get("cards")
    seat = p.attrib.get("seat")
    all_players.append(f"{name} (seat {seat}): {cards}")
    if name == hero_name and cards:
        cards_list = cards.strip().split()
        if len(cards_list) >= 2:
            hero_cards = f"{cards_list[0]} {cards_list[1]}"

print("Players:")
for p in all_players:
    print(f"  {p}")

print(f"\n🎴 Hero ({hero_name}) cards: {hero_cards}")

# Get board
board_cards = []
for rnd in latest_game.findall("round"):
    cards_attr = rnd.attrib.get("cards")
    if cards_attr:
        board_cards = cards_attr.strip().split()

print(f"🏛️  Board: {' '.join(board_cards) if board_cards else '(empty)'}")

# Create game state
if hero_cards:
    state = {
        "hero": hero_cards,
        "board": " ".join(board_cards) if board_cards else "",
        "updated_at": datetime.now().isoformat()
    }
    print(f"\n✅ Game state ready:")
    print(json.dumps(state, indent=2))
else:
    print(f"\n❌ Could not extract hero cards for '{hero_name}'")
