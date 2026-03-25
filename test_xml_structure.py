#!/usr/bin/env python3
import xml.etree.ElementTree as ET
from pathlib import Path

xml_file = Path(r"C:\Users\denis\AppData\Local\Betsolid Poker\data\angryshark\History\Data\Tables\8551647226.xml")
xml_text = xml_file.read_text(encoding="utf-8", errors="ignore")
root = ET.fromstring(xml_text)
games = root.findall("game")
latest = games[-1]

print("=== LATEST GAME XML STRUCTURE ===\n")
print(f"Game attributes: {dict(latest.attrib)}\n")

print("Players in <general><players>:")
genpls = latest.find("./general/players")
if genpls is not None:
    for player in genpls.findall("player"):
        attribs = dict(player.attrib)
        print(f"  Player: {attribs}")

print("\nAll 'player' tags anywhere in game:")
for player in latest.findall(".//player"):
    attribs = dict(player.attrib)
    print(f"  {attribs}")

print(f"\nTotal rounds: {len(latest.findall('round'))}")
for i, rnd in enumerate(latest.findall("round")):
    attribs = dict(rnd.attrib)
    print(f"  Round {i}: {attribs}")
    # Check if there are actions
    actions = rnd.findall(".//action")
    print(f"    -> {len(actions)} actions")
