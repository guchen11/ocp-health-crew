"""Tests for the requested-IP primary UDN scenario templates."""

import unittest

from config.builtin_templates import BUILTIN_TEMPLATES
from config.cnv_scenarios import CNV_SCENARIOS


class RequestedIpUdnTemplateTests(unittest.TestCase):
    def setUp(self):
        self.scenario = CNV_SCENARIOS["requested_ip_udn"]
        self.templates = {item["name"]: item for item in BUILTIN_TEMPLATES}

    def test_scenario_registration_matches_remote_runner(self):
        self.assertEqual("requested-ip-udn", self.scenario["remote_name"])
        self.assertEqual("Scale", self.scenario["category"])
        self.assertFalse(self.scenario["default"])

    def test_scenario_defaults_match_cnv_scenario_vars(self):
        variables = self.scenario["variables"]
        self.assertEqual({"sanity": 2, "full": 100}, variables["vmCount"]["default"])
        self.assertEqual({"sanity": 100, "full": 25}, variables["sshSamplePercent"]["default"])
        self.assertEqual({"sanity": 2, "full": 2}, variables["ipOffset"]["default"])

    def test_validation_template_targets_requested_ip_scenario(self):
        template = self.templates["Validation - Requested IP on Primary UDN"]
        config = template["config"]
        self.assertEqual("sanity", config["scenario_mode"])
        self.assertEqual(["requested-ip-udn"], config["scenario_tests"])
        self.assertEqual("2", config["env_vars"]["requested_ip_udn.vmCount"])
        self.assertEqual("100", config["env_vars"]["requested_ip_udn.sshSamplePercent"])

    def test_full_template_targets_requested_ip_scenario(self):
        template = self.templates["Full - Requested IP on Primary UDN"]
        config = template["config"]
        self.assertEqual("full", config["scenario_mode"])
        self.assertEqual(["requested-ip-udn"], config["scenario_tests"])
        self.assertEqual("100", config["env_vars"]["requested_ip_udn.vmCount"])
        self.assertEqual("25", config["env_vars"]["requested_ip_udn.sshSamplePercent"])


if __name__ == "__main__":
    unittest.main()
