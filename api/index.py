from fastapi import FastAPI
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
    allow_origins=["*"], # Allow all websites for now (dev mode)
    allow_methods=["*"],
    allow_headers=["*"],
)
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    print("❌ API failed to find MONGO_URI at:", env_path)
else:
    print("✅ API successfully connected to MongoDB Atlas")

client = AsyncIOMotorClient(MONGO_URL)
db = client.fellowship_tracker  
collection = db.fellowships     

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