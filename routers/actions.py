from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.exc import IntegrityError

from database import get_db
from models import Hand, Action
from schemas import ActionCreate, ActionOut

router = APIRouter(prefix="/actions", tags=["actions"])

ALLOWED_ACTIONS = {"fold", "call", "raise", "bet", "check", "sb", "bb"}

@router.post("", response_model=ActionOut)
def create_action(payload: ActionCreate, db: DbSession = Depends(get_db)):
    # 1) sjekk hand finnes
    h = db.query(Hand).filter(Hand.id == payload.hand_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Hand not found")

    # 2) enkel validering
    if payload.action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid action: {payload.action}")

    a = Action(
        hand_id=payload.hand_id,
        street=payload.street,
        seq=payload.seq,
        player_name=payload.player_name,
        action_type_code=payload.action_type_code or 0,
        action=payload.action,
        amount=payload.amount,
    )
    db.add(a)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # typisk: (hand_id, street, seq) er unik i modellen din
        raise HTTPException(status_code=400, detail="Action already exists for this hand/street/seq")

    db.refresh(a)
    return a


@router.get("", response_model=list[ActionOut])
def list_actions(hand_id: int, db: DbSession = Depends(get_db)):
    # hand_id som query param: /actions?hand_id=4
    return (
        db.query(Action)
        .filter(Action.hand_id == hand_id)
        .order_by(Action.street.asc(), Action.seq.asc())
        .all()
    )
