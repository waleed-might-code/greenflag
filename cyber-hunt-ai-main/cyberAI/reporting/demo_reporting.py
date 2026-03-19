"""
Demo script for WARC-backed reporting system.
Shows how to create findings with evidence and generate reports.
"""

import asyncio
from datetime import datetime
from pathlib import Path

from cyberAI.config import Config
from cyberAI.models import (
    Finding,
    ImpactType,
    ReproductionStep,
    Severity,
    TestCategory,
    VerifiedFinding,
)
from cyberAI.reporting.reporter import ReportGenerator
from cyberAI.storage import create_warc_writer
from cyberAI.utils.helpers import atomic_write_json


async def demo_warc_capture():
    """Demo: Capture HTTP traffic to WARC."""
    print("=== WARC Capture Demo ===\n")
    
    # Create WARC writer
    engagement_id = "demo_engagement_001"
    warc_writer = create_warc_writer(engagement_id=engagement_id)
    
    print(f"Created WARC writer for engagement: {engagement_id}")
    print(f"WARC directory: {warc_writer.engagement_dir}\n")
    
    # Simulate capturing HTTP traffic
    print("Capturing HTTP request/response...")
    warc_ref = warc_writer.write_request_response(
        method="GET",
        url="https://api.example.com/users/123",
        request_headers={
            "Authorization": "Bearer token_user",
            "User-Agent": "CyberAI/1.0",
        },
        request_body=b"",
        status_code=200,
        reason="OK",
        response_headers={
            "Content-Type": "application/json",
            "Content-Length": "45",
        },
        response_body=b'{"id": 123, "name": "Alice", "role": "user"}',
    )
    
    print(f"✓ Captured to WARC")
    print(f"  WARC ID: {warc_ref.warc_id[:16]}...")
    print(f"  URI: {warc_ref.to_uri()}")
    print(f"  File: {warc_ref.file_path}")
    print(f"  Offset: {warc_ref.offset} bytes")
    print(f"  Length: {warc_ref.length} bytes\n")
    
    # Capture another request (admin accessing same resource)
    print("Capturing second request (admin role)...")
    warc_ref2 = warc_writer.write_request_response(
        method="GET",
        url="https://api.example.com/users/123",
        request_headers={
            "Authorization": "Bearer token_admin",
            "User-Agent": "CyberAI/1.0",
        },
        request_body=b"",
        status_code=200,
        reason="OK",
        response_headers={
            "Content-Type": "application/json",
            "Content-Length": "45",
        },
        response_body=b'{"id": 123, "name": "Alice", "role": "user"}',
    )
    
    print(f"✓ Captured to WARC")
    print(f"  WARC ID: {warc_ref2.warc_id[:16]}...")
    print(f"  URI: {warc_ref2.to_uri()}\n")
    
    warc_writer.close()
    
    return [warc_ref, warc_ref2]


def demo_create_finding_with_evidence(warc_refs):
    """Demo: Create a finding with WARC evidence."""
    print("=== Creating Finding with Evidence ===\n")
    
    finding = VerifiedFinding(
        title="Broken Object Level Authorization (BOLA)",
        severity=Severity.HIGH,
        category=TestCategory.AUTHZ,
        asset="GET /api/users/{id}",
        affected_roles=["user", "guest"],
        affected_states=["authenticated"],
        preconditions=[
            "Valid authentication token",
            "Knowledge of target user ID",
        ],
        reproduction_steps=[
            ReproductionStep(
                step_number=1,
                action="Authenticate as low-privilege user",
                expected_result="Receive user token",
                actual_result="Token received",
            ),
            ReproductionStep(
                step_number=2,
                action="Request GET /api/users/123 with user token",
                expected_result="403 Forbidden or filtered response",
                actual_result="200 OK with full user object",
            ),
            ReproductionStep(
                step_number=3,
                action="Verify response contains sensitive data",
                expected_result="No sensitive data",
                actual_result="Full user profile including email, phone",
            ),
        ],
        reliability_score=95.0,
        root_cause="Missing authorization check on user ID parameter",
        impact_types=[ImpactType.CONFIDENTIALITY, ImpactType.COMPLIANCE],
        cvss_score=7.5,
        cwe_id="CWE-639",
        evidence_warc_refs=[ref.to_uri() for ref in warc_refs],
        verification_method="Cross-role differential testing",
        confirmed_impact="Low-privilege users can access any user's profile data",
        exploit_chain=[
            "Enumerate user IDs (1-1000)",
            "Request each user profile with low-priv token",
            "Extract PII from responses",
        ],
        cross_role_confirmed=True,
        false_positive_ruled_out=True,
    )
    
    print(f"✓ Created finding: {finding.title}")
    print(f"  ID: {finding.id}")
    print(f"  Severity: {finding.severity.value.upper()}")
    print(f"  Evidence: {len(finding.evidence_warc_refs)} WARC references")
    print(f"  Reliability: {finding.reliability_score}%\n")
    
    return finding


def demo_generate_report(findings):
    """Demo: Generate comprehensive report."""
    print("=== Generating Report ===\n")
    
    # Save findings to expected location
    config = Config.get()
    findings_path = config.get_output_path("verification", "confirmed", "verified_findings.json")
    findings_path.parent.mkdir(parents=True, exist_ok=True)
    
    findings_data = {
        "verified_findings": [f.model_dump() for f in findings],
        "generated_at": datetime.utcnow().isoformat(),
    }
    atomic_write_json(findings_path, findings_data)
    print(f"✓ Saved findings to: {findings_path}\n")
    
    # Generate report
    generator = ReportGenerator(run_id="demo_run_001")
    generator.load_verified_findings()
    
    print(f"Loaded {len(generator._findings)} findings")
    
    report = generator.generate_report()
    print(f"✓ Generated report")
    print(f"  Findings: {len(report.findings)}")
    print(f"  Pattern clusters: {len(report.pattern_clusters)}")
    print(f"  Remediation items: {len(report.remediation_queue)}\n")
    
    # Save outputs
    outputs = generator.save_all_outputs()
    
    print(f"✓ Saved {len(outputs)} output files:\n")
    for name, path in outputs.items():
        if Path(path).exists():
            size = Path(path).stat().st_size
            print(f"  {name}: {path} ({size} bytes)")
    
    return report


async def main():
    """Run complete demo."""
    print("\n" + "="*60)
    print("WARC-Backed Reporting System Demo")
    print("="*60 + "\n")
    
    # Initialize config
    Config.load()
    
    # Step 1: Capture HTTP traffic to WARC
    warc_refs = await demo_warc_capture()
    
    # Step 2: Create finding with evidence
    finding = demo_create_finding_with_evidence(warc_refs)
    
    # Step 3: Generate comprehensive report
    report = demo_generate_report([finding])
    
    print("\n" + "="*60)
    print("Demo Complete!")
    print("="*60)
    print("\nNext steps:")
    print("1. Check outputs/reports/ for generated reports")
    print("2. Extract evidence pack: unzip outputs/reports/evidence_packs/evidence_*.zip")
    print("3. View WARC files in outputs/warc/demo_engagement_001/")
    print()


if __name__ == "__main__":
    asyncio.run(main())
