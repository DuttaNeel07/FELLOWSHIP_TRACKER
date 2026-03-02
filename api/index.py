from fastapi import FastAPI
from fastapi.responses import FileResponse
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
import uvicorn

env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    print("❌ API failed to find MONGO_URI at:", env_path)
else:
    print("✅ API successfully connected to MongoDB Atlas")

import typing
import typing_extensions
from typing import Any

client: Any = AsyncIOMotorClient(MONGO_URL)
db: Any = client.fellowship_tracker  
collection: Any = db.fellowships     

@app.get("/")
async def read_index():
    # Serve the index.html file from the parent directory
    index_path = Path(__file__).parent.parent / 'index.html'
    return FileResponse(index_path)

@app.get("/api/fellowships")
async def get_fellowships():
    cursor = collection.find().sort("last_updated", -1).limit(100)
    
    results = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        results.append(doc)
        
    return results 

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)