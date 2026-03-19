"""
WARC Evidence API - Flask service for WARC archive management.
Provides REST API and web UI for browsing archives and generating evidence packs.

Port: 5006
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, render_template_string, send_file
from flask_cors import CORS
from loguru import logger

from cyberAI.storage.warc_writer import WARCWriter, WARCReference
from cyberAI.storage.warc_writer_batched import BatchedWARCWriter
from cyberAI.storage.evidence_store import EvidenceStore
from cyberAI.storage.database import Database, Finding, Severity, FindingStatus

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
WARC_BASE_DIR = Path(os.getenv("WARC_BASE_DIR", "outputs/warc"))
DB_PATH = Path(os.getenv("DB_PATH", "outputs/asrts.db"))

# Initialize components
WARC_BASE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

evidence_store = EvidenceStore(WARC_BASE_DIR)
db = Database(str(DB_PATH))

logger.info(f"WARC API initialized - base_dir: {WARC_BASE_DIR}, db: {DB_PATH}")


@app.route("/")
def index():
    """Web UI for WARC browser."""
    return render_template_string(INDEX_HTML)


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "WARC Evidence API",
        "port": 5006,
        "warc_base_dir": str(WARC_BASE_DIR),
        "db_path": str(DB_PATH),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


@app.route("/api/engagements", methods=["GET"])
def list_engagements():
    """List all engagements with WARC archives."""
    try:
        engagements = []
        if WARC_BASE_DIR.exists():
            for eng_dir in WARC_BASE_DIR.iterdir():
                if eng_dir.is_dir():
                    warc_files = list(eng_dir.glob("*.warc.gz"))
                    stats = db.get_stats(eng_dir.name) if db else {}
                    
                    engagements.append({
                        "engagement_id": eng_dir.name,
                        "warc_files": len(warc_files),
                        "total_size_mb": sum(f.stat().st_size for f in warc_files) / (1024 * 1024),
                        "stats": stats
                    })
        
        return jsonify({"engagements": engagements})
    except Exception as e:
        logger.error(f"Failed to list engagements: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/write", methods=["POST"])
def write_warc_record():
    """
    Write a new WARC record.
    
    Request body:
    {
        "engagement_id": "eng_123",
        "method": "GET",
        "url": "https://example.com/api/users",
        "request_headers": {"Authorization": "Bearer ..."},
        "request_body": "",
        "status_code": 200,
        "reason": "OK",
        "response_headers": {"Content-Type": "application/json"},
        "response_body": "{...}"
    }
    """
    try:
        data = request.json
        engagement_id = data.get("engagement_id")
        
        if not engagement_id:
            return jsonify({"error": "engagement_id required"}), 400
        
        # Create WARC writer
        writer = WARCWriter(base_dir=WARC_BASE_DIR, engagement_id=engagement_id)
        
        # Write record
        ref = writer.write_request_response(
            method=data.get("method", "GET"),
            url=data["url"],
            request_headers=data.get("request_headers", {}),
            request_body=data.get("request_body", "").encode() if isinstance(data.get("request_body"), str) else data.get("request_body", b""),
            status_code=data.get("status_code", 200),
            reason=data.get("reason", "OK"),
            response_headers=data.get("response_headers", {}),
            response_body=data.get("response_body", "").encode() if isinstance(data.get("response_body"), str) else data.get("response_body", b"")
        )
        
        writer.close()
        
        return jsonify({
            "success": True,
            "warc_ref": ref.to_dict()
        })
    except Exception as e:
        logger.error(f"Failed to write WARC record: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/read", methods=["POST"])
def read_warc_record():
    """
    Read a WARC record by reference.
    
    Request body:
    {
        "warc_id": "abc123...",
        "file_path": "eng_123/eng_123_20240101_000.warc.gz",
        "offset": 1234,
        "length": 5678,
        "engagement_id": "eng_123",
        "timestamp": "2024-01-01T00:00:00Z"
    }
    """
    try:
        data = request.json
        
        # Reconstruct WARCReference
        ref = WARCReference(
            warc_id=data["warc_id"],
            file_path=data["file_path"],
            offset=data["offset"],
            length=data["length"],
            engagement_id=data["engagement_id"],
            timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        )
        
        # Read record
        record_bytes = evidence_store.read_warc_record(ref)
        headers, body = evidence_store.extract_http_from_warc(record_bytes)
        
        return jsonify({
            "success": True,
            "warc_id": ref.warc_id,
            "headers": headers,
            "body_size": len(body),
            "body_preview": body[:500].decode("utf-8", errors="replace") if body else "",
            "uri": ref.to_uri()
        })
    except Exception as e:
        logger.error(f"Failed to read WARC record: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/evidence-pack", methods=["POST"])
def generate_evidence_pack():
    """
    Generate evidence pack for a finding.
    
    Request body:
    {
        "finding_id": "find_123",
        "warc_refs": [...],
        "include_screenshots": false,
        "screenshot_paths": []
    }
    """
    try:
        data = request.json
        finding_id = data.get("finding_id")
        
        if not finding_id:
            return jsonify({"error": "finding_id required"}), 400
        
        # Reconstruct WARC references
        warc_refs = []
        for ref_data in data.get("warc_refs", []):
            ref = WARCReference(
                warc_id=ref_data["warc_id"],
                file_path=ref_data["file_path"],
                offset=ref_data["offset"],
                length=ref_data["length"],
                engagement_id=ref_data["engagement_id"],
                timestamp=datetime.fromisoformat(ref_data["timestamp"].replace("Z", "+00:00"))
            )
            warc_refs.append(ref)
        
        # Generate pack
        output_dir = WARC_BASE_DIR / "evidence_packs"
        pack_path = evidence_store.generate_evidence_pack(
            finding_id=finding_id,
            warc_refs=warc_refs,
            output_dir=output_dir,
            include_screenshots=data.get("include_screenshots", False),
            screenshot_paths=data.get("screenshot_paths", [])
        )
        
        return send_file(pack_path, as_attachment=True, download_name=pack_path.name)
    except Exception as e:
        logger.error(f"Failed to generate evidence pack: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/findings", methods=["GET"])
def list_findings():
    """List all findings with evidence links."""
    try:
        engagement_id = request.args.get("engagement_id")
        
        if not engagement_id:
            return jsonify({"error": "engagement_id required"}), 400
        
        findings = db.get_findings_by_engagement(engagement_id)
        
        return jsonify({
            "findings": [f.to_dict() for f in findings]
        })
    except Exception as e:
        logger.error(f"Failed to list findings: {e}")
        return jsonify({"error": str(e)}), 500
