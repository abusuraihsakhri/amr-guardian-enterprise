#!/usr/bin/env python3
"""
AMR Guardian Enterprise - Integration and Regression Test Suite.
"""

import unittest
from test_amr_guardian_enterprise import (
    TestRenalKinetics,
    TestRenalDosingAlerts,
    TestBugDrugMismatch,
    TestDeescalationOpportunities,
    TestIVToPOSwitch,
    TestNHSNMetrics,
    TestSecurityAndAudit,
    TestAMRGuardianEnterpriseOrchestration,
)

if __name__ == "__main__":
    unittest.main()
