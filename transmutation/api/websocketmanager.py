# Copyright 2023 Badreddine LEJMI.
# SPDX-License-Identifier: 	AGPL-3.0-or-later

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self.connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.connections.remove(websocket)

    async def message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.connections:
            await connection.send_text(message)


manager = WebSocketManager()
