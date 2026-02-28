"""Pytest configuration and shared fixtures for CodeRev tests."""

import os
import pytest


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that require real API keys",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires --integration flag)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --integration flag is passed."""
    if config.getoption("--integration"):
        # --integration given: run integration tests
        return
    
    skip_integration = pytest.mark.skip(reason="need --integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture
def anthropic_api_key():
    """Get Anthropic API key from environment.
    
    Skips the test if the key is not available.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY environment variable not set")
    return key


@pytest.fixture
def openai_api_key():
    """Get OpenAI API key from environment.
    
    Skips the test if the key is not available.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY environment variable not set")
    return key


@pytest.fixture
def sample_python_code():
    """Sample Python code with intentional issues for testing."""
    return '''
def calculate_average(numbers):
    total = 0
    for n in numbers:
        total = total + n
    average = total / len(numbers)
    return average

def process_data(data):
    result = []
    for item in data:
        if item != None:
            result.append(item * 2)
    return result

class UserManager:
    def __init__(self):
        self.users = {}
    
    def add_user(self, id, name, email):
        self.users[id] = {"name": name, "email": email}
        return True
    
    def get_user(self, id):
        return self.users[id]  # May raise KeyError
    
    def delete_user(self, id):
        del self.users[id]
        print(f"Deleted user {id}")
'''


@pytest.fixture
def sample_javascript_code():
    """Sample JavaScript code with intentional issues for testing."""
    return '''
function fetchUserData(userId) {
    var data = null;
    fetch('/api/users/' + userId)
        .then(response => response.json())
        .then(json => {
            data = json;
        });
    return data;  // Returns before async completes
}

function processItems(items) {
    let result = [];
    for (var i = 0; i < items.length; i++) {
        setTimeout(() => {
            result.push(items[i] * 2);  // Closure over var
        }, 100);
    }
    return result;
}

const config = {
    apiKey: "sk-1234567890abcdef",  // Hardcoded secret
    debug: true,
}

function validateEmail(email) {
    if (email == undefined) {
        return false;
    }
    return email.includes("@");
}
'''
