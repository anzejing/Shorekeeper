from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.config import router as config_router
from app.api.runtime import router as runtime_router

app = FastAPI(title="Shorekeeper", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router, prefix="/api/config", tags=["config"])
app.include_router(runtime_router, prefix="/api", tags=["runtime"])


@app.get("/health")
async def health():
    return {"status": "ok"}
