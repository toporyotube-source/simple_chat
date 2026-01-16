from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import json

app = FastAPI()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Список комнат (каналов)
ROOMS = ["general", "games", "random"]


class ConnectionManager:
    def __init__(self):
        # комнаты -> список подключений
        self.rooms: Dict[str, List[WebSocket]] = {}
        # комнаты -> история сообщений
        self.history: Dict[str, List[dict]] = {}

    async def connect(self, room: str, websocket: WebSocket):
        await websocket.accept()
        self.rooms.setdefault(room, []).append(websocket)
        self.history.setdefault(room, [])
        # отправляем историю последних сообщений
        await self.send_history(room, websocket)
        await self.broadcast_status(room)

    def disconnect(self, room: str, websocket: WebSocket):
        if room in self.rooms and websocket in self.rooms[room]:
            self.rooms[room].remove(websocket)
            if not self.rooms[room]:
                self.rooms.pop(room, None)

    async def send_history(self, room: str, websocket: WebSocket):
        # последние 50 сообщений
        for msg in self.history.get(room, [])[-50:]:
            await websocket.send_text(json.dumps(msg, ensure_ascii=False))

    async def broadcast_message(self, room: str, message: dict):
        # сохраняем в историю (макс 200 сообщений на комнату)
        self.history.setdefault(room, []).append(message)
        if len(self.history[room]) > 200:
            self.history[room] = self.history[room][-200:]

        text = json.dumps(message, ensure_ascii=False)
        for connection in self.rooms.get(room, []):
            await connection.send_text(text)

    async def broadcast_status(self, room: str):
        online = len(self.rooms.get(room, []))
        msg = {
            "type": "status",
            "room": room,
            "online": online,
        }
        text = json.dumps(msg, ensure_ascii=False)
        for connection in self.rooms.get(room, []):
            await connection.send_text(text)


manager = ConnectionManager()


@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "rooms": ROOMS,
        },
    )


@app.websocket("/ws/{room}")
async def websocket_endpoint(websocket: WebSocket, room: str):
    if room not in ROOMS:
        # простая защита: неизвестные комнаты не разрешаем
        await websocket.close()
        return

    await manager.connect(room, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # ожидаем JSON от клиента
            payload = json.loads(data)
            username = payload.get("username", "Аноним")
            text = payload.get("text", "")
            now = datetime.now().strftime("%H:%M")

            message = {
                "type": "message",
                "room": room,
                "username": username,
                "text": text,
                "time": now,
            }
            await manager.broadcast_message(room, message)
    except WebSocketDisconnect:
        manager.disconnect(room, websocket)
        await manager.broadcast_status(room)