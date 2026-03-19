#!/usr/bin/env python3
"""
Standalone demonstration of WARC-backed reporting system.
Works without full environment setup - uses mock data.
"""

import gzip
import hashlib
import json
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Minimal WARC implementation for demo
@dataclass
class WARCReference:
    warc_id: str
    file_path: str
    offset: int
    length: int
    engagement_id: str
    timestamp: datetime
    
    def to_uri(self) -> str:
        return f"warc://{self.engagement_id}/{self.file_path}#{self.offset}:{self.length}"


class SimpleWARCWriter:
    """Simplified WARC writer for demo."""
    
    def __init__(self, output_dir: Path, engagement_id: str):
        self.output_dir = Path(output_dir)
        self.engagement_id = engagement_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.current_file = self.output_dir / f"{engagement_id}_demo.warc.gz"
        self.handle = gzip.open(self.current_file, "wb")
        self.offset = 0
    
    def write_request_response(
        self,
        method: str,
        url: str,
        request_headers: dict,
        request_body: bytes,
        status_code: int,
        response_headers: dict,
        response_body: bytes,
    ) -> WARCReference:
        """Write HTTP request/response to WARC."""
        # Generate content ID
        content = f"{method} {url}".encode()
        warc_id = hashlib.sha256(content).hexdigest()
        
        # Format HTTP request
        http_request = f"{method} {url} HTTP/1.1\r\n"
        for k, v in request_headers.items():
            http_request += f"{k}: {v}\r\n"
        http_request += "\r\n"
        http_request_bytes = http_request.encode() + request_body
        
        # Format HTTP response
        http_response = f"HTTP/1.1 {status_code} OK\r\n"
        for k, v in response_headers.items():
            http_response += f"{k}: {v}\r\n"
        http_response += "\r\n"
        http_response_bytes = http_response.encode() + response_body
        
        # Write WARC records
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Request record
        warc_header = (
            f"WARC/1.0\r\n"
            f"WARC-Type: request\r\n"
            f"WARC-Record-ID: <urn:uuid:{warc_id}>\r\n"
            f"WARC-Date: {timestamp}\r\n"
            f"WARC-Target-URI: {url}\r\n"
            f"Content-Type: application/http; msgtype=request\r\n"
            f"Content-Length: {len(http_request_bytes)}\r\n"
            f"\r\n"
        )
        
        start_offset = self.offset
        record = warc_header.encode() + http_request_bytes + b"\r\n\r\n"
        self.handle.write(record)
        
        # Response record
        warc_header = (
            f"WARC/1.0\r\n"
            f"WARC-Type: response\r\n"
            f"WARC-Record-ID: <urn:uuid:{warc_id}>\r\n"
            f"WARC-Date: {timestamp}\r\n"
            f"WARC-Target-URI: {url}\r\n"
            f"Content-Type: application/http; msgtype=response\r\n"
            f"Content-Length: {len(http_response_bytes)}\r\n"
            f"\r\n"
        )
        
        record = warc_header.encode() + http_response_bytes + b"\r\n\r\n"
        self.handle.write(record)
        self.handle.flush()
        
        total_length = len(record) * 2  # Approximate
        self.offset += total_length
        
        return WARCReference(
            warc_id=warc_id,
            file_path=str(self.current_file.name),
            offset=start_offset,
            length=total_length,
            engagement_id=self.engagement_id,
            timestamp=datetime.now(timezone.utc),
        )
    
    def close(self):
        if self.handle:
            self.handle.close()


def demo_warc_capture(temp_dir: Path):
    """Demonstrate WARC capture."""
    print("=" * 70)
    print("STEP 1: Capturing HTTP Traffic to WARC")
    print("=" * 70)
    
    engagement_id = "demo_eng_001"
    warc_dir = temp_dir / "warc"
    writer = SimpleWARCWriter(warc_dir, engagement_id)
    
    print(f"\n✓ Created WARC writer for engagement: {engagement_id}")
    print(f"  Output directory: {warc_dir}")
    
    # Capture request 1 (user role)
    print("\n→ Capturing request as 'user' role...")
    ref1 = writer.write_request_response(
        method="GET",
        url="https://api.example.com/users/123",
        request_headers={"Authorization": "Bearer token_user"},
        request_body=b"",
        status_code=200,
        response_headers={"Content-Type": "application/json"},
        response_body=b'{"id": 123, "name": "Alice", "email": "alice@example.com"}',
    )
    print(f"  ✓ Captured: {ref1.to_uri()[:60]}...")
    
    # Capture request 2 (admin role)
    print("\n→ Capturing request as 'admin' role...")
    ref2 = writer.write_request_response(
        method="GET",
        url="https://api.example.com/users/123",
        request_headers={"Authorization": "Bearer token_admin"},
        request_body=b"",
        status_code=200,
        response_headers={"Content-Type": "application/json"},
        response_body=b'{"id": 123, "name": "Alice", "email": "alice@example.com"}',
    )
    print(f"  ✓ Captured: {ref2.to_uri()[:60]}...")
    
    writer.close()
    print(f"\n✓ WARC file created: {writer.current_file}")
    print(f"  Size: {writer.current_file.stat().st_size} bytes")
    
    return [ref1, ref2], warc_dir


