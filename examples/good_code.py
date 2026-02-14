"""Example of well-written Python code."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@dataclass
class User:
    """Represents a user in the system."""
    
    id: int
    name: str
    email: str
    active: bool = True
    
    def __post_init__(self) -> None:
        """Validate user data after initialization."""
        if not self.name:
            raise ValueError("User name cannot be empty")
        if "@" not in self.email:
            raise ValueError("Invalid email format")


class UserRepository:
    """Repository for user data access."""
    
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string
        self._users: dict[int, User] = {}
    
    def get(self, user_id: int) -> Optional[User]:
        """Get user by ID.
        
        Args:
            user_id: The unique identifier of the user.
            
        Returns:
            The User if found, None otherwise.
        """
        return self._users.get(user_id)
    
    def get_or_raise(self, user_id: int) -> User:
        """Get user by ID or raise an exception.
        
        Args:
            user_id: The unique identifier of the user.
            
        Returns:
            The User object.
            
        Raises:
            KeyError: If user is not found.
        """
        user = self.get(user_id)
        if user is None:
            raise KeyError(f"User {user_id} not found")
        return user
    
    def add(self, user: User) -> None:
        """Add a new user to the repository.
        
        Args:
            user: The user to add.
            
        Raises:
            ValueError: If user with same ID already exists.
        """
        if user.id in self._users:
            raise ValueError(f"User {user.id} already exists")
        
        self._users[user.id] = user
        logger.info("Added user %d: %s", user.id, user.name)
    
    def update(self, user: User) -> None:
        """Update an existing user.
        
        Args:
            user: The user to update.
            
        Raises:
            KeyError: If user doesn't exist.
        """
        if user.id not in self._users:
            raise KeyError(f"User {user.id} not found")
        
        self._users[user.id] = user
        logger.info("Updated user %d", user.id)
    
    def delete(self, user_id: int) -> bool:
        """Delete a user by ID.
        
        Args:
            user_id: The ID of the user to delete.
            
        Returns:
            True if user was deleted, False if not found.
        """
        if user_id in self._users:
            del self._users[user_id]
            logger.info("Deleted user %d", user_id)
            return True
        return False
    
    def list_active(self) -> list[User]:
        """Get all active users.
        
        Returns:
            List of active users.
        """
        return [user for user in self._users.values() if user.active]


@contextmanager
def transaction(repo: UserRepository):
    """Context manager for transactional operations.
    
    Args:
        repo: The repository to use.
        
    Yields:
        The repository for use within the transaction.
    """
    logger.debug("Starting transaction")
    try:
        yield repo
        logger.debug("Transaction completed")
    except Exception as e:
        logger.error("Transaction failed: %s", e)
        raise


def process_users(
    users: list[User],
    *,
    filter_inactive: bool = False,
) -> list[str]:
    """Process a list of users and return their emails.
    
    Args:
        users: List of users to process.
        filter_inactive: If True, exclude inactive users.
        
    Returns:
        List of email addresses.
    """
    if filter_inactive:
        users = [u for u in users if u.active]
    
    return [user.email for user in users]
