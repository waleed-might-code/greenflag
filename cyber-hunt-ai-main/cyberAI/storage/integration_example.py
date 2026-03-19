"""
Integration example: Using WARC storage in the recon phase.
Shows how to capture HTTP traffic during reconnaissance.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cyberAI.storage import WARCIntegration
from cyberAI.models import RequestRecord, HttpMethod, Endpoint, EndpointClassification
from datetime import datetime


def simulate_recon_with_warc():
    """
    Simulate reconnaissance phase with WARC capture.
    This shows how to integrate WARC into the existing recon pipeline.
    """
    engagement_id = "eng_recon_demo"
    
    print("=== Reconnaissance with WARC Evidence Capture ===\n")
    
    # Simulate discovering endpoints during recon
    endpoints_discovered = [
        {
            "url": "https://api.target.com/users",
            "method": "GET",
            "response": '{"users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}',
            "status": 200
        },
        {
            "url": "https://api.target.com/users/1",
            "method": "GET",
            "response": '{"id": 1, "name": "Alice", "email": "alice@target.com", "role": "admin"}',
            "status": 200
        },
        {
            "url": "https://api.target.com/admin/settings",
            "method": "GET",
            "response": '{"debug_mode": true, "api_keys": ["sk_live_123..."]}',
            "status": 200
        },
    ]
    
    captured_refs = []
    
    for ep in endpoints_discovered:
        # Create RequestRecord (this is what recon modules already do)
        request = RequestRecord(
            method=HttpMethod[ep["method"]],
            url=ep["url"],
            headers={"User-Agent": "CyberAI/1.0", "Authorization": "Bearer token"},
            response_status=ep["status"],
            response_body=ep["response"],
            response_headers={"Content-Type": "application/json"},
        )
        
        # NEW: Capture to WARC automatically
        ref = WARCIntegration.capture_request(engagement_id, request)
        
        if ref:
            captured_refs.append(ref)
            print(f"✓ Captured: {ep['method']} {ep['url']}")
            print(f"  WARC URI: {ref.to_uri()}")
            print(f"  Request now has warc_ref: {request.warc_ref}\n")
    
    print(f"\n=== Summary ===")
    print(f"Total endpoints discovered: {len(endpoints_discovered)}")
    print(f"Total WARC records: {len(captured_refs)}")
    print(f"Evidence stored in: outputs/warc/{engagement_id}/")
    
    # Close WARC writer
    WARCIntegration.close_writer(engagement_id)
    
    return captured_refs


def simulate_testing_with_warc():
    """
    Simulate testing phase with WARC evidence for findings.
    Shows how findings link to WARC evidence.
    """
    from cyberAI.models import Finding, Severity, TestCategory, FindingStatus
    
    engagement_id = "eng_test_demo"
    
    print("\n\n=== Security Testing with WARC Evidence ===\n")
    
    # Simulate IDOR test
    print("Testing: IDOR on /users/{id} endpoint\n")
    
    # Request 1: Admin accessing user 123
    admin_request = RequestRecord(
        method=HttpMethod.GET,
        url="https://api.target.com/users/123",
        headers={"Authorization": "Bearer admin_token"},
        response_status=200,
        response_body='{"id": 123, "email": "victim@target.com", "ssn": "123-45-6789"}',
        response_headers={"Content-Type": "application/json"},
    )
    admin_ref = WARCIntegration.capture_request(engagement_id, admin_request)
    print(f"✓ Admin request captured: {admin_ref.to_uri()}")
    
    # Request 2: Regular user accessing user 123 (should fail but doesn't)
    user_request = RequestRecord(
        method=HttpMethod.GET,
        url="https://api.target.com/users/123",
        headers={"Authorization": "Bearer user_token"},
        response_status=200,  # BUG: Should be 403!
        response_body='{"id": 123, "email": "victim@target.com", "ssn": "123-45-6789"}',
        response_headers={"Content-Type": "application/json"},
    )
    user_ref = WARCIntegration.capture_request(engagement_id, user_request)
    print(f"✓ User request captured: {user_ref.to_uri()}")
    
    # Create finding with WARC evidence
    from cyberAI.models import ReproductionStep
    
    finding = Finding(
        title="IDOR: Unauthorized Access to User PII",
        severity=Severity.HIGH,
        category=TestCategory.AUTHZ,
        asset="https://api.target.com/users/{id}",
        affected_roles=["user"],
        reproduction_steps=[
            ReproductionStep(step_number=1, action="Authenticate as regular user", expected_result="Get user token"),
            ReproductionStep(step_number=2, action="GET /users/123 with user token", expected_result="403 Forbidden"),
            ReproductionStep(step_number=3, action="Observe actual response", expected_result="200 OK with victim's SSN"),
        ],
        request_proof=user_request,
        reliability_score=95.0,
        impact_types=["confidentiality"],
        cwe_id="CWE-639",
        evidence_warc_refs=[
            admin_ref.to_uri(),
            user_ref.to_uri(),
        ],
    )
    
    print(f"\n=== Finding Created ===")
    print(f"Title: {finding.title}")
    print(f"Severity: {finding.severity.value.upper()}")
    print(f"Reliability: {finding.reliability_score}%")
    print(f"Evidence WARC refs:")
    for ref_uri in finding.evidence_warc_refs:
        print(f"  - {ref_uri}")
    
    print(f"\n✓ Finding can be reproduced by replaying WARC records")
    print(f"✓ Auditors can verify the exact HTTP traffic")
    
    WARCIntegration.close_writer(engagement_id)
    
    return finding


if __name__ == "__main__":
    # Run both examples
    refs = simulate_recon_with_warc()
    finding = simulate_testing_with_warc()
    
    print("\n\n=== Integration Complete ===")
    print("WARC storage is now integrated into:")
    print("  1. Reconnaissance phase (automatic capture)")
    print("  2. Testing phase (evidence linking)")
    print("  3. Findings (traceable to raw HTTP)")
