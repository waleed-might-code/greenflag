"""
Quick test to verify WARC writer functionality.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cyberAI.storage import WARCWriter, WARCReference

def test_warc_writer():
    """Test basic WARC writing."""
    print("Testing WARC Writer...")
    
    writer = WARCWriter(
        base_dir="outputs/warc_test",
        engagement_id="test_001",
        max_file_size_mb=10,
        compress=True
    )
    
    # Write a simple request/response
    ref = writer.write_request_response(
        method="GET",
        url="https://example.com/api/test",
        request_headers={"User-Agent": "Test"},
        request_body=b"",
        status_code=200,
        response_headers={"Content-Type": "text/plain"},
        response_body=b"Hello World",
        reason="OK"
    )
    
    print(f"✓ WARC record written")
    print(f"  ID: {ref.warc_id[:16]}...")
    print(f"  URI: {ref.to_uri()}")
    print(f"  File: {ref.file_path}")
    
    writer.close()
    
    # Verify file exists
    warc_file = Path("outputs/warc_test") / ref.file_path
    if warc_file.exists():
        size = warc_file.stat().st_size
        print(f"✓ WARC file exists: {size} bytes")
        return True
    else:
        print(f"✗ WARC file not found: {warc_file}")
        return False

if __name__ == "__main__":
    success = test_warc_writer()
    sys.exit(0 if success else 1)
