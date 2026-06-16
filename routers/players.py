from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession
from sqlalchemy import func, case

from database import get_db
from schemas import PlayerStatsOut

from models import HandPlayer, Action
from schemas import PlayerHudOut

from schemas import PlayerStatsOut, PlayerHudOut, PlayerInsightsOut, LeakOut

from models import Hand
from models import HoleCards
from schemas import PlayerHudByPosOut, PosStatsOut
from schemas import PlayerFoldTo3betByPosOut, PosFold3betOut
from schemas import PlayerFoldToCbetByPosOut, PosFoldCbetOut
from schemas import PlayerCbetFlopByPosOut, PosCbetOut

from sqlalchemy import func
from schemas import PlayerCbetFlopByPosSplitOut
from sqlalchemy import func
from schemas import PlayerPreflopEdgesOut, PreflopEdgePosOut

from models import Hand
from schemas import PlayerLeakImpactOut, LeakImpactOut
from schemas import PlayerImpactPlanOut, PlanItemOut

from schemas import PlayerSpotCostsOut, SpotCostOut
from schemas import PlayerBBSpotPlanOut, SpotPlanItemOut

# imports øverst
from sqlalchemy.orm import Session
from models import Action

import re
from models import Board

from models import Hand, HandPlayer, Action
from schemas import PlayerSpotCostsOut, SpotCostOut

from schemas import PlayerFold3BetCostBySizeOut, Fold3BetBucketOut
from models import Hand
from schemas import PlayerThreeBetPlanOut, ThreeBetPlanItemOut

from schemas import PlayerFold3BetCostBySizeSplitOut, Fold3BetBucketSplitOut

from schemas import PlayerThreeBetPlanSplitOut, ThreeBetPlanSplitItemOut
from schemas import PlayerFold3BetCostBySizeSplitByOpenPosOut, Fold3BetBucketOpenPosOut

from schemas import PlayerThreeBetResponseMatrixOut, ThreeBetResponseCellOut

from schemas import PlayerThreeBetSamplingPlanOut, ThreeBetSampleTargetOut

from schemas import PlayerThreeBetSamplingPlanOut, ThreeBetSampleTargetOut
from schemas import PlayerNextSessionRules3BetOut, NextRuleOut
from schemas import PlayerHoleCardsOut, HoleCardResultOut

from schemas import LiveHint3BetRequest, LiveHint3BetResponse

from schemas import LiveHint3BetAutoResponse

from schemas import PlayerProfileOut, PlayerResultsOut
from schemas import SessionStatsOut, SessionPlayerStatsOut






router = APIRouter(prefix="/players", tags=["players"])

def conf_from_hands(n: int) -> str:
    # preflop-ish: mer stabilt, men trenger fortsatt litt sample
    if n < 25:
        return "low"
    if n < 100:
        return "medium"
    return "high"


def conf_from_opps(n: int) -> str:
    # postflop/defense oppstår sjeldnere → lavere terskler
    if n < 10:
        return "low"
    if n < 30:
        return "medium"
    return "high"



# ✅ 1) Stats for ALLE spillere (liste)
@router.get("/stats", response_model=list[PlayerStatsOut])
def players_stats(db: DbSession = Depends(get_db)):
    rows = (
        db.query(
            HandPlayer.player_name.label("player_name"),
            func.count(func.distinct(HandPlayer.hand_id)).label("hands"),
            func.coalesce(func.sum(HandPlayer.bet_total), 0.0).label("bet_total"),
            func.coalesce(func.sum(HandPlayer.win_total), 0.0).label("win_total"),
        )
        .group_by(HandPlayer.player_name)
        .order_by(func.count(func.distinct(HandPlayer.hand_id)).desc())
        .all()
    )

    return [
        PlayerStatsOut(
            player_name=r.player_name,
            hands=int(r.hands),
            bet_total=round(float(r.bet_total), 2),
            win_total=round(float(r.win_total), 2),
            net=round(float(r.win_total) - float(r.bet_total), 2),
            )
            for r in rows
    ]


# ✅ 2) Stats for ÉN spiller
@router.get("/{player_name}/stats", response_model=PlayerStatsOut)
def player_stats(player_name: str, db: DbSession = Depends(get_db)):
    row = (
        db.query(
            func.count(func.distinct(HandPlayer.hand_id)).label("hands"),
            func.coalesce(func.sum(HandPlayer.bet_total), 0.0).label("bet_total"),
            func.coalesce(func.sum(HandPlayer.win_total), 0.0).label("win_total"),
        )
        .filter(HandPlayer.player_name == player_name)
        .first()
    )

    hands = int(row.hands or 0)
    bet_total = float(row.bet_total or 0.0)
    win_total = float(row.win_total or 0.0)

    return PlayerStatsOut(
        player_name=player_name,
        hands=hands,
        bet_total=bet_total,
        win_total=win_total,
        net=win_total - bet_total,
    )

# HANDS PLAYED:
# Antall unike hender der spilleren er registrert i HandPlayer.
# (Dette er grunnlaget for alle prosentene.)

