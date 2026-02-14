"""Sample code with intentional issues for testing CodeRev."""

import os
import pickle


# Security issue: Hardcoded credentials
DATABASE_PASSWORD = "super_secret_password_123"
API_KEY = "sk-1234567890abcdef"


def get_user(user_id):
    """Get user from database - contains SQL injection vulnerability."""
    # Bug: SQL injection vulnerability
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return execute_query(query)


def unsafe_deserialize(data):
    """Deserialize data - security issue with pickle."""
    # Security: Unsafe deserialization
    return pickle.loads(data)


def process_items(items):
    """Process items - contains performance issue."""
    result = []
    for item in items:
        # Performance: String concatenation in loop
        result_str = ""
        for char in str(item):
            result_str = result_str + char
        result.append(result_str)
    return result


def calculate_total(numbers):
    """Calculate total - contains potential bug."""
    total = 0
    for i in range(len(numbers)):  # Style: Use enumerate
        # Bug: Possible index error if numbers is empty
        total += numbers[i]
    return total / len(numbers)  # Bug: Division by zero if empty


class UserManager:
    """User management class with various issues."""
    
    def __init__(self):
        self.users = {}
        self.password = "admin123"  # Security: Hardcoded password
    
    def add_user(self, name, data):
        # Bug: No validation
        self.users[name] = data
    
    def get_user_unsafe(self, name):
        # Bug: KeyError if name doesn't exist
        return self.users[name]
    
    def execute_command(self, cmd):
        """Execute system command - security vulnerability."""
        # Security: Command injection
        os.system(cmd)
    
    def read_file(self, filename):
        """Read file contents."""
        # Bug: No error handling, resource leak
        f = open(filename)
        content = f.read()
        return content


def recursive_function(n):
    """Recursive function without base case."""
    # Bug: Missing base case - infinite recursion
    return recursive_function(n - 1) + 1


# This function is fine
def clean_function(items: list[str]) -> list[str]:
    """Example of good code."""
    if not items:
        return []
    
    return [item.strip().lower() for item in items if item]
