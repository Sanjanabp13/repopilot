"""
Fixture: API layer — handlers that call the service layer.

Call chain:
  api.get_user_handler     calls  services.UserService.get_user
  api.list_users_handler   calls  services.UserService.list_users
  api.create_user_handler  calls  services.UserService.add_user
"""

from services import UserService


_svc = UserService()


def get_user_handler(user_id: int) -> dict:
    """Handle GET /users/{user_id}."""
    user = _svc.get_user(user_id)
    return {"id": user.user_id, "name": user.name}


def list_users_handler() -> list:
    """Handle GET /users."""
    users = _svc.list_users()
    return [{"id": u.user_id, "name": u.name} for u in users]


def create_user_handler(user_id: int, name: str) -> dict:
    """Handle POST /users."""
    _svc.add_user(user_id, name)
    return {"created": user_id}
