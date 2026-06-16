"""
Script for å legge til test-kort i eksisterende hands
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Board, HoleCards

DATABASE_URL = "sqlite:///./poker.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def add_test_cards():
    db = SessionLocal()
    try:
        # Eksempel: Legg til kort for hand_id 55
        hand_id = 55
        
        # Sjekk om board allerede eksisterer
        existing_board = db.query(Board).filter(Board.hand_id == hand_id).first()
        if not existing_board:
            board = Board(
                hand_id=hand_id,
                flop1="Qs",
                flop2="Jd", 
                flop3="2c",
                turn="7h",
                river="Kc"
            )
            db.add(board)
            print(f"✅ Added board for hand {hand_id}: Qs Jd 2c 7h Kc")
        else:
            print(f"⚠️ Board already exists for hand {hand_id}")
        
        # Legg til hole cards for angryshark
        existing_hole = db.query(HoleCards).filter(
            HoleCards.hand_id == hand_id,
            HoleCards.player_name == "angryshark"
        ).first()
        
        if not existing_hole:
            hole = HoleCards(
                hand_id=hand_id,
                player_name="angryshark",
                card1="Ah",
                card2="Kh",
                is_known=True
            )
            db.add(hole)
            print(f"✅ Added hole cards for angryshark in hand {hand_id}: Ah Kh")
        else:
            print(f"⚠️ Hole cards already exist for angryshark in hand {hand_id}")
        
        db.commit()
        print("\n✅ Done! Test cards added successfully.")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    add_test_cards()
