
from functools import wraps
from flask import abort
from flask_login import current_user

def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or getattr(current_user, "role", None) not in roles:
                return abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return deco
