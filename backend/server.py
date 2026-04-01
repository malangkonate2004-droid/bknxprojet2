from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()  # Charge les variables du fichier .env

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI(title="BKNX Advisory API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

class ContactRequest(BaseModel):
    firstName: str = Field(..., min_length=1, max_length=100)
    lastName: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=20)
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=20, max_length=5000)

class ContactResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    id: str
    firstName: str
    lastName: str
    email: str
    phone: Optional[str]
    subject: str
    message: str
    status: str
    created_at: str

# Routes
@api_router.get("/")
async def root():
    return {"message": "BKNX Advisory API"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "BKNX Advisory"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

@api_router.post("/contact", response_model=ContactResponse)
async def submit_contact_form(contact: ContactRequest):
    """Submit a contact form request"""
    try:
        contact_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        
        doc = {
            "id": contact_id,
            "firstName": contact.firstName,
            "lastName": contact.lastName,
            "email": contact.email,
            "phone": contact.phone,
            "subject": contact.subject,
            "message": contact.message,
            "status": "new",
            "created_at": created_at
        }
        
        await db.contact_requests.insert_one(doc)
        
        # Remove MongoDB _id before returning
        doc.pop('_id', None)
        
        logging.info(f"New contact request from {contact.email} - Subject: {contact.subject}")
        
        return ContactResponse(**doc)
        
    except Exception as e:
        logging.error(f"Error submitting contact form: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'envoi du formulaire")

@api_router.get("/contact", response_model=List[ContactResponse])
async def get_contact_requests():
    """Get all contact requests (admin endpoint)"""
    contacts = await db.contact_requests.find({}, {"_id": 0}).to_list(1000)
    return [ContactResponse(**c) for c in contacts]

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
