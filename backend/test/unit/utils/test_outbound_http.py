"""共享出站 HTTP 安全原语单元测试。"""

from __future__ import annotations

import ipaddress

import pytest

from yuxi.utils.outbound_http import (
    CLOUD_METADATA_ADDRESSES,
    OutboundSecurityPolicy,
    PUBLIC_ONLY_POLICY,
    assert_no_blocked_address,
    resolve_hostname_addresses,
    validate_endpoint_template,
)


class TestOutboundSecurityPolicy:
    """安全策略 IP 分类。"""

    def test_public_address_not_blocked(self):
        policy = PUBLIC_ONLY_POLICY
        assert not policy.is_blocked(ipaddress.ip_address("8.8.8.8"))

    def test_cloud_metadata_blocked(self):
        policy = PUBLIC_ONLY_POLICY
        assert policy.is_blocked(ipaddress.ip_address("169.254.169.254"))

    def test_aliyun_metadata_blocked(self):
        policy = PUBLIC_ONLY_POLICY
        assert policy.is_blocked(ipaddress.ip_address("100.100.200.200"))

    def test_private_address_blocked_by_default(self):
        policy = PUBLIC_ONLY_POLICY
        assert policy.is_blocked(ipaddress.ip_address("10.0.0.1"))
        assert policy.is_blocked(ipaddress.ip_address("192.168.1.1"))
        assert policy.is_blocked(ipaddress.ip_address("172.16.0.1"))

    def test_private_address_allowed_with_cidr(self):
        policy = OutboundSecurityPolicy(
            allow_private_cidrs=(ipaddress.ip_network("10.0.0.0/8"),),
        )
        assert not policy.is_blocked(ipaddress.ip_address("10.0.0.1"))
        assert policy.is_blocked(ipaddress.ip_address("192.168.1.1"))

    def test_loopback_blocked_by_default(self):
        policy = PUBLIC_ONLY_POLICY
        assert policy.is_blocked(ipaddress.ip_address("127.0.0.1"))

    @pytest.mark.parametrize(
        "target",
        ["127.0.0.1", "::1", "169.254.1.1", "fe80::1", "224.0.0.1", "ff02::1", "0.0.0.0", "::", "::ffff:127.0.0.1"],
    )
    def test_explicit_cidr_cannot_allow_special_addresses(self, target):
        """显式内网允许范围不能授权回环、链路、组播或未指定地址。"""
        policy = OutboundSecurityPolicy(
            allow_private_cidrs=(
                ipaddress.ip_network("0.0.0.0/0"),
                ipaddress.ip_network("::/0"),
            )
        )
        assert policy.is_blocked(ipaddress.ip_address(target))

    def test_ipv6_metadata_blocked(self):
        policy = PUBLIC_ONLY_POLICY
        assert policy.is_blocked(ipaddress.ip_address("fd00:ec2::254"))

    def test_custom_blocked_addresses(self):
        policy = OutboundSecurityPolicy(
            extra_blocked_addresses=frozenset({ipaddress.ip_address("1.2.3.4")}),
        )
        assert policy.is_blocked(ipaddress.ip_address("1.2.3.4"))
        assert not policy.is_blocked(ipaddress.ip_address("8.8.8.8"))


class TestAssertNoBlockedAddress:
    """地址列表校验。"""

    def test_all_public_passes(self):
        addresses = [ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("1.1.1.1")]
        assert_no_blocked_address(addresses)

    def test_blocked_address_raises(self):
        addresses = [
            ipaddress.ip_address("8.8.8.8"),
            ipaddress.ip_address("169.254.169.254"),
        ]
        with pytest.raises(ValueError, match="disallow"):
            assert_no_blocked_address(addresses)

    def test_empty_list_passes(self):
        assert_no_blocked_address([])

    def test_custom_policy(self):
        policy = OutboundSecurityPolicy(
            allow_private_cidrs=(ipaddress.ip_network("10.0.0.0/8"),),
        )
        addresses = [ipaddress.ip_address("10.0.0.1")]
        assert_no_blocked_address(addresses, policy)


class TestValidateEndpointTemplate:
    """endpoint_template 安全校验。"""

    def test_valid_relative_path(self):
        assert validate_endpoint_template("/v1/users") == "/v1/users"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            validate_endpoint_template("")

    def test_backslash_rejected(self):
        with pytest.raises(ValueError, match="反斜杠"):
            validate_endpoint_template("/v1\\users")

    def test_path_traversal_dotdot_rejected(self):
        with pytest.raises(ValueError, match="路径穿越"):
            validate_endpoint_template("/v1/../secret")

    def test_absolute_url_rejected(self):
        with pytest.raises(ValueError, match="路径穿越|scheme"):
            validate_endpoint_template("https://evil.com/steal")

    def test_userinfo_rejected(self):
        with pytest.raises(ValueError, match="userinfo"):
            validate_endpoint_template("/v1/@user/data")

    def test_fragment_rejected(self):
        with pytest.raises(ValueError, match="scheme"):
            validate_endpoint_template("/v1/data#fragment")

    def test_leading_slash_stripped_for_check(self):
        result = validate_endpoint_template("/api/v1/list")
        assert result == "/api/v1/list"

    def test_hidden_dot_prefix_rejected(self):
        with pytest.raises(ValueError, match="路径穿越"):
            validate_endpoint_template("/v1/.hidden")


class TestCloudMetadataAddresses:
    def test_known_metadata_ips_present(self):
        assert ipaddress.ip_address("169.254.169.254") in CLOUD_METADATA_ADDRESSES
        assert ipaddress.ip_address("100.100.200.200") in CLOUD_METADATA_ADDRESSES
        assert ipaddress.ip_address("fd00:ec2::254") in CLOUD_METADATA_ADDRESSES
