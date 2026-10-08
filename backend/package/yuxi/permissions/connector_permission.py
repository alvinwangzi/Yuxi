"""连接器执行范围不继承管理员的管理权。"""

from yuxi.permissions.resource_permission import scope_matches
from yuxi.storage.postgres.models_business import User


def connector_scope_matches(user: User | None, scope: dict | None) -> bool:
    """只允许有效用户命中显式配置的执行范围。"""
    return bool(user and user.uid and not user.is_deleted and scope_matches(user, scope))


def normalize_connector_scope(scope: dict | None) -> dict:
    """管理写入拒绝未知格式，执行权只由明确范围授予。"""
    if scope is None:
        return {"access_level": "deny"}
    if not isinstance(scope, dict) or set(scope) - {"access_level", "department_ids", "user_uids"}:
        raise ValueError("connector_scope_invalid")
    level = scope.get("access_level")
    if level not in ("deny", "global", "department", "user"):
        raise ValueError("connector_scope_invalid")
    departments = scope.get("department_ids", [])
    users = scope.get("user_uids", [])
    if not isinstance(departments, list) or any(type(value) is not int or value <= 0 for value in departments):
        raise ValueError("connector_department_scope_invalid")
    if not isinstance(users, list) or any(not isinstance(value, str) or not value.strip() for value in users):
        raise ValueError("connector_user_scope_invalid")
    if level == "department" and not departments or level == "user" and not users:
        raise ValueError("connector_scope_members_required")
    return {
        "access_level": level,
        "department_ids": sorted(set(departments)) if level == "department" else [],
        "user_uids": sorted(set(users)) if level == "user" else [],
    }
