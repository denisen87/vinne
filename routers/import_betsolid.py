from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.exc import IntegrityError
import xml.etree.ElementTree as ET
import re

from database import get_db
from models import Session as PokerSession, Hand, HandPlayer, Action, Board, HoleCards

router = APIRouter(prefix="/import", tags=["import"])

ACTION_MAP = {
    0: "fold",
    1: "sb",
    2: "bb",
    3: "call",
    4: "check",
    5: "bet",
    23: "raise",
}

MONEY_RE = re.compile(r"[^\d,.\-]")

def money_to_float(s: str | None) -> float:
    if not s:
        return 0.0
    s = s.strip()
    s = MONEY_RE.sub("", s)   # fjern € osv
    s = s.replace(",", ".")
    return float(s) if s else 0.0


@router.post("/betsolid", summary="Import BetSolid XML (text/plain)")
def import_betsolid(
    xml_text: str = Body(..., media_type="text/plain"),
    db: DbSession = Depends(get_db),
):
    # Parse XML
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {e}")

    if root.tag != "session":
        raise HTTPException(status_code=400, detail="Root element must be <session>")

    session_code = root.attrib.get("sessioncode")
    if not session_code:
        raise HTTPException(status_code=400, detail="Missing sessioncode attribute")

    gen = root.find("general")

    nickname = gen.findtext("nickname") if gen is not None else None
    game_type = gen.findtext("gametype") if gen is not None else None
    currency = gen.findtext("currency") if gen is not None else "EUR"
    table_name = gen.findtext("tablename") if gen is not None else None
    start_date = gen.findtext("startdate") if gen is not None else None
    duration = gen.findtext("duration") if gen is not None else None
    game_count = int(gen.findtext("gamecount")) if gen is not None and gen.findtext("gamecount") else None
    sb = money_to_float(gen.findtext("smallblind")) if gen is not None else 0.0
    bb = money_to_float(gen.findtext("bigblind")) if gen is not None else 0.0

    # Finn eller lag session
    session = db.query(PokerSession).filter(PokerSession.session_code == session_code).first()
    if not session:
        session = PokerSession(
            site="betsolid",
            session_code=session_code,
            nickname=nickname,
            game_type=game_type,
            currency=currency,
            sb=sb,
            bb=bb,
            table_name=table_name,
            start_date=start_date,
            duration=duration,
            game_count=game_count,
        )
        db.add(session)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # session_code er unik; hvis den finnes likevel, hent den
            session = db.query(PokerSession).filter(PokerSession.session_code == session_code).first()
        db.refresh(session)
    else:
        # Oppdater litt info
        session.nickname = nickname
        session.game_type = game_type
        session.currency = currency
        session.sb = sb
        session.bb = bb
        session.table_name = table_name
        session.start_date = start_date
        session.duration = duration
        session.game_count = game_count
        db.commit()

    imported_hands = 0
    skipped_hands = 0
    imported_hand_players = 0
    imported_actions = 0

    # Importer alle games
    for game in root.findall("game"):
        gamecode = game.attrib.get("gamecode")
        if not gamecode:
            continue

        # Hvis hand finnes, hopp
        if db.query(Hand).filter(Hand.site_hand_id == gamecode).first():
            skipped_hands += 1
            continue

        ggen = game.find("general")
        started_at = ggen.findtext("startdate") if ggen is not None else None

        hand = Hand(
            site_hand_id=gamecode,
            session_id=session.id,
            started_at=started_at,
            max_players=None,
            button_seat=None,
            variant="NLHE",
            currency=currency,
            sb=sb,
            bb=bb,
        )
        db.add(hand)
        try:
            db.commit()
            db.refresh(hand)
            imported_hands += 1
        except IntegrityError:
            db.rollback()
            skipped_hands += 1
            continue

        # Players
        players_node = ggen.find("players") if ggen is not None else None
        if players_node is not None:
            for p in players_node.findall("player"):
                name = p.attrib.get("name")
                if not name:
                    continue

                seat = int(p.attrib.get("seat")) if p.attrib.get("seat") else None
                is_dealer = True if p.attrib.get("dealer") == "1" else False if p.attrib.get("dealer") else None

                hp = HandPlayer(
                    hand_id=hand.id,
                    player_name=name,
                    seat=seat,
                    is_dealer=is_dealer,
                    stack_start=money_to_float(p.attrib.get("chips")),
                    bet_total=money_to_float(p.attrib.get("bet")),
                    win_total=money_to_float(p.attrib.get("win")),
                    rake=money_to_float(p.attrib.get("rakeamount")),
                    cashout=True if p.attrib.get("cashout") == "1" else False if p.attrib.get("cashout") else None,
                    cashout_fee=money_to_float(p.attrib.get("cashout_fee")),
                )
                db.add(hp)
                try:
                    db.commit()
                    imported_hand_players += 1
                except IntegrityError:
                    db.rollback()

        # Actions
        for rnd in game.findall("round"):
            street = int(rnd.attrib.get("no", "0"))  # BetSolid bruker 0/1/2/3/4
            for a in rnd.findall("action"):
                seq = int(a.attrib.get("no", "0"))
                player = a.attrib.get("player") or "UNKNOWN"
                t = int(a.attrib.get("type", "0"))
                amount = money_to_float(a.attrib.get("sum"))

                act = Action(
                    hand_id=hand.id,
                    street=street,
                    seq=seq,
                    player_name=player,
                    action_type_code=t,
                    action=ACTION_MAP.get(t, "raw"),
                    amount=amount,
                )
                db.add(act)
                try:
                    db.commit()
                    imported_actions += 1
                except IntegrityError:
                    db.rollback()

        # Board cards (fra <round> tags med "cards" attributt)
        board_cards = {}  # {street: [cards]}
        for rnd in game.findall("round"):
            cards_attr = rnd.attrib.get("cards")
            if cards_attr:
                street = int(rnd.attrib.get("no", "0"))
                # BetSolid format: "Qs Jd 2c" eller lignende
                cards = cards_attr.strip().split()
                board_cards[street] = cards

        # Bygg Board-entry (street 1=flop, 2=turn, 3=river)
        flop1, flop2, flop3, turn, river = None, None, None, None, None
        if 1 in board_cards and len(board_cards[1]) >= 3:
            flop1, flop2, flop3 = board_cards[1][0], board_cards[1][1], board_cards[1][2]
        if 2 in board_cards and len(board_cards[2]) >= 1:
            turn = board_cards[2][0]
        if 3 in board_cards and len(board_cards[3]) >= 1:
            river = board_cards[3][0]

        if any([flop1, flop2, flop3, turn, river]):
            b = Board(hand_id=hand.id, flop1=flop1, flop2=flop2, flop3=flop3, turn=turn, river=river)
            db.add(b)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()

        # Hole cards (fra <player cards="..."> hvis tilgjengelig)
        if players_node is not None:
            for p in players_node.findall("player"):
                name = p.attrib.get("name")
                cards_attr = p.attrib.get("cards")
                if name and cards_attr:
                    cards = cards_attr.strip().split()
                    if len(cards) >= 2:
                        hc = HoleCards(
                            hand_id=hand.id,
                            player_name=name,
                            card1=cards[0],
                            card2=cards[1],
                            is_known=True,
                        )
                        db.add(hc)
                        try:
                            db.commit()
                        except IntegrityError:
                            db.rollback()

    return {
        "session_id": session.id,
        "session_code": session.session_code,
        "imported_hands": imported_hands,
        "skipped_hands": skipped_hands,
        "imported_hand_players": imported_hand_players,
        "imported_actions": imported_actions,
    }
