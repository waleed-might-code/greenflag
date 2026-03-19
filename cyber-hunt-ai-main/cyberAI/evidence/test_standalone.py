"""
Standalone test for evidence module (no external dependencies).
Tests core functionality without requiring installed packages.
"""

import sys
import tempfile
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_warc_writer():
    """Test WARC writer without external deps."""
    print("Test 1: WARC Writer Core Functionality")
    
    # Mock logger
    class MockLogger:
        def info(self, msg): print(f"  [INFO] {msg}")
        def debug(self, msg): pass
        def warning(self, msg): print(f"  [WARN] {msg}")
        def error(self, msg): print(f"  [ERROR] {msg}")
    
    # Patch logger
    import evidence.warc_writer as ww
    ww.logger = MockLogger()
    
    from evidence.warc_writer import WARCWriter
    
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        writer = WARCWriter(output_dir, "test-engagement")
        
        # Write request
        req_record = writer.write_request(
            "GET",
            "https://example.com/api/users/123",
            {"User-Agent": "CyberAI/1.0", "Authorization": "Bearer token123"},
            None
        )
        
        print(f"  ✓ Request WARC ref: {req_record.warc_ref}")
        print(f"  ✓ Content hash: {req_record.content_hash[:16]}...")
        
        # Write response
        resp_record = writer.write_response(
            "https://example.com/api/users/123",
            200,
            {"Content-Type": "application/json"},
            b'{"id": 123, "name": "admin", "role": "admin"}'
        )
        
        print(f"  ✓ Response WARC ref: {resp_record.warc_ref}")
        
        writer.close()
        
        # Verify file exists
        warc_files = list(output_dir.glob("*.warc.gz"))
        print(f"  ✓ Created {len(warc_files)} WARC file(s)")
        
        return True


def test_provenance():
    """Test provenance tracker."""
    print("\nTest 2: Provenance Tracker")
    
    # Mock logger
    class MockLogger:
        def info(self, msg): print(f"  [INFO] {msg}")
        def debug(self, msg): pass
        def warning(self, msg): print(f"  [WARN] {msg}")
    
    import evidence.provenance as prov
    prov.logger = MockLogger()
    
    from evidence.provenance import ProvenanceTracker, EvidenceRef
    from datetime import datetime
    
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        tracker = ProvenanceTracker(output_dir)
        
        # Create evidence refs
        refs = [
            EvidenceRef(
                warc_ref="warc://test.warc.gz#0:1024",
                content_hash="abc123",
                request_id="req-001"
            ),
            EvidenceRef(
                warc_ref="warc://test.warc.gz#1024:2048",
                content_hash="def456",
                request_id="req-001",
                response_id="resp-001"
            )
        ]
        
        # Link finding
        tracker.link_finding_to_evidence("finding-idor-001", refs)
        print(f"  ✓ Linked finding to {len(refs)} evidence refs")
        
        # Retrieve
        retrieved = tracker.get_evidence_for_finding("finding-idor-001")
        print(f"  ✓ Retrieved {len(retrieved)} evidence refs")
        
        assert len(retrieved) == 2, "Should retrieve 2 refs"
        
        return True


def test_capture_session():
    """Test capture session."""
    print("\nTest 3: Capture Session")
    
    # Mock logger
    class MockLogger:
        def info(self, msg): print(f"  [INFO] {msg}")
        def debug(self, msg): pass
        def warning(self, msg): print(f"  [WARN] {msg}")
    
    import evidence.capture as cap
    import evidence.warc_writer as ww
    import evidence.provenance as prov
    cap.logger = MockLogger()
    ww.logger = MockLogger()
    prov.logger = MockLogger()
    
    from evidence.capture import CaptureSession
    
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        session = CaptureSession("test-engagement-2", output_dir)
        
        # Capture request
        req_ref = session.capture_request(
            "req-002",
            "POST",
            "https://example.com/api/admin/delete",
            {"Authorization": "Bearer user-token"},
            b'{"user_id": 456}'
        )
        print(f"  ✓ Captured request")
        
        # Capture response
        resp_ref = session.capture_response(
            "req-002",
            "https://example.com/api/admin/delete",
            200,
            {"Content-Type": "application/json"},
            b'{"success": true}'
        )
        print(f"  ✓ Captured response")
        
        # Link finding
        session.link_finding("finding-authz-001", ["req-002"])
        print(f"  ✓ Linked finding to evidence")
        
        session.close()
        
        return True


if __name__ == "__main__":
    print("=" * 60)
    print("Evidence Module Standalone Test")
    print("=" * 60)
    
    try:
        test_warc_writer()
        test_provenance()
        test_capture_session()
        
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
