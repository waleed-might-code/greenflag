"""
Flask API for evidence management and retrieval.
Provides REST endpoints for querying evidence and generating packs.
"""

from flask import Flask, jsonify, request, send_file
from pathlib import Path
from datetime import datetime
import tempfile

from cyberAI.evidence import CaptureSession, ProvenanceTracker
from cyberAI.config import get_config

app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "CyberAI Evidence API",
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route('/api/evidence/findings/<finding_id>', methods=['GET'])
def get_finding_evidence(finding_id: str):
    """Get evidence references for a finding."""
    config = get_config()
    provenance_dir = config.get_output_path("evidence", "provenance")
    
    tracker = ProvenanceTracker(provenance_dir)
    evidence_refs = tracker.get_evidence_for_finding(finding_id)
    
    return jsonify({
        "finding_id": finding_id,
        "evidence_count": len(evidence_refs),
        "evidence_refs": [ref.to_dict() for ref in evidence_refs]
    })


@app.route('/api/evidence/pack/<finding_id>', methods=['GET'])
def generate_evidence_pack(finding_id: str):
    """Generate and download evidence pack for a finding."""
    config = get_config()
    provenance_dir = config.get_output_path("evidence", "provenance")
    warc_dir = config.get_output_path("evidence", "warc")
    
    tracker = ProvenanceTracker(provenance_dir)
    
    # Generate pack in temp file
    with tempfile.NamedTemporaryFile(suffix='.warc.gz', delete=False) as tmp:
        output_path = Path(tmp.name)
    
    tracker.generate_evidence_pack(finding_id, warc_dir, output_path)
    
    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"evidence_{finding_id}.warc.gz",
        mimetype="application/gzip"
    )



@app.route('/api/evidence/stats', methods=['GET'])
def get_evidence_stats():
    """Get statistics about captured evidence."""
    config = get_config()
    warc_dir = config.get_output_path("evidence", "warc")
    provenance_dir = config.get_output_path("evidence", "provenance")
    
    # Count WARC files
    warc_files = list(warc_dir.glob("*.warc.gz")) if warc_dir.exists() else []
    
    # Count findings with evidence
    findings_with_evidence = 0
    if (provenance_dir / "provenance_index.jsonl").exists():
        with open(provenance_dir / "provenance_index.jsonl", 'r') as f:
            findings_with_evidence = sum(1 for _ in f)
    
    # Calculate total size
    total_size = sum(f.stat().st_size for f in warc_files)
    
    return jsonify({
        "warc_files": len(warc_files),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "findings_with_evidence": findings_with_evidence,
        "warc_directory": str(warc_dir)
    })


@app.route('/api/evidence/engagements', methods=['GET'])
def list_engagements():
    """List all engagements with evidence."""
    config = get_config()
    warc_dir = config.get_output_path("evidence", "warc")
    
    if not warc_dir.exists():
        return jsonify({"engagements": []})
    
    # Extract engagement IDs from WARC filenames
    engagements = set()
    for warc_file in warc_dir.glob("*.warc.gz"):
        # Format: engagement-id_timestamp_hash.warc.gz
        engagement_id = warc_file.stem.split('_')[0]
        engagements.add(engagement_id)
    
    return jsonify({
        "engagements": sorted(list(engagements)),
        "count": len(engagements)
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5004, debug=True)
