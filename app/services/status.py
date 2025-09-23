from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, Any

from .. import db
from ..models import Event, EventParent, EventChild, EventLoad, EventPresence

def build_status(ev: Event) -> Dict[str, Any]:
    """
    Build the live status dict used by the UI:
    {
      "verifications": { "<childId>": {"verified": bool, "by": str, "at": iso}, ... },
      "parents_complete": { "<parentId>": bool, ... },
      "loaded": { "<parentId>": bool, ... },
      "busy": { "<parentId>": ["Alice", "Bob"], ... }
    }
    """
    # verifications for all children
    verifs = {}
    rows = EventChild.query.filter_by(event_id=ev.id).all()
    for r in rows:
        verifs[str(r.child_id)] = {
            "verified": bool(r.verified),
            "by": r.verified_by or None,
            "at": r.verified_at.isoformat() if r.verified_at else None,
        }

    # parents_complete: all included leaves under parent verified
    parents_complete = {}
    eparents = EventParent.query.filter_by(event_id=ev.id).all()
    included_ids = {r.child_id for r in rows if r.included}

    for ep in eparents:
        # traverse descendants of the parent
        stack = list(ep.parent.children)
        needed = []
        while stack:
            n = stack.pop(0)
            if n.kind == "leaf":
                if n.id in included_ids:
                    needed.append(n.id)
            else:
                stack.extend(list(n.children))

        if not needed:
            parents_complete[str(ep.parent_id)] = True
        else:
            # all needed verified?
            ok = all(verifs.get(str(cid), {}).get("verified", False) for cid in needed)
            parents_complete[str(ep.parent_id)] = ok

    # loaded map
    loads = EventLoad.query.filter_by(event_id=ev.id).all()
    loaded_map = {str(l.parent_id): bool(l.loaded) for l in loads}

    # busy: list volunteers seen in the last 2 minutes (parent_id==0 = global presence)
    since = datetime.utcnow() - timedelta(minutes=2)
    pres = EventPresence.query.filter(
        EventPresence.event_id == ev.id,
        EventPresence.last_seen >= since
    ).all()
    # group by parent_id (we mostly use 0/global)
    busy = {}
    for p in pres:
        lst = busy.setdefault(str(p.parent_id), [])
        if p.actor not in lst:
            lst.append(p.actor)

    return {
        "verifications": verifs,
        "parents_complete": parents_complete,
        "loaded": loaded_map,
        "busy": busy,
    }