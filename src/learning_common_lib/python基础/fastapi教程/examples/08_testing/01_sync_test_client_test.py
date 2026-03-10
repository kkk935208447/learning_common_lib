"""
测试: 01_sync_test_client——演示 TestClient 同步测试 + dependency_overrides
运行命令: uv run python examples/08_testing/01_sync_test_client_test.py  (从 fastapi教程/ 目录)

本文件本身就是教学内容：展示如何用 TestClient 写同步测试。
"""

import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_spec = importlib.util.spec_from_file_location(
    "_svc", Path(__file__).with_name("01_sync_test_client.py")
)
_svc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_svc)
router = _svc.router
get_settings = _svc.get_settings


def test_read_settings():
    """测试正常端点。"""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.get("/settings")
    assert r.status_code == 200
    assert r.json()["env"] == "production"
    print("  ✓ test_read_settings")


def test_dependency_override():
    """测试依赖覆盖——将 production 替换为 test。"""
    app = FastAPI()
    app.include_router(router)

    def override_settings() -> dict:
        return {"env": "test", "debug": True}

    app.dependency_overrides[get_settings] = override_settings
    client = TestClient(app)
    r = client.get("/settings")
    assert r.status_code == 200
    assert r.json()["env"] == "test"
    print("  ✓ test_dependency_override")


def test_create_item():
    """测试创建资源。"""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/items", json={"name": "Gadget", "price": 19.99})
    assert r.status_code == 201
    assert r.json()["name"] == "Gadget"
    print("  ✓ test_create_item")


def test_validation_error():
    """测试校验错误返回 422。"""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post("/items", json={"name": "", "price": -1})
    assert r.status_code == 422
    print("  ✓ test_validation_error")


def test_not_found():
    """测试 404。"""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.get("/items/999")
    assert r.status_code == 404
    print("  ✓ test_not_found")


if __name__ == "__main__":
    print("--- 同步 TestClient 测试 ---")
    test_read_settings()
    test_dependency_override()
    test_create_item()
    test_validation_error()
    test_not_found()
    print("\n所有测试通过！")
