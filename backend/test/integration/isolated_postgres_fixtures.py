"""隔离 Schema 测试显式选择的资源边界，不装配共享 HTTP 清理。"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """导入模块自行创建 Schema，不校验共享 API 数据库。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """隔离 Schema 模块不创建共享知识库资源。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """隔离 Schema 模块不创建或清理共享沙盒。"""
    yield
