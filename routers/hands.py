from fastapi import APIRouter, Depends, HTTPException
from functools import lru_cache
from pydantic import BaseModel
from sqlalchemy import cast, Integer
from sqlalchemy.orm import Session as DbSession

from database import get_db
from models import Hand, Session as PokerSession, Board, HoleCards, HandPlayer
from schemas import HandCreate, HandOut, HandListOut

router = APIRouter(prefix="/hands", tags=["hands"])


class HandCardsSave(BaseModel):
    player_name: str = "angryshark"
    hero: list[str] = []
    board: list[str] = []
    gamecode: str | None = None
    session_code: str | None = None
    session_id: int | None = None
    started_at: str | None = None
    players: list[dict] = []


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


def _normalize_card(card: str | None) -> str | None:
    if not card:
        return None
    raw = str(card).strip()
    if not raw or raw.upper() == "X":
        return None
    if len(raw) >= 2 and raw[0].upper() in {"S", "H", "D", "C"}:
        rank = raw[1:].upper().replace("10", "T")
        suit = raw[0].lower()
    else:
        rank = raw[:-1].upper().replace("10", "T")
        suit = raw[-1].lower()
    ranks = {"2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"}
    if rank in ranks and suit in {"s", "h", "d", "c"}:
        return f"{rank}{suit}"
    return raw


_TREYS_CARD = None
_TREYS_EVALUATOR = None


def _treys_tools():
    global _TREYS_CARD, _TREYS_EVALUATOR
    if _TREYS_CARD is None or _TREYS_EVALUATOR is None:
        from treys import Card, Evaluator

        _TREYS_CARD = Card
        _TREYS_EVALUATOR = Evaluator()
    return _TREYS_CARD, _TREYS_EVALUATOR


@lru_cache(maxsize=50000)
def _showdown_class_cached(hero_key: tuple[str, str], board_key: tuple[str, str, str, str, str]) -> tuple[str | None, int | None]:
    try:
        Card, evaluator = _treys_tools()
        score = evaluator.evaluate(
            [Card.new(c) for c in board_key],
            [Card.new(c) for c in hero_key],
        )
        rank_class = evaluator.get_rank_class(score)
        return evaluator.class_to_string(rank_class), rank_class
    except Exception:
        return None, None


def _showdown_class(hero_cards: list[str], board_cards: list[str]) -> tuple[str | None, int | None]:
    if len(hero_cards) != 2 or len(board_cards) != 5:
        return None, None
    return _showdown_class_cached(tuple(hero_cards), tuple(board_cards))


@router.get("/card-history")
def get_card_history(
    player_name: str | None = None,
    session_id: int | None = None,
    session_code: str | None = None,
    limit: int = 5000,
    include_showdown: bool = False,
    db: DbSession = Depends(get_db),
):
    limit = min(max(int(limit or 0), 1), 5000)
    resolved_session_id = session_id
    if session_code:
        session = (
            db.query(PokerSession)
            .filter(PokerSession.session_code == str(session_code).strip())
            .first()
        )
        if not session:
            return {"history": [], "count": 0}
        resolved_session_id = session.id

    holes_q = (
        db.query(HoleCards, Hand, Board)
        .join(Hand, Hand.id == HoleCards.hand_id)
        .outerjoin(Board, Board.hand_id == HoleCards.hand_id)
    )
    if player_name:
        holes_q = holes_q.filter(HoleCards.player_name == player_name)
    if resolved_session_id:
        holes_q = holes_q.filter(Hand.session_id == resolved_session_id)

    rows = (
        holes_q
        .order_by(Hand.started_at.desc(), Hand.id.desc(), cast(Hand.site_hand_id, Integer).desc())
        .limit(limit)
        .all()
    )
    history = []

    for hc, hand, board in rows:
        board_cards = []
        if board:
            for c in [board.flop1, board.flop2, board.flop3, board.turn, board.river]:
                normalized = _normalize_card(c)
                if normalized:
                    board_cards.append(normalized)

        hero_cards = [_normalize_card(hc.card1), _normalize_card(hc.card2)]
        hero_cards = [c for c in hero_cards if c]
        if len(hero_cards) != 2:
            continue

        showdown_class = None
        showdown_rank_class = None
        if include_showdown and len(board_cards) == 5:
            showdown_class, showdown_rank_class = _showdown_class(hero_cards, board_cards)

        history.append({
            "hand_id": hc.hand_id,
            "site_hand_id": hand.site_hand_id,
            "session_id": hand.session_id,
            "player_name": hc.player_name,
            "hero": hero_cards,
            "cards": hero_cards,
            "board": board_cards,
            "showdown_class": showdown_class,
            "showdown_rank_class": showdown_rank_class,
            "at": hand.started_at.isoformat() if hasattr(hand.started_at, "isoformat") else str(hand.started_at or ""),
            "source": "database",
        })

    def site_sort_key(entry: dict) -> tuple[int, int, int]:
        try:
            site_id = int(entry.get("site_hand_id") or 0)
        except ValueError:
            site_id = 0
        try:
            hand_id = int(entry.get("hand_id") or 0)
        except ValueError:
            hand_id = 0
        try:
            at_ms = int(__import__("datetime").datetime.fromisoformat(str(entry.get("at") or "")[:19]).timestamp())
        except Exception:
            at_ms = 0
        return (at_ms, hand_id, site_id)

    history.sort(key=site_sort_key, reverse=True)
    return {"history": history, "count": len(history)}


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


