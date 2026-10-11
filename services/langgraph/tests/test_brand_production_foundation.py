"""Side-effect-free ACE brand-production foundation regression tests."""
import unittest

from services.langgraph.agency.creative.brand_production import (
    BrandProfile, Project, StyleGuide, compile_page_prompt, route, weighted_coverage,
)


class BrandProductionTests(unittest.TestCase):
    def setUp(self):
        self.guide = StyleGuide("brand-a", "v1", "APPROVED", {"tone": "precise"})
        self.project = Project("project-a", "brand-a", "v1", "website", ("web", "image"))

    def test_optional_routes_and_provider_gap(self):
        plan = route(self.project, self.guide)
        self.assertEqual([n["capability"] for n in plan["nodes"]], ["brand_guide", "web", "image"])
        self.assertEqual(plan["nodes"][-1]["status"], "BLOCKED")
        self.assertEqual(plan["nodes"][-1]["reason"], "provider_gap")
        self.assertIn("merchandise", plan["skipped"])
        self.assertEqual(plan["provider_execution"], "DISABLED")

    def test_project_boundary(self):
        other = Project("project-b", "brand-b", "v1", "website", ("web",))
        with self.assertRaises(ValueError):
            route(other, self.guide)

    def test_page_prompts_distinct_and_compiler_only(self):
        home = compile_page_prompt(self.project, self.guide, "home", "Introduce product")
        price = compile_page_prompt(self.project, self.guide, "pricing", "Compare plans")
        self.assertNotEqual(home["prompt_hash"], price["prompt_hash"])
        self.assertFalse(home["generation_executed"])
        self.assertEqual(home["state"], "PROMPT_PACKAGE_READY")

    def test_critical_gate(self):
        result = weighted_coverage([{"weight": 9, "status": "VERIFIED"},
                                    {"weight": 1, "status": "VOID", "critical": True}])
        self.assertEqual(result["score"], 0.9)
        self.assertEqual(result["status"], "HUMAN_APPROVAL_REQUIRED")

    def test_provenance_validation(self):
        with self.assertRaises(ValueError):
            BrandProfile("brand-a", "Example", provenance={"tone": "CONFIRMED"})

    def test_deterministic_plan(self):
        self.assertEqual(route(self.project, self.guide), route(self.project, self.guide))


if __name__ == "__main__":
    unittest.main()
