"""A2UI emitter + approval-gate tests (a2ui-project/a2ui rebuild).

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
Synthetic data only (adapters.a2ui_emitter.synthetic_*): no
renderer, no host app, no a2ui package, no network.
Never claim a test passed unless it ran here.
"""

import json
import os
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import a2ui_emitter as ae  # noqa: E402


def _pass_unapproved():
    plan = ae.synthetic_verified_plan()
    plan["human_approved"] = False
    return plan


def _fail_plan():
    plan = ae.synthetic_verified_plan()
    plan["verification_status"] = "FAIL"
    plan["human_approved"] = True
    return plan


class TestEmitVerifiedApproved(unittest.TestCase):
    def test_verified_approved_plan_emits_create_surface(self):
        surface = ae.emit_surface(ae.synthetic_verified_plan())
        self.assertEqual(surface["message"], "createSurface")
        self.assertEqual(surface["protocol"], "a2ui")
        self.assertEqual(surface["version"], "1.0")
        self.assertEqual(surface["surface_id"],
                         "surface-synthetic-food-plan-001")
        self.assertEqual(surface["plan_id"], "synthetic-food-plan-001")
        json.dumps(surface, sort_keys=True)

    def test_verification_status_stamped_on_surface(self):
        surface = ae.emit_surface(ae.synthetic_verified_plan())
        self.assertEqual(surface["verification"]["status"], "PASS")
        self.assertIs(surface["verification"]["human_approved"], True)
        self.assertIs(surface["verification"]["needs_human_decision"], True)
        # Stamped in the data model too.
        self.assertEqual(
            surface["dataModel"]["verification"]["status"], "PASS")
        self.assertIs(
            surface["dataModel"]["verification"]["human_approved"], True)

    def test_surface_carries_plan_content_as_data_only(self):
        surface = ae.emit_surface(ae.synthetic_verified_plan())
        self.assertEqual(surface["components"][0]["type"], "Card")
        self.assertEqual(surface["components"][0]["title"],
                         "Synthetic food plan")
        texts = [c["text"] for c in surface["components"][0]["children"]]
        self.assertIn("delivered_t: 600", texts)
        self.assertIn("shortage_t: 50", texts)
        self.assertIn("land_ha: 70", texts)
        # Data only: no callables anywhere in the surface.
        self.assertNotIn("callable", json.dumps(surface))

    def test_surface_has_no_consumer(self):
        surface = ae.emit_surface(ae.synthetic_verified_plan())
        self.assertEqual(surface["consumer"], "none")
        self.assertEqual(ae.consumer_status(),
                         {"renderer": None, "host_app": None,
                          "status": "no consumer — emitter only"})

    def test_emission_is_deterministic(self):
        plan = ae.synthetic_verified_plan()
        self.assertEqual(ae.emit_surface(plan), ae.emit_surface(plan))

    def test_update_and_delete_allowed_for_verified_approved(self):
        plan = ae.synthetic_verified_plan()
        surface = ae.emit_surface(plan)
        update = ae.update_data_model(
            surface, {"shortage_t": 50}, plan)
        self.assertEqual(update["message"], "updateDataModel")
        self.assertEqual(update["surface_id"], surface["surface_id"])
        self.assertEqual(update["dataModel"], {"shortage_t": 50})
        self.assertEqual(update["verification"]["status"], "PASS")
        deleted = ae.delete_surface(surface, plan)
        self.assertEqual(deleted["message"], "deleteSurface")
        self.assertEqual(deleted["surface_id"], surface["surface_id"])


class TestEmitRefusals(unittest.TestCase):
    def test_unverified_plan_refused(self):
        with self.assertRaises(ae.EmissionRefused):
            ae.emit_surface(ae.synthetic_unverified_plan())

    def test_pass_but_unapproved_plan_refused(self):
        with self.assertRaises(ae.EmissionRefused):
            ae.emit_surface(_pass_unapproved())

    def test_fail_plan_refused_even_when_approved(self):
        with self.assertRaises(ae.EmissionRefused):
            ae.emit_surface(_fail_plan())

    def test_update_refused_for_unverified_plan(self):
        plan = ae.synthetic_verified_plan()
        surface = ae.emit_surface(plan)
        with self.assertRaises(ae.EmissionRefused):
            ae.update_data_model(surface, {"x": 1},
                                 ae.synthetic_unverified_plan())

    def test_delete_refused_for_pass_but_unapproved_plan(self):
        plan = ae.synthetic_verified_plan()
        surface = ae.emit_surface(plan)
        with self.assertRaises(ae.EmissionRefused):
            ae.delete_surface(surface, _pass_unapproved())

    def test_update_refused_for_wrong_surface(self):
        plan = ae.synthetic_verified_plan()
        surface = ae.emit_surface(plan)
        other = dict(surface)
        other["surface_id"] = "surface-someone-else"
        with self.assertRaises(ae.EmissionRefused):
            ae.update_data_model(other, {"x": 1}, plan)

    def test_bad_plan_shapes_refused(self):
        with self.assertRaises(ae.EmissionRefused):
            ae.emit_surface("not a plan")
        bad = ae.synthetic_verified_plan()
        del bad["plan_id"]
        with self.assertRaises(ae.EmissionRefused):
            ae.emit_surface(bad)
        bad = ae.synthetic_verified_plan()
        bad["verification_status"] = "pass"  # lowercase is not PASS
        with self.assertRaises(ae.EmissionRefused):
            ae.emit_surface(bad)
        bad = ae.synthetic_verified_plan()
        bad["human_approved"] = "yes"  # truthy string is not True
        with self.assertRaises(ae.EmissionRefused):
            ae.emit_surface(bad)


