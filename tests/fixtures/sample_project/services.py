"""
Fixture: service layer — user service.

Call chain:
  services.UserService.get_user   calls  models.User.__init__
  services.UserService.get_user   calls  models.User.display_name
  services.UserService.list_users calls  models.User.__init__
"""

from models import User


class UserService:
    """Service for managing users."""

    def __init__(self) -> None:
        self._store: dict = {}

    def get_user(self, user_id: int) -> User:
        """Fetch a user by ID and return a User instance."""
        raw = self._store.get(user_id, {"user_id": user_id, "name": "Unknown"})
        user = User(raw["user_id"], raw["name"])
        return user

    def list_users(self) -> list:
        """Return all users as User objects."""
        return [User(uid, data["name"]) for uid, data in self._store.items()]

    def add_user(self, user_id: int, name: str) -> None:
        """Persist a new user."""
        self._store[user_id] = {"user_id": user_id, "name": name}
