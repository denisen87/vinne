from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from treys import Card, Deck, Evaluator

router = APIRouter(prefix="", tags=["equity"])

class EquityRequest(BaseModel):
    hero: List[str]
    board: List[str] = []
    villains: int = 1
    iters: int = 20000

class EquityResponse(BaseModel):
    win: float
    tie: float
    lose: float
    iters: int

@router.post("/equity", response_model=EquityResponse)
def equity(req: EquityRequest):
    evaluator = Evaluator()

    try:
        hero_cards = [Card.new(c) for c in req.hero]
        board_cards = [Card.new(c) for c in req.board]
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Kortformat feil: {str(e)}. Bruk f.eks. 'As', 'Kh', '7d'")

    wins = ties = losses = 0

    for _ in range(req.iters):
        deck = Deck()

        for c in hero_cards + board_cards:
            deck.cards.remove(c)

        villains = []
        for _ in range(req.villains):
            villains.append([deck.draw(1)[0], deck.draw(1)[0]])

        board = board_cards[:]
        while len(board) < 5:
            board.append(deck.draw(1)[0])

        hero_score = evaluator.evaluate(board, hero_cards)
        villain_scores = [evaluator.evaluate(board, v) for v in villains]
        best_villain = min(villain_scores)

        if hero_score < best_villain:
            wins += 1
        elif hero_score == best_villain:
            ties += 1
        else:
            losses += 1

    total = wins + ties + losses

    return EquityResponse(
        win=wins / total,
        tie=ties / total,
        lose=losses / total,
        iters=req.iters
    )
