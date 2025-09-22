from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str

class LoginRequest(BaseModel):
    email: str
    password: str

class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str
    role: Literal["ADMIN","CHEF","SECOURISTE"] = "CHEF"

class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool

class ItemBase(BaseModel):
    name: str
    description: str = ""
    type: Literal["UNIQUE","BULK","KIT"] = "BULK"
    serial_number: Optional[str] = None
    stock_qty: int = 0

class ItemOut(ItemBase):
    id: str

class KitItem(BaseModel):
    component_id: str
    required_qty: int = 1

class KitRecipe(BaseModel):
    kit_id: str
    items: List[KitItem]

class EventCreate(BaseModel):
    title: str
    location: str = ""
    chief_id: Optional[str] = None
    kit_ids: list[str] = []

class EventOut(BaseModel):
    id: str
    title: str
    location: str
    start_at: datetime
    chief_id: Optional[str]
    access_code: str
    is_active: bool

class ParticipantJoin(BaseModel):
    first_name: str
    last_name: str

class VerificationIn(BaseModel):
    item_id: str
    kit_id: Optional[str] = None
    qty_checked: int = 0
    status: Literal["OK","MISSING","DAMAGED"] = "OK"
    comment: str = ""

class EventStatus(BaseModel):
    kits: list
    verifications: list
    participants: list

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[Literal["ADMIN","CHEF","SECOURISTE"]] = None
    is_active: Optional[bool] = None

class ItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[Literal["UNIQUE","BULK","KIT"]] = None
    serial_number: Optional[str] = None
    stock_qty: Optional[int] = None

class EventUpdate(BaseModel):
    title: Optional[str] = None
    location: Optional[str] = None
    chief_id: Optional[str] = None
    is_active: Optional[bool] = None
