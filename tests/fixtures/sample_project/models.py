"""
Fixture: data layer — database models.

Call chain:
  models.User.__init__          (leaf — nothing calls into it from here)
"""


class User:
    """A simple user record."""

    def __init__(self, user_id: int, name: str) -> None:
        self.user_id = user_id
        self.name = name

    def display_name(self) -> str:
        """Return a formatted display name."""
        return f"User({self.user_id}): {self.name}"
