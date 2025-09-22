from fastapi import FastAPI, Depends, HTTPException, Query, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sqlalchemy.orm import Session
from sqlalchemy import select
from .database import SessionLocal, Base, engine
from . import models, schemas, security
from .deps import get_current
from .utils import seed_admin, seed_demo_items

import os
import pathlib
import random
import string

# --------------------------------------------------------------------------------------
# APP
# --------------------------------------------------------------------------------------
app = FastAPI(
    title="PC Isère - Inventaire & Missions",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs"
)

# CORS
origins = os.getenv("CORS_ORIGINS", "http://localhost,http://127.0.0.1").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------------------
# Static (serveur du frontend buildé) + Fallback SPA
# --------------------------------------------------------------------------------------
STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

# Si une route n'existe pas côté API/static et que ce n'est pas /api -> renvoyer index.html
@app.exception_handler(StarletteHTTPException)
async def spa_404_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api"):
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
    raise exc

# --------------------------------------------------------------------------------------
# DB INIT + SEED
# --------------------------------------------------------------------------------------
Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    # Admin par défaut: admin@pcisere.fr / (ADMIN_DEFAULT_PASSWORD ou 'admin')
    seed_admin(db, os.getenv("ADMIN_DEFAULT_PASSWORD", "admin"))
    # Items/KITs de démo (Sac PS, gants, DAE…)
    seed_demo_items(db)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def gen_code(n: int = 6) -> str:
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))

# --------------------------------------------------------------------------------------
# AUTH
# --------------------------------------------------------------------------------------
@app.post("/api/auth/login", response_model=schemas.Token)
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == body.email).first()
    if not user or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = security.create_token(user.id, user.role.value)
    return {"access_token": token, "role": user.role.value}

# --------------------------------------------------------------------------------------
# USERS (Admin)
# --------------------------------------------------------------------------------------
@app.post("/api/admin/users", response_model=schemas.UserOut)
def create_user(
    body: schemas.UserCreate,
    db: Session = Depends(get_db),
    me=Depends(get_current(role="ADMIN")),
):
    if db.query(models.User).filter(models.User.email == body.email).first():
        raise HTTPException(400, "Email already exists")
    user = models.User(
        email=body.email,
        full_name=body.full_name,
        role=models.Role(body.role),
        password_hash=security.hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return schemas.UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
    )

