from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from database import get_db
from models import Session as PokerSession
from schemas import SessionCreate, SessionOut

from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from models import Hand
from schemas import HandListOut

from models import HandPlayer
from schemas import SessionHudOut, PlayerHudOut
from routers.players import player_hud, player_leaks  # gjenbruker logikken
from models import Hand, HandPlayer  
from schemas import SessionLeaksOut, SessionPlayerLeaksOut  

from models import Hand, HandPlayer
from schemas import SessionInsightsOut, SessionInsightsPlayerOut




router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut)
def create_session(payload: SessionCreate, db: DbSession = Depends(get_db)):
    s = PokerSession(**payload.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s

@router.post("", response_model=SessionOut)
def create_session(payload: SessionCreate, db: DbSession = Depends(get_db)):
    s = PokerSession(**payload.model_dump())
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="session_code already exists")
    db.refresh(s)
    return s


@router.get("", response_model=list[SessionOut])
def list_sessions(db: DbSession = Depends(get_db)):
    return db.query(PokerSession).order_by(PokerSession.id.desc()).all()


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: int, db: DbSession = Depends(get_db)):
    s = db.query(PokerSession).filter(PokerSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


@router.delete("/{session_id}")
def delete_session(session_id: int, db: DbSession = Depends(get_db)):
    s = db.query(PokerSession).filter(PokerSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(s)
    db.commit()
    return {"deleted": True, "id": session_id}

@router.get("/{session_id}/hands", response_model=list[HandListOut])
def list_hands_for_session(session_id: int, db: DbSession = Depends(get_db)):
    # 1) Sjekk at session finnes
    s = db.query(PokerSession).filter(PokerSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2) Hent hender for denne session
    return (
        db.query(Hand)
        .filter(Hand.session_id == session_id)
        .order_by(Hand.id.desc())
        .all()
    )

@router.get("/{session_id}/hud", response_model=SessionHudOut)
def session_hud(
    session_id: int,
    min_hands: int = 5,
    db: DbSession = Depends(get_db),
):
    # Sjekk at session finnes
    s = db.query(PokerSession).filter(PokerSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    # Finn alle spillere i denne sessionen via HandPlayer -> Hand -> session_id
    # (vi kan gjøre dette enkelt: finn hand_ids for session, og så player_names)
    hand_ids = [h.id for h in db.query(Hand).filter(Hand.session_id == session_id).all()]

    if not hand_ids:
        return SessionHudOut(session_id=session_id, players=[])

    player_names = (
        db.query(HandPlayer.player_name)
        .filter(HandPlayer.hand_id.in_(hand_ids))
        .distinct()
        .all()
    )
    player_names = [p[0] for p in player_names]

    # Regn HUD for hver spiller
    players_hud: list[PlayerHudOut] = []
    for name in player_names:
        players_hud.append(player_hud(name, db))  # gjenbruk

        # Filtrer vekk små samples
    players_hud = [p for p in players_hud if p.hands_played >= min_hands]

    # Sorter: mest data først
    players_hud.sort(key=lambda p: p.hands_played, reverse=True)


    return SessionHudOut(session_id=session_id, players=players_hud)

@router.get("/{session_id}/insights", response_model=SessionInsightsOut)
def session_insights(
    session_id: int,
    min_hands: int = 5,
    mode: str = "both",  # "leaks" | "observations" | "both"
    db: DbSession = Depends(get_db),
):
    

    # 1) Finn session
    s = db.query(PokerSession).filter(PokerSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2) Finn alle hands i session
    hand_ids = [h[0] for h in db.query(Hand.id).filter(Hand.session_id == session_id).all()]
    if not hand_ids:
        return SessionInsightsOut(session_id=session_id, min_hands=min_hands, mode=mode, players=[])

    # 3) Finn spillere i session
    player_names = (
        db.query(HandPlayer.player_name)
        .filter(HandPlayer.hand_id.in_(hand_ids))
        .distinct()
        .all()
    )
    player_names = [p[0] for p in player_names]

    # Importer funksjoner fra players (inne i funksjonen for å unngå circular import)
    from routers.players import player_hud, player_leaks

    points = {"low": 10, "medium": 25, "high": 45}

    players_out: list[SessionInsightsPlayerOut] = []

    for name in player_names:
        hud = player_hud(name, db)
        if hud.hands_played < min_hands:
            continue

        try:
            insights = player_leaks(name, db, session_id=session_id)
        except Exception as e:
            # Logg hvem som feiler + hvorfor (vises i terminalen)
            print(f"[INSIGHTS ERROR] player={name} session={session_id} err={type(e).__name__}: {e}")
            continue

        # velg hva vi skal inkludere
        if mode == "leaks":
            leaks_list = insights.leaks
            obs_list = []
        elif mode == "observations":
            leaks_list = []
            obs_list = insights.observations
        else:  # both
            leaks_list = insights.leaks
            obs_list = insights.observations

        leak_score = sum(points.get(l.severity, 0) for l in leaks_list)
        obs_score = sum(points.get(l.severity, 0) for l in obs_list)

        # ta bare med spillere som faktisk har noe å vise
        if leak_score == 0 and obs_score == 0:
            continue

        players_out.append(
            SessionInsightsPlayerOut(
                player_name=name,
                hands_played=hud.hands_played,
                leak_score=int(leak_score),
                obs_score=int(obs_score),
                leaks=leaks_list,
                observations=obs_list,
            )
        )

        def weight(conf: str | None) -> float:
            if conf == "high":
                return 1.0
            if conf == "medium":
                return 0.7
            return 0.4  # low eller None   

        points = {"low": 10, "medium": 25, "high": 45}

        leak_score = sum(points.get(l.severity, 0) * weight(l.confidence) for l in leaks_list)
        obs_score = sum(points.get(l.severity, 0) * weight(l.confidence) for l in obs_list)

        leak_score = int(round(leak_score))
        obs_score = int(round(obs_score))


    # 4) Sorter: leak_score først, deretter obs_score, deretter hands
    players_out.sort(key=lambda p: (p.leak_score, p.obs_score, p.hands_played), reverse=True)

    return SessionInsightsOut(session_id=session_id, min_hands=min_hands, mode=mode, players=players_out)




@router.get("/{session_id}/leaks", response_model=SessionLeaksOut)
def session_leaks(session_id: int, min_hands: int = 5, db: DbSession = Depends(get_db)):
    # Finn session
    s = db.query(PokerSession).filter(PokerSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    # Finn alle hand_ids i session
    hand_ids = [h.id for h in db.query(Hand.id).filter(Hand.session_id == session_id).all()]
    if not hand_ids:
        return SessionLeaksOut(session_id=session_id, min_hands=min_hands, players=[])

    # Finn alle spiller-navn i session
    player_names = (
        db.query(HandPlayer.player_name)
        .filter(HandPlayer.hand_id.in_(hand_ids))
        .distinct()
        .all()
    )
    player_names = [p[0] for p in player_names]

    # Importer funksjoner fra players-router (inne i funksjon for å unngå circular issues)
    from routers.players import player_hud, player_leaks

    players_out: list[SessionPlayerLeaksOut] = []

    for name in player_names:
        hud = player_hud(name, db)

        # filtrer på hands_played
        if hud.hands_played < min_hands:
            continue

    leaks_obj = player_leaks(name, db)

    if leaks_obj.leaks:
        severity_points = {"low": 10, "medium": 25, "high": 45}
        score = sum(severity_points.get(l.severity, 0) for l in leaks_obj.leaks)

        players_out.append(
            SessionPlayerLeaksOut(
                player_name=name,
                hands_played=hud.hands_played,
                leak_score=int(score),
                leaks=leaks_obj.leaks,
            )
        )



    # Sorter: flest "alvorlige" leaks først, deretter antall hender
    severity_rank = {"high": 2, "medium": 1, "low": 0}

    def score_player(p: SessionPlayerLeaksOut) -> tuple[int, int]:
        max_sev = max((severity_rank.get(l.severity, 0) for l in p.leaks), default=0)
        return (max_sev, p.hands_played)

    players_out.sort(key=lambda p: (p.leak_score, p.hands_played), reverse=True)

    return SessionLeaksOut(session_id=session_id, min_hands=min_hands, players=players_out)


