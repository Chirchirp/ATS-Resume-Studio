import unittest

from utils.ai_runtime import TASK_OUTPUT_LIMITS, reasoning_effort_for_task


class AiRuntimeTests(unittest.TestCase):
    def test_classification_budget_leaves_room_for_groq_final_text(self):
        self.assertGreaterEqual(TASK_OUTPUT_LIMITS["classification"], 256)

    def test_short_groq_tasks_reduce_hidden_reasoning(self):
        self.assertEqual(
            reasoning_effort_for_task(
                "classification", "groq", "openai/gpt-oss-120b", "high"
            ),
            "low",
        )
        self.assertEqual(
            reasoning_effort_for_task(
                "classification", "groq", "qwen/qwen3.6-27b", "default"
            ),
            "none",
        )

    def test_document_tasks_preserve_configured_reasoning(self):
        self.assertGreaterEqual(TASK_OUTPUT_LIMITS["resume"], 4_600)
        self.assertEqual(
            reasoning_effort_for_task(
                "resume", "groq", "openai/gpt-oss-120b", "high"
            ),
            "high",
        )


if __name__ == "__main__":
    unittest.main()
