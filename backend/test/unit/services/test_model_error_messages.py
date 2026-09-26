"""friendly_model_error：把模型服务原始异常翻译为用户可见中文文案。"""

from yuxi.services.model_error_messages import friendly_model_error

CONTEXT_OVERFLOW_400 = (
    "Error code: 400 - {'error': {'code': 400, 'message': 'request (16453 tokens) "
    "exceeds the available context size (16384 tokens), try increasing it', "
    "'type': 'exceed_context_size_error', 'n_prompt_tokens': 16453, 'n_ctx': 16384}}"
)


class TestContextOverflow:
    def test_screenshot_error_maps_to_context_overflow_with_numbers(self):
        message, detail = friendly_model_error(RuntimeError(CONTEXT_OVERFLOW_400))

        assert "上下文" in message
        assert "16453" in message
        assert "16384" in message
        assert "exceed_context_size_error" not in message
        assert CONTEXT_OVERFLOW_400 in detail

    def test_openai_max_context_length_phrasing(self):
        raw = (
            "Error code: 400 - {'error': {'message': \"This model's maximum context "
            "length is 16385 tokens. However, you requested 16400 tokens\", "
            "'type': 'invalid_request_error', 'code': 'context_length_exceeded'}}"
        )
        message, _ = friendly_model_error(RuntimeError(raw))

        assert "上下文" in message
        assert "16385" in message
        assert "16400" in message

    def test_overflow_without_parseable_numbers_stays_generic(self):
        raw = "Error code: 400 - {'error': {'message': 'context length exceeded', 'code': 'context_length_exceeded'}}"
        message, _ = friendly_model_error(RuntimeError(raw))

        assert "上下文" in message
        assert "tokens" not in message


class TestCommonStatusErrors:
    def test_401_maps_to_auth_failure(self):
        raw = (
            "Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-abc', "
            "'type': 'invalid_request_error', 'code': 'invalid_api_key'}}"
        )
        message, _ = friendly_model_error(RuntimeError(raw))

        assert "认证" in message
        assert "API Key" in message
        assert "sk-abc" not in message

    def test_model_not_found_maps_to_model_missing(self):
        raw = (
            "Error code: 404 - {'error': {'message': 'The model `gpt-foo` does not exist', "
            "'type': 'invalid_request_error', 'code': 'model_not_found'}}"
        )
        message, _ = friendly_model_error(RuntimeError(raw))

        assert "模型" in message
        assert "gpt-foo" not in message

    def test_429_maps_to_rate_limit(self):
        raw = "Error code: 429 - {'error': {'message': 'Rate limit reached for requests', 'code': 'rate_limit_exceeded'}}"
        message, _ = friendly_model_error(RuntimeError(raw))

        assert "频繁" in message or "配额" in message

    def test_5xx_maps_to_service_unavailable(self):
        raw = "Error code: 503 - {'error': {'message': 'Internal Server Error'}}"
        message, _ = friendly_model_error(RuntimeError(raw))

        assert "暂时不可用" in message

    def test_timeout_maps_to_connection_failure(self):
        message, _ = friendly_model_error(TimeoutError("Request timed out."))

        assert "连接" in message or "超时" in message

    def test_connection_error_maps_to_connection_failure(self):
        message, _ = friendly_model_error(ConnectionError("Connection error."))

        assert "连接" in message or "超时" in message


class TestFallback:
    def test_unknown_error_never_leaks_raw_text(self):
        raw = "Some weird english failure with secret endpoint http://internal:9999/v1"
        message, detail = friendly_model_error(RuntimeError(raw))

        assert "weird english failure" not in message
        assert "请稍后重试" in message
        assert "模型服务" not in message
        assert raw in detail

    def test_detail_preserves_original_and_is_truncated(self):
        raw = "x" * 5000
        _, detail = friendly_model_error(RuntimeError(raw))

        assert len(detail) <= 2000

    def test_error_without_status_has_no_http_prefix(self):
        message, _ = friendly_model_error(RuntimeError("something broke"))

        assert "HTTP" not in message