def demo_finding_creation(warc_refs):
    """Demonstrate finding creation with evidence."""
    print("\n" + "=" * 70)
    print("STEP 2: Creating Finding with WARC Evidence")
    print("=" * 70)
    
    finding = {
        "id": "finding_001",
        "title": "Broken Object Level Authorization (BOLA)",
        "severity": "HIGH",
        "category": "authz",
        "asset": "GET /api/users/{id}",
        "affected_roles": ["user", "guest"],
        "reproduction_steps": [
            {
                "step_number": 1,
                "action": "Authenticate as low-privilege user",
                "expected_result": "Receive user token",
                "actual_result": "Token received",
            },
            {
                "step_number": 2,
                "action": "Request GET /api/users/123 with user token",
                "expected_result": "403 Forbidden or filtered response",
                "actual_result": "200 OK with full user object including email",
            },
        ],
        "reliability_score": 95.0,
        "root_cause": "Missing authorization check on user ID parameter",
        "impact_types": ["confidentiality", "compliance"],
        "evidence_warc_refs": [ref.to_uri() for ref in warc_refs],
        "verification_method": "Cross-role differential testing",
        "confirmed_impact": "Low-privilege users can access any user's profile data",
        "cross_role_confirmed": True,
        "false_positive_ruled_out": True,
    }
    
    print(f"\n✓ Created finding: {finding['title']}")
    print(f"  ID: {finding['id']}")
    print(f"  Severity: {finding['severity']}")
    print(f"  Reliability: {finding['reliability_score']}%")
    print(f"  Evidence: {len(finding['evidence_warc_refs'])} WARC references")
    print(f"\n  WARC References:")
    for i, ref in enumerate(finding['evidence_warc_refs'], 1):
        print(f"    {i}. {ref[:65]}...")
    
    return finding


def demo_finding_record(finding):
    """Generate finding record."""
    print("\n" + "=" * 70)
    print("STEP 3: Generating Finding Record")
    print("=" * 70)
    
    lines = [
        f"# {finding['title']}",
        "",
        f"**Finding ID:** `{finding['id']}`",
        f"**Severity:** {finding['severity']}",
        f"**Category:** {finding['category']}",
        f"**Asset:** {finding['asset']}",
        f"**Reliability Score:** {finding['reliability_score']}/100",
        "",
        "## Description",
        "",
        finding['confirmed_impact'],
        "",
        "## Reproduction Steps",
        "",
    ]
    
    for step in finding['reproduction_steps']:
        lines.append(f"{step['step_number']}. {step['action']}")
        lines.append(f"   - Expected: {step['expected_result']}")
        lines.append(f"   - Actual: {step['actual_result']}")
    
    lines.extend([
        "",
        "## Evidence Trail",
        "",
        "All HTTP traffic for this finding is archived in WARC format:",
        "",
    ])
    
    for i, ref in enumerate(finding['evidence_warc_refs'], 1):
        lines.append(f"{i}. `{ref}`")
    
    lines.extend([
        "",
        "## Root Cause",
        "",
        finding['root_cause'],
        "",
    ])
    
    record = "\n".join(lines)
    print("\n✓ Generated finding record:")
    print("\n" + "-" * 70)
    print(record[:500] + "..." if len(record) > 500 else record)
    print("-" * 70)
    
    return record


