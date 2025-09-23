
from app.extensions import db
from app.models import ActivityLog

def log_action(action: str, user_id=None, event_id=None, target_node_id=None, details=None):
    log = ActivityLog(
        user_id=user_id,
        event_id=event_id,
        action=action,
        target_node_id=target_node_id,
        details=details or {}
    )
    db.session.add(log)
    db.session.commit()
    return log
