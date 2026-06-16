"""
Legger inn testdata for flere hender med forskjellige kort.
Kjør: python add_multiple_test_hands.py
"""
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Board, HoleCards

# Database setup
DATABASE_URL = "sqlite:///./poker.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

# Testdata for forskjellige hender
test_hands = [
    {
        "hand_id": 56,
        "player": "angryshark",
        "hero_cards": ("As", "Ks"),  # Pocket Aces suited
        "board": ("Qh", "Jh", "2d", None, None),  # Flop only
    },
    {
        "hand_id": 57,
        "player": "angryshark",
        "hero_cards": ("Qd", "Qc"),  # Pocket Queens
        "board": ("Ac", "Kd", "7s", "3h", None),  # Turn
    },
    {
        "hand_id": 58,
        "player": "angryshark",
        "hero_cards": ("9s", "8s"),  # Suited connectors
        "board": ("Th", "Jc", "Qs", "2d", "Ah"),  # River - straight!
    },
    {
        "hand_id": 59,
        "player": "angryshark",
        "hero_cards": ("Ad", "Kc"),  # AK offsuit
        "board": ("As", "Ah", "Kh", "Kd", "Ks"),  # Full house!
    },
    {
        "hand_id": 60,
        "player": "angryshark",
        "hero_cards": ("7h", "7d"),  # Pocket sevens
        "board": ("2c", "3s", "4h", None, None),  # Flop only
    },
]

added = 0
for hand_data in test_hands:
    hid = hand_data["hand_id"]
    player = hand_data["player"]
    c1, c2 = hand_data["hero_cards"]
    f1, f2, f3, turn, river = hand_data["board"]
    
    # Sjekk om Board allerede finnes
    existing_board = db.query(Board).filter(Board.hand_id == hid).first()
    if existing_board:
        print(f"⚠️  Board for hand {hid} finnes allerede, hopper over")
    else:
        board = Board(
            hand_id=hid,
            flop1=f1,
            flop2=f2,
            flop3=f3,
            turn=turn,
            river=river,
        )
        db.add(board)
        print(f"✅ Lagt til Board for hand {hid}: {f1} {f2} {f3} {turn or ''} {river or ''}")
        added += 1
    
    # Sjekk om HoleCards allerede finnes
    existing_hc = db.query(HoleCards).filter(
        HoleCards.hand_id == hid,
        HoleCards.player_name == player
    ).first()
    if existing_hc:
        print(f"⚠️  HoleCards for hand {hid} ({player}) finnes allerede, hopper over")
    else:
        hc = HoleCards(
            hand_id=hid,
            player_name=player,
            card1=c1,
            card2=c2,
            is_known=True,
        )
        db.add(hc)
        print(f"✅ Lagt til HoleCards for hand {hid} ({player}): {c1} {c2}")
        added += 1

try:
    db.commit()
    print(f"\n🎉 Ferdig! Lagt til {added} nye entries i databasen.")
    print("\n📝 Test nå:")
    print("   1. Gå til Live Coach i nettleseren")
    print("   2. Klikk på hand 56, 57, 58, 59, 60")
    print("   3. Se at equity-tallene OPPDATERES for hver hånd!")
except Exception as e:
    db.rollback()
    print(f"❌ Feil: {e}")
    sys.exit(1)
finally:
    db.close()