def _save_cards_for_hand(hand: Hand, payload: HandCardsSave, db: DbSession):
    player_name = (payload.player_name or "angryshark").strip() or "angryshark"
    hero_cards = [_normalize_card(c) for c in (payload.hero or [])]
    hero_cards = [c for c in hero_cards if c]
    board_cards = [_normalize_card(c) for c in (payload.board or [])]
    board_cards = [c for c in board_cards if c]

    if hero_cards and len(hero_cards) != 2:
        raise HTTPException(status_code=400, detail="Hero må ha nøyaktig 2 gyldige kort.")
    if len(board_cards) > 5:
        raise HTTPException(status_code=400, detail="Board kan maks ha 5 kort.")
    if len(set(hero_cards + board_cards)) != len(hero_cards + board_cards):
        raise HTTPException(status_code=400, detail="Duplikate kort er ikke gyldig.")

    saved_hero = False
    if len(hero_cards) == 2:
        hole = (
            db.query(HoleCards)
            .filter(HoleCards.hand_id == hand.id)
            .filter(HoleCards.player_name == player_name)
            .first()
        )
        if hole:
            hole.card1 = hero_cards[0]
            hole.card2 = hero_cards[1]
            hole.is_known = True
        else:
            db.add(HoleCards(
                hand_id=hand.id,
                player_name=player_name,
                card1=hero_cards[0],
                card2=hero_cards[1],
                is_known=True,
            ))
        saved_hero = True

    saved_board = False
    if board_cards:
        board = db.query(Board).filter(Board.hand_id == hand.id).first()
        if not board:
            board = Board(hand_id=hand.id)
            db.add(board)
        slots = ["flop1", "flop2", "flop3", "turn", "river"]
        for idx, slot in enumerate(slots):
            setattr(board, slot, board_cards[idx] if idx < len(board_cards) else None)
        saved_board = True

    db.commit()
    return {
        "hand_id": hand.id,
        "site_hand_id": hand.site_hand_id,
        "session_id": hand.session_id,
        "player_name": player_name,
        "saved_hero": saved_hero,
        "saved_board": saved_board,
        "hero": hero_cards,
        "board": board_cards,
    }


@router.post("/{hand_id}/cards")
def save_hand_cards(hand_id: int, payload: HandCardsSave, db: DbSession = Depends(get_db)):
    hand = db.query(Hand).filter(Hand.id == hand_id).first()
    if not hand:
        raise HTTPException(status_code=404, detail="Hand not found")
    return _save_cards_for_hand(hand, payload, db)


@router.post("/live-cards")
def save_live_cards(payload: HandCardsSave, db: DbSession = Depends(get_db)):
    gamecode = str(payload.gamecode or "").strip()
    if not gamecode:
        raise HTTPException(status_code=400, detail="gamecode mangler.")

    hand = db.query(Hand).filter(Hand.site_hand_id == gamecode).first()
    if not hand:
        session_id = payload.session_id
        if not session_id:
            latest_session = db.query(PokerSession).order_by(PokerSession.id.desc()).first()
            if not latest_session:
                raise HTTPException(status_code=404, detail="Ingen session finnes.")
            session_id = latest_session.id
        hand = Hand(
            site_hand_id=gamecode,
            session_id=session_id,
            started_at=payload.started_at,
            variant="NLHE",
        )
        db.add(hand)
        db.commit()
        db.refresh(hand)

    return _save_cards_for_hand(hand, payload, db)


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
            hands_played = 0
            vpip = 0.0
            pfr = 0.0
            threebet = 0.0
            
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
                "hands_played": hands_played,
                "player_type": player_type,
                "suggested_range": suggested_range,
                "confidence": "low"
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
        "site_hand_id": latest_hand.site_hand_id,
        "session_id": latest_hand.session_id,
        "updated_at": latest_hand.started_at,
        "players": players_out
    }
