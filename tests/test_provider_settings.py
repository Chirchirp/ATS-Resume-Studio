import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from config import settings


class ProviderSettingsTests(unittest.TestCase):
    def setUp(self):
        self.fake_streamlit = SimpleNamespace(session_state={}, secrets={})
        self.streamlit_patch = patch.object(settings, "st", self.fake_streamlit)
        self.streamlit_patch.start()
        self.environment_patch = patch.dict(os.environ, {}, clear=False)
        self.environment_patch.start()
        os.environ.pop("GROQ_API_KEY", None)

    def tearDown(self):
        self.environment_patch.stop()
        self.streamlit_patch.stop()

    def test_normalizes_pasted_key_artifacts(self):
        self.assertEqual(
            settings.normalize_api_key('  "Bearer gsk_test\u200b_key\n"  '),
            "gsk_test_key",
        )

    def test_session_override_has_priority_and_can_be_cleared(self):
        self.fake_streamlit.secrets["GROQ_API_KEY"] = "gsk_deployed_secret_long"
        settings.set_api_key("gsk_session_override_long", "groq")

        self.assertEqual(settings.get_api_key_source("groq"), "session override")
        self.assertEqual(settings.get_api_key("groq"), "gsk_session_override_long")

        settings.clear_session_api_key("groq", "api_key_input_groq")

        self.assertEqual(settings.get_api_key_source("groq"), "Streamlit secret")
        self.assertEqual(settings.get_api_key("groq"), "gsk_deployed_secret_long")
        self.assertEqual(
            self.fake_streamlit.session_state["api_key_input_groq"], ""
        )

    def test_validation_is_bound_to_exact_credential(self):
        settings.set_api_key("gsk_first_key_long_enough", "groq")
        settings.set_api_key_validation("groq", "verified")
        self.assertEqual(settings.get_api_key_validation("groq"), "verified")

        settings.set_api_key("gsk_second_key_long_enough", "groq")
        self.assertEqual(settings.get_api_key_validation("groq"), "unverified")

        settings.set_api_key_validation("groq", "rejected")
        self.assertEqual(settings.get_api_key_validation("groq"), "rejected")


if __name__ == "__main__":
    unittest.main()
