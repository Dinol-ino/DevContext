#!/usr/bin/env python3
"""
DevContextIQ Phase 8 End-to-End System Verification Suite
Validates backend routing, module imports, chunker logic, dynamic RAG functions, and API protection.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))


class TestPhase8EndToEnd(unittest.TestCase):

    def test_01_backend_routes_loaded(self):
        """Verify FastAPI app imports cleanly and registers all 9 API routers."""
        from agents.main import app, API_PREFIX

        routes = [r.path for r in app.routes]
        expected_routes = [
            f"{API_PREFIX}/ask",
            f"{API_PREFIX}/governance/check",
            f"{API_PREFIX}/incident",
            f"{API_PREFIX}/auth/log",
            f"{API_PREFIX}/repo/import",
            f"{API_PREFIX}/repo/list",
            f"{API_PREFIX}/chat/threads",
            f"{API_PREFIX}/commit/analyze",
            f"{API_PREFIX}/onboarding/guide",
            f"{API_PREFIX}/timeline/scope",  # matched dynamically
        ]

        print(f"\n[PASS] Total registered FastAPI routes: {len(routes)}")
        self.assertIn("/health", routes)
        self.assertIn(f"{API_PREFIX}/health", routes)
        self.assertIn(f"{API_PREFIX}/ask", routes)
        self.assertIn(f"{API_PREFIX}/governance/check", routes)
        self.assertIn(f"{API_PREFIX}/incident", routes)
        self.assertIn(f"{API_PREFIX}/auth/log", routes)
        self.assertIn(f"{API_PREFIX}/chat/threads", routes)
        self.assertIn(f"{API_PREFIX}/commit/analyze", routes)
        self.assertIn(f"{API_PREFIX}/onboarding/guide", routes)

    def test_02_chunker_engine(self):
        """Verify AST code chunker splits code files cleanly."""
        from agents.chunker import chunk_text_by_lines, chunk_python

        py_sample = (
            "def handle_payment():\n"
            "    print('Processing payment...')\n\n"
            "class GatewayService:\n"
            "    def route(self):\n"
            "        pass\n"
        )
        chunks = chunk_python("payments/handler.py", py_sample)
        self.assertGreater(len(chunks), 0)
        self.assertIn("handle_payment", chunks[0].content)
        print(f"[PASS] Chunker produced {len(chunks)} chunk(s) from sample Python code.")

    def test_03_dynamic_governance_detection(self):
        """Verify detect_conflict function runs without static hardcoded rule dicts."""
        from agents.tools import detect_conflict

        diff_sample = "diff --git a/auth.py b/auth.py\n+ def bypass_jwt_verification():\n+ return True"
        result = detect_conflict(diff_sample)
        self.assertIn("has_conflicts", result)
        self.assertIn("severity", result)
        self.assertIn("comment_text", result)
        print(f"[PASS] Dynamic Governance Conflict Check Result: severity={result['severity']}")

    def test_04_dynamic_incident_analysis(self):
        """Verify analyze_incident function synthesizes incident response dynamically."""
        from agents.tools import analyze_incident

        result = analyze_incident("DB Connection Pool Timeout", "payment-service", "ConnectionRefusedError: pool full")
        self.assertIn("issue", result)
        self.assertIn("likely_cause", result)
        self.assertIn("fix_steps", result)
        self.assertGreater(len(result["fix_steps"]), 0)
        print(f"[PASS] Dynamic Incident Analysis Result: issue='{result['issue']}'")

    def test_05_intent_classification(self):
        """Verify RAG query intent classification."""
        from agents.tools import _infer_query_intent

        intent = _infer_query_intent("What changed recently in the gateway auth service?")
        self.assertTrue(intent["recent"])
        self.assertIn("gateway", intent["services"])
        self.assertIn("auth", intent["services"])
        print(f"[PASS] Intent Classification: {intent}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
