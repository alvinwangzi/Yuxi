"""连接器 HTTP 客户端安全边界单元测试。"""

from __future__ import annotations

import ipaddress

import pytest

from yuxi.services.connectors.http_client import (
    ConnectorHTTPConfig,
    ConnectorHTTPError,
    ConnectorResponseTooLargeError,
    ConnectorTimeoutError,
    ConnectorUnsafeTargetError,
    build_full_url,
    build_security_policy,
    validate_request_origin,
)


class TestConnectorHTTPConfig:
    """HTTP 配置构造与校验。"""

    def test_valid_https_config(self):
        config = ConnectorHTTPConfig.from_dict({
            "base_url": "https://api.example.com",
            "allowed_origins": ["https://api.example.com"],
        })
        assert config.base_url == "https://api.example.com"
        assert config.allowed_origins == ("https://api.example.com",)

    def test_empty_base_url_raises(self):
        with pytest.raises(ConnectorHTTPError, match="base_url"):
            ConnectorHTTPConfig.from_dict({"base_url": ""})

    def test_invalid_scheme_raises(self):
        with pytest.raises(ConnectorHTTPError, match="http/https"):
            ConnectorHTTPConfig.from_dict({"base_url": "ftp://example.com"})

    def test_missing_hostname_raises(self):
        with pytest.raises(ConnectorHTTPError, match="主机名"):
            ConnectorHTTPConfig.from_dict({"base_url": "https://"})

    def test_http_without_origins_raises(self):
        with pytest.raises(ConnectorHTTPError, match="allowed_origins"):
            ConnectorHTTPConfig.from_dict({"base_url": "http://internal.local"})

    def test_http_with_explicit_origins_allowed(self):
        config = ConnectorHTTPConfig.from_dict({
            "base_url": "http://internal.local",
            "allowed_origins": ["http://internal.local"],
        })
        assert config.base_url == "http://internal.local"

    def test_invalid_origin_format_raises(self):
        with pytest.raises(ConnectorHTTPError, match="格式无效"):
            ConnectorHTTPConfig.from_dict({
                "base_url": "https://api.example.com",
                "allowed_origins": ["not-a-url"],
            })

    def test_invalid_cidr_raises(self):
        with pytest.raises(ConnectorHTTPError, match="CIDR"):
            ConnectorHTTPConfig.from_dict({
                "base_url": "https://api.example.com",
                "allowed_private_cidrs": ["not-a-cidr"],
            })

    def test_valid_cidr_accepted(self):
        config = ConnectorHTTPConfig.from_dict({
            "base_url": "https://api.example.com",
            "allowed_private_cidrs": ["10.0.0.0/8"],
        })
        assert len(config.allowed_private_cidrs) == 1

    def test_origins_trailing_slash_stripped(self):
        config = ConnectorHTTPConfig.from_dict({
            "base_url": "https://api.example.com",
            "allowed_origins": ["https://api.example.com/"],
        })
        assert config.allowed_origins == ("https://api.example.com",)

    def test_default_timeout_and_response_bytes(self):
        config = ConnectorHTTPConfig.from_dict({
            "base_url": "https://api.example.com",
        })
        assert config.timeout_seconds == 30
        assert config.max_response_bytes == 1 * 1024 * 1024


class TestValidateRequestOrigin:
    """请求 URL origin 校验。"""

    def test_https_without_explicit_origins_allowed(self):
        config = ConnectorHTTPConfig(base_url="https://api.example.com")
        validate_request_origin("https://api.example.com/v1/data", config)

    def test_http_without_explicit_origins_rejected(self):
        config = ConnectorHTTPConfig(base_url="https://api.example.com")
        with pytest.raises(ConnectorUnsafeTargetError, match="仅允许 HTTPS"):
            validate_request_origin("http://api.example.com/v1", config)

    def test_matching_origin_allowed(self):
        config = ConnectorHTTPConfig(
            base_url="https://api.example.com",
            allowed_origins=("https://api.example.com",),
        )
        validate_request_origin("https://api.example.com/v1/data", config)

    def test_non_matching_origin_rejected(self):
        config = ConnectorHTTPConfig(
            base_url="https://api.example.com",
            allowed_origins=("https://other.example.com",),
        )
        with pytest.raises(ConnectorUnsafeTargetError, match="不在允许"):
            validate_request_origin("https://evil.com/steal", config)

    def test_unsupported_scheme_rejected(self):
        config = ConnectorHTTPConfig(base_url="https://api.example.com")
        with pytest.raises(ConnectorUnsafeTargetError, match="scheme"):
            validate_request_origin("ftp://api.example.com/file", config)

    def test_missing_hostname_rejected(self):
        config = ConnectorHTTPConfig(base_url="https://api.example.com")
        with pytest.raises(ConnectorUnsafeTargetError, match="主机名"):
            validate_request_origin("https://", config)

    def test_same_hostname_different_path_allowed(self):
        config = ConnectorHTTPConfig(
            base_url="https://api.example.com",
            allowed_origins=("https://api.example.com",),
        )
        validate_request_origin("https://api.example.com/deep/path", config)


class TestBuildFullUrl:
    """URL 拼接与主机名校验。"""

    def test_simple_join(self):
        url = build_full_url("https://api.example.com", "/v1/users", None)
        assert url == "https://api.example.com/v1/users"

    def test_template_with_params(self):
        url = build_full_url(
            "https://api.example.com",
            "/v1/users/{{user_id}}",
            {"user_id": "42"},
        )
        assert url == "https://api.example.com/v1/users/42"

    def test_absolute_endpoint_rejected(self):
        with pytest.raises(Exception):
            build_full_url("https://api.example.com", "https://evil.com/steal", None)

    def test_template_missing_variable_rejected(self):
        with pytest.raises(Exception):
            build_full_url(
                "https://api.example.com",
                "/v1/users/{{user_id}}",
                {"other": "value"},
            )


class TestBuildSecurityPolicy:
    def test_default_policy_blocks_private(self):
        config = ConnectorHTTPConfig(base_url="https://api.example.com")
        policy = build_security_policy(config)
        assert policy.is_blocked(ipaddress.ip_address("10.0.0.1"))
        assert policy.is_blocked(ipaddress.ip_address("169.254.169.254"))

    def test_configured_cidrs_allowed(self):
        config = ConnectorHTTPConfig(
            base_url="https://api.example.com",
            allowed_private_cidrs=(ipaddress.ip_network("10.0.0.0/8"),),
        )
        policy = build_security_policy(config)
        assert not policy.is_blocked(ipaddress.ip_address("10.0.0.1"))
        assert policy.is_blocked(ipaddress.ip_address("192.168.1.1"))


class TestExceptionTypes:
    def test_http_error_carries_code(self):
        err = ConnectorHTTPError("fail", code="custom_code", status_code=500)
        assert err.code == "custom_code"
        assert err.status_code == 500

    def test_unsafe_target_code(self):
        err = ConnectorUnsafeTargetError("bad target")
        assert err.code == "unsafe_target"

    def test_response_too_large_code(self):
        err = ConnectorResponseTooLargeError(1024)
        assert err.code == "response_too_large"

    def test_timeout_code(self):
        err = ConnectorTimeoutError(30.0)
        assert err.code == "timeout"
