from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio

from src.dashboard import DashboardState


dashboard_state = DashboardState()
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
api = FastAPI(title="FillPac AI Dashboard")
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.get("/health")
async def health():
    return {"status": "ok"}


@api.get("/state")
async def state():
    return dashboard_state.snapshot()


@sio.event
async def connect(sid, environ, auth):
    await sio.emit("dashboard_state", dashboard_state.snapshot(), to=sid)


app = socketio.ASGIApp(sio, api)