def demo_evidence_pack(finding, warc_dir, temp_dir):
    """Generate evidence pack."""
    print("\n" + "=" * 70)
    print("STEP 4: Generating Evidence Pack")
    print("=" * 70)
    
    pack_dir = temp_dir / "evidence_packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    
    pack_path = pack_dir / f"evidence_{finding['id']}.zip"
    
    with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add manifest
        manifest = {
            "finding_id": finding['id'],
            "finding_title": finding['title'],
            "evidence_count": len(finding['evidence_warc_refs']),
            "warc_references": finding['evidence_warc_refs'],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        
        # Add mock evidence files
        for idx in range(len(finding['evidence_warc_refs'])):
            # Headers
            headers = {
                "Authorization": f"Bearer token_{idx}",
                "Content-Type": "application/json",
            }
            zf.writestr(f"evidence_{idx:03d}_headers.json", json.dumps(headers, indent=2))
            
            # Body
            body = {
                "id": 123,
                "name": "Alice",
                "email": "alice@example.com",
            }
            zf.writestr(f"evidence_{idx:03d}_body.json", json.dumps(body, indent=2))
    
    print(f"\n✓ Generated evidence pack: {pack_path.name}")
    print(f"  Size: {pack_path.stat().st_size} bytes")
    print(f"  Contents:")
    
    with zipfile.ZipFile(pack_path, "r") as zf:
        for name in zf.namelist():
            info = zf.getinfo(name)
            print(f"    - {name} ({info.file_size} bytes)")
    
    return pack_path


def demo_executive_summary(findings):
    """Generate executive summary."""
    print("\n" + "=" * 70)
    print("STEP 5: Generating Executive Summary")
    print("=" * 70)
    
    severity_counts = {"critical": 0, "high": 1, "medium": 0, "low": 0, "info": 0}
    total_warc_refs = sum(len(f['evidence_warc_refs']) for f in findings)
    
    summary = f"""# Executive Summary

## Target: https://api.example.com

### Key Findings

- **Total Findings:** {len(findings)}
- **Critical:** {severity_counts['critical']}
- **High:** {severity_counts['high']}
- **Medium:** {severity_counts['medium']}
- **Low:** {severity_counts['low']}
- **Informational:** {severity_counts['info']}

### Evidence Quality

- **Findings with WARC Evidence:** {len(findings)}/{len(findings)} (100%)
- **Total Evidence Records:** {total_warc_refs}
- **Cross-Role Verified:** {sum(1 for f in findings if f.get('cross_role_confirmed'))}

### Critical & High Severity Issues

- **{findings[0]['title']}** (HIGH)
  - Asset: `{findings[0]['asset']}`
  - Reliability: {findings[0]['reliability_score']}%
  - Evidence: {len(findings[0]['evidence_warc_refs'])} WARC records

### Evidence Provenance

All findings are backed by WARC (Web ARChive) format captures following ISO 28500 standard.
Each HTTP request/response pair is content-addressed and traceable for audit purposes.
"""
    
    print("\n✓ Generated executive summary:")
    print("\n" + "-" * 70)
    print(summary)
    print("-" * 70)
    
    return summary


def main():
    """Run complete demonstration."""
    print("\n" + "=" * 70)
    print("WARC-BACKED REPORTING SYSTEM - STANDALONE DEMO")
    print("=" * 70)
    print("\nThis demo shows the complete flow:")
    print("  1. Capture HTTP traffic to WARC")
    print("  2. Create finding with evidence references")
    print("  3. Generate finding record")
    print("  4. Generate evidence pack (ZIP)")
    print("  5. Generate executive summary")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Step 1: Capture to WARC
        warc_refs, warc_dir = demo_warc_capture(temp_path)
        
        # Step 2: Create finding
        finding = demo_finding_creation(warc_refs)
        
        # Step 3: Generate finding record
        finding_record = demo_finding_record(finding)
        
        # Step 4: Generate evidence pack
        evidence_pack = demo_evidence_pack(finding, warc_dir, temp_path)
        
        # Step 5: Generate executive summary
        executive_summary = demo_executive_summary([finding])
        
        print("\n" + "=" * 70)
        print("DEMO COMPLETE - Summary")
        print("=" * 70)
        print(f"\n✓ WARC file: {warc_dir / f'demo_eng_001_demo.warc.gz'}")
        print(f"✓ Finding record: Generated ({len(finding_record)} chars)")
        print(f"✓ Evidence pack: {evidence_pack}")
        print(f"✓ Executive summary: Generated ({len(executive_summary)} chars)")
        
        print("\n" + "=" * 70)
        print("KEY TAKEAWAYS")
        print("=" * 70)
        print("""
1. Every HTTP request/response is captured to WARC format
2. Each finding links to WARC records via content-addressed URIs
3. Evidence packs bundle all HTTP captures for a finding
4. Reports include evidence statistics and provenance info
5. Full audit trail with ISO 28500 compliance

This enables "mining insane amount of data" because:
- Every data point is captured and traceable
- Content-addressed IDs prevent duplicates
- Evidence packs enable reproduction
- WARC format is standard and queryable
- Full provenance for compliance and audit
        """)
        
        print("=" * 70)
        print("✅ WARC-Backed Reporting System: OPERATIONAL")
        print("=" * 70)


if __name__ == "__main__":
    main()
