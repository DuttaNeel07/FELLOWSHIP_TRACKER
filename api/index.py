from fastapi import FastAPI
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
import uvicorn

# 1. Load Environment Variables
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# 2. Initialize FastAPI
app = FastAPI()

# 3. CORS Configuration (Crucial!)
# This allows your index.html to talk to this Python script.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all websites for now (dev mode)
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. MongoDB Connection
# Motor is the async driver for MongoDB
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    print("❌ API failed to find MONGO_URI at:", env_path)
else:
    print("✅ API successfully connected to MongoDB Atlas")

client = AsyncIOMotorClient(MONGO_URL)
db = client.fellowship_tracker  # Your database name
collection = db.fellowships     # Your 'table' name

# 5. The API Endpoint
@app.get("/api/fellowships")
async def get_fellowships():
    # Fetch top 100 fellowships sorted by the newest first
    cursor = collection.find().sort("last_updated", -1).limit(100)
    
    results = []
    async for doc in cursor:
        # MongoDB uses a special 'ObjectId' format that JS doesn't understand.
        # We must convert it to a standard string.
        doc["_id"] = str(doc["_id"])
        results.append(doc)
        
    return results # FastAPI automatically turns this list into JSON

# 6. Run the server
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)