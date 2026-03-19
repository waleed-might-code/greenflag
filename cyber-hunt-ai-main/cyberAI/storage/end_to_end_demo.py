"""
End-to-End Provenance Demo

Demonstrates the complete flow:
1. Capture HTTP traffic from a simulated security scan
2. Store in WARC with content-addressed IDs
3. Extract insertion points and run security tests
4. Generate findings with WARC evidence links
5. Generate evidence pack for audit/reporting

This proves that every finding is traceable to raw HTTP captures.
"""

import asyncio
import random
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from loguru import logger

from cyberAI.storage.provenance_pipeline import (
    ProvenancePipeline, CapturedRequest
)
from cyberAI.storage.evidence_store import EvidenceStore
from cyberAI.storage.database import Severity


class SecurityScanSimulator:
    """
    Simulates a realistic security scan with:
    - Multi-role crawling (guest, user, admin)
    - API endpoint discovery
    - Authorization testing (BOLA/IDOR detection)
    - Evidence capture for all findings
    """
    
    def __init__(self, engagement_id: str, base_dir: Path):
        self.engagement_id = engagement_id
        self.base_dir = base_dir
        self.pipeline = ProvenancePipeline(
            engagement_id=engagement_id,
            warc_base_dir=str(base_dir / "warc"),
            db_path=str(base_dir / "scan.db"),
            batch_size=50,
            enable_dedup=True,
        )
        self.evidence_store = EvidenceStore(warc_base_dir=base_dir / "warc")
    
    async def run_scan(self):
        """Run complete security scan."""
        logger.info("=" * 80)
        logger.info(f"SECURITY SCAN: {self.engagement_id}")
        logger.info("=" * 80)
        
        # Phase 1: Discovery
        logger.info("\n[Phase 1] Discovery - Crawling target application")
        endpoints = await self.discover_endpoints()
        logger.info(f"  Discovered {len(endpoints)} endpoints")
        
        # Phase 2: Multi-role testing
        logger.info("\n[Phase 2] Multi-Role Testing")
        test_results = await self.test_authorization(endpoints)
        logger.info(f"  Tested {len(test_results)} endpoint/role combinations")
        
        # Phase 3: Finding generation
        logger.info("\n[Phase 3] Finding Generation")
        findings = await self.generate_findings(test_results)
        logger.info(f"  Generated {len(findings)} security findings")
        
        # Phase 4: Evidence packaging
        logger.info("\n[Phase 4] Evidence Packaging")
        evidence_packs = await self.package_evidence(findings)
        logger.info(f"  Created {len(evidence_packs)} evidence packs")
        
        # Phase 5: Reporting
        logger.info("\n[Phase 5] Reporting")
        report = self.generate_report(findings)
        
        logger.info("\n" + "=" * 80)
        logger.info("SCAN COMPLETE")
        logger.info("=" * 80)
        
        return {
            "endpoints": len(endpoints),
            "findings": len(findings),
            "evidence_packs": evidence_packs,
            "report": report,
        }
    
    async def discover_endpoints(self) -> list[dict]:
        """Simulate endpoint discovery."""
        endpoints = [
            {"path": "/api/users", "method": "GET", "auth": "public"},
            {"path": "/api/users/{id}", "method": "GET", "auth": "authenticated"},
            {"path": "/api/users/{id}", "method": "PUT", "auth": "owner_or_admin"},
            {"path": "/api/users/{id}", "method": "DELETE", "auth": "admin"},
            {"path": "/api/admin/users", "method": "GET", "auth": "admin"},
            {"path": "/api/admin/settings", "method": "GET", "auth": "admin"},
            {"path": "/api/orders/{id}", "method": "GET", "auth": "owner_or_admin"},
            {"path": "/api/posts", "method": "POST", "auth": "authenticated"},
        ]
        
        # Capture discovery traffic
        for endpoint in endpoints:
            url = f"https://target.example.com{endpoint['path'].replace('{id}', '123')}"
            req = CapturedRequest(
                method=endpoint["method"],
                url=url,
                request_headers={"User-Agent": "CyberAI/1.0"},
                request_body=b"",
                status_code=200,
                reason="OK",
                response_headers={"Content-Type": "application/json"},
                response_body=b'{"status": "ok"}',
                role="guest",
                engagement_id=self.engagement_id,
            )
            self.pipeline.ingest_request(req)
        
        return endpoints
    
    async def test_authorization(self, endpoints: list[dict]) -> list[dict]:
        """Test each endpoint with different roles."""
        results = []
        roles = ["guest", "user", "admin"]
        
        for endpoint in endpoints:
            for role in roles:
                # Simulate request as this role
                url = f"https://target.example.com{endpoint['path'].replace('{id}', '123')}"
                
                # Determine expected behavior
                should_allow = self._should_allow(endpoint["auth"], role)
                actual_status = 200 if should_allow else 403
                
                # Capture request
                req = CapturedRequest(
                    method=endpoint["method"],
                    url=url,
                    request_headers={
                        "User-Agent": "CyberAI/1.0",
                        "Authorization": f"Bearer {role}_token",
                    },
                    request_body=b"",
                    status_code=actual_status,
                    reason="OK" if should_allow else "Forbidden",
                    response_headers={"Content-Type": "application/json"},
                    response_body=b'{"data": "sensitive"}' if should_allow else b'{"error": "forbidden"}',
                    role=role,
                    engagement_id=self.engagement_id,
                )
                
                request_id = self.pipeline.ingest_request(req)
                
                results.append({
                    "endpoint": endpoint,
                    "role": role,
                    "request_id": request_id,
                    "status": actual_status,
                    "should_allow": should_allow,
                })
        
        return results
    
    def _should_allow(self, required_auth: str, role: str) -> bool:
        """Determine if role should have access."""
        if required_auth == "public":
            return True
        if required_auth == "authenticated":
            return role in ["user", "admin"]
        if required_auth == "admin":
            return role == "admin"
        if required_auth == "owner_or_admin":
            return role in ["user", "admin"]  # Simplified
        return False
