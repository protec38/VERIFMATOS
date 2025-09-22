from fastapi import Header, HTTPException, Depends
from .security import decode_token
from typing import Optional

def get_current(role: Optional[str] = None):
    def _dep(authorization: str = Header(None)):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Not authenticated")
        token = authorization.split()[1]
        try:
            payload = decode_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")
        if role and payload.get("role") not in ([role] if isinstance(role, str) else role):
            raise HTTPException(status_code=403, detail="Forbidden")
        return payload
    return _dep