class TestApprovalGate(unittest.TestCase):
    def test_consequential_without_approval_refused(self):
        call = {"function_name": "apply_plan", "boundary": "agentOnly",
                "consequential": True, "args": {"plan_id": "x"}}
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call(call)

    def test_consequential_with_approval_allowed_and_recorded(self):
        call = {"function_name": "apply_plan", "boundary": "agentOnly",
                "consequential": True, "args": {"plan_id": "x"}}
        result = ae.gate_function_call(call, ae.synthetic_approval())
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["function_name"], "apply_plan")
        self.assertEqual(result["approval"]["approved_by"],
                         "human-reviewer")
        self.assertEqual(result["approval"]["approval_id"],
                         "approval-001")
        self.assertEqual(result["approval"]["scope"], "apply_plan")
        self.assertIs(result["needs_human_decision"], True)
        json.dumps(result, sort_keys=True)

    def test_approval_with_list_scope_allowed(self):
        call = {"function_name": "apply_plan",
                "boundary": "rendererOrAgent", "consequential": True}
        approval = ae.synthetic_approval()
        approval["scope"] = ["review_plan", "apply_plan"]
        result = ae.gate_function_call(call, approval)
        self.assertIs(result["allowed"], True)
        self.assertEqual(result["approval"]["scope"],
                         ["review_plan", "apply_plan"])

    def test_approval_false_refused(self):
        call = {"function_name": "apply_plan", "boundary": "agentOnly",
                "consequential": True}
        approval = ae.synthetic_approval()
        approval["approved"] = False
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call(call, approval)

    def test_approval_wrong_scope_refused(self):
        call = {"function_name": "apply_plan", "boundary": "agentOnly",
                "consequential": True}
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call(call,
                                  ae.synthetic_approval("other_fn"))

    def test_approval_missing_who_or_id_refused(self):
        call = {"function_name": "apply_plan", "boundary": "agentOnly",
                "consequential": True}
        no_who = ae.synthetic_approval()
        del no_who["approved_by"]
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call(call, no_who)
        no_id = ae.synthetic_approval()
        no_id["approval_id"] = ""
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call(call, no_id)

    def test_renderer_only_refused_even_with_approval(self):
        call = {"function_name": "openUrl", "boundary": "rendererOnly",
                "consequential": True}
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call(call, ae.synthetic_approval("openUrl"))

    def test_non_consequential_allowed_without_approval(self):
        call = {"function_name": "show_status",
                "boundary": "rendererOrAgent", "consequential": False}
        result = ae.gate_function_call(call)
        self.assertIs(result["allowed"], True)
        self.assertIs(result["approval"], None)

    def test_unknown_boundary_refused(self):
        call = {"function_name": "apply_plan", "boundary": "anywhere",
                "consequential": False}
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call(call)

    def test_bad_call_shapes_refused(self):
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call("not a call")
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call({"boundary": "agentOnly",
                                   "consequential": False})
        with self.assertRaises(ae.GateRefused):
            ae.gate_function_call({"function_name": "apply_plan",
                                   "boundary": "agentOnly",
                                   "consequential": "yes"})


class TestNoA2uiDependency(unittest.TestCase):
    def test_no_a2ui_import_or_dependency(self):
        path = os.path.join(os.path.dirname(__file__), "..",
                            "adapters", "a2ui_emitter.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        # The module docstring names the packages it does NOT
        # adopt; check the code after the docstring instead.
        code = source.split('"""', 2)[2]
        self.assertNotIn("import a2ui", code)
        self.assertNotIn("a2ui-core", code)
        self.assertNotIn("a2ui_core", code)
        self.assertNotIn("a2ui-agent-sdk", code)
        self.assertNotIn("from a2ui", code)
        self.assertIn("no a2ui code was copied", source.lower())


if __name__ == "__main__":
    unittest.main()