@router.get("/{player_name}/hud", response_model=PlayerHudOut)
def player_hud(player_name: str, db: DbSession = Depends(get_db)):
# 1) Hands played (fra HandPlayer)
    hands_played = (
        db.query(func.count(func.distinct(HandPlayer.hand_id)))
        .filter(HandPlayer.player_name == player_name)
        .scalar()
    ) or 0

    if hands_played == 0:
        return PlayerHudOut(
            player_name=player_name,
            hands_played=0,
            vpip_hands=0,
            vpip_pct=0.0,
            pfr_hands=0,
            pfr_pct=0.0,
            threebet_hands=0,
            threebet_pct=0.0,
            cb_flop_opp=0,
            cb_flop_made=0,
            cb_flop_pct=0.0,
            fold_to_cb_flop_opp=0,
            fold_to_cb_flop=0,
            fold_to_cb_flop_pct=0.0,
            fold_to_3bet_opp=0,
            fold_to_3bet=0,
            fold_to_3bet_pct=0.0,
            player_type="UNKNOWN",
            confidence="low",
            confidence_overall="low",
            confidence_vpip_pfr="low",
            confidence_3bet="low",
            confidence_cbet_flop="low",
            confidence_fold_to_cbet="low",
            confidence_fold_to_3bet="low",
        )
    
    # VPIP (Voluntarily Put Money In Pot):
    # Teller en hånd som VPIP hvis spilleren call'er eller raiser preflop (street=1).
    # Blinds (sb/bb) teller ikke som VPIP.
    # Vi teller bare hender hvor spilleren finnes i HandPlayer.


    # 2) VPIP-hender: call/raise på street=1
    # VPIP: call/raise preflop på hender der spilleren finnes i HandPlayer
    vpip_hands = (
        db.query(func.count(func.distinct(Action.hand_id)))
        .join(HandPlayer, HandPlayer.hand_id == Action.hand_id)
        .filter(HandPlayer.player_name == player_name)
        .filter(Action.player_name == player_name)
        .filter(Action.street == 1)
        .filter(Action.action.in_(["call", "raise"]))
        .scalar()
    ) or 0

    # PFR (Preflop Raise):
    # Teller en hånd som PFR hvis spilleren gjør action="raise" preflop (street=1),
    # og spilleren finnes i HandPlayer for hånden.

    # PFR: raise preflop på hender der spilleren finnes i HandPlayer
    pfr_hands = (
        db.query(func.count(func.distinct(Action.hand_id)))
        .join(HandPlayer, HandPlayer.hand_id == Action.hand_id)
        .filter(HandPlayer.player_name == player_name)
        .filter(Action.player_name == player_name)
        .filter(Action.street == 1)
        .filter(Action.action == "raise")
        .scalar()
    ) or 0

    vpip_pct = round(100.0 * vpip_hands / hands_played, 1)
    pfr_pct = round(100.0 * pfr_hands / hands_played, 1)

    # 3-BET:
    # Teller en hånd som 3-bet hvis spilleren raiser preflop (street=1)
    # og det finnes minst én tidligere raise i samme hånd (lavere seq).
    # (seq = rekkefølge på actions på samme street.)


    # 4) 3-bet: raise preflop der det allerede finnes en tidligere raise i samme hånd
    threebet_hands = 0

    # Hent raises kun for hands der spilleren er registrert i HandPlayer
    raises = (
        db.query(Action.hand_id, Action.seq)
        .join(HandPlayer, HandPlayer.hand_id == Action.hand_id)
        .filter(HandPlayer.player_name == player_name)
        .filter(Action.player_name == player_name)
        .filter(Action.street == 1)
        .filter(Action.action == "raise")
        .all()
    )


    for hand_id, seq in raises:
        prev_raise = (
            db.query(Action.id)
            .filter(Action.hand_id == hand_id)
            .filter(Action.street == 1)
            .filter(Action.action == "raise")
            .filter(Action.seq < seq)
            .first()
        )
        if prev_raise:
            threebet_hands += 1

    threebet_pct = round(100.0 * threebet_hands / hands_played, 1)

    # C-BET FLOP:
    # Opportunity: spilleren er siste raiser preflop (preflop aggressor)
    # og det finnes minst én flop-action (street=2).
    # Made: spilleren bettor/raiser flop (action in ["bet","raise"]).


        # 5) C-bet på flop
    cb_flop_opp = 0
    cb_flop_made = 0

    # Finn alle hand_id der spilleren faktisk har spilt (fra HandPlayer)
    hand_ids = (
        db.query(HandPlayer.hand_id)
        .filter(HandPlayer.player_name == player_name)
        .distinct()
        .all()
    )
    hand_ids = [h[0] for h in hand_ids]

    for hid in hand_ids:
    # Finn siste raiser preflop (høyeste seq med action="raise")
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        if not last_raiser:
            continue  

    # ingen preflop aggressor i denne hånden

        preflop_aggressor = last_raiser[0]
        if preflop_aggressor != player_name:
            continue  
    # spilleren var ikke aggressor

    # Sjekk om flop finnes (minst én action på street=2)
        flop_any = (
            db.query(Action.id)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .first()
        )
        if not flop_any:
            continue  
        
    # ingen flop-actions lagret

        cb_flop_opp += 1

    # Sjekk om aggressor bettor/raiser flop
        cb = (
            db.query(Action.id)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .filter(Action.player_name == player_name)
            .filter(Action.action.in_(["bet", "raise"]))
            .first()
        )
        if cb:
            cb_flop_made += 1

    cb_flop_pct = round(100.0 * cb_flop_made / cb_flop_opp, 1) if cb_flop_opp > 0 else 0.0

    # FOLD TO C-BET FLOP:
    # Opportunity: noen andre er preflop aggressor, aggressor c-better flop,
    # og spilleren har en registrert respons etter c-betten på flop.
    # Made: spillerens første respons etter c-betten er fold.
    # 6) Fold to C-bet (flop)

    fold_to_cb_flop_opp = 0
    fold_to_cb_flop = 0

    # Rebruk hand_ids fra HandPlayer (spilleren må være med i hånda)
    for hid in hand_ids:
    # Finn preflop aggressor (siste raiser preflop)
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        if not last_raiser:
            continue

        aggressor = last_raiser[0]
        if aggressor == player_name:
            continue  
    # spilleren kan ikke "folde til egen c-bet"

    # Finn første c-bet på flop fra aggressor (bet/raise)
        cb = (
            db.query(Action.seq)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .filter(Action.player_name == aggressor)
            .filter(Action.action.in_(["bet", "raise"]))
            .order_by(Action.seq.asc())
            .first()
        )
        if not cb:
            continue

        cb_seq = cb[0]

    # Finn spillerens første respons etter c-betten (seq > cb_seq)
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .filter(Action.player_name == player_name)
            .filter(Action.seq > cb_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            continue 

    # ingen respons registrert (ucomplete data)

        fold_to_cb_flop_opp += 1
        if resp[0] == "fold":
            fold_to_cb_flop += 1

    fold_to_cb_flop_pct = (
        round(100.0 * fold_to_cb_flop / fold_to_cb_flop_opp, 1)
        if fold_to_cb_flop_opp > 0
        else 0.0
    )

    # FOLD TO 3-BET:
    # Opportunity: det finnes minst to raises preflop (raise + 3-bet),
    # spilleren er ikke 3-betteren, og spilleren har en respons etter 3-betten.
    # Made: spillerens første respons etter 3-betten er fold.


    # 7) Fold to 3-bet (preflop)
    fold_to_3bet_opp = 0
    fold_to_3bet = 0

    for hid in hand_ids:
    # Finn alle preflop raises i denne hånden i rekkefølge
        raises = (
            db.query(Action.seq, Action.player_name)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )

    # Trenger minst to raises for at det skal finnes en 3-bet
        if len(raises) < 2:
            continue

    # 3-betten er den andre raisen i rekkefølgen (v1-definisjon)
        threebettor_seq, threebettor_name = raises[1]

    # Hvis spilleren selv er 3-better, teller det ikke som "fold to 3bet faced"
        if threebettor_name == player_name:
            continue

    # Finn spillerens første respons etter 3-betten (seq > threebettor_seq)
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.player_name == player_name)
            .filter(Action.seq > threebettor_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            continue

        fold_to_3bet_opp += 1
        if resp[0] == "fold":
            fold_to_3bet += 1

    fold_to_3bet_pct = (
        round(100.0 * fold_to_3bet / fold_to_3bet_opp, 1)
        if fold_to_3bet_opp > 0
        else 0.0
    )

    # Player type (enkel klassifisering) + confidence basert på sample size
    if hands_played == 0:
        return PlayerHudOut(
            player_name=player_name,
            hands_played=0,
            vpip_hands=0,
            vpip_pct=0.0,
            pfr_hands=0,
            pfr_pct=0.0,
            threebet_hands=0,
            threebet_pct=0.0,
            cb_flop_opp=0,
            cb_flop_made=0,
            cb_flop_pct=0.0,
            fold_to_cb_flop_opp=0,
            fold_to_cb_flop=0,
            fold_to_cb_flop_pct=0.0,
            fold_to_3bet_opp=0,
            fold_to_3bet=0,
            fold_to_3bet_pct=0.0,
            player_type="UNKNOWN",
            confidence="low",
            confidence_overall="low",
            confidence_vpip_pfr="low",
            confidence_3bet="low",
            confidence_cbet_flop="low",
            confidence_fold_to_cbet="low",
            confidence_fold_to_3bet="low",
        )


    # --- confidence (må alltid settes) ---
    confidence_overall = conf_from_hands(hands_played)
    confidence_vpip_pfr = conf_from_hands(hands_played)
    confidence_3bet = conf_from_hands(hands_played)
    confidence_cbet_flop = conf_from_opps(cb_flop_opp)
    confidence_fold_to_cbet = conf_from_opps(fold_to_cb_flop_opp)
    confidence_fold_to_3bet = conf_from_opps(fold_to_3bet_opp)

    # “kort” confidence for visning
    confidence = confidence_overall

    if hands_played < 20:
        player_type = "LOW_SAMPLE"



    # --- player_type (må alltid settes) ---
    vpip = vpip_pct
    pfr = pfr_pct

    if vpip < 15 and pfr < 12:
        player_type = "NIT"
    elif vpip < 22 and pfr >= 15:
        player_type = "TAG"
    elif vpip >= 30 and pfr >= 20:
        player_type = "LAG"
    elif vpip >= 35 and pfr < 15:
        player_type = "FISH"
    elif vpip < 25 and pfr < 15:
        player_type = "TP"
    elif vpip >= 25 and pfr < 15:
        player_type = "LP"
    else:
        player_type = "UNKNOWN"

    return PlayerHudOut(
        player_name=player_name,
        hands_played=int(hands_played),
        vpip_hands=int(vpip_hands),
        vpip_pct=vpip_pct,
        pfr_hands=int(pfr_hands),
        pfr_pct=pfr_pct,
        threebet_hands=int(threebet_hands),
        threebet_pct=threebet_pct,
        cb_flop_opp=int(cb_flop_opp),
        cb_flop_made=int(cb_flop_made),
        cb_flop_pct=cb_flop_pct,
        fold_to_cb_flop_opp=int(fold_to_cb_flop_opp),
        fold_to_cb_flop=int(fold_to_cb_flop),
        fold_to_cb_flop_pct=fold_to_cb_flop_pct,
        fold_to_3bet_opp=int(fold_to_3bet_opp),
        fold_to_3bet=int(fold_to_3bet),
        fold_to_3bet_pct=fold_to_3bet_pct,
        player_type=player_type,
        confidence=confidence,
        confidence_overall=confidence_overall,
        confidence_vpip_pfr=confidence_vpip_pfr,
        confidence_3bet=confidence_3bet,
        confidence_cbet_flop=confidence_cbet_flop,
        confidence_fold_to_cbet=confidence_fold_to_cbet,
        confidence_fold_to_3bet=confidence_fold_to_3bet,
    )

from schemas import PlayerLeaksOut, LeakOut

def severity_cap_by_conf(sev: str, conf: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    inv = {0: "low", 1: "medium", 2: "high"}

    cap = 2
    if conf == "low":
        cap = 1      # aldri "high" når confidence er low
    elif conf == "medium":
        cap = 2
    else:  # high
        cap = 2

    return inv[min(order.get(sev, 1), cap)]


def severity_cap_by_opp(sev: str, opp: int | None) -> str:
    # lite datagrunnlag => lavere severity
    if opp is None:
        return sev
    if opp < 5:
        return "low"
    if opp < 10 and sev == "high":
        return "medium"
    return sev


def cbet_hu_by_pos(db: DbSession, player_name: str, session_id: int | None = None) -> dict[str, dict[str, int | float]]:
    # returnerer dict: pos -> {"opp": int, "made": int, "pct": float}
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return {}

    pos_keys = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
    agg = {p: {"opp": 0, "made": 0} for p in pos_keys}

    for hid in hand_ids:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        if not hps:
            continue

        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            continue

        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        if not btn_hp:
            continue
        button_seat = btn_hp.seat

        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not me:
            continue
        my_seat = me.seat

        pos = _pos_6max(seats, button_seat, my_seat)
        if pos not in agg:
            continue

        # preflop aggressor = siste raiser
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        if not last_raiser or last_raiser[0] != player_name:
            continue

        flop_players = (
            db.query(func.count(func.distinct(Action.player_name)))
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .scalar()
        ) or 0

        if flop_players != 2:
            continue  # kun HU

        agg[pos]["opp"] += 1

        cb = (
            db.query(Action.id)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .filter(Action.player_name == player_name)
            .filter(Action.action.in_(["bet", "raise"]))
            .first()
        )
        if cb:
            agg[pos]["made"] += 1

    out = {}
    for pos, d in agg.items():
        if d["opp"] == 0:
            continue
        opp = int(d["opp"])
        made = int(d["made"])
        pct = round(100.0 * made / opp, 1)
        out[pos] = {"opp": opp, "made": made, "pct": pct}
    return out


@router.get("/{player_name}/leaks", response_model=PlayerInsightsOut)
def player_leaks(player_name: str, db: DbSession = Depends(get_db), session_id: int | None = None):
    hud = player_hud(player_name, db)

    leaks: list[LeakOut] = []
    observations: list[LeakOut] = []

    def severity_cap_by_conf(sev: str, conf: str) -> str:
        order = {"low": 0, "medium": 1, "high": 2}
        inv = {0: "low", 1: "medium", 2: "high"}

        cap = 2
        if conf == "low":
            cap = 1

        return inv[min(order.get(sev, 1), cap)]


    def severity_cap_by_opp(sev: str, opp: int | None) -> str:
        if opp is None:
            return sev
        if opp < 5:
            return "low"
        if opp < 10 and sev == "high":
            return "medium"
        return sev

    def add_item(target_list: list[LeakOut], item: LeakOut):
        item.severity = severity_cap_by_opp(item.severity, item.opp)
        if item.confidence:
            item.severity = severity_cap_by_conf(item.severity, item.confidence)
        target_list.append(item)

    def enough(opp: int | None, min_opp: int) -> bool:
        return opp is not None and opp >= min_opp

        # --- HU c-bet by pos (v1) ---
    hu = cbet_hu_by_pos(db, player_name, session_id=session_id)

    for pos in ["BTN", "CO", "MP", "UTG"]:
        if pos not in hu:
            continue

        opp = hu[pos]["opp"]
        pct = hu[pos]["pct"]

        # observation
        if opp >= 3 and pct <= 35:
            add_item(observations, LeakOut(
                leak_id=f"obs_hu_cbet_low_{pos}",
                severity="medium",
                message=f"Observasjon: HU c-bet på flop er lav fra {pos} ({pct}%) over {opp} spotter.",
                suggestion="På HU boards som er tørre/overkort-heavy kan du ofte c-bette smått oftere.",
                stat=f"hu_cbet_flop_pct_{pos}",
                value=pct,
                opp=opp,
                confidence="low" if opp < 10 else "medium",
            ))

        # leak
        if opp >= 10 and pct <= 40:
            add_item(leaks, LeakOut(
                leak_id=f"hu_cbet_low_{pos}",
                severity="medium",
                message=f"HU c-bet på flop er lav fra {pos} ({pct}%) over {opp} spotter.",
                suggestion="Legg inn flere små c-bets på tørre boards når du har range advantage.",
                stat=f"hu_cbet_flop_pct_{pos}",
                value=pct,
                opp=opp,
                confidence="medium" if opp >= 30 else "low",
            ))




    # --- severity caps ---
    def severity_cap_by_conf(sev: str, conf: str) -> str:
        order = {"low": 0, "medium": 1, "high": 2}
        inv = {0: "low", 1: "medium", 2: "high"}
        cap = 2
        if conf == "low":
            cap = 1
        return inv[min(order.get(sev, 1), cap)]

    def severity_cap_by_opp(sev: str, opp: int | None) -> str:
        if opp is None:
            return sev
        if opp < 5:
            return "low"
        if opp < 10 and sev == "high":
            return "medium"
        return sev

    def add_item(target_list: list[LeakOut], item: LeakOut):
        item.severity = severity_cap_by_opp(item.severity, item.opp)
        if item.confidence:
            item.severity = severity_cap_by_conf(item.severity, item.confidence)
        target_list.append(item)

    def enough(opp: int | None, min_opp: int) -> bool:
        return opp is not None and opp >= min_opp

    # -------------------------
    # LEAKS (strenge)
    # -------------------------
    if any(l.leak_id == "vpip_very_high" for l in leaks):
        observations = [o for o in observations if o.leak_id != "obs_vpip_high"]


    if enough(hud.fold_to_cb_flop_opp, 10) and hud.fold_to_cb_flop_pct >= 70:
        add_item(leaks, LeakOut(
            leak_id="fold_to_cbet_high",
            severity="high" if hud.fold_to_cb_flop_pct >= 80 else "medium",
            message=f"Fold to c-bet flop er høy ({hud.fold_to_cb_flop_pct}%).",
            suggestion="Forsvar mer med backdoors/overkort i posisjon. Ikke overfold mot små c-bets.",
            stat="fold_to_cb_flop_pct",
            value=hud.fold_to_cb_flop_pct,
            opp=hud.fold_to_cb_flop_opp,
            confidence=hud.confidence_fold_to_cbet,
        ))

    if enough(hud.cb_flop_opp, 10) and hud.cb_flop_pct >= 75:
        add_item(leaks, LeakOut(
            leak_id="cbet_flop_too_high",
            severity="medium",
            message=f"C-bet flop er høy ({hud.cb_flop_pct}%).",
            suggestion="Sjekk om du c-better for mye i multiway og på boards som treffer callers.",
            stat="cb_flop_pct",
            value=hud.cb_flop_pct,
            opp=hud.cb_flop_opp,
            confidence=hud.confidence_cbet_flop,
        ))

    if enough(hud.fold_to_3bet_opp, 10) and hud.fold_to_3bet_pct >= 65:
        add_item(leaks, LeakOut(
            leak_id="fold_to_3bet_high",
            severity="medium",
            message=f"Fold to 3-bet er høy ({hud.fold_to_3bet_pct}%).",
            suggestion="Bygg en enkel 'defense-plan' vs 3-bets, spesielt i posisjon.",
            stat="fold_to_3bet_pct",
            value=hud.fold_to_3bet_pct,
            opp=hud.fold_to_3bet_opp,
            confidence=hud.confidence_fold_to_3bet,
            examples=[
            "Call mer IP med: AQs/AJs/KQs/QJs og pocket pairs 77–JJ (avhengig av sizing)",
            "4-bet for value: QQ+/AK (tilpass etter motstander)",
            "4-bet bluff av og til med blockers: A5s/A4s/K5s (velg få, ikke spam)",
            ],
            rules=[
            "Neste økt: når du åpner IP og møter liten 3-bet → vurder call med suited broadways + pocket pairs",
            "Hvis du åpner mye: legg inn noen 4-bets (value + få bluffs) så du ikke blir utnyttet",
            "Mål: fold-to-3bet ofte rundt 50–70% (avhengig av stakes/population), ikke 80%+",
            ],
))

    

    if hud.hands_played >= 50 and hud.vpip_pct >= 45:
        add_item(leaks, LeakOut(
            leak_id="vpip_very_high",
            severity = "high"if hud.vpip_pct >= 60 else "medium",
            message=f"VPIP er høy ({hud.vpip_pct}%).",
            suggestion="Stram inn preflop: fjern de svakeste offsuit-hendene og reduser cold-calls OOP.",
            stat="vpip_pct",
            value=hud.vpip_pct,
            opp=hud.hands_played,
            confidence=hud.confidence_vpip_pfr,
            examples=[
            "Fold flere offsuit-kombinasjoner som K9o/Q9o/J8o/T8o fra tidlig posisjon",
            "Call mindre OOP med svake suited hender (f.eks. 96s, T4s)",
            "I stedet: åpne færre hender, og ha en klar plan for 3-bets",
            ],
            rules=[
        "Neste 50 hender: dropp 3–5 marginale opens per orbit (spesielt UTG/MP)",
        "Hvis du er OOP og ikke har en plan vs 3-bet → fold preflop",
        "Mål: VPIP ned mot 25–40% (6-max), avhengig av stil",
        ],
))


    # -------------------------
    # OBSERVATIONS (myke)
    # -------------------------
    if enough(hud.fold_to_cb_flop_opp, 2) and hud.fold_to_cb_flop_pct >= 70:
        add_item(observations, LeakOut(
            leak_id="obs_fold_to_cbet_high",
            severity="medium",
            message=f"Observasjon: Fold to c-bet flop er høy ({hud.fold_to_cb_flop_pct}%), men lite sample.",
            suggestion="Følg med på dette når opp-telleren blir større.",
            stat="fold_to_cb_flop_pct",
            value=hud.fold_to_cb_flop_pct,
            opp=hud.fold_to_cb_flop_opp,
            confidence=hud.confidence_fold_to_cbet,
        ))

    if enough(hud.cb_flop_opp, 2) and (hud.cb_flop_pct >= 75 or hud.cb_flop_pct <= 40):
        add_item(observations, LeakOut(
            leak_id="obs_cbet_flop_extreme",
            severity="medium",
            message=f"Observasjon: C-bet flop er {hud.cb_flop_pct}% (lite sample).",
            suggestion="Se om dette stabiliserer seg med flere hender.",
            stat="cb_flop_pct",
            value=hud.cb_flop_pct,
            opp=hud.cb_flop_opp,
            confidence=hud.confidence_cbet_flop,
        ))

    if enough(hud.fold_to_3bet_opp, 2) and hud.fold_to_3bet_pct >= 65:
        add_item(observations, LeakOut(
            leak_id="obs_fold_to_3bet_high",
            severity="medium",
            message=f"Observasjon: Fold to 3-bet er høy ({hud.fold_to_3bet_pct}%), men lite sample.",
            suggestion="Følg med når du får flere 3-bet-situasjoner.",
            stat="fold_to_3bet_pct",
            value=hud.fold_to_3bet_pct,
            opp=hud.fold_to_3bet_opp,
            confidence=hud.confidence_fold_to_3bet,
        ))

    if hud.hands_played >= 15 and hud.vpip_pct >= 45:
        add_item(observations, LeakOut(
            leak_id="obs_vpip_high",
            severity="medium",
            message=f"Observasjon: VPIP er høy ({hud.vpip_pct}%) på {hud.hands_played} hender.",
            suggestion="Hvis dette holder seg, stram inn preflop ranges.",
            stat="vpip_pct",
            value=hud.vpip_pct,
            opp=hud.hands_played,
            confidence=hud.confidence_vpip_pfr,
        ))

    # sortér inne i hver liste
    sev_rank = {"high": 2, "medium": 1, "low": 0}
    leaks.sort(key=lambda l: (sev_rank.get(l.severity, 0), (l.opp or 0)), reverse=True)
    observations.sort(key=lambda l: (sev_rank.get(l.severity, 0), (l.opp or 0)), reverse=True)

# Hvis en streng leak finnes, fjern tilsvarende observation
    leak_ids = {l.leak_id for l in leaks}

    if "vpip_very_high" in leak_ids:
        observations = [o for o in observations if o.leak_id != "obs_vpip_high"]

    if "fold_to_3bet_high" in leak_ids:
        observations = [o for o in observations if o.leak_id != "obs_fold_to_3bet_high"]
    if "fold_to_cbet_high" in leak_ids:
        observations = [o for o in observations if o.leak_id != "obs_fold_to_cbet_high"]

    if "cbet_flop_too_high" in leak_ids:
        observations = [o for o in observations if o.leak_id != "obs_cbet_flop_extreme"]

    return PlayerInsightsOut(player_name=player_name, leaks=leaks, observations=observations)

def _seat_order(seats: list[int], button_seat: int) -> list[int]:
    seats_sorted = sorted(seats)
    if button_seat not in seats_sorted:
        return seats_sorted
    i = seats_sorted.index(button_seat)
    # returner “ring” der setet etter BTN er først
    return seats_sorted[i+1:] + seats_sorted[:i+1]


def _pos_6max(seats: list[int], button_seat: int, player_seat: int) -> str:
    seats_sorted = sorted(seats)
    if player_seat == button_seat:
        return "BTN"

    order = _seat_order(seats_sorted, button_seat)  # [SB, BB, ..., BTN]
    if len(order) < 2:
        return "OTHER"

    sb_seat = order[0]
    bb_seat = order[1]
    if player_seat == sb_seat:
        return "SB"
    if player_seat == bb_seat:
        return "BB"

    # For 6-max: UTG, MP, CO, BTN, SB, BB
    if len(seats_sorted) == 6:
        idx = {s: i for i, s in enumerate(seats_sorted)}
        btn_i = idx[button_seat]
        p_i = idx[player_seat]
        dist = (btn_i - p_i) % 6
        if dist == 1:
            return "CO"
        if dist == 2:
            return "MP"
        if dist == 3:
            return "UTG"

    return "OTHER"


@router.get("/{player_name}/hud_by_pos", response_model=PlayerHudByPosOut)
def hud_by_pos(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    # finn hands å vurdere (ev. filtrert på session)
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerHudByPosOut(player_name=player_name, session_id=session_id, by_pos={})

    # init teller per pos
    pos_keys = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
    by_pos = {p: {"hands": 0, "vpip": 0, "pfr": 0} for p in pos_keys}

    # hent alle hand_players for disse hendene (for å finne seats og button)
    # Vi gjør det enkelt: loop hands og gjør få spørringer (OK i v1)
    for hid in hand_ids:
        # finn alle players i hånden + seats
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        if not hps:
            continue

        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:  # for lite data
            continue

        # finn button (dealer)
        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        if not btn_hp:
            continue
        button_seat = btn_hp.seat

        # finn spillerens seat i denne hånden
        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not me:
            continue
        my_seat = me.seat

        pos = _pos_6max(seats, button_seat, my_seat)
        if pos not in by_pos:
            continue

        by_pos[pos]["hands"] += 1

        # VPIP/PFR fra actions preflop for denne hånden
        vpip = db.query(Action.id).filter(
            Action.hand_id == hid,
            Action.street == 1,
            Action.player_name == player_name,
            Action.action.in_(["call", "raise"]),
        ).first() is not None

        pfr = db.query(Action.id).filter(
            Action.hand_id == hid,
            Action.street == 1,
            Action.player_name == player_name,
            Action.action == "raise",
        ).first() is not None

        if vpip:
            by_pos[pos]["vpip"] += 1
        if pfr:
            by_pos[pos]["pfr"] += 1

    # bygg response
    out: dict[str, PosStatsOut] = {}
    for pos, d in by_pos.items():
        hands = d["hands"]
        if hands == 0:
            continue
        vpip_h = d["vpip"]
        pfr_h = d["pfr"]
        out[pos] = PosStatsOut(
            hands=hands,
            vpip_hands=vpip_h,
            vpip_pct=round(100.0 * vpip_h / hands, 1),
            pfr_hands=pfr_h,
            pfr_pct=round(100.0 * pfr_h / hands, 1),
        )

    return PlayerHudByPosOut(player_name=player_name, session_id=session_id, by_pos=out)


@router.get("/{player_name}/fold_to_3bet_by_pos", response_model=PlayerFoldTo3betByPosOut)
def fold_to_3bet_by_pos(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    # finn hands (evt session-filter)
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerFoldTo3betByPosOut(player_name=player_name, session_id=session_id, by_pos={})

    pos_keys = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
    agg = {p: {"opp": 0, "fold": 0} for p in pos_keys}

    for hid in hand_ids:
        # hent players og seats
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        if not hps:
            continue

        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            continue

        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        if not btn_hp:
            continue
        button_seat = btn_hp.seat

        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not me:
            continue
        my_seat = me.seat

        pos = _pos_6max(seats, button_seat, my_seat)
        if pos not in agg:
            continue

        # finn raises preflop i denne hånden
        raises = (
            db.query(Action.seq, Action.player_name)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            continue  # ingen 3bet i hånden

        threebettor_seq, threebettor_name = raises[1]

        # hvis spilleren selv er 3-better, teller vi ikke "fold to 3bet faced"
        if threebettor_name == player_name:
            continue

        # finn spillerens første respons etter 3bet
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.player_name == player_name)
            .filter(Action.seq > threebettor_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            continue

        agg[pos]["opp"] += 1
        if resp[0] == "fold":
            agg[pos]["fold"] += 1

    # bygg response (kun posisjoner med opp>0)
    out: dict[str, PosFold3betOut] = {}
    for pos, d in agg.items():
        opp = d["opp"]
        if opp == 0:
            continue
        fold = d["fold"]
        out[pos] = PosFold3betOut(
            opp=opp,
            fold=fold,
            fold_pct=round(100.0 * fold / opp, 1)
        )

    return PlayerFoldTo3betByPosOut(player_name=player_name, session_id=session_id, by_pos=out)


@router.get("/{player_name}/fold_to_cbet_by_pos", response_model=PlayerFoldToCbetByPosOut)
def fold_to_cbet_by_pos(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerFoldToCbetByPosOut(player_name=player_name, session_id=session_id, by_pos={})

    pos_keys = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
    agg = {p: {"opp": 0, "fold": 0} for p in pos_keys}

    for hid in hand_ids:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        if not hps:
            continue

        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            continue

        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        if not btn_hp:
            continue
        button_seat = btn_hp.seat

        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not me:
            continue
        my_seat = me.seat

        pos = _pos_6max(seats, button_seat, my_seat)
        if pos not in agg:
            continue

        # preflop aggressor = siste raiser preflop
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        if not last_raiser:
            continue

        aggressor = last_raiser[0]
        if aggressor == player_name:
            continue  # kan ikke "folde til egen cbet"

        # finn første c-bet på flop fra aggressor
        cb = (
            db.query(Action.seq)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .filter(Action.player_name == aggressor)
            .filter(Action.action.in_(["bet", "raise"]))
            .order_by(Action.seq.asc())
            .first()
        )
        if not cb:
            continue

        cb_seq = cb[0]

        # finn spillerens første respons etter cbet
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .filter(Action.player_name == player_name)
            .filter(Action.seq > cb_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            continue

        agg[pos]["opp"] += 1
        if resp[0] == "fold":
            agg[pos]["fold"] += 1

    out: dict[str, PosFoldCbetOut] = {}
    for pos, d in agg.items():
        opp = d["opp"]
        if opp == 0:
            continue
        fold = d["fold"]
        out[pos] = PosFoldCbetOut(
            opp=opp,
            fold=fold,
            fold_pct=round(100.0 * fold / opp, 1),
        )

    return PlayerFoldToCbetByPosOut(player_name=player_name, session_id=session_id, by_pos=out)


@router.get("/{player_name}/cbet_flop_by_pos", response_model=PlayerCbetFlopByPosOut)
def cbet_flop_by_pos(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerCbetFlopByPosOut(player_name=player_name, session_id=session_id, by_pos={})

    pos_keys = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
    agg = {p: {"opp": 0, "made": 0} for p in pos_keys}

    for hid in hand_ids:
        # Finn seats + BTN + spillerens seat
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        if not hps:
            continue

        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            continue

        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        if not btn_hp:
            continue
        button_seat = btn_hp.seat

        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not me:
            continue
        my_seat = me.seat

        pos = _pos_6max(seats, button_seat, my_seat)
        if pos not in agg:
            continue

        # Sjekk om spilleren er preflop aggressor (siste raiser)
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        if not last_raiser:
            continue
        if last_raiser[0] != player_name:
            continue  # ikke aggressor

        # Flop må eksistere for opportunity
        flop_any = (
            db.query(Action.id)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .first()
        )
        if not flop_any:
            continue

        agg[pos]["opp"] += 1

        # Sjekk om spilleren c-better flop
        cb = (
            db.query(Action.id)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .filter(Action.player_name == player_name)
            .filter(Action.action.in_(["bet", "raise"]))
            .first()
        )
        if cb:
            agg[pos]["made"] += 1

    out: dict[str, PosCbetOut] = {}
    for pos, d in agg.items():
        opp = d["opp"]
        if opp == 0:
            continue
        made = d["made"]
        out[pos] = PosCbetOut(
            opp=opp,
            made=made,
            pct=round(100.0 * made / opp, 1),
        )

    return PlayerCbetFlopByPosOut(player_name=player_name, session_id=session_id, by_pos=out)


@router.get("/{player_name}/cbet_flop_by_pos_split", response_model=PlayerCbetFlopByPosSplitOut)
def cbet_flop_by_pos_split(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerCbetFlopByPosSplitOut(player_name=player_name, session_id=session_id, hu={}, mw={})

    pos_keys = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
    agg_hu = {p: {"opp": 0, "made": 0} for p in pos_keys}
    agg_mw = {p: {"opp": 0, "made": 0} for p in pos_keys}

    for hid in hand_ids:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        if not hps:
            continue

        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            continue

        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        if not btn_hp:
            continue
        button_seat = btn_hp.seat

        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not me:
            continue
        my_seat = me.seat

        pos = _pos_6max(seats, button_seat, my_seat)
        if pos not in agg_hu:
            continue

        # preflop aggressor = siste raiser
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 1)
            .filter(Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        if not last_raiser or last_raiser[0] != player_name:
            continue

        # Finn antall unike spillere som har en flop-action
        flop_players = (
            db.query(func.count(func.distinct(Action.player_name)))
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .scalar()
        ) or 0

        if flop_players < 2:
            continue  # ingen ekte flop-action

        bucket = "hu" if flop_players == 2 else "mw"
        agg = agg_hu if bucket == "hu" else agg_mw

        # Opportunity
        agg[pos]["opp"] += 1

        # Made c-bet
        cb = (
            db.query(Action.id)
            .filter(Action.hand_id == hid)
            .filter(Action.street == 2)
            .filter(Action.player_name == player_name)
            .filter(Action.action.in_(["bet", "raise"]))
            .first()
        )
        if cb:
            agg[pos]["made"] += 1

    def build_out(agg: dict[str, dict[str, int]]) -> dict[str, PosCbetOut]:
        out: dict[str, PosCbetOut] = {}
        for pos, d in agg.items():
            opp = d["opp"]
            if opp == 0:
                continue
            made = d["made"]
            out[pos] = PosCbetOut(
                opp=opp,
                made=made,
                pct=round(100.0 * made / opp, 1),
            )
        return out

    return PlayerCbetFlopByPosSplitOut(
        player_name=player_name,
        session_id=session_id,
        hu=build_out(agg_hu),
        mw=build_out(agg_mw),
    )

@router.get("/{player_name}/preflop_edges", response_model=PlayerPreflopEdgesOut)
def preflop_edges(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    bypos = hud_by_pos(player_name, session_id=session_id, db=db).by_pos

    # targets (6-max) – v1
    targets = {
        "UTG": {"pfr_min": 14, "pfr_max": 18},
        "MP":  {"pfr_min": 18, "pfr_max": 22},
        "CO":  {"pfr_min": 24, "pfr_max": 30},
        "BTN": {"pfr_min": 35, "pfr_max": 45},
        "SB":  {"pfr_min": 20, "pfr_max": 30},
        "BB":  {"pfr_min": 0,  "pfr_max": 15},  # BB er “spesiell”
    }

    out: dict[str, PreflopEdgePosOut] = {}

    for pos, s in bypos.items():
        hands = s.hands
        vpip = s.vpip_pct
        pfr = s.pfr_pct
        gap = round(vpip - pfr, 1)

        advice: list[str] = []
        verdict_parts: list[str] = []

        # sample guard
        if hands < 10:
            verdict = "LOW_SAMPLE"
            advice.append("For lite data i denne posisjonen ennå. Spill flere hender før du konkluderer.")
            out[pos] = PreflopEdgePosOut(hands=hands, vpip_pct=vpip, pfr_pct=pfr, gap=gap, verdict=verdict, advice=advice)
            continue

        # loose/tight vurdering via PFR target
        t = targets.get(pos, None)
        if t:
            if pfr < t["pfr_min"]:
                verdict_parts.append("TOO_TIGHT_OPEN")
                advice.append(f"Du åpner lite fra {pos}. Vurder å åpne litt flere hender når bordet er passivt.")
            elif pfr > t["pfr_max"]:
                verdict_parts.append("TOO_LOOSE_OPEN")
                advice.append(f"Du åpner veldig mye fra {pos}. Stram inn de svakeste opens (særlig offsuit).")
            else:
                verdict_parts.append("OPEN_OK")

        # passive gap vurdering
        if gap > 15:
            verdict_parts.append("TOO_CALL_HEAVY")
            advice.append("Stor VPIP−PFR gap → du caller mye. Kutt ned cold calls, spesielt OOP.")
        elif gap > 10:
            verdict_parts.append("CALL_HEAVY")
            advice.append("Gap litt høy → vurder færre calls og mer klar raise/fold-plan.")
        else:
            verdict_parts.append("GAP_OK")

        # pos-spesifikke råd
        if pos in ["UTG", "MP"] and pfr > 25:
            advice.append("Tidlig posisjon: unngå svake suited connectors/offsuit broadways. Spill tightest her.")
        if pos == "BTN" and pfr < 30:
            advice.append("BTN: du kan ofte åpne bredere når blinds er passive.")
        if pos in ["SB", "BB"] and gap > 15:
            advice.append("Blinds: pass på å ikke 'komplette/calle' for mye uten plan postflop.")

        verdict = "+".join(verdict_parts) if verdict_parts else "OK"

        out[pos] = PreflopEdgePosOut(
            hands=hands,
            vpip_pct=vpip,
            pfr_pct=pfr,
            gap=gap,
            verdict=verdict,
            advice=advice,
        )

    return PlayerPreflopEdgesOut(player_name=player_name, session_id=session_id, by_pos=out)


@router.get("/{player_name}/leak_impact", response_model=PlayerLeakImpactOut)
def leak_impact(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    # finn hand_ids (session-filter)
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerLeakImpactOut(player_name=player_name, session_id=session_id, impacts=[])


    # helper: net for hero i en hand
    def hero_net_for_hand(hid: int) -> float | None:
        hp = (
            db.query(HandPlayer)
            .filter(HandPlayer.hand_id == hid, HandPlayer.player_name == player_name)
            .first()
        )
        if not hp:
            return None
        bet = float(hp.bet_total or 0.0)
        win = float(hp.win_total or 0.0)
        return win - bet
    
    session_nets = []
    for hid in hand_ids:
        n = hero_net_for_hand(hid)
        if n is not None:
            session_nets.append(n)
    session_net_total = round(sum(session_nets), 2) if session_nets else 0.0

    # helper: pos i hand (6-max v1)
    def hero_pos_for_hand(hid: int) -> str | None:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            return None
        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not btn_hp or not me:
            return None
        return _pos_6max(seats, btn_hp.seat, me.seat)

    # helper: hero VPIP preflop i hand?
    def hero_vpip_in_hand(hid: int) -> bool:
        return db.query(Action.id).filter(
            Action.hand_id == hid,
            Action.street == 1,
            Action.player_name == player_name,
            Action.action.in_(["call", "raise"]),
        ).first() is not None

    # helper: hero fold to 3bet i hand? (samme logikk som fold_to_3bet)
    def hero_fold_to_3bet_in_hand(hid: int) -> bool | None:
        raises = (
            db.query(Action.seq, Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None  # ingen 3bet situasjon
        threebettor_seq, threebettor_name = raises[1]
        if threebettor_name == player_name:
            return None  # hero var 3better, ikke "faced"
        resp = (
            db.query(Action.action)
            .filter(
                Action.hand_id == hid,
                Action.street == 1,
                Action.player_name == player_name,
                Action.seq > threebettor_seq,
            )
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            return None
        return resp[0] == "fold"

    impacts: list[LeakImpactOut] = []

    # -----------------------------
    # IMPACT 1: VPIP for høy i tidlig pos (UTG/MP)
    # (v1: bare måle net på VPIP-hender i UTG/MP)
    # -----------------------------
    utg_mp_hands = []
    for hid in hand_ids:
        pos = hero_pos_for_hand(hid)
        if pos in ("UTG", "MP") and hero_vpip_in_hand(hid):
            utg_mp_hands.append(hid)

    nets = [hero_net_for_hand(h) for h in utg_mp_hands]
    nets = [n for n in nets if n is not None]
    if len(nets) > 0:
        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0
        impacts.append(LeakImpactOut(
            leak_id="vpip_high_early_pos",
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            note="Net på hender der du VPIP'er fra UTG/MP (ofte dyreste posisjoner).",
            share_of_total_pct=share,

        ))

    # -----------------------------
    # IMPACT 2: Fold to 3-bet (hender der du faktisk folder)
    # -----------------------------
    fold3_hands = []
    for hid in hand_ids:
        f = hero_fold_to_3bet_in_hand(hid)
        if f is True:
            fold3_hands.append(hid)

    nets = [hero_net_for_hand(h) for h in fold3_hands]
    nets = [n for n in nets if n is not None]
    if len(nets) > 0:
        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0
        impacts.append(LeakImpactOut(
            leak_id="fold_to_3bet_cost",
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            note="Net på hender der du møter 3-bet og folder (taper ofte open-size).",
            share_of_total_pct=share,

        ))

    # -----------------------------
    # IMPACT 3: BB fold to c-bet cost
    # -----------------------------
    bb_fold_cbet_hands = []

    for hid in hand_ids:
        pos = hero_pos_for_hand(hid)
        if pos != "BB":
            continue

        # Finn preflop aggressor (siste raiser preflop)
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        if not last_raiser:
            continue

        aggressor = last_raiser[0]
        if aggressor == player_name:
            continue  # kan ikke folde til egen c-bet

        # Finn første c-bet på flop fra aggressor
        cb = (
            db.query(Action.seq)
            .filter(Action.hand_id == hid, Action.street == 2)
            .filter(Action.player_name == aggressor)
            .filter(Action.action.in_(["bet", "raise"]))
            .order_by(Action.seq.asc())
            .first()
        )
        if not cb:
            continue

        cb_seq = cb[0]

        # Finn hero sin første respons etter c-betten
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid, Action.street == 2)
            .filter(Action.player_name == player_name)
            .filter(Action.seq > cb_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            continue

        if resp[0] == "fold":
            bb_fold_cbet_hands.append(hid)

    nets = [hero_net_for_hand(h) for h in bb_fold_cbet_hands]
    nets = [n for n in nets if n is not None]
    if len(nets) > 0:
        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0

        impacts.append(LeakImpactOut(
            leak_id="bb_fold_to_cbet_cost",
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            share_of_total_pct=share,
            note="Net på hender der du sitter BB, møter c-bet på flop og folder (kan være overfold-leak).",
        ))


    # sorter: mest negativ net_total først
    impacts.sort(key=lambda x: x.net_total)

    return PlayerLeakImpactOut(
    player_name=player_name,
    session_id=session_id,
    session_net_total=session_net_total,
    impacts=impacts
    )
    

@router.get("/{player_name}/impact_plan", response_model=PlayerImpactPlanOut)
def impact_plan(
    player_name: str,
    session_id: int | None = None,
    min_hands: int = 1,
    min_abs_net: float = 0.0,
    db: DbSession = Depends(get_db),
):
    report = leak_impact(player_name, session_id=session_id, db=db)

    filtered_impacts = [
        i for i in report.impacts
        if (i.hands is None or i.hands >= min_hands) and (abs(float(i.net_total)) >= min_abs_net)
    ]
    impacts_source = filtered_impacts or report.impacts

    # sortér impacts: høyest andel først (mest viktig)
    impacts = sorted(
        impacts_source,
        key=lambda x: (abs(x.share_of_total_pct), abs(x.net_total)),
        reverse=True,
    )

    plan: list[PlanItemOut] = []
    priority = 1

    for imp in impacts[:3]:  # topp 3 max
        if imp.leak_id == "vpip_high_early_pos":
            plan.append(PlanItemOut(
                title="Stram inn UTG/MP preflop",
                priority=priority,
                impact_share_pct=imp.share_of_total_pct,
                rationale=f"Dette forklarer ca {imp.share_of_total_pct}% av tapet ditt i sessionen.",
                actions=[
                    "Neste økt: kutt 30–50% av UTG/MP opens (dropp svak offsuit og lave suited).",
                    "Ingen plan vs 3-bet OOP? Fold preflop i stedet for å spille marginalt.",
                    "Mål: UTG/MP PFR ned mot ~15–25% (avhengig av bord).",
                ],
            ))
            priority += 1

        elif imp.leak_id == "fold_to_3bet_cost":
            plan.append(PlanItemOut(
                title="Lag en enkel 3-bet defense-plan",
                priority=priority,
                impact_share_pct=imp.share_of_total_pct,
                rationale=f"Du taper ofte open-size når du folder vs 3-bet (ca {imp.share_of_total_pct}% av tapet).",
                actions=[
                    "IP: call litt mer med AQs/AJs/KQs og pocket pairs 77–JJ (tilpass sizing).",
                    "Ha 1–2 4-bet value-hender (QQ+/AK) og 1 bluff med blockers (A5s) i noen spots.",
                    "Mål: fold-to-3bet ned fra 80%+ mot ~55–70% (avhenger av stakes).",
                ],
            ))
            priority += 1

        elif imp.leak_id == "bb_fold_to_cbet_cost":
            plan.append(PlanItemOut(
                title="BB: ikke overfold mot små c-bets (watchlist)",
                priority=priority,
                impact_share_pct=imp.share_of_total_pct,
                rationale=f"Foreløpig lite sample, men dyrt per hånd når det skjer.",
                actions=[
                    "Neste økt: velg 1–2 ekstra defenses i BB (backdoor/overkort) før du autopiloter fold.",
                    "Forsvar mer mot små sizing, fold mer mot store sizing (tommelregel).",
                    "Mål: få 10+ opps før du konkluderer hardt.",
                ],
            ))
            priority += 1

    return PlayerImpactPlanOut(
        player_name=report.player_name,
        session_id=report.session_id,
        session_net_total=report.session_net_total,
        top_impacts=impacts[:3],
        plan=plan
    )

# ✅ LEGG DENNE HØYT OPPE I FILEN (før router-funksjoner)

def pot_before_action(db: DbSession, hid: int, street: int, seq: int) -> float:
    rows = (
        db.query(Action.street, Action.seq, Action.action, Action.amount)
        .filter(Action.hand_id == hid)
        .order_by(Action.street.asc(), Action.seq.asc())
        .all()
    )

    pot = 0.0
    for st, s, act, amt in rows:
        if (st > street) or (st == street and s >= seq):
            break
        if act in ("sb", "bb", "call", "raise", "bet"):
            pot += float(amt or 0.0)

    return pot



@router.get("/{player_name}/spot_costs_bb", response_model=PlayerSpotCostsOut)
def spot_costs_bb(
    player_name: str,
    session_id: int | None = None,
    min_hands: int = 1,
    min_abs_net: float = 0.0,
    db: DbSession = Depends(get_db),
):
    # ---- finn hands i session ----
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerSpotCostsOut(
            player_name=player_name,
            session_id=session_id,
            session_net_total=0.0,
            spots=[],
        )

    # ---- helpers ----
    def hero_net_for_hand(hid: int) -> float | None:
        hp = (
            db.query(HandPlayer)
            .filter(HandPlayer.hand_id == hid, HandPlayer.player_name == player_name)
            .first()
        )
        if not hp:
            return None
        bet = float(hp.bet_total or 0.0)
        win = float(hp.win_total or 0.0)
        return win - bet

    # session total net
    session_nets: list[float] = []
    for hid in hand_ids:
        n = hero_net_for_hand(hid)
        if n is not None:
            session_nets.append(n)
    session_net_total = round(sum(session_nets), 2) if session_nets else 0.0

    # pos i hand (bruker pos-funksjonen din)
    def hero_pos_for_hand(hid: int) -> str | None:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            return None
        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not btn_hp or not me:
            return None
        return _pos_6max(seats, btn_hp.seat, me.seat)

    # Finn første flop c-bet (bet/raise) fra preflop aggressor og returner bet% av pot før bet
    def first_flop_cbet_pct(hid: int) -> float | None:

        # preflop aggressor = siste raiser
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        if not last_raiser:
            return None
        aggressor = last_raiser[0]

        cb_row = (
            db.query(Action.seq, Action.amount)
            .filter(Action.hand_id == hid, Action.street == 2)
            .filter(Action.player_name == aggressor)
            .filter(Action.action.in_(["bet", "raise"]))
            .order_by(Action.seq.asc())
            .first()
        )
        if not cb_row:
            return None

        cb_seq, cb_amt = cb_row
        cb_amt = float(cb_amt or 0.0)

        pot_before = pot_before_action(db, hid, street=2, seq=cb_seq)
        if pot_before <= 0:
            return None

        return round(100.0 * (cb_amt / pot_before), 1)
    
    def _parse_card(token: str) -> tuple[str | None, str | None]:
        """
        Støtter både:
        - 'H10' (suit først)
        - 'Ah' / 'Td' (suit sist)
        Returnerer: (rank, suit) der rank er 'A,K,Q,J,T,9..2'
        """
        if not token:
            return None, None
        t = token.strip()
        if not t:
            return None, None

        suits = {"S", "H", "D", "C", "s", "h", "d", "c"}

        # suit først: H10, DJ, C2 ...
        if t[0] in suits:
            suit = t[0].upper()
            rank_raw = t[1:].upper()
        # suit sist: Ah, Td, 7c ...
        elif t[-1] in suits:
            suit = t[-1].upper()
            rank_raw = t[:-1].upper()
        else:
            return None, None

        if rank_raw == "10":
            rank = "T"
        else:
            rank = rank_raw

        return rank, suit


    def _simple_flop_type(hid: int) -> str:
        b = db.query(Board).filter(Board.hand_id == hid).first()
        if not b or not b.flop1 or not b.flop2 or not b.flop3:
            return "unknown"

        cards = [b.flop1, b.flop2, b.flop3]
        parsed = [_parse_card(c) for c in cards]
        ranks = [r for r, s in parsed]
        suits = [s for r, s in parsed]

        if any(r is None for r in ranks) or any(s is None for s in suits):
            return "unknown"

        # paired?
        if len(set(ranks)) < 3:
            return "paired"

        # rainbow?
        rainbow = len(set(suits)) == 3

        # rank values for "connected"
        val_map = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10,
                "9": 9, "8": 8, "7": 7, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2}
        vals = sorted(val_map.get(r, 0) for r in ranks)
        if 0 in vals:
            return "unknown"

        spread = vals[-1] - vals[0]
        connected = spread <= 4  # grov v1

        high = any(r in {"A", "K", "Q"} for r in ranks)
        low = any(r in {"2", "3", "4", "5", "6"} for r in ranks)

        if high and rainbow and not connected:
            return "dry_high_rainbow"
        if low and connected:
            return "low_connected"
        if connected:
            return "connected"
        return "unknown"


    spots: list[SpotCostOut] = []

    def threebet_size_bb(hid: int) -> float | None:
        h = db.query(Hand).filter(Hand.id == hid).first()
        if not h or not h.bb:
            return None
        bb = float(h.bb)
        if bb <= 0:
            return None

        # finn raises preflop i rekkefølge
        raises = (
            db.query(Action.seq, Action.amount)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None  # ingen 3-bet

        # 2. raise = 3-bet (v1)
        _, amt = raises[1]
        return round(float(amt or 0.0) / bb, 1)



    # -------------------------------------------------------
    # SPOT 1: BB fold vs small c-bet (<=33% pot)
    # -------------------------------------------------------
    bb_fold_small_cbet_hands: list[int] = []

    for hid in hand_ids:
        if hero_pos_for_hand(hid) != "BB":
            continue

        # preflop aggressor
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        if not last_raiser:
            continue
        aggressor = last_raiser[0]
        if aggressor == player_name:
            continue

        # første flop bet/raise fra aggressor
        cb_row = (
            db.query(Action.seq, Action.amount)
            .filter(Action.hand_id == hid, Action.street == 2)
            .filter(Action.player_name == aggressor)
            .filter(Action.action.in_(["bet", "raise"]))
            .order_by(Action.seq.asc())
            .first()
        )
        if not cb_row:
            continue

        cb_seq, cb_amt = cb_row
        cb_amt = float(cb_amt or 0.0)

        pot_before = pot_before_action(db, hid, street=2, seq=cb_seq)
        if pot_before <= 0:
            continue

        bet_pct = cb_amt / pot_before
        if bet_pct > 0.33:
            continue  # ikke "small" i pot%

        # hero respons etter c-bet
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid, Action.street == 2)
            .filter(Action.player_name == player_name)
            .filter(Action.seq > cb_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            continue

        if resp[0] == "fold":
            bb_fold_small_cbet_hands.append(hid)

    nets = [hero_net_for_hand(h) for h in bb_fold_small_cbet_hands]
    nets = [n for n in nets if n is not None]
    if nets:
        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0

        ex_ids = bb_fold_small_cbet_hands[:3]
        ex_details: list[str] = []
        for h in ex_ids:
            pct = first_flop_cbet_pct(h)
            ft = _simple_flop_type(h)

            pct_txt = f"{pct}% pot" if pct is not None else "ukjent sizing"
            if ft != "unknown":
                ex_details.append(f"hand {h}: flop c-bet ≈ {pct_txt} | flop: {ft}")
            else:
                ex_details.append(f"hand {h}: flop c-bet ≈ {pct_txt}")


        spots.append(SpotCostOut(
            spot_id="bb_fold_vs_small_cbet",
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            share_of_total_pct=share,
            note="BB: du folder mot små c-bets (<=33% pot, v1 pot-estimat uten rake).",
            example_hand_ids=ex_ids,
            example_details=ex_details,
        ))

    # -------------------------------------------------------
    # SPOT 2: BB call preflop -> fold flop, bucketed by flop c-bet size (35/60)
    # -------------------------------------------------------
    buckets = {
        "bb_call_pre_fold_flop_vs_small": [],
        "bb_call_pre_fold_flop_vs_medium": [],
        "bb_call_pre_fold_flop_vs_big": [],
    }

    for hid in hand_ids:
        if hero_pos_for_hand(hid) != "BB":
            continue

        # hero caller preflop?
        did_call_pre = db.query(Action.id).filter(
            Action.hand_id == hid,
            Action.street == 1,
            Action.player_name == player_name,
            Action.action == "call",
        ).first() is not None
        if not did_call_pre:
            continue

        # hero folder på flop?
        did_fold_flop = db.query(Action.id).filter(
            Action.hand_id == hid,
            Action.street == 2,
            Action.player_name == player_name,
            Action.action == "fold",
        ).first() is not None
        if not did_fold_flop:
            continue

        # c-bet sizing i pot% (fra helperen du allerede har)
        pct = first_flop_cbet_pct(hid)
        if pct is None:
            continue  # v1: hvis vi ikke finner c-bet, skip

        # bucket (35/60)
        if pct <= 35.0:
            buckets["bb_call_pre_fold_flop_vs_small"].append(hid)
        elif pct <= 60.0:
            buckets["bb_call_pre_fold_flop_vs_medium"].append(hid)
        else:
            buckets["bb_call_pre_fold_flop_vs_big"].append(hid)

    # lag SpotCostOut for hver bucket
    for spot_id, hlist in buckets.items():
        nets = [hero_net_for_hand(h) for h in hlist]
        nets = [n for n in nets if n is not None]
        if not nets:
            continue

        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0

        ex_ids = hlist[:3]
        ex_details: list[str] = []
        for h in ex_ids:
            pct = first_flop_cbet_pct(h)
            if pct is None:
                ex_details.append(f"hand {h}: flop c-bet: ukjent")
            else:
                ex_details.append(f"hand {h}: flop c-bet ≈ {pct}% pot")

        note_map = {
            "bb_call_pre_fold_flop_vs_small": "BB: call pre -> fold flop vs SMALL-ish c-bet (≤35% pot).",
            "bb_call_pre_fold_flop_vs_medium": "BB: call pre -> fold flop vs MEDIUM c-bet (35–60% pot).",
            "bb_call_pre_fold_flop_vs_big": "BB: call pre -> fold flop vs BIG c-bet (>60% pot).",
        }

        spots.append(SpotCostOut(
            spot_id=spot_id,
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            share_of_total_pct=share,
            note=note_map.get(spot_id, "BB: call pre -> fold flop (bucketed)."),
            example_hand_ids=ex_ids,
            example_details=ex_details,
        ))

    


# -------------------------------------------------------
# SPOT 3: BB cold-call 3-bet -> fold flop
# -------------------------------------------------------
    bb_call_3bet_fold_flop_hands = []

    for hid in hand_ids:
        if hero_pos_for_hand(hid) != "BB":
            continue

        # finn alle raises preflop
        preflop_raises = (
            db.query(Action)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )

        # må være minst open + 3-bet
        if len(preflop_raises) < 2:
            continue

        # hero caller preflop?
        did_call_pre = (
            db.query(Action.id)
            .filter(
                Action.hand_id == hid,
                Action.street == 1,
                Action.player_name == player_name,
                Action.action == "call",
            )
            .first()
            is not None
        )
        if not did_call_pre:
            continue

        # hero folder på flop?
        did_fold_flop = (
            db.query(Action.id)
            .filter(
                Action.hand_id == hid,
                Action.street == 2,
                Action.player_name == player_name,
                Action.action == "fold",
            )
            .first()
            is not None
        )
        if not did_fold_flop:
            continue

        bb_call_3bet_fold_flop_hands.append(hid)

    nets = [hero_net_for_hand(h) for h in bb_call_3bet_fold_flop_hands]
    nets = [n for n in nets if n is not None]

    if nets:
        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0

        ex_ids = bb_call_3bet_fold_flop_hands[:3]
        ex_details: list[str] = []
        for h in ex_ids:
            pct = first_flop_cbet_pct(h)
            tbb = threebet_size_bb(h)

            pct_txt = f"{pct}% pot" if pct is not None else "ukjent cbet%"
            tbb_txt = f"3bet≈{tbb}bb" if tbb is not None else "3bet=ukjent"

            ex_details.append(f"hand {h}: {tbb_txt} | flop c-bet ≈ {pct_txt}")


        spots.append(SpotCostOut(
            spot_id="bb_call_3bet_fold_flop",
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            share_of_total_pct=share,
            note="BB: du cold-caller 3-bet preflop og folder på flop (dyr OOP-spot).",
            example_hand_ids=ex_ids,
            example_details=ex_details,
        ))

    # filtrer på minimums-krav (bruk OR for å fange opp enten volum eller impact)
    spots = [
        s for s in spots
        if s.hands >= min_hands or abs(float(s.net_total)) >= min_abs_net
    ]

    # sorter: mest negativ total først
    spots.sort(key=lambda s: s.net_total)

    return PlayerSpotCostsOut(
        player_name=player_name,
        session_id=session_id,
        session_net_total=session_net_total,
        spots=spots,
    )


def parse_cbet_pcts(details: list[str] | None) -> list[float]:
    if not details:
        return []
    pcts = []
    for s in details:
        # matcher f.eks. "hand 70: flop c-bet ≈ 34.1% pot"
        m = re.search(r"(\d+(\.\d+)?)%\s*pot", s)
        if m:
            pcts.append(float(m.group(1)))
    return pcts

def size_bucket(avg_pct: float) -> str:
    # buckets i pot%
    if avg_pct <= 33.0:
        return "small"
    if avg_pct <= 55.0:
        return "medium"
    return "big"

def defend_rules_for_bucket(bucket: str) -> list[str]:
    # V1 tommelregler (ikke GTO, men praktisk og god)
    if bucket == "small":
        return [
            "Vs SMALL c-bet (<=33% pot): forsvar mer – call med par/draw/backdoor/overkort+backdoor.",
            "Ikke autopilot-fold alt som bommer; du får gode odds mot små bets.",
        ]
    if bucket == "medium":
        return [
            "Vs MEDIUM c-bet (33–55% pot): forsvar med par, gode draws og noen overkort+backdoor.",
            "Fold mer av 'ren luft' uten backdoors.",
        ]
    return [
        "Vs BIG c-bet (>55% pot): fold mer – fortsett hovedsakelig med par+ og sterke draws.",
        "Hvis du ofte call→fold vs store bets: kutt preflop-calls som ikke tåler press.",
    ]


@router.get("/{player_name}/spot_costs_ip", response_model=PlayerSpotCostsOut)
def spot_costs_ip(
    player_name: str,
    session_id: int | None = None,
    min_hands: int = 5,
    min_abs_net: float = 0.10,
    db: DbSession = Depends(get_db),
):

    # ---- finn hands i session ----
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerSpotCostsOut(player_name=player_name, session_id=session_id, session_net_total=0.0, spots=[])

    # ---- helpers ----
    def hero_net_for_hand(hid: int) -> float | None:
        hp = (
            db.query(HandPlayer)
            .filter(HandPlayer.hand_id == hid, HandPlayer.player_name == player_name)
            .first()
        )
        if not hp:
            return None
        bet = float(hp.bet_total or 0.0)
        win = float(hp.win_total or 0.0)
        return win - bet

    # session total net
    session_nets: list[float] = []
    for hid in hand_ids:
        n = hero_net_for_hand(hid)
        if n is not None:
            session_nets.append(n)
    session_net_total = round(sum(session_nets), 2) if session_nets else 0.0

    # pos i hand
    def hero_pos_for_hand(hid: int) -> str | None:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            return None
        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not btn_hp or not me:
            return None
        return _pos_6max(seats, btn_hp.seat, me.seat)

    def preflop_aggressor(hid: int) -> str | None:
        last_raiser = (
            db.query(Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.desc())
            .first()
        )
        return last_raiser[0] if last_raiser else None

    def first_flop_bet_pct(hid: int, bettor: str) -> tuple[float | None, int | None]:
        row = (
            db.query(Action.seq, Action.amount)
            .filter(Action.hand_id == hid, Action.street == 2)
            .filter(Action.player_name == bettor)
            .filter(Action.action.in_(["bet", "raise"]))
            .order_by(Action.seq.asc())
            .first()
        )
        if not row:
            return None, None
        seq, amt = row
        amt = float(amt or 0.0)
        pot_before = pot_before_action(db, hid, street=2, seq=seq)
        if pot_before <= 0:
            return None, None
        pct = round(100.0 * (amt / pot_before), 1)
        return pct, seq

    def bucket35_60(pct: float) -> str:
        if pct <= 35.0:
            return "small"
        if pct <= 60.0:
            return "medium"
        return "big"

    spots: list[SpotCostOut] = []

    # -------------------------------------------------------
    # SPOT A: IP open -> check flop -> fold vs bet (give-up)
    # CO/BTN only, hero must be preflop aggressor
    # -------------------------------------------------------
    ip_open_giveup_flop_hands: list[int] = []

    for hid in hand_ids:
        pos = hero_pos_for_hand(hid)
        if pos not in ("CO", "BTN"):
            continue

        agg = preflop_aggressor(hid)
        if agg != player_name:
            continue  # hero må være aggressor preflop

        # hero check på flop?
        hero_check = (
            db.query(Action.seq)
            .filter(Action.hand_id == hid, Action.street == 2)
            .filter(Action.player_name == player_name, Action.action == "check")
            .order_by(Action.seq.asc())
            .first()
        )
        if not hero_check:
            continue

        hero_check_seq = hero_check[0]

        # finn første bet/raise fra villain etter hero-check
        vill_bet = (
            db.query(Action.player_name, Action.seq)
            .filter(Action.hand_id == hid, Action.street == 2)
            .filter(Action.seq > hero_check_seq)
            .filter(Action.action.in_(["bet", "raise"]))
            .order_by(Action.seq.asc())
            .first()
        )
        if not vill_bet:
            continue

        villain_name, vill_bet_seq = vill_bet

        # hero folder etter villain bet?
        hero_fold = (
            db.query(Action.id)
            .filter(Action.hand_id == hid, Action.street == 2)
            .filter(Action.player_name == player_name, Action.action == "fold")
            .filter(Action.seq > vill_bet_seq)
            .first()
        )
        if not hero_fold:
            continue

        ip_open_giveup_flop_hands.append(hid)

    nets = [hero_net_for_hand(h) for h in ip_open_giveup_flop_hands]
    nets = [n for n in nets if n is not None]
    if nets:
        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0

        ex_ids = ip_open_giveup_flop_hands[:3]
        ex_details: list[str] = []
        for h in ex_ids:
            # finn villain bet% (første bet etter hero check)
            agg = preflop_aggressor(h)
            # finn hero check seq
            hero_check_seq = (
                db.query(Action.seq)
                .filter(Action.hand_id == h, Action.street == 2)
                .filter(Action.player_name == player_name, Action.action == "check")
                .order_by(Action.seq.asc())
                .first()
            )
            if not hero_check_seq:
                ex_details.append(f"hand {h}: villain bet: ukjent")
                continue

            vill_bet = (
                db.query(Action.player_name, Action.seq)
                .filter(Action.hand_id == h, Action.street == 2)
                .filter(Action.seq > hero_check_seq[0])
                .filter(Action.action.in_(["bet", "raise"]))
                .order_by(Action.seq.asc())
                .first()
            )
            if not vill_bet:
                ex_details.append(f"hand {h}: villain bet: ukjent")
                continue

            villain_name, bet_seq = vill_bet
            pct, _ = first_flop_bet_pct(h, villain_name)
            if pct is None:
                ex_details.append(f"hand {h}: villain bet: ukjent")
            else:
                ex_details.append(f"hand {h}: villain bet ≈ {pct}% pot")

        spots.append(SpotCostOut(
            spot_id="ip_open_giveup_flop",
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            share_of_total_pct=share,
            note="CO/BTN: du er preflop aggressor, checker flop og folder vs bet (give-up).",
            example_hand_ids=ex_ids,
            example_details=ex_details,
        ))

    # -------------------------------------------------------
    # SPOT B: IP c-bet flop bucketed by size (35/60)
    # CO/BTN only, hero must be preflop aggressor
    # -------------------------------------------------------
    cbet_buckets = {
        "ip_cbet_flop_vs_small": [],
        "ip_cbet_flop_vs_medium": [],
        "ip_cbet_flop_vs_big": [],
    }

    for hid in hand_ids:
        pos = hero_pos_for_hand(hid)
        if pos not in ("CO", "BTN"):
            continue

        agg = preflop_aggressor(hid)
        if agg != player_name:
            continue

        pct, seq = first_flop_bet_pct(hid, bettor=player_name)
        if pct is None or seq is None:
            continue  # hero c-bettet ikke flop

        b = bucket35_60(pct)
        if b == "small":
            cbet_buckets["ip_cbet_flop_vs_small"].append(hid)
        elif b == "medium":
            cbet_buckets["ip_cbet_flop_vs_medium"].append(hid)
        else:
            cbet_buckets["ip_cbet_flop_vs_big"].append(hid)

    note_map = {
        "ip_cbet_flop_vs_small": "CO/BTN: c-bet flop (≤35% pot).",
        "ip_cbet_flop_vs_medium": "CO/BTN: c-bet flop (35–60% pot).",
        "ip_cbet_flop_vs_big": "CO/BTN: c-bet flop (>60% pot).",
    }

    for spot_id, hlist in cbet_buckets.items():
        nets = [hero_net_for_hand(h) for h in hlist]
        nets = [n for n in nets if n is not None]
        if not nets:
            continue

        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0

        ex_ids = hlist[:3]
        ex_details: list[str] = []
        for h in ex_ids:
            pct, _ = first_flop_bet_pct(h, bettor=player_name)
            ex_details.append(f"hand {h}: hero c-bet ≈ {pct}% pot" if pct is not None else f"hand {h}: hero c-bet: ukjent")

        spots.append(SpotCostOut(
            spot_id=spot_id,
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            share_of_total_pct=share,
            note=note_map.get(spot_id, "CO/BTN: c-bet flop (bucketed)."),
            example_hand_ids=ex_ids,
            example_details=ex_details,
        ))

    # filter bort støy
    spots = [
        s for s in spots
        if s.hands >= min_hands and abs(float(s.net_total)) >= min_abs_net
    ]


    # sorter: mest negativ total først
    spots.sort(key=lambda s: s.net_total)

    return PlayerSpotCostsOut(
        player_name=player_name,
        session_id=session_id,
        session_net_total=session_net_total,
        spots=spots,
    )



@router.get("/{player_name}/spot_plan_bb", response_model=PlayerBBSpotPlanOut)
def spot_plan_bb(
    player_name: str,
    session_id: int | None = None,
    min_hands: int = 3,
    min_abs_net: float = 0.1,
    db: DbSession = Depends(get_db),
):
    report = spot_costs_bb(
        player_name,
        session_id=session_id,
        min_hands=min_hands,
        min_abs_net=min_abs_net,
        db=db,
    )

    filtered_spots = [
        s for s in report.spots
        if s.hands >= min_hands or abs(float(s.net_total)) >= min_abs_net
    ]
    spots_source = filtered_spots or report.spots

    # sortér spots: størst andel først
    spots = sorted(
        spots_source,
        key=lambda s: (abs(s.share_of_total_pct), abs(s.net_total)),
        reverse=True,
    )

    plan: list[SpotPlanItemOut] = []
    priority = 1

    for sp in spots[:3]:

        # ---- bucketed BB call->fold spots ----
        if sp.spot_id.startswith("bb_call_pre_fold_flop_vs_"):
            # suffix = small / medium / big
            suffix = sp.spot_id.split("_vs_")[-1]

            pcts = parse_cbet_pcts(sp.example_details)
            avg = round(sum(pcts) / len(pcts), 1) if pcts else None

            # bucket summary (35/60 cutoffs)
            small_n = sum(1 for x in pcts if x <= 35.0)
            med_n = sum(1 for x in pcts if 35.0 < x <= 60.0)
            big_n = sum(1 for x in pcts if x > 60.0)

            if pcts:
                bucket_summary = f"Buckets: small={small_n}, medium={med_n}, big={big_n}."
            else:
                bucket_summary = "Ingen sizing-data på eksempelhender ennå."

            # actions per suffix (hovedpoenget)
            actions = [
                "BB preflop: call litt strammere med hender som ofte ender i 'call→fold'.",
                "Hvis du caller BB: ha en plan for minst én type flop du fortsetter på (par/draw/backdoor/overkort+backdoor).",
            ]

            if suffix == "small":
                actions += [
                    "Vs SMALL-ish c-bet (≤35% pot): øk forsvar. Call med par/draw og flere overkort+backdoor.",
                    "Mål: ikke auto-fold alt som bommer når sizing er liten.",
                ]
            elif suffix == "medium":
                actions += [
                    "Vs MEDIUM c-bet (35–60% pot): forsvar med par, gode draws og noen overkort+backdoor.",
                    "Fold mer av ren luft uten backdoors.",
                ]
            elif suffix == "big":
                actions += [
                    "Vs BIG c-bet (>60% pot): fold mer – fortsett hovedsakelig med par+ og sterke draws.",
                    "Hvis du ofte call→fold vs store bets: kutt preflop-calls som ikke tåler press.",
                ]

            plan.append(SpotPlanItemOut(
                spot_id=sp.spot_id,
                priority=priority,
                share_of_total_pct=sp.share_of_total_pct,
                rationale=(
                    f"BB call→fold flop ({suffix}) står for ca {sp.share_of_total_pct}% av tapet. "
                    + (f"Eksempel-betsizing avg ≈ {avg}% pot. " if avg is not None else "")
                    + bucket_summary
                ),
                actions=actions,
            ))
            priority += 1

        # ---- 3-bet pot spot ----
        elif sp.spot_id == "bb_call_3bet_fold_flop":
            pcts = parse_cbet_pcts(sp.example_details)
            avg = round(sum(pcts) / len(pcts), 1) if pcts else None

            bucket = size_bucket(avg) if avg is not None else "medium"
            sizing_actions = defend_rules_for_bucket(bucket)

            plan.append(SpotPlanItemOut(
                spot_id=sp.spot_id,
                priority=priority,
                share_of_total_pct=sp.share_of_total_pct,
                rationale=(
                    f"BB cold-call 3-bet → fold flop er dyrt per forekomst. "
                    + (f"Eksempel-betsizing ≈ {avg}% pot ({bucket})." if avg is not None else "")
                ),
                actions=[
                    "Preflop (viktigst): BB vs 3-bet OOP → kutt cold-calls kraftig. Velg mest fold eller 4-bet (value).",
                    "Call 3-bet OOP kun med hender som tåler c-bets på mange flops (typisk TT+ og AQs+ som startregel).",
                    "Hvis du caller likevel: bestem på forhånd hvilke flopper du fortsetter på (par/draw/backdoor), ellers er call pre ofte -EV.",
                    *sizing_actions,
                ],
            ))
            priority += 1

        # ---- fallback ----
        else:
            plan.append(SpotPlanItemOut(
                spot_id=sp.spot_id,
                priority=priority,
                share_of_total_pct=sp.share_of_total_pct,
                rationale="Spot koster penger – følg med og samle mer sample.",
                actions=[
                    "Samle mer sample (flere hender).",
                    "Se på hand histories for dette spot_id og finn mønster.",
                ],
            ))
            priority += 1

    return PlayerBBSpotPlanOut(
        player_name=report.player_name,
        session_id=report.session_id,
        session_net_total=report.session_net_total,
        top_spots=spots[:3],
        plan=plan,
    )


@router.get("/{player_name}/fold_to_3bet_cost_by_size", response_model=PlayerFold3BetCostBySizeOut)
def fold_to_3bet_cost_by_size(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    # ---- hands ----
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerFold3BetCostBySizeOut(player_name=player_name, session_id=session_id, session_net_total=0.0, buckets=[])

    # ---- helpers ----
    def hero_net_for_hand(hid: int) -> float | None:
        hp = db.query(HandPlayer).filter(HandPlayer.hand_id == hid, HandPlayer.player_name == player_name).first()
        if not hp:
            return None
        return float(hp.win_total or 0.0) - float(hp.bet_total or 0.0)

    def hand_bb(hid: int) -> float | None:
        h = db.query(Hand).filter(Hand.id == hid).first()
        if not h or not h.bb:
            return None
        bb = float(h.bb)
        return bb if bb > 0 else None

    def threebet_size_bb(hid: int) -> float | None:
        bb = hand_bb(hid)
        if bb is None:
            return None

        raises = (
            db.query(Action.seq, Action.amount)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None

        # 2. raise = 3-bet (v1)
        _, amt = raises[1]
        amt = float(amt or 0.0)
        return round(amt / bb, 1)

    def hero_fold_to_3bet_in_hand(hid: int) -> bool:
        # Finn seq på 3-betten (2. raise)
        raises = (
            db.query(Action.seq, Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return False

        threebet_seq, threebettor = raises[1]

        # Hvis hero selv er 3-better, er dette ikke "fold to 3bet"
        if threebettor == player_name:
            return False

        # Hero må ha en respons etter 3-betten
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid, Action.street == 1, Action.player_name == player_name)
            .filter(Action.seq > threebet_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            return False

        return resp[0] == "fold"

    def bucket_for_size(sz_bb: float) -> str:
        if sz_bb <= 7.0:
            return "vs_small_3bet"
        if sz_bb <= 9.0:
            return "vs_medium_3bet"
        return "vs_big_3bet"

    # ---- session total net ----
    session_nets = []
    for hid in hand_ids:
        n = hero_net_for_hand(hid)
        if n is not None:
            session_nets.append(n)
    session_net_total = round(sum(session_nets), 2) if session_nets else 0.0

    # ---- collect ----
    bucket_hands = {
        "vs_small_3bet": [],
        "vs_medium_3bet": [],
        "vs_big_3bet": [],
    }

    for hid in hand_ids:
        if not hero_fold_to_3bet_in_hand(hid):
            continue

        sz = threebet_size_bb(hid)
        if sz is None:
            continue

        b = bucket_for_size(sz)
        bucket_hands[b].append(hid)

    out: list[Fold3BetBucketOut] = []
    note_map = {
        "vs_small_3bet": "Fold vs SMALL 3-bet (≤7bb). Her skjer ofte overfold-leaks.",
        "vs_medium_3bet": "Fold vs MEDIUM 3-bet (7–9bb).",
        "vs_big_3bet": "Fold vs BIG 3-bet (>9bb). Ofte mer legitimt å folde.",
    }

    for b, hlist in bucket_hands.items():
        nets = [hero_net_for_hand(h) for h in hlist]
        nets = [n for n in nets if n is not None]
        if not nets:
            continue

        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0

        out.append(Fold3BetBucketOut(
            bucket=b,
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            share_of_total_pct=share,
            example_hand_ids=hlist[:3],
            note=note_map.get(b, ""),
        ))

    # sorter: mest negativ total først
    out.sort(key=lambda x: x.net_total)

    return PlayerFold3BetCostBySizeOut(
        player_name=player_name,
        session_id=session_id,
        session_net_total=session_net_total,
        buckets=out,
    )


@router.get("/{player_name}/spot_plan_3bet", response_model=PlayerThreeBetPlanOut)
def spot_plan_3bet(
    player_name: str,
    session_id: int | None = None,
    min_hands: int = 3,
    min_abs_net: float = 0.1,
    db: DbSession = Depends(get_db),
):
    rep = fold_to_3bet_cost_by_size(player_name, session_id=session_id, db=db)

    # Prioriter buckets: mest negativ net_total først
    buckets = [b for b in rep.buckets if b.hands >= min_hands or abs(float(b.net_total)) >= min_abs_net]
    buckets = sorted(buckets, key=lambda b: b.net_total)[:3]

    plan: list[ThreeBetPlanItemOut] = []
    priority = 1

    for b in buckets:
        # Basic guard: hvis få hands, marker "watch"
        low_sample = b.hands < 5

        if b.bucket == "vs_small_3bet":
            rationale = (
                f"Du folder vs SMALL 3-bets (≤7bb) {b.hands} ganger. "
                f"Total {b.net_total} ({b.share_of_total_pct}% av session). "
                + ("Lite sample: fokus = watch + test små justeringer." if low_sample else "Small 3-bets kan ofte forsvares mer IP.")
            )
            actions = [
                "IP (CO/BTN): vurder flere calls med suited broadways (AQs/AJs/KQs/QJs) og pocket pairs (77–JJ), spesielt vs små 3-bets.",
                "Hold 4-bet value stramt (QQ+/AK) som start – ikke overkompliser.",
                "Mål (v1): reduser 'auto-fold' vs små 3-bets, men ikke begynn å calle OOP uten plan.",
            ]
            if low_sample:
                actions.append("Samle 10+ spotter før du gjør store endringer.")

        elif b.bucket == "vs_medium_3bet":
            rationale = (
                f"Dette er hovedbucketet ditt: MEDIUM 3-bets (7–9bb) skjer {b.hands} ganger. "
                f"Total {b.net_total} ({b.share_of_total_pct}% av session). "
                + ("Lite sample: start forsiktig." if low_sample else "Her er ofte størst edge å hente.")
            )
            actions = [
                "IP: lag en enkel defense-plan vs 7–9bb: call litt mer med AQs/AJs/KQs og 77–JJ (tilpass mot spiller).",
                "OOP: fold mer, og 4-bet mest for value (QQ+/AK) – unngå mange cold-calls OOP.",
                "Mål (v1): hvis du åpner mye i CO/BTN, prøv 1–2 ekstra defenses per økt (IP) i denne bucket’en.",
            ]
            if low_sample:
                actions.append("Samle mer sample før du konkluderer hardt.")

        else:  # vs_big_3bet
            rationale = (
                f"BIG 3-bets (>9bb) er dyre per forekomst (ofte stort sizing). "
                f"Du har {b.hands} spotter, total {b.net_total} ({b.share_of_total_pct}%). "
                + ("Lite sample." if low_sample else "Fold er ofte helt OK her.")
            )
            actions = [
                "Fold vs store 3-bets er ofte riktig – ikke tving calls bare for å 'defende'.",
                "Juster heller preflop: åpne litt strammere OOP mot spillere som bruker store 3-bets.",
                "Når du fortsetter: foretrekk 4-bet value (QQ+/AK) fremfor marginale calls OOP.",
            ]
            if low_sample:
                actions.append("Samle mer sample før du gjør store justeringer.")

        plan.append(ThreeBetPlanItemOut(
            bucket=b.bucket,
            priority=priority,
            hands=b.hands,
            net_total=b.net_total,
            share_of_total_pct=b.share_of_total_pct,
            rationale=rationale,
            actions=actions,
            example_hand_ids=b.example_hand_ids,
        ))
        priority += 1

    return PlayerThreeBetPlanOut(
        player_name=rep.player_name,
        session_id=rep.session_id,
        session_net_total=rep.session_net_total,
        buckets=rep.buckets,
        plan=plan,
    )


@router.get("/{player_name}/fold_to_3bet_cost_by_size_split", response_model=PlayerFold3BetCostBySizeSplitOut)
def fold_to_3bet_cost_by_size_split(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    # ---- hands ----
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerFold3BetCostBySizeSplitOut(player_name=player_name, session_id=session_id, session_net_total=0.0, buckets=[])

    # ---- helpers ----
    def hero_net_for_hand(hid: int) -> float | None:
        hp = db.query(HandPlayer).filter(HandPlayer.hand_id == hid, HandPlayer.player_name == player_name).first()
        if not hp:
            return None
        return float(hp.win_total or 0.0) - float(hp.bet_total or 0.0)

    def hero_pos_for_hand(hid: int) -> str | None:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            return None
        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        me = next((hp for hp in hps if hp.player_name == player_name and hp.seat is not None), None)
        if not btn_hp or not me:
            return None
        return _pos_6max(seats, btn_hp.seat, me.seat)

    def villain_pos_for_hand(hid: int, villain_name: str) -> str | None:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            return None
        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        v = next((hp for hp in hps if hp.player_name == villain_name and hp.seat is not None), None)
        if not btn_hp or not v:
            return None
        return _pos_6max(seats, btn_hp.seat, v.seat)

    # postflop-rank (hvem har posisjon?): SB -> BB -> UTG -> MP -> CO -> BTN
    postflop_rank = {"SB": 0, "BB": 1, "UTG": 2, "MP": 3, "CO": 4, "BTN": 5}

    def stance_vs(vpos: str | None, hpos: str | None) -> str | None:
        if not vpos or not hpos:
            return None
        if vpos not in postflop_rank or hpos not in postflop_rank:
            return None
        return "IP" if postflop_rank[hpos] > postflop_rank[vpos] else "OOP"

    def hand_bb(hid: int) -> float | None:
        h = db.query(Hand).filter(Hand.id == hid).first()
        if not h or not h.bb:
            return None
        bb = float(h.bb)
        return bb if bb > 0 else None

    def threebet_size_bb(hid: int) -> float | None:
        bb = hand_bb(hid)
        if bb is None:
            return None
        raises = (
            db.query(Action.seq, Action.player_name, Action.amount)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None
        _, _, amt = raises[1]  # 2. raise = 3-bet (v1)
        return round(float(amt or 0.0) / bb, 1)

    def bucket_for_size(sz_bb: float) -> str:
        if sz_bb <= 7.0:
            return "vs_small_3bet"
        if sz_bb <= 9.0:
            return "vs_medium_3bet"
        return "vs_big_3bet"

    def hero_fold_to_3bet_in_hand(hid: int) -> tuple[bool, str | None]:
        """
        Returnerer (folded?, threebettor_name)
        """
        raises = (
            db.query(Action.seq, Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return False, None

        threebet_seq, threebettor = raises[1]
        if threebettor == player_name:
            return False, threebettor

        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid, Action.street == 1, Action.player_name == player_name)
            .filter(Action.seq > threebet_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            return False, threebettor

        return resp[0] == "fold", threebettor

    # ---- session total net ----
    session_nets = []
    for hid in hand_ids:
        n = hero_net_for_hand(hid)
        if n is not None:
            session_nets.append(n)
    session_net_total = round(sum(session_nets), 2) if session_nets else 0.0

    # ---- collect ----
    # key: (bucket, stance) -> list[hand_id]
    bucket_hands: dict[tuple[str, str], list[int]] = {}

    for hid in hand_ids:
        folded, threebettor = hero_fold_to_3bet_in_hand(hid)
        if not folded or not threebettor:
            continue

        sz = threebet_size_bb(hid)
        if sz is None:
            continue
        bucket = bucket_for_size(sz)

        hpos = hero_pos_for_hand(hid)
        vpos = villain_pos_for_hand(hid, threebettor)
        st = stance_vs(vpos, hpos)
        if st is None:
            continue

        bucket_hands.setdefault((bucket, st), []).append(hid)

    note_map = {
        ("vs_small_3bet", "IP"): "Fold vs SMALL 3-bet (≤7bb) når du har posisjon.",
        ("vs_small_3bet", "OOP"): "Fold vs SMALL 3-bet (≤7bb) OOP.",
        ("vs_medium_3bet", "IP"): "Fold vs MEDIUM 3-bet (7–9bb) når du har posisjon.",
        ("vs_medium_3bet", "OOP"): "Fold vs MEDIUM 3-bet (7–9bb) OOP.",
        ("vs_big_3bet", "IP"): "Fold vs BIG 3-bet (>9bb) IP.",
        ("vs_big_3bet", "OOP"): "Fold vs BIG 3-bet (>9bb) OOP.",
    }

    out: list[Fold3BetBucketSplitOut] = []
    for (bucket, st), hlist in bucket_hands.items():
        nets = [hero_net_for_hand(h) for h in hlist]
        nets = [n for n in nets if n is not None]
        if not nets:
            continue

        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0

        out.append(Fold3BetBucketSplitOut(
            bucket=bucket,
            stance=st,
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            share_of_total_pct=share,
            example_hand_ids=hlist[:3],
            note=note_map.get((bucket, st), ""),
        ))

    # sorter: mest negativ total først
    out.sort(key=lambda x: x.net_total)

    return PlayerFold3BetCostBySizeSplitOut(
        player_name=player_name,
        session_id=session_id,
        session_net_total=session_net_total,
        buckets=out,
    )


@router.get("/{player_name}/spot_plan_3bet_split", response_model=PlayerThreeBetPlanSplitOut)
def spot_plan_3bet_split(
    player_name: str,
    session_id: int | None = None,
    min_hands: int = 3,
    min_abs_net: float = 0.1,
    db: DbSession = Depends(get_db),
):
    rep = fold_to_3bet_cost_by_size_split(player_name, session_id=session_id, db=db)

    # prioriter: mest negativ net_total først
    buckets = [b for b in rep.buckets if b.hands >= min_hands or abs(float(b.net_total)) >= min_abs_net]
    buckets = sorted(buckets, key=lambda b: b.net_total)[:3]

    plan: list[ThreeBetPlanSplitItemOut] = []
    priority = 1

    for b in buckets:
        low_sample = b.hands < 5

        # --- actions avhenger av (bucket, stance) ---
        if b.stance == "IP" and b.bucket in ("vs_small_3bet", "vs_medium_3bet"):
            rationale = (
                f"{b.note} Du folder {b.hands} ganger. Total {b.net_total} ({b.share_of_total_pct}%). "
                + ("Lite sample, men IP er stedet å justere først." if low_sample else "IP kan du ofte forsvare mer uten å øke variance for mye.")
            )
            actions = [
                "IP: legg inn 1–2 ekstra calls per økt vs small/medium 3-bets (AQs/AJs/KQs, 77–JJ som start).",
                "Legg inn noen få 4-bet bluffs med blockers (A5s/A4s) i riktige spots (ikke spam).",
                "Mål: reduser auto-fold IP vs 7–9bb, men hold OOP stramt.",
            ]
            if low_sample:
                actions.append("Samle 10+ spotter før du gjør store endringer.")

        elif b.stance == "OOP" and b.bucket in ("vs_small_3bet", "vs_medium_3bet"):
            rationale = (
                f"{b.note} Du folder {b.hands} ganger. Total {b.net_total} ({b.share_of_total_pct}%). "
                + ("Lite sample." if low_sample else "OOP calls er vanskelig: juster opens og 4-bet-range heller enn å calle mer.")
            )
            actions = [
                "OOP: ikke øk cold-calls bare for å forsvare. Prioriter fold eller 4-bet (value).",
                "Juster åpninger OOP: dropp marginale opens mot aggressive 3-bettere.",
                "4-bet value (startregel): QQ+/AK. Call OOP kun med toppdelen (f.eks TT–JJ/AQs hvis du må).",
            ]
            if low_sample:
                actions.append("Samle mer sample før du endrer mye OOP.")

        else:
            # BIG 3-bets (IP/OOP): ofte greit å folde
            rationale = (
                f"{b.note} Du folder {b.hands} ganger. Total {b.net_total} ({b.share_of_total_pct}%). "
                + ("Lite sample." if low_sample else "Store 3-bets: fold er ofte helt OK, spesielt OOP.")
            )
            actions = [
                "Vs BIG 3-bets: ikke tving calls. Fortsett mest med 4-bet value (QQ+/AK) eller fold.",
                "Juster preflop: åpne litt strammere mot spillere som 3-better stort.",
            ]
            if low_sample:
                actions.append("Samle mer sample før du konkluderer hardt.")

        plan.append(ThreeBetPlanSplitItemOut(
            bucket=b.bucket,
            stance=b.stance,
            priority=priority,
            hands=b.hands,
            net_total=b.net_total,
            share_of_total_pct=b.share_of_total_pct,
            rationale=rationale,
            actions=actions,
            example_hand_ids=b.example_hand_ids,
        ))
        priority += 1

    return PlayerThreeBetPlanSplitOut(
        player_name=rep.player_name,
        session_id=rep.session_id,
        session_net_total=rep.session_net_total,
        buckets=rep.buckets,
        plan=plan,
    )


@router.get("/{player_name}/fold_to_3bet_cost_by_size_split_by_openpos",
            response_model=PlayerFold3BetCostBySizeSplitByOpenPosOut)
def fold_to_3bet_cost_by_size_split_by_openpos(
    player_name: str,
    session_id: int | None = None,
    min_hands: int = 3,
    group_openpos: bool = True,
    db: DbSession = Depends(get_db),
):


    # ---- hands ----
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerFold3BetCostBySizeSplitByOpenPosOut(
            player_name=player_name,
            session_id=session_id,
            session_net_total=0.0,
            buckets=[],
        )

    # ---- helpers ----
    def hero_net_for_hand(hid: int) -> float | None:
        hp = (
            db.query(HandPlayer)
            .filter(HandPlayer.hand_id == hid, HandPlayer.player_name == player_name)
            .first()
        )
        if not hp:
            return None
        return float(hp.win_total or 0.0) - float(hp.bet_total or 0.0)

    def hero_pos_for_hand(hid: int, who: str) -> str | None:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            return None
        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        p = next((hp for hp in hps if hp.player_name == who and hp.seat is not None), None)
        if not btn_hp or not p:
            return None
        return _pos_6max(seats, btn_hp.seat, p.seat)

    postflop_rank = {"SB": 0, "BB": 1, "UTG": 2, "MP": 3, "CO": 4, "BTN": 5}

    def stance_vs(vpos: str | None, hpos: str | None) -> str | None:
        if not vpos or not hpos:
            return None
        if vpos not in postflop_rank or hpos not in postflop_rank:
            return None
        return "IP" if postflop_rank[hpos] > postflop_rank[vpos] else "OOP"

    def hand_bb(hid: int) -> float | None:
        h = db.query(Hand).filter(Hand.id == hid).first()
        if not h or not h.bb:
            return None
        bb = float(h.bb)
        return bb if bb > 0 else None

    def threebet_size_bb(hid: int) -> float | None:
        bb = hand_bb(hid)
        if bb is None:
            return None
        raises = (
            db.query(Action.seq, Action.player_name, Action.amount)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None
        _, _, amt = raises[1]  # 2. raise = 3-bet
        return round(float(amt or 0.0) / bb, 1)

    def bucket_for_size(sz_bb: float) -> str:
        if sz_bb <= 7.0:
            return "vs_small_3bet"
        if sz_bb <= 9.0:
            return "vs_medium_3bet"
        return "vs_big_3bet"

    def opener_and_threebettor(hid: int) -> tuple[str | None, int | None, str | None]:
        """
        Returnerer: (opener_name, threebet_seq, threebettor_name)
        """
        raises = (
            db.query(Action.seq, Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None, None, None
        opener_seq, opener = raises[0]
        threebet_seq, threebettor = raises[1]
        return opener, threebet_seq, threebettor

    def hero_folds_after_seq(hid: int, seq: int) -> bool:
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid, Action.street == 1, Action.player_name == player_name)
            .filter(Action.seq > seq)
            .order_by(Action.seq.asc())
            .first()
        )
        return bool(resp and resp[0] == "fold")

    # ---- session total net ----
    session_nets: list[float] = []
    for hid in hand_ids:
        n = hero_net_for_hand(hid)
        if n is not None:
            session_nets.append(n)
    session_net_total = round(sum(session_nets), 2) if session_nets else 0.0

    # ---- collect ----
    # key: (bucket, stance, open_pos) -> list[hand_id]
    bucket_hands: dict[tuple[str, str, str], list[int]] = {}

    for hid in hand_ids:
        opener, threebet_seq, threebettor = opener_and_threebettor(hid)
        if not opener or threebet_seq is None or not threebettor:
            continue

        # Vi vil bare måle "open -> face 3bet -> fold"
        if opener != player_name:
            continue

        if not hero_folds_after_seq(hid, threebet_seq):
            continue

        sz = threebet_size_bb(hid)
        if sz is None:
            continue
        bucket = bucket_for_size(sz)

        def open_group(pos: str) -> str:
            if pos in ("UTG", "MP"):
                return "EARLY"
            if pos in ("CO", "BTN"):
                return "LATE"
            if pos in ("SB", "BB"):
                return "BLINDS"
            return pos

        open_pos = hero_pos_for_hand(hid, player_name)
        threebettor_pos = hero_pos_for_hand(hid, threebettor)
        st = stance_vs(threebettor_pos, open_pos)
        if not open_pos or not st:
            continue

        pos_key = open_group(open_pos) if group_openpos else open_pos
        bucket_hands.setdefault((bucket, st, pos_key), []).append(hid)


    note_map = {
        "vs_small_3bet": "Small 3-bets (≤7bb): ofte mer forsvar IP, men vær forsiktig OOP.",
        "vs_medium_3bet": "Medium 3-bets (7–9bb): vanligste sizing, ofte størst edge å hente IP.",
        "vs_big_3bet": "Big 3-bets (>9bb): fold er oftere OK, særlig OOP.",
    }

    out: list[Fold3BetBucketOpenPosOut] = []
    for (bucket, st, open_pos), hlist in bucket_hands.items():
        nets = [hero_net_for_hand(h) for h in hlist]
        nets = [n for n in nets if n is not None]
        if len(nets) < min_hands:
            continue


        total = round(sum(nets), 2)
        per = round(total / len(nets), 3)
        share = round(100.0 * total / session_net_total, 1) if session_net_total != 0 else 0.0

        out.append(Fold3BetBucketOpenPosOut(
            bucket=bucket,
            stance=st,
            open_pos=open_pos,
            hands=len(nets),
            net_total=total,
            net_per_hand=per,
            share_of_total_pct=share,
            example_hand_ids=hlist[:3],
            note=note_map.get(bucket, ""),
        ))

    out.sort(key=lambda x: x.net_total)

    return PlayerFold3BetCostBySizeSplitByOpenPosOut(
        player_name=player_name,
        session_id=session_id,
        session_net_total=session_net_total,
        buckets=out,
    )


@router.get("/{player_name}/threebet_response_matrix", response_model=PlayerThreeBetResponseMatrixOut)
def threebet_response_matrix(
    player_name: str,
    session_id: int | None = None,
    min_faced: int = 3,
    group_openpos: bool = True,
    db: DbSession = Depends(get_db),
):
    # ---- hands ----
    q = db.query(Hand.id)
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    hand_ids = [x[0] for x in q.all()]
    if not hand_ids:
        return PlayerThreeBetResponseMatrixOut(
            player_name=player_name,
            session_id=session_id,
            min_faced=min_faced,
            group_openpos=group_openpos,
            total_faced=0,
            cells_returned=0,
            recommended_min_faced=1,
            cells=[],
        )
    
    def conf_from_faced(n: int) -> str:
        if n < 5:
            return "low"
        if n < 15:
            return "medium"
        return "high"

    # ---- helpers ----
    def hero_pos_for_hand(hid: int, who: str) -> str | None:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            return None
        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        p = next((hp for hp in hps if hp.player_name == who and hp.seat is not None), None)
        if not btn_hp or not p:
            return None
        return _pos_6max(seats, btn_hp.seat, p.seat)

    postflop_rank = {"SB": 0, "BB": 1, "UTG": 2, "MP": 3, "CO": 4, "BTN": 5}

    def stance_vs(vpos: str | None, hpos: str | None) -> str | None:
        if not vpos or not hpos:
            return None
        if vpos not in postflop_rank or hpos not in postflop_rank:
            return None
        return "IP" if postflop_rank[hpos] > postflop_rank[vpos] else "OOP"

    def open_group(pos: str) -> str:
        if pos in ("UTG", "MP"):
            return "EARLY"
        if pos in ("CO", "BTN"):
            return "LATE"
        if pos in ("SB", "BB"):
            return "BLINDS"
        return pos

    def hand_bb(hid: int) -> float | None:
        h = db.query(Hand).filter(Hand.id == hid).first()
        if not h or not h.bb:
            return None
        bb = float(h.bb)
        return bb if bb > 0 else None

    def threebet_size_bb(hid: int) -> float | None:
        bb = hand_bb(hid)
        if bb is None:
            return None
        raises = (
            db.query(Action.seq, Action.player_name, Action.amount)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None
        _, _, amt = raises[1]  # 2. raise = 3-bet (v1)
        return round(float(amt or 0.0) / bb, 1)

    def bucket_for_size(sz_bb: float) -> str:
        if sz_bb <= 7.0:
            return "vs_small_3bet"
        if sz_bb <= 9.0:
            return "vs_medium_3bet"
        return "vs_big_3bet"

    def opener_and_threebettor(hid: int) -> tuple[str | None, int | None, str | None]:
        raises = (
            db.query(Action.seq, Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None, None, None
        opener_seq, opener = raises[0]
        threebet_seq, threebettor = raises[1]
        return opener, threebet_seq, threebettor

    def hero_response_after_threebet(hid: int, threebet_seq: int) -> str | None:
        """
        Returnerer: 'fold' / 'call' / 'fourbet' (raise) / None
        """
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid, Action.street == 1, Action.player_name == player_name)
            .filter(Action.seq > threebet_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            return None
        act = resp[0]
        if act == "fold":
            return "fold"
        if act == "call":
            return "call"
        if act == "raise":
            return "fourbet"
        # hvis logs bruker annet ord (sjeldent)
        return None

    # ---- collect ----
    # key: (open_group_or_pos, stance, bucket)
    counts: dict[tuple[str, str, str], dict[str, object]] = {}

    for hid in hand_ids:
        opener, threebet_seq, threebettor = opener_and_threebettor(hid)
        if opener != player_name or threebet_seq is None or not threebettor:
            continue  # vi ser kun på "du åpner og møter 3-bet"

        hpos = hero_pos_for_hand(hid, player_name)
        vpos = hero_pos_for_hand(hid, threebettor)
        st = stance_vs(vpos, hpos)
        if not hpos or not st:
            continue

        pos_key = open_group(hpos) if group_openpos else hpos

        sz = threebet_size_bb(hid)
        if sz is None:
            continue
        bucket = bucket_for_size(sz)

        resp = hero_response_after_threebet(hid, threebet_seq)
        if resp is None:
            continue

        key = (pos_key, st, bucket)
        if key not in counts:
            counts[key] = {"faced": 0, "fold": 0, "call": 0, "fourbet": 0, "examples": []}

        counts[key]["faced"] = int(counts[key]["faced"]) + 1
        counts[key][resp] = int(counts[key][resp]) + 1

        # lagre noen eksempler
        ex = counts[key]["examples"]
        if isinstance(ex, list) and len(ex) < 3:
            ex.append(hid)

    # ---- build response ----
    cells: list[ThreeBetResponseCellOut] = []
    note_map = {
        "vs_small_3bet": "Small 3-bet (≤7bb): ofte mulig å forsvare mer IP.",
        "vs_medium_3bet": "Medium 3-bet (7–9bb): vanligst sizing, ofte mest edge IP.",
        "vs_big_3bet": "Big 3-bet (>9bb): fold oftere OK, spesielt OOP.",
    }

    for (pos_key, st, bucket), d in counts.items():
        faced = int(d["faced"])
        if faced < min_faced:
            continue

        fold = int(d["fold"])
        call = int(d["call"])
        fourbet = int(d["fourbet"])

        fold_pct = round(100.0 * fold / faced, 1)
        call_pct = round(100.0 * call / faced, 1)
        fourbet_pct = round(100.0 * fourbet / faced, 1)

        examples = d["examples"] if isinstance(d["examples"], list) else None

        conf = conf_from_faced(faced)

        def conf_from_faced(n: int) -> str:
            if n < 5:
                return "low"
            if n < 15:
                return "medium"
            return "high"
        
        conf = conf_from_faced(faced)

        cells.append(ThreeBetResponseCellOut(
            open_group=pos_key,
            stance=st,
            bucket=bucket,
            faced=faced,
            fold=fold,
            call=call,
            fourbet=fourbet,
            fold_pct=fold_pct,
            call_pct=call_pct,
            fourbet_pct=fourbet_pct,
            example_hand_ids=examples,
            note=note_map.get(bucket),
            confidence=conf,
        
        ))

    # sorter: mest faced først, deretter høy fold_pct
    cells.sort(key=lambda c: (c.faced, c.fold_pct), reverse=True)

    total_faced = sum(c.faced for c in cells)
    # enkel anbefaling:
    # hvis total_faced < 20 -> 1
    # hvis total_faced < 50 -> 3
    # ellers -> 5
    if total_faced < 20:
        recommended_min_faced = 1
    elif total_faced < 50:
        recommended_min_faced = 3
    else:
        recommended_min_faced = 5


    return PlayerThreeBetResponseMatrixOut(
        player_name=player_name,
        session_id=session_id,
        min_faced=min_faced,
        group_openpos=group_openpos,
        total_faced=total_faced,
        cells_returned=len(cells),
        recommended_min_faced=recommended_min_faced,
        cells=cells,
    )


@router.get("/{player_name}/threebet_sampling_plan", response_model=PlayerThreeBetSamplingPlanOut)
def threebet_sampling_plan(
    player_name: str,
    session_id: int | None = None,
    group_openpos: bool = True,
    db: DbSession = Depends(get_db),
):
    rep = threebet_response_matrix(
        player_name=player_name,
        session_id=session_id,
        min_faced=1,
        group_openpos=group_openpos,
        db=db,
    )

    # prioritetscore: vi vil samle mer på spottene som typisk har høy EV-impact
    def priority_score(c: ThreeBetResponseCellOut) -> int:
        # høyest prioritet: LATE+IP+medium/small
        if c.open_group == "LATE" and c.stance == "IP" and c.bucket in ("vs_small_3bet", "vs_medium_3bet"):
            return 100
        # nest: EARLY+OOP+small (ofte tricky/leaky)
        if c.open_group == "EARLY" and c.stance == "OOP" and c.bucket == "vs_small_3bet":
            return 80
        # ellers: medium
        if c.bucket == "vs_medium_3bet":
            return 60
        # big 3bets er ofte mindre prioritet for “defend more”
        return 40

    def micro_rule(c: ThreeBetResponseCellOut) -> str:
        if c.open_group == "LATE" and c.stance == "IP" and c.bucket == "vs_medium_3bet":
            return "Neste gang: vurder 1 call med AQs/KQs/TT–JJ i stedet for auto-fold."
        if c.open_group == "LATE" and c.stance == "IP" and c.bucket == "vs_small_3bet":
            return "Neste gang: forsvar litt mer IP vs liten 3-bet; call noen suited broadways/pairs."
        if c.open_group == "EARLY" and c.stance == "OOP" and c.bucket == "vs_small_3bet":
            return "Neste gang: ikke øk calls OOP; vurder strammere open eller 4-bet value med QQ+/AK."
        if c.bucket == "vs_big_3bet":
            return "Neste gang: fold er ofte ok; fokuser på åpne strammere mot store 3-bets."
        return "Neste gang: merk spotten og samle mer sample før du endrer mye."

    targets: list[ThreeBetSampleTargetOut] = []

    for c in rep.cells:
        # vi definerer medium-confidence som faced>=5
        need = max(0, 5 - c.faced)
        targets.append(ThreeBetSampleTargetOut(
            open_group=c.open_group,
            stance=c.stance,
            bucket=c.bucket,
            priority=priority_score(c),
            faced=c.faced,
            need_more_for_medium=need,
            why=(c.note or ""),
            micro_rule=micro_rule(c),
            example_hand_ids=c.example_hand_ids,
        ))

    # sorter: høy priority først, så mest "need"
    targets.sort(key=lambda t: (t.priority, t.need_more_for_medium), reverse=True)

    return PlayerThreeBetSamplingPlanOut(
        player_name=rep.player_name,
        session_id=rep.session_id,
        total_faced=rep.total_faced,
        targets=targets[:8],  # topp 8 er nok
    )

@router.get("/{player_name}/threebet_sampling_plan", response_model=PlayerThreeBetSamplingPlanOut)
def threebet_sampling_plan(
    player_name: str,
    session_id: int | None = None,
    group_openpos: bool = True,
    db: DbSession = Depends(get_db),
):
    # Vi bruker matrixen i diagnose-modus (min_faced=1)
    rep = threebet_response_matrix(
        player_name=player_name,
        session_id=session_id,
        min_faced=1,
        group_openpos=group_openpos,
        db=db,
    )

    def priority_score(open_group: str, stance: str, bucket: str) -> int:
        # høyest: LATE + IP + small/medium (mest edge)
        if open_group == "LATE" and stance == "IP" and bucket in ("vs_small_3bet", "vs_medium_3bet"):
            return 100
        # nest: EARLY + OOP + small (ofte tricky)
        if open_group == "EARLY" and stance == "OOP" and bucket == "vs_small_3bet":
            return 80
        # medium-sizing generelt
        if bucket == "vs_medium_3bet":
            return 60
        # big-sizing ofte mindre “defend mer” fokus
        return 40

    def micro_rule(open_group: str, stance: str, bucket: str) -> str:
        if open_group == "LATE" and stance == "IP" and bucket == "vs_medium_3bet":
            return "Neste gang: vurder 1 call med AQs/KQs/TT–JJ i stedet for auto-fold."
        if open_group == "LATE" and stance == "IP" and bucket == "vs_small_3bet":
            return "Neste gang: forsvar litt mer IP vs liten 3-bet; call noen suited broadways/pairs."
        if open_group == "EARLY" and stance == "OOP" and bucket == "vs_small_3bet":
            return "Neste gang: ikke øk calls OOP; vurder strammere open eller 4-bet value (QQ+/AK)."
        if bucket == "vs_big_3bet":
            return "Neste gang: fold er ofte ok; fokuser på åpne strammere mot store 3-bets."
        return "Neste gang: merk spotten og samle mer sample før du endrer mye."

    targets: list[ThreeBetSampleTargetOut] = []

    for c in rep.cells:
        # medium-confidence = faced >= 5 (samme terskel som conf_from_faced)
        need = max(0, 5 - c.faced)

        targets.append(ThreeBetSampleTargetOut(
            open_group=c.open_group,
            stance=c.stance,
            bucket=c.bucket,
            priority=priority_score(c.open_group, c.stance, c.bucket),
            faced=c.faced,
            need_more_for_medium=need,
            why=(c.note or ""),
            micro_rule=micro_rule(c.open_group, c.stance, c.bucket),
            example_hand_ids=c.example_hand_ids,
        ))

    # sorter: høy priority først, så mest "need"
    targets.sort(key=lambda t: (t.priority, t.need_more_for_medium), reverse=True)

    return PlayerThreeBetSamplingPlanOut(
        player_name=rep.player_name,
        session_id=rep.session_id,
        total_faced=rep.total_faced,
        targets=targets[:8],  # topp 8
    )

@router.get("/{player_name}/next_session_rules_3bet", response_model=PlayerNextSessionRules3BetOut)
def next_session_rules_3bet(
    player_name: str,
    session_id: int | None = None,
    group_openpos: bool = True,
    db: DbSession = Depends(get_db),
):
    plan = threebet_sampling_plan(
        player_name=player_name,
        session_id=session_id,
        group_openpos=group_openpos,
        db=db,
    )

    # Ta topp 3 targets (de er allerede sortert etter priority)
    top = plan.targets[:3]

    rules = []
    for t in top:
        key = f"{t.open_group}/{t.stance}/{t.bucket}"
        rule_text = f"{t.micro_rule} (mål: +{t.need_more_for_medium} spotter til medium confidence)"

        rules.append({
            "rule": rule_text,
            "why": t.why,
            "target": key,
            "need_more_for_medium": t.need_more_for_medium,
            "example_hand_ids": t.example_hand_ids,
        })



    goal = (
        "Samle flere 3-bet-spotter i de høyest prioriterte targetene "
        "(målet er å komme til >=5 faced for medium confidence)."
    )

    return PlayerNextSessionRules3BetOut(
        player_name=plan.player_name,
        session_id=plan.session_id,
        total_faced=plan.total_faced,
        goal=goal,
        rules=rules,
    )


@router.post("/live_hint/3bet", response_model=LiveHint3BetResponse)
def live_hint_3bet(req: LiveHint3BetRequest, db: DbSession = Depends(get_db)):
    # 1) hent sampling-planen (bruker din eksisterende funksjon)
    plan = threebet_sampling_plan(
        player_name=req.player_name,
        session_id=req.session_id,
        group_openpos=True,
        db=db,
    )

    target_key = f"{req.open_group}/{req.stance}/{req.bucket}"

    # 2) finn matching target (hvis den finnes)
    tmatch = next(
        (t for t in plan.targets if f"{t.open_group}/{t.stance}/{t.bucket}" == target_key),
        None
    )

    # 3) confidence (v1: basert på faced= i matrix)
    mat = threebet_response_matrix(
        player_name=req.player_name,
        session_id=req.session_id,
        min_faced=1,
        group_openpos=True,
        db=db,
    )
    cmatch = next(
        (c for c in mat.cells if c.open_group == req.open_group and c.stance == req.stance and c.bucket == req.bucket),
        None
    )
    confidence = (cmatch.confidence if cmatch else "low")

    # 4) lag hint-tekst (coaching, ikke “trykk X nå”)
    situation = f"{req.open_group}/{req.stance}/{req.bucket}"

    # default hint
    hint = "Samle mer sample i denne situasjonen før du gjør store endringer."
    watchouts = [
        "Hold deg til enkle regler – ikke overjuster på 1–2 hender.",
        "Hvis du er usikker: spill strammere OOP og mer fleksibelt IP."
    ]
    evidence = None

    if tmatch:
        hint = tmatch.micro_rule
        evidence = tmatch.example_hand_ids

        # noen ekstra watchouts basert på bucket/stance
        if req.stance == "IP" and req.bucket in ("vs_small_3bet", "vs_medium_3bet"):
            watchouts = [
                "IP: prioriter calls med suited broadways og pocket pairs (TT–JJ/77–99 i riktige spots).",
                "Ikke gjør dette OOP uten plan.",
                "Fokuser på én test-justering per økt, ikke mange."
            ]
        elif req.stance == "OOP" and req.bucket in ("vs_small_3bet", "vs_medium_3bet"):
            watchouts = [
                "OOP: ikke øk cold-calls bare for å ‘forsvare’ – fold/4-bet value er ofte best.",
                "Juster opens OOP mot aggressive 3-bettere.",
                "Hvis du fortsetter OOP, gjør det med toppdelen."
            ]
        else:
            watchouts = [
                "Vs store 3-bets: fold er ofte helt OK, spesielt OOP.",
                "Juster heller åpninger (mindre marginalt) enn å tvinge forsvar.",
            ]

    one_liner = hint  # default

    # gjør den litt kortere og mer “spillbar”
    if req.stance == "IP" and req.bucket == "vs_medium_3bet" and req.open_group == "LATE":
        one_liner = "LATE/IP vs 7–9bb: test 1 call med AQs/KQs/TT–JJ (ikke auto-fold)."
    elif req.stance == "OOP" and req.bucket == "vs_small_3bet" and req.open_group == "EARLY":
        one_liner = "EARLY/OOP vs ≤7bb: ikke øk calls – strammere open eller 4-bet value (QQ+/AK)."
    elif req.bucket == "vs_big_3bet":
        one_liner = "Vs >9bb 3-bet: fold er ofte OK – juster opens mot store sizings."
    else:
        # fallback: kortversjon av hint
        one_liner = hint


    return LiveHint3BetResponse(
        situation=situation,
        player_name=req.player_name,
        villain_name=req.villain_name,
        session_id=req.session_id,
        confidence=confidence,
        hint=hint,
        watchouts=watchouts,
        evidence_hand_ids=evidence,
        one_liner=one_liner,
    )


@router.get("/live_hint/3bet/auto", response_model=LiveHint3BetAutoResponse)
def live_hint_3bet_auto(
    player_name: str,
    session_id: int | None = None,
    lookback_hands: int = 50,
    group_openpos: bool = True,
    mode: str = "latest",      # "latest" | "targeted"
    target_rank: int = 1,      # 1 = top target
    db: DbSession = Depends(get_db),
):
    # ---- helpers ----
    def open_group(pos: str) -> str:
        if pos in ("UTG", "MP"):
            return "EARLY"
        if pos in ("CO", "BTN"):
            return "LATE"
        if pos in ("SB", "BB"):
            return "BLINDS"
        return pos

    postflop_rank = {"SB": 0, "BB": 1, "UTG": 2, "MP": 3, "CO": 4, "BTN": 5}

    def stance_vs(vpos: str | None, hpos: str | None) -> str | None:
        if not vpos or not hpos:
            return None
        if vpos not in postflop_rank or hpos not in postflop_rank:
            return None
        return "IP" if postflop_rank[hpos] > postflop_rank[vpos] else "OOP"

    def hero_pos_for_hand(hid: int, who: str) -> str | None:
        hps = db.query(HandPlayer).filter(HandPlayer.hand_id == hid).all()
        seats = [hp.seat for hp in hps if hp.seat is not None]
        if len(seats) < 4:
            return None
        btn_hp = next((hp for hp in hps if hp.is_dealer and hp.seat is not None), None)
        p = next((hp for hp in hps if hp.player_name == who and hp.seat is not None), None)
        if not btn_hp or not p:
            return None
        return _pos_6max(seats, btn_hp.seat, p.seat)

    def hand_bb(hid: int) -> float | None:
        h = db.query(Hand).filter(Hand.id == hid).first()
        if not h or not h.bb:
            return None
        bb = float(h.bb)
        return bb if bb > 0 else None

    def threebet_size_bb(hid: int) -> float | None:
        bb = hand_bb(hid)
        if bb is None:
            return None
        raises = (
            db.query(Action.seq, Action.player_name, Action.amount)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None
        _, _, amt = raises[1]
        return round(float(amt or 0.0) / bb, 1)

    def bucket_for_size(sz_bb: float) -> str:
        if sz_bb <= 7.0:
            return "vs_small_3bet"
        if sz_bb <= 9.0:
            return "vs_medium_3bet"
        return "vs_big_3bet"

    def opener_and_threebettor(hid: int) -> tuple[str | None, int | None, str | None]:
        raises = (
            db.query(Action.seq, Action.player_name)
            .filter(Action.hand_id == hid, Action.street == 1, Action.action == "raise")
            .order_by(Action.seq.asc())
            .all()
        )
        if len(raises) < 2:
            return None, None, None
        opener_seq, opener = raises[0]
        threebet_seq, threebettor = raises[1]
        return opener, threebet_seq, threebettor

    def hero_response_after_threebet(hid: int, threebet_seq: int) -> str | None:
        resp = (
            db.query(Action.action)
            .filter(Action.hand_id == hid, Action.street == 1, Action.player_name == player_name)
            .filter(Action.seq > threebet_seq)
            .order_by(Action.seq.asc())
            .first()
        )
        if not resp:
            return None
        act = resp[0]
        if act in ("fold", "call", "raise"):
            return act
        return None

    # ---- last hands ----
    q = db.query(Hand.id).order_by(Hand.id.desc())
    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)
    recent = [x[0] for x in q.limit(lookback_hands).all()]

    # ---- targeted tuple (open_group, stance, bucket) ----
    wanted: tuple[str, str, str] | None = None
    if mode == "targeted":
        sp = threebet_sampling_plan(
            player_name=player_name,
            session_id=session_id,
            group_openpos=group_openpos,
            db=db,
        )
        if sp.targets:
            idx = max(0, min(target_rank - 1, len(sp.targets) - 1))
            t = sp.targets[idx]
            wanted = (t.open_group, t.stance, t.bucket)

    # ---- helper: scan recent hands, optionally require wanted match ----
    def scan(wanted_tuple: tuple[str, str, str] | None):
        for hid in recent:
            opener, threebet_seq, threebettor = opener_and_threebettor(hid)
            if opener != player_name or threebet_seq is None or not threebettor:
                continue

            resp = hero_response_after_threebet(hid, threebet_seq)
            if resp is None:
                continue

            sz = threebet_size_bb(hid)
            if sz is None:
                continue
            bucket = bucket_for_size(sz)

            hpos = hero_pos_for_hand(hid, player_name)
            vpos = hero_pos_for_hand(hid, threebettor)
            st = stance_vs(vpos, hpos)
            if not hpos or not st:
                continue

            og = open_group(hpos) if group_openpos else hpos

            if wanted_tuple is not None:
                if (og, st, bucket) != wanted_tuple:
                    continue

            # bruk live_hint_3bet for tekst
            hint_resp = live_hint_3bet(
                LiveHint3BetRequest(
                    player_name=player_name,
                    villain_name=threebettor,
                    session_id=session_id,
                    open_group=og,
                    stance=st,
                    bucket=bucket,
                ),
                db=db,
            )

            return LiveHint3BetAutoResponse(
                found=True,
                reason=None if wanted_tuple is None else f"Matched target {wanted_tuple[0]}/{wanted_tuple[1]}/{wanted_tuple[2]}",
                player_name=player_name,
                session_id=session_id,
                hand_id=hid,
                villain_name=threebettor,
                open_group=og,
                stance=st,
                bucket=bucket,
                confidence=hint_resp.confidence,
                hint=hint_resp.hint,
                watchouts=hint_resp.watchouts,
                evidence_hand_ids=hint_resp.evidence_hand_ids,
            )
        return None

    # 1) targeted scan first (if mode=targeted)
    if mode == "targeted" and wanted is not None:
        res = scan(wanted)
        if res is not None:
            return res

    # 2) fallback: latest scan
    res = scan(None)
    if res is not None:
        return res

    return LiveHint3BetAutoResponse(
        found=False,
        reason="No recent open->face-3bet spots found in lookback window.",
        player_name=player_name,
        session_id=session_id,
    )

@router.get("/{player_name}/profile", response_model=PlayerProfileOut)
def player_profile(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    # ---- 1) HUD (grunnstats) ----
    hud = player_hud(player_name, db)  # din eksisterende HUD
    hands = int(hud.hands_played or 0)

    # ---- 2) Results (net + bb/100) ----
    # net_total = sum(win_total - bet_total) over hands (session-filter hvis gitt)
    q = db.query(HandPlayer).filter(HandPlayer.player_name == player_name)
    if session_id is not None:
        q = q.join(Hand, Hand.id == HandPlayer.hand_id).filter(Hand.session_id == session_id)

    hps = q.all()

    net_total = 0.0
    net_bb_sum = 0.0
    hands_count = 0

    for hp in hps:
        bet = float(hp.bet_total or 0.0)
        win = float(hp.win_total or 0.0)
        net = (win - bet)
        net_total += net

        h = db.query(Hand).filter(Hand.id == hp.hand_id).first()
        if h and h.bb:
            bb = float(h.bb)
            if bb and bb > 0:
                net_bb_sum += (net / bb)
                hands_count += 1

    net_total = round(net_total, 2)

    if hands_count > 0:
        bb_per_100 = round((net_bb_sum / hands_count) * 100.0, 2)
    else:
        bb_per_100 = 0.0

    hands = hands_count  # sørg for at hands matcher results



    # confidence for results (enkel v1)
    def conf_from_hands(n: int) -> str:
        if n < 200:
            return "low"
        if n < 1000:
            return "medium"
        return "high"

    results_conf = conf_from_hands(hands)

    results = PlayerResultsOut(
        hands=hands,
        net_total=net_total,
        bb_per_100=bb_per_100,
        confidence=results_conf,
    )

    # ---- 3) Aggression score (0–100, enkel v1) ----
    # Bruk PFR, 3bet, cbet som “aggro”, og VPIP-PFR gap som “passiv”
    vpip = float(hud.vpip_pct or 0.0)
    pfr = float(hud.pfr_pct or 0.0)
    threebet = float(hud.threebet_pct or 0.0)
    cbet = float(hud.cb_flop_pct or 0.0)
    gap = max(0.0, vpip - pfr)

    ag = 50.0
    ag += pfr * 0.6
    ag += threebet * 1.5
    ag += cbet * 0.3
    ag -= gap * 1.0

    aggression_score = int(max(0, min(100, round(ag))))

    if aggression_score < 35:
        aggression_label = "passiv"
    elif aggression_score < 65:
        aggression_label = "moderat"
    else:
        aggression_label = "aggressiv"

    # ---- 4) Fundamentals score (0–100) ----
    # Bruk leaks som “straff”: jo flere/levere leaks, jo lavere fundamentals
    # Vi bruker leaks-endpointet du har: player_leaks(...)
    # NB: din player_leaks returnerer PlayerInsightsOut (leaks + observations)
    insights = player_leaks(player_name, db=db, session_id=session_id)

    # enkel severity-vekting
    sev_w = {"low": 5, "medium": 12, "high": 20}
    penalty = 0
    for l in insights.leaks:
        penalty += sev_w.get(l.severity, 8)

    fundamentals_score = int(max(0, min(100, 100 - penalty)))

    if fundamentals_score < 35:
        fundamentals_label = "leak-heavy"
    elif fundamentals_score < 65:
        fundamentals_label = "ok"
    else:
        fundamentals_label = "solid"

    # ---- 5) Strength estimate (kombiner fundamentals + results) ----
    # V1: fundamentals teller mest, results teller mer når sample øker
    if results_conf == "low":
        w_results = 0.15
    elif results_conf == "medium":
        w_results = 0.30
    else:
        w_results = 0.40

    w_fund = 1.0 - w_results

    # maps bb/100 til en “results_score” 0–100 (veldig enkel v1)
    # -10 bb/100 -> 20, 0 -> 50, +10 -> 80, +20 -> 95
    rs = 50.0 + (bb_per_100 * 3.0)
    rs = max(0.0, min(100.0, rs))
    results_score = rs

    strength = (fundamentals_score * w_fund) + (results_score * w_results)
    strength_score = int(max(0, min(100, round(strength))))

    if strength_score < 35:
        strength_label = "svak"
    elif strength_score < 65:
        strength_label = "ok"
    elif strength_score < 85:
        strength_label = "solid"
    else:
        strength_label = "sterk"

    # overall confidence (v1): bruk hud.confidence_overall hvis du har den, ellers hands
    overall_conf = getattr(hud, "confidence_overall", None) or conf_from_hands(hands)

    notes = []
    if results_conf == "low":
        notes.append("Results er usikre (lav sample). Vekt legger mer på fundamentals.")
    if hands == 0:
        notes.append("Ingen hender funnet for spilleren.")
    if session_id is not None:
        notes.append(f"Profil filtrert på session_id={session_id}.")

    return PlayerProfileOut(
        player_name=player_name,
        session_id=session_id,
        player_type=hud.player_type,
        confidence=overall_conf,
        aggression_score=aggression_score,
        aggression_label=aggression_label,
        fundamentals_score=fundamentals_score,
        fundamentals_label=fundamentals_label,
        results=results,
        strength_score=strength_score,
        strength_label=strength_label,
        notes=notes,
    )


@router.get("/{player_name}/hole_cards", response_model=PlayerHoleCardsOut)
def player_hole_cards(
    player_name: str,
    session_id: int | None = None,
    db: DbSession = Depends(get_db),
):
    q = (
        db.query(
            HoleCards.card1.label("card1"),
            HoleCards.card2.label("card2"),
            func.count().label("hands"),
            func.coalesce(func.sum(HandPlayer.bet_total), 0.0).label("bet_total"),
            func.coalesce(func.sum(HandPlayer.win_total), 0.0).label("win_total"),
            func.sum(case((HandPlayer.win_total > HandPlayer.bet_total, 1), else_=0)).label("won"),
            func.sum(case((HandPlayer.win_total == HandPlayer.bet_total, 1), else_=0)).label("tied"),
            func.coalesce(func.sum(Hand.bb), 0.0).label("sum_bb"),
        )
        .join(
            HandPlayer,
            (HandPlayer.hand_id == HoleCards.hand_id) & (HandPlayer.player_name == player_name),
        )
        .join(Hand, Hand.id == HoleCards.hand_id)
        .filter(HoleCards.player_name == player_name)
    )

    if session_id is not None:
        q = q.filter(Hand.session_id == session_id)

    rows = q.group_by(HoleCards.card1, HoleCards.card2).all()

    combos: list[HoleCardResultOut] = []
    total_hands = 0

    for r in rows:
        hands = int(r.hands or 0)
        total_hands += hands

        bet_total = float(r.bet_total or 0.0)
        win_total = float(r.win_total or 0.0)
        net_total = round(win_total - bet_total, 2)
        avg_net = round(net_total / hands, 3) if hands else 0.0

        won = int(r.won or 0)
        tied = int(r.tied or 0)
        lost = max(0, hands - won - tied)

        sum_bb = float(r.sum_bb or 0.0)
        bb_per_100 = round(100.0 * net_total / sum_bb, 2) if sum_bb else None

        combos.append(
            HoleCardResultOut(
                card1=r.card1,
                card2=r.card2,
                hands=hands,
                won=won,
                tied=tied,
                lost=lost,
                net_total=net_total,
                avg_net=avg_net,
                bb_per_100=bb_per_100,
            )
        )

    # Sort: best avg_net first
    combos.sort(key=lambda c: (c.avg_net, c.hands), reverse=True)

    return PlayerHoleCardsOut(
        player_name=player_name,
        session_id=session_id,
        total_hands=total_hands,
        combos=combos,
    )

@router.get("/session/{session_id}/stats", response_model=SessionStatsOut)
def session_stats(session_id: int, db: DbSession = Depends(get_db)):
    """
    Returnerer statistikk for alle spillere i en sesjon.
    """
    from schemas import SessionStatsOut, SessionPlayerStatsOut
    from models import Session as PokerSession
    
    # Finn session
    session = db.query(PokerSession).filter(PokerSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Hent alle HandPlayer-poster for denne sesjonen
    hand_players = (
        db.query(HandPlayer)
        .join(Hand, Hand.id == HandPlayer.hand_id)
        .filter(Hand.session_id == session_id)
        .all()
    )
    
    if not hand_players:
        return SessionStatsOut(
            session_id=session_id,
            session_code=session.session_code,
            total_players=0,
            total_hands=0,
            players=[]
        )
    
    # Aggreger per spiller
    player_stats: dict[str, dict] = {}
    
    for hp in hand_players:
        name = hp.player_name
        if name not in player_stats:
            player_stats[name] = {
                "hands": set(),
                "bet_total": 0.0,
                "win_total": 0.0,
                "bb_total": 0.0,
            }
        
        player_stats[name]["hands"].add(hp.hand_id)
        player_stats[name]["bet_total"] += float(hp.bet_total or 0.0)
        player_stats[name]["win_total"] += float(hp.win_total or 0.0)
        
        # Hent BB fra Hand
        hand = db.query(Hand).filter(Hand.id == hp.hand_id).first()
        if hand and hand.bb:
            player_stats[name]["bb_total"] += float(hand.bb or 0.0)
    
    # Bygg response
    players_out = []
    for name, stats in player_stats.items():
        hands = len(stats["hands"])
        bet = stats["bet_total"]
        win = stats["win_total"]
        net = win - bet
        bb_total = stats["bb_total"]
        bb_per_hand = (bb_total / hands) if hands > 0 else 0.0
        
        players_out.append(SessionPlayerStatsOut(
            player_name=name,
            hands=hands,
            bet_total=round(bet, 2),
            win_total=round(win, 2),
            net_total=round(net, 2),
            bb_per_hand=round(bb_per_hand, 2),
        ))
    
    # Sorter: best net først
    players_out.sort(key=lambda p: p.net_total, reverse=True)
    
    return SessionStatsOut(
        session_id=session_id,
        session_code=session.session_code,
        total_players=len(players_out),
        total_hands=len(set(hp.hand_id for hp in hand_players)),
        players=players_out
    )