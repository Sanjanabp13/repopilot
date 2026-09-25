"""
Fixture: test file — tests for the service layer.

Call chain:
  test_services.test_get_user     calls  services.UserService.get_user
  test_services.test_list_users   calls  services.UserService.list_users
  test_services.test_add_user     calls  services.UserService.add_user
"""

from services import UserService


def test_get_user() -> None:
    """Test that get_user returns a User with correct ID."""
    svc = UserService()
    svc.add_user(1, "Alice")
    user = svc.get_user(1)
    assert user.user_id == 1
    assert user.name == "Alice"


def test_list_users() -> None:
    """Test that list_users returns all added users."""
    svc = UserService()
    svc.add_user(1, "Alice")
    svc.add_user(2, "Bob")
    users = svc.list_users()
    assert len(users) == 2


def test_add_user() -> None:
    """Test that add_user persists a user."""
    svc = UserService()
    svc.add_user(42, "Charlie")
    result = svc.get_user(42)
    assert result.name == "Charlie"
