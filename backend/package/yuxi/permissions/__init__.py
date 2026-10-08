"""跨资源权限能力。"""

from yuxi.permissions.connector_permission import connector_scope_matches

from yuxi.permissions.resource_permission import (
    AGENT_PERMISSION_POLICY,
    KNOWLEDGE_BASE_PERMISSION_POLICY,
    SKILL_PERMISSION_POLICY,
    ResourcePermission,
    ResourcePermissionDenied,
    normalize_permission_config,
    require_knowledge_base_permission,
    require_resource_permission,
    resolve_agent_permission,
    resolve_knowledge_base_permission,
    resolve_resource_permission,
    resolve_skill_permission,
    scope_matches,
)

__all__ = [
    "connector_scope_matches",
    "AGENT_PERMISSION_POLICY",
    "KNOWLEDGE_BASE_PERMISSION_POLICY",
    "SKILL_PERMISSION_POLICY",
    "ResourcePermission",
    "ResourcePermissionDenied",
    "normalize_permission_config",
    "require_knowledge_base_permission",
    "require_resource_permission",
    "resolve_agent_permission",
    "resolve_knowledge_base_permission",
    "resolve_resource_permission",
    "resolve_skill_permission",
    "scope_matches",
]
