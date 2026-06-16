from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.exc import IntegrityError

from database import get_db
from models import Hand, HandPlayer
from schemas import HandPlayerCreate, HandPlayerOut

router = APIRouter(prefix="/hand_players", tags=["hand_players"])


@router.post("", response_model=HandPlayerOut)
def create_hand_player(payload: HandPlayerCreate, db: DbSession = Depends(get_db)):
    # 1) Sjekk at hand finnes
    h = db.query(Hand).filter(Hand.id == payload.hand_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Hand not found")

    hp = HandPlayer(**payload.model_dump())
    db.add(hp)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # typisk: (hand_id, player_name) finnes allerede
        raise HTTPException(status_code=400, detail="HandPlayer already exists for this hand")

    db.refresh(hp)
    return hp
