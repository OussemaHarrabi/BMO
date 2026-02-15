from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import re

from api.routes import chat, memory, system, capture


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="BMO API",
    description="Personal AI Memory System",
    version="0.1.0",
    lifespan=lifespan
)

allowed_origins = [
    os.getenv("FRONTEND_URL", "http://localhost:3000"),
    "http://localhost:3000",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^chrome-extension://.*$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(memory.router, prefix="/api/memory", tags=["Memory"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(capture.router, prefix="/api/capture", tags=["Capture"])


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/")
async def root():
    return {
        "name": "BMO API",
        "version": "0.1.0",
        "docs": "/docs"
    }

