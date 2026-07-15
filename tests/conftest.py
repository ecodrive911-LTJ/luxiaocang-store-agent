"""
conftest.py — pytest 共享 fixtures
"""
import pytest, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

@pytest.fixture(scope="session")
def base_url():
    return os.environ.get("LXC_BASE_URL", "http://127.0.0.1:8420")

@pytest.fixture(scope="session")
def admin_token(base_url):
    """返回 admin token（会话级复用）"""
    import urllib.request, json
    data = json.dumps({"username": "luxiaocang", "password": "LXC2025"}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read()).get("token")

@pytest.fixture(scope="session")
def store_ids(base_url, admin_token):
    import urllib.request, json
    req = urllib.request.Request(
        f"{base_url}/api/stores",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read()).get("stores", [])
