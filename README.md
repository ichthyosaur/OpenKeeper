# OpenKeeper

TRPG Agent system with a Keeper/GM driven by JSON-only output, server-authoritative state, strict secret visibility, and persistent history.

## Layout
- `backend/` FastAPI + MongoDB + WebSocket server
- `frontend/` React UI for Player/Host

## Backend
1. Configure `backend/config.yaml`
2. Install deps

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

3. Run server

```bash
uvicorn app.main:app --reload --app-dir backend
```

## Frontend
```bash
cd frontend
npm install
npm run dev
```

## Notes
- Single room, max 12 players.
- Keeper is stubbed; replace in `backend/app/keeper.py`.
- Server is authoritative; all state changes go through actions.
