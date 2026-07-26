import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils.ai_client import (
    AIClientError,
    _safe_error,
    clear_response_cache,
    get_ai_response,
    get_ai_result,
    get_ai_result_with_fallback,
)
from config.settings import PROVIDERS, get_reasoning_options


class AiClientTests(unittest.TestCase):
    def setUp(self):
        clear_response_cache()

    @patch("utils.ai_client.Groq")
    def test_sends_separate_system_and_user_messages(self, groq_class):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="grounded output"))]
        )
        groq_class.return_value.chat.completions.create.return_value = completion

        result = get_ai_response(
            "gsk_test_key_long_enough",
            "test-model",
            "<candidate_resume>source data</candidate_resume>",
            system_prompt="System rules",
            temperature=0.0,
        )

        self.assertEqual(result, "grounded output")
        call = groq_class.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(call["messages"][0], {"role": "system", "content": "System rules"})
        self.assertEqual(call["messages"][1]["role"], "user")
        self.assertEqual(call["temperature"], 0.0)
        self.assertIn("max_completion_tokens", call)
        self.assertNotIn("max_tokens", call)

    @patch("utils.ai_client.Groq")
    def test_sends_supported_reasoning_parameters_to_groq(self, groq_class):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="final answer"))]
        )
        groq_class.return_value.chat.completions.create.return_value = completion

        get_ai_result(
            "gsk_test_key_long_enough",
            "openai/gpt-oss-120b",
            "review this resume",
            reasoning_effort="high",
            use_cache=False,
        )

        call = groq_class.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(call["reasoning_effort"], "high")
        self.assertEqual(call["reasoning_format"], "hidden")

    @patch("utils.ai_client.Groq")
    def test_provider_failures_raise_typed_safe_error(self, groq_class):
        groq_class.return_value.chat.completions.create.side_effect = RuntimeError(
            "401 invalid_api_key secret-provider-detail"
        )
        with self.assertRaisesRegex(AIClientError, "Invalid API key"):
            get_ai_response(
                "gsk_test_key_long_enough",
                "test-model",
                "prompt",
            )

    @patch("utils.ai_client.Groq")
    def test_empty_reasoning_completion_is_rejected(self, groq_class):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=""))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=96),
        )
        groq_class.return_value.chat.completions.create.return_value = completion
        with self.assertRaisesRegex(AIClientError, "without returning final text"):
            get_ai_result(
                "gsk_test_key_long_enough",
                "reasoning-model",
                "short classification",
                max_tokens=96,
                use_cache=False,
            )

    @patch("utils.ai_client.Groq")
    def test_identical_requests_use_bounded_memory_cache(self, groq_class):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="cached output"))],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5),
        )
        groq_class.return_value.chat.completions.create.return_value = completion
        first = get_ai_result("gsk_test_key_long_enough", "model", "same prompt")
        second = get_ai_result("gsk_test_key_long_enough", "model", "same prompt")
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.usage.cached_tokens, 25)
        self.assertEqual(
            groq_class.return_value.chat.completions.create.call_count,
            1,
        )

    @patch("utils.ai_client.get_ai_result")
    def test_fallback_runs_only_for_retryable_failures(self, get_result):
        get_result.side_effect = [
            AIClientError("rate limited", retryable=True, provider="groq"),
            SimpleNamespace(
                text="fallback",
                provider="gemini",
                model="flash",
                usage=SimpleNamespace(
                    input_tokens=3,
                    output_tokens=2,
                    cached_tokens=0,
                ),
                cache_hit=False,
                fallback_used=False,
            ),
        ]
        result = get_ai_result_with_fallback(
            api_key="primary-key-long",
            provider="groq",
            model="llama",
            prompt="prompt",
            fallback_api_key="fallback-key-long",
            fallback_provider="gemini",
            fallback_model="flash",
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.provider, "gemini")

    @patch("utils.ai_client.get_ai_result")
    def test_same_provider_model_fallback_is_supported(self, get_result):
        get_result.side_effect = [
            AIClientError(
                "Groq rate limit reached",
                retryable=True,
                provider="groq",
                model="openai/gpt-oss-120b",
                category="rate_limit",
                status_code=429,
            ),
            SimpleNamespace(
                text="fallback model output",
                provider="groq",
                model="openai/gpt-oss-20b",
                usage=SimpleNamespace(
                    input_tokens=3,
                    output_tokens=2,
                    cached_tokens=0,
                ),
                cache_hit=False,
                fallback_used=False,
            ),
        ]
        result = get_ai_result_with_fallback(
            api_key="primary-key-long",
            provider="groq",
            model="openai/gpt-oss-120b",
            prompt="prompt",
            fallback_api_key="primary-key-long",
            fallback_provider="groq",
            fallback_model="openai/gpt-oss-20b",
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.model, "openai/gpt-oss-20b")

    def test_structured_groq_rate_limit_error_is_actionable(self):
        exc = RuntimeError("provider request failed")
        exc.status_code = 429
        exc.body = {
            "error": {
                "type": "rate_limit_error",
                "message": "tokens per minute reached",
            }
        }
        exc.response = SimpleNamespace(
            headers={"retry-after": "12", "x-request-id": "req_safe_123"}
        )
        error = _safe_error(exc, "groq", "openai/gpt-oss-120b")
        self.assertEqual(error.category, "rate_limit")
        self.assertTrue(error.retryable)
        self.assertEqual(error.status_code, 429)
        self.assertEqual(error.retry_after, "12")
        self.assertEqual(error.request_id, "req_safe_123")
        self.assertIn("Retry shortly", str(error))
        self.assertNotIn("tokens per minute reached", str(error))

    def test_request_size_and_parameter_errors_are_not_hidden(self):
        too_large = RuntimeError("request failed")
        too_large.status_code = 413
        too_large.body = {"error": {"type": "request_too_large"}}
        too_large.response = SimpleNamespace(headers={})
        size_error = _safe_error(too_large, "groq", "model")
        self.assertEqual(size_error.category, "request_too_large")
        self.assertFalse(size_error.retryable)
        self.assertIn("too large", str(size_error))

        bad_parameter = RuntimeError("request failed")
        bad_parameter.status_code = 400
        bad_parameter.body = {
            "error": {
                "type": "invalid_request_error",
                "message": "reasoning_effort is not supported",
            }
        }
        bad_parameter.response = SimpleNamespace(headers={})
        parameter_error = _safe_error(bad_parameter, "groq", "model")
        self.assertEqual(parameter_error.category, "model_parameters")
        self.assertTrue(parameter_error.retryable)
        self.assertIn("reasoning", str(parameter_error))

    @patch("utils.ai_client.requests.post")
    def test_openrouter_adapter_parses_usage(self, post):
        response = post.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "model": "chosen-free-model",
            "choices": [{"message": {"content": "router output"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }
        result = get_ai_result(
            "sk-or-v1-test-key",
            "openrouter/free",
            "prompt",
            provider="openrouter",
            use_cache=False,
        )
        self.assertEqual(result.text, "router output")
        self.assertEqual(result.model, "chosen-free-model")
        self.assertEqual(result.usage.total_tokens, 18)

    @patch("utils.ai_client.requests.post")
    def test_gemini_adapter_parses_usage(self, post):
        response = post.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "gemini output"}]}}
            ],
            "usageMetadata": {
                "promptTokenCount": 13,
                "candidatesTokenCount": 6,
            },
        }
        result = get_ai_result(
            "AIza-test-key-long",
            "gemini-2.5-flash",
            "prompt",
            provider="gemini",
            use_cache=False,
        )
        self.assertEqual(result.text, "gemini output")
        self.assertEqual(result.usage.total_tokens, 19)

    def test_current_groq_catalogue_and_reasoning_options(self):
        self.assertEqual(
            PROVIDERS["groq"]["default_model"],
            "openai/gpt-oss-120b",
        )
        self.assertIn("qwen/qwen3.6-27b", PROVIDERS["groq"]["models"])
        self.assertNotIn("llama-3.3-70b-versatile", PROVIDERS["groq"]["models"])
        self.assertEqual(
            get_reasoning_options("openai/gpt-oss-120b", "groq"),
            (["low", "medium", "high"], "medium"),
        )
        self.assertEqual(
            get_reasoning_options("qwen/qwen3.6-27b", "groq"),
            (["none", "default"], "none"),
        )


if __name__ == "__main__":
    unittest.main()
