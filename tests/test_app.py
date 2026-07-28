import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app import load_test_cases, run_baseline_chatbot, run_baseline_suite


class SpyProvider:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, system_prompt=""):
        self.calls.append((prompt, system_prompt))
        return "Câu trả lời baseline"


import unittest


class BaselineTests(unittest.TestCase):
    def test_calls_provider_once_and_returns_response(self):
        provider = SpyProvider()

        response = run_baseline_chatbot("Tôi cần tìm nhà trọ.", provider, emit=False)

        self.assertEqual(response, "Câu trả lời baseline")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][0], "Tôi cần tìm nhà trọ.")
        self.assertTrue(provider.calls[0][1])

    def test_baseline_suite_runs_all_loaded_cases(self):
        provider = SpyProvider()

        results = run_baseline_suite(provider, emit=False)

        self.assertEqual(len(results), len(load_test_cases()))
        self.assertEqual(len(results), 5)
        self.assertEqual(len(provider.calls), 5)
        self.assertEqual([result["id"] for result in results], [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
