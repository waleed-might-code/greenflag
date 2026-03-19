"""
Comprehensive demo: WARC storage in realistic security testing workflow.
Shows end-to-end flow from reconnaissance to finding with evidence.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cyberAI.storage import WARCIntegration, create_warc_writer
from cyberAI.models import (
    RequestRecord, HttpMethod, Finding, Severity, 
    TestCategory, ReproductionStep, Endpoint, EndpointClassification
)


class SecurityTestingDemo:
    """Demonstrates WARC-enabled security testing workflow."""
    
    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self.endpoints_discovered = []
        self.findings = []
    
    def print_header(self, text: str):
        """Print section header."""
        print(f"\n{'='*70}")
        print(f"  {text}")
        print(f"{'='*70}\n")
    
    def phase_1_reconnaissance(self):
        """Phase 1: Discover endpoints and capture traffic."""
        self.print_header("PHASE 1: RECONNAISSANCE")
        
        print("🔍 Crawling target application...")
        print("   - Discovering endpoints")
        print("   - Capturing HTTP traffic to WARC")
        print("   - Building attack surface map\n")
        
        # Simulate discovering endpoints
        discovered = [
            {
                "url": "https://api.target.com/users",
                "method": "GET",
                "classification": EndpointClassification.READ,
                "response": '{"users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}',
                "status": 200
            },
            {
                "url": "https://api.target.com/users/123",
                "method": "GET",
                "classification": EndpointClassification.READ,
                "response": '{"id": 123, "name": "Alice", "email": "alice@target.com", "role": "admin"}',
                "status": 200
            },
            {
                "url": "https://api.target.com/users/123",
                "method": "PUT",
                "classification": EndpointClassification.UPDATE,
                "response": '{"id": 123, "updated": true}',
                "status": 200
            },
            {
                "url": "https://api.target.com/admin/settings",
                "method": "GET",
                "classification": EndpointClassification.ADMIN,
                "response": '{"debug_mode": true, "api_keys": ["sk_live_123..."]}',
                "status": 200
            },
        ]
        
        warc_refs = []
        
        for ep in discovered:
            # Create RequestRecord
            request = RequestRecord(
                method=HttpMethod[ep["method"]],
                url=ep["url"],
                headers={
                    "User-Agent": "CyberAI/1.0",
                    "Authorization": "Bearer recon_token"
                },
                response_status=ep["status"],
                response_body=ep["response"],
                response_headers={"Content-Type": "application/json"},
            )
            
            # Capture to WARC
            ref = WARCIntegration.capture_request(self.engagement_id, request)
            warc_refs.append(ref)
            
            # Store endpoint
            endpoint = Endpoint(
                url=ep["url"],
                method=HttpMethod[ep["method"]],
                classification=ep["classification"],
            )
            self.endpoints_discovered.append({
                "endpoint": endpoint,
                "request": request,
                "warc_ref": ref
            })
            
            print(f"✓ Discovered: {ep['method']:6} {ep['url']}")
            print(f"  Classification: {ep['classification'].value}")
            print(f"  WARC: {ref.warc_id[:16]}...")
        
        print(f"\n📊 Reconnaissance Summary:")
        print(f"   Endpoints discovered: {len(self.endpoints_discovered)}")
        print(f"   WARC records: {len(warc_refs)}")
        print(f"   Evidence stored: outputs/warc/{self.engagement_id}/")
    
    def phase_2_vulnerability_testing(self):
        """Phase 2: Test for vulnerabilities with evidence capture."""
        self.print_header("PHASE 2: VULNERABILITY TESTING")
        
        print("🔬 Running security tests...")
        print("   - Authorization bypass (IDOR)")
        print("   - Privilege escalation")
        print("   - Mass assignment\n")
        
        # Test 1: IDOR on user endpoint
        print("Test 1: IDOR on /users/{id}")
        print("-" * 50)
        
        # Request as admin (baseline)
        admin_request = RequestRecord(
            method=HttpMethod.GET,
            url="https://api.target.com/users/123",
            headers={"Authorization": "Bearer admin_token"},
            response_status=200,
            response_body='{"id": 123, "email": "victim@target.com", "ssn": "123-45-6789", "salary": 150000}',
            response_headers={"Content-Type": "application/json"},
        )
        admin_ref = WARCIntegration.capture_request(self.engagement_id, admin_request)
        print(f"  ✓ Admin request: 200 OK")
        print(f"    WARC: {admin_ref.warc_id[:16]}...")
        
        # Request as regular user (should fail but doesn't - IDOR!)
        user_request = RequestRecord(
            method=HttpMethod.GET,
            url="https://api.target.com/users/123",
            headers={"Authorization": "Bearer user_token"},
            response_status=200,  # BUG: Should be 403!
            response_body='{"id": 123, "email": "victim@target.com", "ssn": "123-45-6789", "salary": 150000}',
            response_headers={"Content-Type": "application/json"},
        )
        user_ref = WARCIntegration.capture_request(self.engagement_id, user_request)
        print(f"  ✓ User request: 200 OK (EXPECTED: 403)")
        print(f"    WARC: {user_ref.warc_id[:16]}...")
        
        # Create finding
        finding = Finding(
            title="IDOR: Unauthorized Access to User PII",
            severity=Severity.HIGH,
            category=TestCategory.AUTHZ,
            asset="https://api.target.com/users/{id}",
            affected_roles=["user"],
            reproduction_steps=[
                ReproductionStep(
                    step_number=1,
                    action="Authenticate as regular user",
                    expected_result="Receive user-level JWT token"
                ),
                ReproductionStep(
                    step_number=2,
                    action="Send GET /users/123 with user token",
                    expected_result="403 Forbidden (user cannot access other users)"
                ),
                ReproductionStep(
                    step_number=3,
                    action="Observe actual response",
                    expected_result="200 OK with victim's SSN and salary (VULNERABILITY)"
                ),
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
        
        self.findings.append(finding)
        
        print(f"\n  🚨 VULNERABILITY FOUND!")
        print(f"     Title: {finding.title}")
        print(f"     Severity: {finding.severity.value.upper()}")
        print(f"     CWE: {finding.cwe_id}")
        print(f"     Confidence: {finding.reliability_score}%")
        print(f"     Evidence: {len(finding.evidence_warc_refs)} WARC refs")
        
        # Test 2: Mass assignment on user update
        print(f"\n\nTest 2: Mass Assignment on /users/{{id}}")
        print("-" * 50)
        
        # Normal update
        normal_update = RequestRecord(
            method=HttpMethod.PUT,
            url="https://api.target.com/users/456",
            headers={"Authorization": "Bearer user_456_token", "Content-Type": "application/json"},
            body='{"name": "Updated Name"}',
            response_status=200,
            response_body='{"id": 456, "name": "Updated Name", "role": "user"}',
            response_headers={"Content-Type": "application/json"},
        )
        normal_ref = WARCIntegration.capture_request(self.engagement_id, normal_update)
        print(f"  ✓ Normal update: 200 OK")
        
        # Mass assignment attempt
        mass_assign = RequestRecord(
            method=HttpMethod.PUT,
            url="https://api.target.com/users/456",
            headers={"Authorization": "Bearer user_456_token", "Content-Type": "application/json"},
            body='{"name": "Hacker", "role": "admin", "is_verified": true}',
            response_status=200,  # BUG: Should reject role/is_verified
            response_body='{"id": 456, "name": "Hacker", "role": "admin", "is_verified": true}',
            response_headers={"Content-Type": "application/json"},
        )
        mass_ref = WARCIntegration.capture_request(self.engagement_id, mass_assign)
        print(f"  ✓ Mass assignment: 200 OK (EXPECTED: 400 or filtered)")
        
        finding2 = Finding(
            title="Mass Assignment: Privilege Escalation via User Update",
            severity=Severity.CRITICAL,
            category=TestCategory.MASS_ASSIGNMENT,
            asset="https://api.target.com/users/{id}",
            affected_roles=["user"],
            reproduction_steps=[
                ReproductionStep(
                    step_number=1,
                    action="Authenticate as regular user",
                    expected_result="User-level access"
                ),
                ReproductionStep(
                    step_number=2,
                    action='Send PUT /users/456 with {"role": "admin"}',
                    expected_result="Server should filter/reject role field"
                ),
                ReproductionStep(
                    step_number=3,
                    action="Observe response",
                    expected_result="User role changed to admin (VULNERABILITY)"
                ),
            ],
            request_proof=mass_assign,
            reliability_score=98.0,
            impact_types=["integrity", "confidentiality"],
            cwe_id="CWE-915",
            evidence_warc_refs=[
                normal_ref.to_uri(),
                mass_ref.to_uri(),
            ],
        )
        
        self.findings.append(finding2)
        
        print(f"\n  🚨 CRITICAL VULNERABILITY FOUND!")
        print(f"     Title: {finding2.title}")
        print(f"     Severity: {finding2.severity.value.upper()}")
        print(f"     CWE: {finding2.cwe_id}")
        print(f"     Confidence: {finding2.reliability_score}%")
        
        print(f"\n📊 Testing Summary:")
        print(f"   Tests run: 2")
        print(f"   Vulnerabilities found: {len(self.findings)}")
        print(f"   Evidence captured: {sum(len(f.evidence_warc_refs) for f in self.findings)} WARC refs")
    
    def phase_3_reporting(self):
        """Phase 3: Generate report with evidence."""
        self.print_header("PHASE 3: REPORTING")
        
        print("📝 Generating security assessment report...\n")
        
        print("=" * 70)
        print("  SECURITY ASSESSMENT REPORT")
        print("=" * 70)
        print(f"\nEngagement ID: {self.engagement_id}")
        print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Target: https://api.target.com")
        
        print(f"\n{'─'*70}")
        print("EXECUTIVE SUMMARY")
        print(f"{'─'*70}")
        print(f"\nEndpoints Discovered: {len(self.endpoints_discovered)}")
        print(f"Vulnerabilities Found: {len(self.findings)}")
        print(f"  - Critical: {sum(1 for f in self.findings if f.severity == Severity.CRITICAL)}")
        print(f"  - High: {sum(1 for f in self.findings if f.severity == Severity.HIGH)}")
        print(f"  - Medium: {sum(1 for f in self.findings if f.severity == Severity.MEDIUM)}")
        print(f"  - Low: {sum(1 for f in self.findings if f.severity == Severity.LOW)}")
        
        print(f"\n{'─'*70}")
        print("FINDINGS")
        print(f"{'─'*70}")
        
        for i, finding in enumerate(self.findings, 1):
            print(f"\n[{i}] {finding.title}")
            print(f"    Severity: {finding.severity.value.upper()}")
            print(f"    Category: {finding.category.value}")
            print(f"    CWE: {finding.cwe_id}")
            print(f"    Confidence: {finding.reliability_score}%")
            print(f"    Asset: {finding.asset}")
            print(f"\n    Reproduction Steps:")
            for step in finding.reproduction_steps:
                print(f"      {step.step_number}. {step.action}")
                print(f"         Expected: {step.expected_result}")
            print(f"\n    Evidence (WARC References):")
            for ref_uri in finding.evidence_warc_refs:
                print(f"      - {ref_uri}")
            print(f"\n    Impact: {', '.join(finding.impact_types)}")
        
        print(f"\n{'─'*70}")
        print("EVIDENCE PROVENANCE")
        print(f"{'─'*70}")
        print(f"\nAll findings are backed by WARC archives containing:")
        print(f"  ✓ Complete HTTP request/response pairs")
        print(f"  ✓ Timestamps and metadata")
        print(f"  ✓ Content-addressed IDs for verification")
        print(f"  ✓ ISO 28500 standard format")
        print(f"\nEvidence Location: outputs/warc/{self.engagement_id}/")
        print(f"\nAuditors can:")
        print(f"  1. Extract WARC records using standard tools")
        print(f"  2. Replay exact HTTP requests")
        print(f"  3. Verify findings independently")
        print(f"  4. Maintain chain of custody for compliance")
        
        print(f"\n{'='*70}\n")
    
    def run(self):
        """Run complete demo."""
        print("\n" + "="*70)
        print("  CYBERAI SECURITY TESTING DEMO")
        print("  WARC-Enabled Evidence Collection")
        print("="*70)
        
        self.phase_1_reconnaissance()
        self.phase_2_vulnerability_testing()
        self.phase_3_reporting()
        
        # Cleanup
        WARCIntegration.close_writer(self.engagement_id)
        
        print("✅ Demo complete!")
        print(f"\n📁 Check outputs/warc/{self.engagement_id}/ for WARC files")
        print(f"💡 Use 'zcat' to inspect WARC contents")


if __name__ == "__main__":
    demo = SecurityTestingDemo(engagement_id="demo_realistic_001")
    demo.run()