@app.get("/api/admin/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), me=Depends(get_current(role="ADMIN"))):
    users = db.query(models.User).all()
    return [
        schemas.UserOut(
            id=u.id, email=u.email, full_name=u.full_name, role=u.role.value, is_active=u.is_active
        )
        for u in users
    ]

@app.put("/api/admin/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: str,
    body: schemas.UserUpdate,
    db: Session = Depends(get_db),
    me=Depends(get_current(role="ADMIN")),
):
    u = db.get(models.User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.role is not None:
        u.role = models.Role(body.role)
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.password:
        u.password_hash = security.hash_password(body.password)
    db.commit()
    db.refresh(u)
    return schemas.UserOut(
        id=u.id, email=u.email, full_name=u.full_name, role=u.role.value, is_active=u.is_active
    )

@app.delete("/api/admin/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db), me=Depends(get_current(role="ADMIN"))):
    u = db.get(models.User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    db.delete(u)
    db.commit()
    return {"ok": True}

# --------------------------------------------------------------------------------------
# STOCK: Items & Kits (Admin / Chef lecture)
# --------------------------------------------------------------------------------------
@app.post("/api/admin/items", response_model=schemas.ItemOut)
def create_item(
    body: schemas.ItemBase,
    db: Session = Depends(get_db),
    me=Depends(get_current(role="ADMIN")),
):
    item = models.Item(
        name=body.name,
        description=body.description,
        type=models.ItemType(body.type),
        serial_number=body.serial_number,
        stock_qty=body.stock_qty,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return schemas.ItemOut(
        id=item.id,
        name=item.name,
        description=item.description,
        type=item.type.value,
        serial_number=item.serial_number,
        stock_qty=item.stock_qty,
    )

@app.get("/api/admin/items", response_model=list[schemas.ItemOut])
def list_items(db: Session = Depends(get_db), me=Depends(get_current(role=["ADMIN", "CHEF"]))):
    items = db.query(models.Item).all()

    def to_out(i: models.Item):
        return {
            "id": i.id,
            "name": i.name,
            "description": i.description,
            "type": i.type.value,
            "serial_number": i.serial_number,
            "stock_qty": i.stock_qty,
        }

    return [to_out(i) for i in items]

@app.put("/api/admin/items/{item_id}", response_model=schemas.ItemOut)
def update_item(
    item_id: str,
    body: schemas.ItemUpdate,
    db: Session = Depends(get_db),
    me=Depends(get_current(role="ADMIN")),
):
    it = db.get(models.Item, item_id)
    if not it:
        raise HTTPException(404, "Item not found")
    for field, value in body.dict(exclude_unset=True).items():
        if field == "type" and value is not None:
            setattr(it, field, models.ItemType(value))
        else:
            setattr(it, field, value)
    db.commit()
    db.refresh(it)
    return {
        "id": it.id,
        "name": it.name,
        "description": it.description,
        "type": it.type.value,
        "serial_number": it.serial_number,
        "stock_qty": it.stock_qty,
    }

@app.delete("/api/admin/items/{item_id}")
def delete_item(item_id: str, db: Session = Depends(get_db), me=Depends(get_current(role="ADMIN"))):
    it = db.get(models.Item, item_id)
    if not it:
        raise HTTPException(404, "Item not found")
    db.delete(it)
    db.commit()
    return {"ok": True}

# Recette d'un KIT (SET/GET)
@app.post("/api/admin/kits/{kit_id}/recipe")
def set_kit_recipe(
    kit_id: str,
    body: schemas.KitRecipe,
    db: Session = Depends(get_db),
    me=Depends(get_current(role="ADMIN")),
):
    kit = db.get(models.Item, kit_id)
    if not kit or kit.type != models.ItemType.KIT:
        raise HTTPException(404, "KIT not found")
    db.query(models.KitItem).filter(models.KitItem.kit_id == kit_id).delete()
    for it in body.items:
        db.add(
            models.KitItem(
                kit_id=kit_id, component_id=it.component_id, required_qty=it.required_qty
            )
        )
    db.commit()
    return {"ok": True}

@app.get("/api/admin/kits/{kit_id}/recipe")
def kits_recipe(
    kit_id: str,
    db: Session = Depends(get_db),
    me=Depends(get_current(role=["ADMIN", "CHEF"])),
):
    kit = db.get(models.Item, kit_id)
    if not kit or kit.type != models.ItemType.KIT:
        raise HTTPException(404, "KIT not found")
    comps = (
        db.query(models.KitItem, models.Item)
        .join(models.Item, models.KitItem.component_id == models.Item.id)
        .filter(models.KitItem.kit_id == kit_id)
        .all()
    )
    return {
        "kit": {"id": kit.id, "name": kit.name},
        "components": [
            {"item_id": it.id, "name": it.name, "required_qty": ki.required_qty}
            for ki, it in comps
        ],
    }

# --------------------------------------------------------------------------------------
# EVENTS (Chef/Admin)
# --------------------------------------------------------------------------------------
@app.post("/api/events", response_model=schemas.EventOut)
def create_event(
    body: schemas.EventCreate,
    db: Session = Depends(get_db),
    me=Depends(get_current(role=["ADMIN", "CHEF"])),
):
    access_code = gen_code()
    ev = models.Event(
        title=body.title, location=body.location, chief_id=body.chief_id, access_code=access_code
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    for kid in body.kit_ids:
        db.add(models.EventKit(event_id=ev.id, kit_id=kid))
    db.commit()
    return schemas.EventOut(
        id=ev.id,
        title=ev.title,
        location=ev.location,
        start_at=ev.start_at,
        chief_id=ev.chief_id,
        access_code=ev.access_code,
        is_active=ev.is_active,
    )

@app.get("/api/events", response_model=list[schemas.EventOut])
def list_events(db: Session = Depends(get_db), me=Depends(get_current(role=["ADMIN", "CHEF"]))):
    evs = db.query(models.Event).order_by(models.Event.start_at.desc()).all()
    return [
        schemas.EventOut(
            id=e.id,
            title=e.title,
            location=e.location,
            start_at=e.start_at,
            chief_id=e.chief_id,
            access_code=e.access_code,
            is_active=e.is_active,
        )
        for e in evs
    ]

@app.get("/api/events/{event_id}", response_model=schemas.EventOut)
def get_event(
    event_id: str, db: Session = Depends(get_db), me=Depends(get_current(role=["ADMIN", "CHEF"]))
):
    e = db.get(models.Event, event_id)
    if not e:
        raise HTTPException(404, "Not found")
    return schemas.EventOut(
        id=e.id,
        title=e.title,
        location=e.location,
        start_at=e.start_at,
        chief_id=e.chief_id,
        access_code=e.access_code,
        is_active=e.is_active,
    )

@app.put("/api/events/{event_id}", response_model=schemas.EventOut)
def update_event(
    event_id: str,
    body: schemas.EventUpdate,
    db: Session = Depends(get_db),
    me=Depends(get_current(role=["ADMIN", "CHEF"])),
):
    e = db.get(models.Event, event_id)
    if not e:
        raise HTTPException(404, "Not found")
    for k, v in body.dict(exclude_unset=True).items():
        setattr(e, k, v)
    db.commit()
    db.refresh(e)
    return schemas.EventOut(
        id=e.id,
        title=e.title,
        location=e.location,
        start_at=e.start_at,
        chief_id=e.chief_id,
        access_code=e.access_code,
        is_active=e.is_active,
    )

@app.delete("/api/events/{event_id}")
def delete_event(
    event_id: str, db: Session = Depends(get_db), me=Depends(get_current(role=["ADMIN", "CHEF"]))
):
    e = db.get(models.Event, event_id)
    if not e:
        raise HTTPException(404, "Not found")
    db.delete(e)
    db.commit()
    return {"ok": True}

@app.post("/api/events/{event_id}/assign_chief/{user_id}")
def assign_chief(
    event_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    me=Depends(get_current(role=["ADMIN"])),
):
    e = db.get(models.Event, event_id)
    u = db.get(models.User, user_id)
    if not e or not u:
        raise HTTPException(404, "Not found")
    e.chief_id = u.id
    db.commit()
    return {"ok": True, "chief_id": e.chief_id}

@app.get("/api/events/{event_id}/status", response_model=schemas.EventStatus)
def event_status(
    event_id: str, db: Session = Depends(get_db), me=Depends(get_current(role=["ADMIN", "CHEF"]))
):
    kits = (
        db.query(models.EventKit, models.Item)
        .join(models.Item, models.Item.id == models.EventKit.kit_id)
        .filter(models.EventKit.event_id == event_id)
        .all()
    )
    kits_out = [
        {"event_kit_id": ek.id, "kit_id": kit.id, "kit_name": kit.name, "loaded": ek.loaded}
        for ek, kit in kits
    ]
    verifs = (
        db.query(models.Verification)
        .filter(models.Verification.event_id == event_id)
        .order_by(models.Verification.verified_at.desc())
        .all()
    )
    ver_out = [
        {
            "id": v.id,
            "kit_id": v.kit_id,
            "item_id": v.item_id,
            "qty_checked": v.qty_checked,
            "status": v.status.value,
            "comment": v.comment,
            "verified_by": v.verified_by,
            "verified_at": v.verified_at.isoformat(),
        }
        for v in verifs
    ]
    parts = (
        db.query(models.Participant)
        .filter(models.Participant.event_id == event_id)
        .order_by(models.Participant.joined_at.desc())
        .all()
    )
    p_out = [
        {
            "id": p.id,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "joined_at": p.joined_at.isoformat(),
        }
        for p in parts
    ]
    return {"kits": kits_out, "verifications": ver_out, "participants": p_out}

@app.post("/api/events/{event_id}/kits/{event_kit_id}/loaded")
def set_kit_loaded(
    event_id: str,
    event_kit_id: str,
    loaded: bool = Query(True),
    db: Session = Depends(get_db),
    me=Depends(get_current(role=["ADMIN", "CHEF"])),
):
    ek = db.get(models.EventKit, event_kit_id)
    if not ek or ek.event_id != event_id:
        raise HTTPException(404, "Not found")
    ek.loaded = loaded
    db.commit()
    return {"ok": True, "loaded": ek.loaded}

# --------------------------------------------------------------------------------------
# PUBLIC / FLOW SECOURISTE
# --------------------------------------------------------------------------------------
@app.get("/api/public/event_by_code/{code}")
def event_by_code(code: str, db: Session = Depends(get_db)):
    ev = (
        db.query(models.Event)
        .filter(models.Event.access_code == code, models.Event.is_active == True)
        .first()
    )
    if not ev:
        raise HTTPException(404, "Event not found or inactive")
    e_ks = db.query(models.EventKit).filter(models.EventKit.event_id == ev.id).all()
    kits = []
    for ek in e_ks:
        kit = db.get(models.Item, ek.kit_id)
        comps = (
            db.query(models.KitItem, models.Item)
            .join(models.Item, models.KitItem.component_id == models.Item.id)
            .filter(models.KitItem.kit_id == kit.id)
            .all()
        )
        kits.append(
            {
                "event_kit_id": ek.id,
                "kit_id": kit.id,
                "kit_name": kit.name,
                "components": [
                    {
                        "item_id": it.id,
                        "name": it.name,
                        "type": it.type.value,
                        "required_qty": ki.required_qty,
                    }
                    for ki, it in comps
                ],
            }
        )
    return {
        "event": {
            "id": ev.id,
            "title": ev.title,
            "location": ev.location,
            "start_at": ev.start_at.isoformat(),
        },
        "kits": kits,
    }

@app.post("/api/public/{event_id}/join")
def join_event(event_id: str, body: schemas.ParticipantJoin, db: Session = Depends(get_db)):
    p = models.Participant(
        event_id=event_id, first_name=body.first_name, last_name=body.last_name
    )
    db.add(p)
    db.commit()
    return {"ok": True, "participant_id": p.id, "display_name": f"{p.first_name} {p.last_name}"}

@app.post("/api/public/{event_id}/verify")
def add_verification(
    event_id: str,
    body: schemas.VerificationIn,
    participant: str = Query(..., description="participant display name"),
    db: Session = Depends(get_db),
):
    v = models.Verification(
        event_id=event_id,
        kit_id=body.kit_id,
        item_id=body.item_id,
        qty_checked=body.qty_checked,
        status=models.CheckStatus(body.status),
        comment=body.comment,
        verified_by=participant,
    )
    db.add(v)
    db.commit()
    return {"ok": True, "id": v.id}
