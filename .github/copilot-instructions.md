# Copilot / AI agent instructions — Vinne (backend)

Short, actionable guidance for contributing code and making fast, correct edits.

1) Big picture
- Backend: FastAPI app in `backend/main.py` that registers `routers/*` endpoints and calls `Base.metadata.create_all` (no Alembic).
- DB: SQLite via SQLAlchemy (`backend/database.py`, `sqlite:///./poker.db`, `check_same_thread=False`).
- Data model: `backend/models.py` defines `Session`, `Hand`, `HandPlayer`, `Action`, `Board`, `HoleCards`. Relationships are ORM-driven and relied on heavily by router logic.
- Schemas: `backend/schemas.py` contains Pydantic response/input models. Many endpoints use `response_model` and `Config.from_attributes = True`.

2) Where core logic lives
- Most domain logic (HUD stats, leaks, impact calculations) lives in `backend/routers/players.py` and is reused by other routers (e.g. sessions compare). Expect heavy SQLAlchemy queries and in-file helper functions.
- Import endpoints: `backend/routers/import_betsolid.py` parses BetSolid XML and writes `Hand`, `HandPlayer`, `Action` rows. Use this as canonical XML->DB example.
- `backend/services/` is present but currently empty — router modules contain business logic rather than service-layer abstractions.

3) Project-specific conventions & pitfalls
- Circular imports are avoided by importing helper functions inside route functions (e.g., `from routers.players import player_hud` inside handlers). Follow this pattern when reusing router helpers.
- The code assumes 6-max seating logic (see `_pos_6max`) and uses that to compute positions; reuse this helper or mirror its behavior when adding related features.
- DB migrations: there are none. `main.py` creates tables at startup (`Base.metadata.create_all`). For schema changes, be explicit and safe — dropping the DB file (`poker.db`) resets state.
- Note: `backend/routers/_init_.py` exists and is empty. It's not the standard `__init__.py` filename — be cautious if you add package-level imports or rely on package import side-effects.

4) Running & debugging
- From the project root, run the backend (from `backend/` working dir):

```bash
cd backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- Health-check: `GET http://127.0.0.1:8000/health`
- Import example (BetSolid XML):

```bash
curl -X POST -H "Content-Type: text/plain" --data-binary @session.xml \
  http://127.0.0.1:8000/import/betsolid
```

- Compare sessions example:

```
GET /compare-sessions?player_name=Alice&from_session_id=1&to_session_id=2
```

5) Patterns to follow when editing
- Keep heavy DB logic inside routers where similar logic already lives, or extract to `services/` and update imports consistently.
- When adding new endpoints that reuse existing helpers, import those helpers inside the endpoint function to avoid circular imports.
- Use the existing Pydantic schemas in `backend/schemas.py` for request/response models; many endpoints rely on `from_attributes = True` (they expect ORM objects or objects with attributes).
- Respect existing sampling guards and confidence logic (e.g., `conf_from_hands`, `conf_from_opps`) — these are used by leak scoring.

6) Integration points & external dependencies
- No external services are configured. Primary external artifact is uploaded BetSolid XML via `/import/betsolid`.
- SQLite DB file `poker.db` in `backend/` is the single persistent store.

7) Useful file references
 - App entry: [backend/main.py](../backend/main.py)
 - DB setup: [backend/database.py](../backend/database.py)
 - Models: [backend/models.py](../backend/models.py)
 - Schemas: [backend/schemas.py](../backend/schemas.py)
 - Main domain logic: [backend/routers/players.py](../backend/routers/players.py)
 - XML import example: [backend/routers/import_betsolid.py](../backend/routers/import_betsolid.py)

If any section is unclear or you'd like additional examples (unit tests, refactor plan to move logic into `services/`), tell me which part to expand. I'll iterate.
