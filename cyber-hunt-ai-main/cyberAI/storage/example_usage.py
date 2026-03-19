"""
Example usage of WARC writer for evidence storage.
Demonstrates how to integrate WARC archival into the testing pipeline.
"""

from pathlib import Path
from cyberAI.storage import WARCWriter, create_warc_writer


def example_basic_usage():
    """Basic WARC writing example."""
    # Create writer for an engagement
    writer = WARCWriter(
        base_dir="outputs/warc",
        engagement_id="eng_demo_001",
        max_file_size_mb=50,
        compress=True,
    )
    
    # Write a request/response pair
    ref = writer.write_request_response(
        method="GET",
        url="https://api.example.com/users/123",
        request_headers={
            "Authorization": "Bearer token123",
            "User-Agent": "CyberAI/1.0",
            "Accept": "application/json",
        },
        request_body=b"",
        status_code=200,
        response_headers={
            "Content-Type": "application/json",
            "X-Request-ID": "req-456",
        },
        response_body=b'{"id": 123, "email": "user@example.com", "role": "admin"}',
        reason="OK",
    )
    
    print(f"WARC Reference:")
    print(f"  ID: {ref.warc_id}")
    print(f"  URI: {ref.to_uri()}")
    print(f"  File: {ref.file_path}")
    print(f"  Offset: {ref.offset}, Length: {ref.length}")
    
    writer.close()
    return ref


def example_context_manager():
    """Using WARC writer as context manager."""
    with create_warc_writer("eng_demo_002") as writer:
        # Write multiple requests
        refs = []
        
        for i in range(5):
            ref = writer.write_request_response(
                method="POST",
                url=f"https://api.example.com/items/{i}",
                request_headers={"Content-Type": "application/json"},
                request_body=f'{{"name": "item_{i}"}}'.encode(),
                status_code=201,
                response_headers={"Content-Type": "application/json"},
                response_body=f'{{"id": {i}, "created": true}}'.encode(),
                reason="Created",
            )
            refs.append(ref)
        
        print(f"\nWrote {len(refs)} WARC records")
        for ref in refs:
            print(f"  - {ref.warc_id[:12]}... @ {ref.to_uri()}")


def example_finding_with_evidence():
    """Example: Link WARC refs to security findings."""
    from cyberAI.models import Finding, Severity, TestCategory, FindingStatus
    
    # Create WARC writer
    with create_warc_writer("eng_demo_003") as writer:
        # Simulate IDOR test: access user 123 as different roles
        
        # Request as admin (should succeed)
        admin_ref = writer.write_request_response(
            method="GET",
            url="https://api.example.com/users/123",
            request_headers={"Authorization": "Bearer admin_token"},
            request_body=b"",
            status_code=200,
            response_headers={"Content-Type": "application/json"},
            response_body=b'{"id": 123, "email": "victim@example.com", "ssn": "123-45-6789"}',
        )
        
        # Request as regular user (should fail but doesn't - IDOR!)
        user_ref = writer.write_request_response(
            method="GET",
            url="https://api.example.com/users/123",
            request_headers={"Authorization": "Bearer user_token"},
            request_body=b"",
            status_code=200,  # Should be 403!
            response_headers={"Content-Type": "application/json"},
            response_body=b'{"id": 123, "email": "victim@example.com", "ssn": "123-45-6789"}',
        )
        
        # Create finding with WARC evidence
        finding = Finding(
            title="IDOR: Unauthorized Access to User Profile",
            description="Regular user can access other users' sensitive data including SSN",
            severity=Severity.HIGH,
            category=TestCategory.AUTHZ,
            asset="https://api.example.com/users/{id}",
            evidence={
                "admin_request": admin_ref.to_dict(),
                "user_request": user_ref.to_dict(),
                "comparison": "Both requests returned 200 with identical sensitive data",
            },
            evidence_warc_refs=[
                admin_ref.to_uri(),
                user_ref.to_uri(),
            ],
            reproduction_steps=[
                "1. Authenticate as regular user (user_token)",
                "2. Send GET /users/123 with user credentials",
                "3. Observe 200 response with victim's SSN",
                f"4. Evidence: {admin_ref.to_uri()}",
                f"5. Evidence: {user_ref.to_uri()}",
            ],
            status=FindingStatus.CONFIRMED,
            confidence=0.95,
        )
        
        print("\n=== Security Finding ===")
        print(f"Title: {finding.title}")
        print(f"Severity: {finding.severity.value.upper()}")
        print(f"Evidence WARC refs:")
        for ref_uri in finding.evidence_warc_refs:
            print(f"  - {ref_uri}")
        
        return finding


if __name__ == "__main__":
    print("=== Example 1: Basic Usage ===")
    example_basic_usage()
    
    print("\n=== Example 2: Context Manager ===")
    example_context_manager()
    
    print("\n=== Example 3: Finding with Evidence ===")
    example_finding_with_evidence()
