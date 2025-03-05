"""Tests related to TODO

:Requirement: Hammer

:CaseAutomation: Automated

:CaseComponent:

:Team: Endeavour

:CaseImportance: Critical

"""

import pytest
import yaml

from robottelo.constants import DataFile

USAGE_REPORT_ITEMS = yaml.safe_load(DataFile.USAGE_REPORT_ITEMS.read_text())


def test_positive_usage_report_items(module_target_sat, module_generate_report):
    """check all expected entries are present in usage report

    :id: fe03c15f-4cd3-4282-988f-28112e60a909

    :expectedresults: All expected entries are present

    """
    generated_report_set = set(module_generate_report.keys())
    expected_keys_set = set(USAGE_REPORT_ITEMS.keys())
    if generated_report_set != expected_keys_set:
        added_items = generated_report_set - expected_keys_set
        removed_items = expected_keys_set - generated_report_set
        pytest.fail(
            f'Report field mismatch: added items: {added_items}, removed items: {removed_items}'
        )
