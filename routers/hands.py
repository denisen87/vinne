from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from database import get_db
from models import Hand, Session as PokerSession, Board, HoleCards, HandPlayer
from schemas import HandCreate, HandOut, HandListOut

router = APIRouter(prefix="/hands", tags=["hands"])


# 🔹 Opprett en hand
@router.post("", response_model=HandOut)
def create_hand(payload: HandCreate, db: DbSession = Depends(get_db)):
    # 1) sjekk at session finnes
    s = db.query(PokerSession).filter(PokerSession.id == payload.session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2) lag Hand
    h = Hand(**payload.model_dump())
    db.add(h)

    try:
        db.commit()
    except Exception:
        db.rollback()
        # typisk: site_hand_id er allerede brukt
        raise HTTPException(status_code=400, detail="Could not create hand (duplicate site_hand_id?)")

    db.refresh(h)
    return h


# 🔹 Alle hender (evt filtrert på session via query-param)
@router.get("", response_model=list[HandListOut])
def list_hands(session_id: int | None = None, db: DbSession = Depends(get_db)):
    q = db.query(Hand)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)

    return q.order_by(Hand.id.desc()).limit(200).all()


# 🔹 Én spesifikk hand
@router.get("/{hand_id}", response_model=HandOut)
def get_hand(hand_id: int, db: DbSession = Depends(get_db)):
    h = db.query(Hand).filter(Hand.id == hand_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Hand not found")
    return h

@router.get("/{hand_id}/cards")
def get_hand_cards(hand_id: int, db: DbSession = Depends(get_db)):
    hand = db.query(Hand).filter(Hand.id == hand_id).first()
    if not hand:
        raise HTTPException(status_code=404, detail="Hand not found")

    board = db.query(Board).filter(Board.hand_id == hand_id).first()
    holes = db.query(HoleCards).filter(HoleCards.hand_id == hand_id).all()

    board_cards = []
    if board:
        for c in [board.flop1, board.flop2, board.flop3, board.turn, board.river]:
            if c:
                board_cards.append(c)

    hole_out = []
    for h in holes:
        hole_out.append({
            "player_name": h.player_name,
            "card1": h.card1,
            "card2": h.card2,
            "is_known": bool(h.is_known),
        })

    return {
        "hand_id": hand_id,
        "session_id": hand.session_id,
        "board": board_cards,
        "hole_cards": hole_out
    }

@router.get("/latest/board")
def get_latest_board(db: DbSession = Depends(get_db)):
    """
    Returnerer board fra den siste hånden i databasen.
    Brukes av frontend polling for å få live board updates fra BetSolid.
    """
    latest_hand = db.query(Hand).order_by(Hand.id.desc()).first()
    if not latest_hand:
        return {"board": "", "hand_id": None, "updated_at": None}
    
    board = db.query(Board).filter(Board.hand_id == latest_hand.id).first()
    
    board_cards = []
    if board:
        for c in [board.flop1, board.flop2, board.flop3, board.turn, board.river]:
            if c:
                board_cards.append(c)
    
    board_str = " ".join(board_cards) if board_cards else ""
    
    return {
        "board": board_str,
        "hand_id": latest_hand.id,
        "updated_at": latest_hand.started_at
    }


@router.get("/latest/with-adaptive-stats")
def get_latest_with_adaptive_stats(db: DbSession = Depends(get_db)):
    """
    Returnerer siste hånd med adaptive ranges for alle motspillere basert på deres historikk.
    Beregner VPIP, PFR, position og foreslår range for hver spiller.
    """
    from routers.players import player_hud, hud_by_pos
    
    latest_hand = db.query(Hand).order_by(Hand.id.desc()).first()
    if not latest_hand:
        return {"error": "No hands in database", "board": "", "players": []}
    
    # Hent board
    board = db.query(Board).filter(Board.hand_id == latest_hand.id).first()
    board_cards = []
    if board:
        for c in [board.flop1, board.flop2, board.flop3, board.turn, board.river]:
            if c:
                board_cards.append(c)
    board_str = " ".join(board_cards) if board_cards else ""
    
    # Hent alle players ved bordet
    hand_players = db.query(HandPlayer).filter(HandPlayer.hand_id == latest_hand.id).all()
    
    players_out = []
    
    for hp in hand_players:
        player_name = hp.player_name
        
        try:
            # Hent HUD stats for denne spilleren (all-time, ikke session-spesifikk)
            hud = player_hud(player_name, db)
            
            # Klassifiser spiller-type basert på stats
            vpip = float(hud.vpip_pct or 0)
            pfr = float(hud.pfr_pct or 0)
            threebet = float(hud.threebet_pct or 0)
            
            # Enkel klassifisering
            if vpip < 15 and pfr < 10:
                player_type = "nit"
            elif vpip < 25 and pfr >= 12:
                player_type = "tag"
            elif vpip >= 30 and pfr >= 18:
                player_type = "lag"
            elif vpip >= 35 and pfr < 15:
                player_type = "fish"
            else:
                player_type = "unknown"
            
            # Generer range basert på spiller-type
            ranges_map = {
                "nit": "AA,KK,QQ,JJ,TT,99, AKs,AQs,AJs",
                "tag": "AA,KK,QQ,JJ,TT,99,88,77,66,55, AKs,AQs,AJs,ATs, AKo,AQo, KQs,KJs",
                "lag": "AA,KK,QQ,JJ,TT,99,88,77,66,55,44,33,22, AKs,AQs,AJs,ATs,A9s, AKo,AQo,AJo, KQs,KJs,KTs, QJs,QTs, JTs, T9s, 98s",
                "fish": "AA,KK,QQ,JJ,TT,99,88,77, AKs,AQs,AJs,AKo,AQo, KQs,KJs,QJs",
                "unknown": "AA,KK,QQ,JJ,TT,99,88,77,66,55, AKs,AQs,AJs, KQs,KJs"
            }
            
            suggested_range = ranges_map.get(player_type, ranges_map["unknown"])
            
            players_out.append({
                "name": player_name,
                "seat": hp.seat,
                "vpip_pct": vpip,
                "pfr_pct": pfr,
                "threebet_pct": threebet,
                "hands_played": hud.hands_played,
                "player_type": player_type,
                "suggested_range": suggested_range,
                "confidence": hud.confidence
            })
        except Exception as e:
            # Hvis noe feiler for en spiller, inkluder dem likevel men uten stats
            players_out.append({
                "name": player_name,
                "seat": hp.seat,
                "error": str(e),
                "suggested_range": "QQ,AK"  # conservativ default
            })
    
    return {
        "board": board_str,
        "hand_id": latest_hand.id,
        "updated_at": latest_hand.started_at,
        "players": players_out
    }
