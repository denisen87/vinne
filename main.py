from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import json
from pathlib import Path

from database import engine
from models import Base

from routers.sessions import router as sessions_router
from routers.equity import router as equity_router
from routers.hands import router as hands_router   # ✅ denne er riktig

from routers.players import router as players_router
from routers.hand_players import router as hand_players_router

from routers.actions import router as actions_router

from routers.import_betsolid import router as import_router

from fastapi import Depends
from sqlalchemy.orm import Session as DbSession

from database import get_db
from schemas import SessionCompareOut, ImpactDeltaOut, CompareKeyMetricsOut
from models import HandPlayer  # Hand brukes via hud_by_pos, men ok å ha HandPlayer her

from routers.players import hud_by_pos, fold_to_3bet_by_pos, leak_impact



app = FastAPI(title="Poker Equity API", version="0.1")

# basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vinne")

# Opprett tabeller
Base.metadata.create_all(bind=engine)

# Middleware
app.add_middleware(
    CORSMiddleware,
    # Development fallback: allow all origins but disable credentials to avoid CORS errors.
    # NOTE: This is a temporary dev setting. Do NOT use in production.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Koble routers (én gang hver)
app.include_router(sessions_router)
app.include_router(hands_router)   # ✅ MANGLET
app.include_router(equity_router)
app.include_router(players_router)
app.include_router(hand_players_router)
app.include_router(actions_router)
app.include_router(import_router)



@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/current-game")
def current_game():
    """
    Returnerer aktuelle spill-data (hero-kort + board).
    Brukes av frontend for live equity-updates mens du spiller.
    """
    current_game_file = Path(__file__).parent / "current_game.json"
    if current_game_file.exists():
        try:
            data = json.loads(current_game_file.read_text())
            return data
        except Exception as e:
            logger.warning(f"Error reading current_game.json: {e}")
    
    return {"hero": "", "board": "", "updated_at": None}


# Generic exception handler to return JSON and include CORS header
@app.exception_handler(Exception)
def handle_unexpected_exception(request, exc):
    # Log full exception
    logger.exception("Unhandled exception: %s", exc)
    content = {"detail": "Internal Server Error", "error": str(exc)}
    headers = {"Access-Control-Allow-Origin": "*"}
    return JSONResponse(status_code=500, content=content, headers=headers)

@app.get("/compare-sessions", response_model=SessionCompareOut)
def compare_sessions(
    player_name: str,
    from_session_id: int,
    to_session_id: int,
    db: DbSession = Depends(get_db),
):
    # Importer funksjoner fra players-router (inni for å unngå circular import)
    from routers.players import leak_impact, hud_by_pos, fold_to_3bet_by_pos

    # 1) Money/impact
    rep_from = leak_impact(player_name, session_id=from_session_id, db=db)
    rep_to = leak_impact(player_name, session_id=to_session_id, db=db)

    from_net = float(rep_from.session_net_total)
    to_net = float(rep_to.session_net_total)
    delta_net = round(to_net - from_net, 2)

    # Bygg map fra impacts
    from_map = {i.leak_id: i for i in rep_from.impacts}
    to_map = {i.leak_id: i for i in rep_to.impacts}
    all_ids = sorted(set(from_map.keys()) | set(to_map.keys()))

    impacts: list[ImpactDeltaOut] = []
    for lid in all_ids:
        a = from_map.get(lid)
        b = to_map.get(lid)

        from_net_i = float(a.net_total) if a else 0.0
        to_net_i = float(b.net_total) if b else 0.0
        delta_net_i = round(to_net_i - from_net_i, 2)

        from_share = float(a.share_of_total_pct) if a else 0.0
        to_share = float(b.share_of_total_pct) if b else 0.0
        delta_share = round(to_share - from_share, 1)

        from_hands = int(a.hands) if a else 0
        to_hands = int(b.hands) if b else 0

        impacts.append(ImpactDeltaOut(
            leak_id=lid,
            from_net=round(from_net_i, 2),
            to_net=round(to_net_i, 2),
            delta_net=delta_net_i,
            from_share=round(from_share, 1),
            to_share=round(to_share, 1),
            delta_share=delta_share,
            from_hands=from_hands,
            to_hands=to_hands,
        ))

    # Sorter impacts: størst absolutt delta_share først, deretter delta_net
    impacts.sort(key=lambda x: (abs(x.delta_share), abs(x.delta_net)), reverse=True)

    # 2) Key metrics: UTG/MP VPIP/PFR (fra hud_by_pos)
    pos_from = hud_by_pos(player_name, session_id=from_session_id, db=db).by_pos
    pos_to = hud_by_pos(player_name, session_id=to_session_id, db=db).by_pos

    def get_pos(pos_dict, pos, field):
        if pos in pos_dict:
            return float(getattr(pos_dict[pos], field))
        return None

    # 3) Total fold-to-3bet % i session (fra by_pos, summert)
    f3_from = fold_to_3bet_by_pos(player_name, session_id=from_session_id, db=db).by_pos
    f3_to = fold_to_3bet_by_pos(player_name, session_id=to_session_id, db=db).by_pos

    def total_fold3(by_pos_dict):
        opp = sum(int(v.opp) for v in by_pos_dict.values())
        fold = sum(int(v.fold) for v in by_pos_dict.values())
        if opp == 0:
            return None
        return round(100.0 * fold / opp, 1)

    key = CompareKeyMetricsOut(
        utg_vpip_pct_from=get_pos(pos_from, "UTG", "vpip_pct"),
        utg_vpip_pct_to=get_pos(pos_to, "UTG", "vpip_pct"),
        utg_pfr_pct_from=get_pos(pos_from, "UTG", "pfr_pct"),
        utg_pfr_pct_to=get_pos(pos_to, "UTG", "pfr_pct"),

        mp_vpip_pct_from=get_pos(pos_from, "MP", "vpip_pct"),
        mp_vpip_pct_to=get_pos(pos_to, "MP", "vpip_pct"),
        mp_pfr_pct_from=get_pos(pos_from, "MP", "pfr_pct"),
        mp_pfr_pct_to=get_pos(pos_to, "MP", "pfr_pct"),

        fold_to_3bet_pct_from=total_fold3(f3_from),
        fold_to_3bet_pct_to=total_fold3(f3_to),
    )

    # 4) Verdict + next focus (enkelt v1)
    verdict = "improved" if delta_net > 0 else "worse" if delta_net < 0 else "unchanged"

    # velg next_focus fra største negative impact i "to"-session
    next_focus = "none"
    worst = None
    for i in rep_to.impacts:
        if worst is None or i.net_total < worst.net_total:
            worst = i
    if worst:
        next_focus = worst.leak_id

    return SessionCompareOut(
        player_name=player_name,
        from_session_id=from_session_id,
        to_session_id=to_session_id,
        from_net_total=round(from_net, 2),
        to_net_total=round(to_net, 2),
        delta_net_total=delta_net,
        impacts=impacts,
        key_metrics=key,
        verdict=verdict,
        next_focus=next_focus,
    )



