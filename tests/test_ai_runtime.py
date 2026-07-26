import unittest

from utils.ai_runtime import (
    TASK_OUTPUT_LIMITS,
    reasoning_effort_for_task,
    resume_output_limit,
)


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

    def test_resume_generation_uses_page_aware_output_and_efficient_reasoning(self):
        self.assertGreaterEqual(TASK_OUTPUT_LIMITS["resume"], 4_600)
        self.assertEqual(
            [resume_output_limit(page) for page in range(1, 5)],
            [1_400, 2_400, 3_400, 4_300],
        )
        self.assertEqual(
            reasoning_effort_for_task(
                "resume", "groq", "openai/gpt-oss-120b", "high"
            ),
            "low",
        )


if __name__ == "__main__":
    unittest.main()
