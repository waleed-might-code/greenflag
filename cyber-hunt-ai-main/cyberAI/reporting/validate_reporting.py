#!/usr/bin/env python3
"""
Quick validation test for WARC-backed reporting system.
Tests core functionality without requiring full environment setup.
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        from cyberAI.storage.warc_writer import WARCWriter, WARCReference
        print("  ✓ WARCWriter")
    except Exception as e:
        print(f"  ✗ WARCWriter: {e}")
        return False
    
    try:
        from cyberAI.storage.evidence_store import EvidenceStore
        print("  ✓ EvidenceStore")
    except Exception as e:
        print(f"  ✗ EvidenceStore: {e}")
        return False
    
    try:
        from cyberAI.reporting.evidence_pack import generate_evidence_pack
        print("  ✓ generate_evidence_pack")
    except Exception as e:
        print(f"  ✗ generate_evidence_pack: {e}")
        return False
    
    try:
        from cyberAI.reporting.finding_record import generate_finding_record
        print("  ✓ generate_finding_record")
    except Exception as e:
        print(f"  ✗ generate_finding_record: {e}")
        return False
    
    try:
        from cyberAI.reporting.executive_summary import generate_executive_summary
        print("  ✓ generate_executive_summary")
    except Exception as e:
        print(f"  ✗ generate_executive_summary: {e}")
        return False
    
    try:
        from cyberAI.reporting.engineering_handoff import generate_engineering_handoff
        print("  ✓ generate_engineering_handoff")
    except Exception as e:
        print(f"  ✗ generate_engineering_handoff: {e}")
        return False
    
    return True


def test_warc_reference():
    """Test WARC reference creation and URI generation."""
    print("\nTesting WARC reference...")
    
    try:
        from cyberAI.storage.warc_writer import WARCReference
        from datetime import datetime, timezone
        
        ref = WARCReference(
            warc_id="abc123def456",
            file_path="eng_001/eng_001_20240316_001.warc.gz",
            offset=1024,
            length=2048,
            engagement_id="eng_001",
            timestamp=datetime.now(timezone.utc),
        )
        
        uri = ref.to_uri()
        expected_prefix = "warc://eng_001/eng_001"
        
        if uri.startswith(expected_prefix):
            print(f"  ✓ URI format correct: {uri}")
            return True
        else:
            print(f"  ✗ URI format incorrect: {uri}")
            return False
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def test_finding_record_generation():
    """Test finding record generation."""
    print("\nTesting finding record generation...")
    
    try:
        from cyberAI.models import (
            VerifiedFinding,
            Severity,
            TestCategory,
            ImpactType,
            ReproductionStep,
        )
        from cyberAI.reporting.finding_record import generate_finding_record
        
        finding = VerifiedFinding(
            title="Test BOLA Finding",
            severity=Severity.HIGH,
            category=TestCategory.AUTHZ,
            asset="/api/users/123",
            affected_roles=["user"],
            reproduction_steps=[
                ReproductionStep(
                    step_number=1,
                    action="Test action",
                    expected_result="Expected",
                    actual_result="Actual",
                )
            ],
            reliability_score=90.0,
            impact_types=[ImpactType.CONFIDENTIALITY],
            evidence_warc_refs=[
                "warc://eng_001/file.warc.gz#1024:2048",
                "warc://eng_001/file.warc.gz#3072:1024",
            ],
            verification_method="Cross-role testing",
            confirmed_impact="Unauthorized access",
            cross_role_confirmed=True,
            false_positive_ruled_out=True,
        )
        
        record = generate_finding_record(finding)
        
        # Check key sections are present
        checks = [
            ("Title", "# Test BOLA Finding" in record),
            ("Severity", "HIGH" in record),
            ("Evidence Trail", "Evidence Trail" in record),
            ("WARC refs", "warc://eng_001" in record),
            ("Verification", "Verification" in record),
            ("Cross-role", "Cross-Role Confirmed" in record),
        ]
        
        all_passed = True
        for check_name, passed in checks:
            if passed:
                print(f"  ✓ {check_name}")
            else:
                print(f"  ✗ {check_name}")
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_executive_summary():
    """Test executive summary generation."""
    print("\nTesting executive summary generation...")
    
    try:
        from cyberAI.models import (
            VerifiedFinding,
            Severity,
            TestCategory,
            ImpactType,
        )
        from cyberAI.reporting.executive_summary import generate_executive_summary
        
        findings = [
            VerifiedFinding(
                title="Critical Finding",
                severity=Severity.CRITICAL,
                category=TestCategory.AUTHZ,
                asset="/api/admin",
                reliability_score=95.0,
                impact_types=[ImpactType.CONFIDENTIALITY],
                evidence_warc_refs=["warc://eng_001/file.warc.gz#0:1024"],
                verification_method="Test",
                confirmed_impact="Test",
                cross_role_confirmed=True,
            ),
            VerifiedFinding(
                title="High Finding",
                severity=Severity.HIGH,
                category=TestCategory.AUTH,
                asset="/api/users",
                reliability_score=85.0,
                impact_types=[ImpactType.INTEGRITY],
                evidence_warc_refs=["warc://eng_001/file.warc.gz#1024:512"],
                verification_method="Test",
                confirmed_impact="Test",
            ),
        ]
        
        summary = generate_executive_summary(
            findings,
            "https://target.example.com",
            total_endpoints=50,
            total_tests=200,
        )
        
        checks = [
            ("Title", "# Executive Summary" in summary),
            ("Target", "target.example.com" in summary),
            ("Critical count", "**Critical:** 1" in summary),
            ("High count", "**High:** 1" in summary),
            ("Evidence stats", "Findings with WARC Evidence" in summary),
            ("Coverage", "Endpoints Tested" in summary),
        ]
        
        all_passed = True
        for check_name, passed in checks:
            if passed:
                print(f"  ✓ {check_name}")
            else:
                print(f"  ✗ {check_name}")
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all validation tests."""
    print("="*60)
    print("WARC-Backed Reporting System Validation")
    print("="*60)
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("WARC Reference", test_warc_reference()))
    results.append(("Finding Record", test_finding_record_generation()))
    results.append(("Executive Summary", test_executive_summary()))
    
    print("\n" + "="*60)
    print("Validation Results")
    print("="*60)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status:8} {test_name}")
    
    all_passed = all(passed for _, passed in results)
    
    print("="*60)
    if all_passed:
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
