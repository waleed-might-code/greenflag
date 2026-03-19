"""
Differential authorization testing engine.
Replays requests with different roles to detect BOLA/IDOR vulnerabilities.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import httpx
from loguru import logger

from ..identity.multi_role_manager import MultiRoleSessionManager, SessionState


@dataclass
class AuthzTestResult:
    """Result of an authorization test."""
    endpoint: str
    method: str
    url: str
    test_role: str
    baseline_role: str
    
    # Response data
    test_status: int
    baseline_status: int
    test_body_hash: str
    baseline_body_hash: str
    test_body_length: int
    baseline_body_length: int
    
    # Analysis
    is_vulnerable: bool
    vulnerability_type: str  # "BOLA", "IDOR", "privilege_escalation", "none"
    confidence: float  # 0.0 to 1.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "endpoint": self.endpoint,
            "method": self.method,
            "url": self.url,
            "test_role": self.test_role,
            "baseline_role": self.baseline_role,
            "test_status": self.test_status,
            "baseline_status": self.baseline_status,
            "test_body_hash": self.test_body_hash,
            "baseline_body_hash": self.baseline_body_hash,
            "test_body_length": self.test_body_length,
            "baseline_body_length": self.baseline_body_length,
            "is_vulnerable": self.is_vulnerable,
            "vulnerability_type": self.vulnerability_type,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
        }


class DifferentialAuthzTester:
    """
    Tests authorization by comparing responses across different roles.
    Detects BOLA, IDOR, and privilege escalation vulnerabilities.
    """
    
    def __init__(
        self,
        session_manager: MultiRoleSessionManager,
        output_dir: Path,
        timeout: int = 30,
    ):
        """
        Initialize differential tester.
        
        Args:
            session_manager: Multi-role session manager
            output_dir: Output directory for results
            timeout: Request timeout in seconds
        """
        self.session_manager = session_manager
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.timeout = timeout
        
        # Results storage
        self.results: List[AuthzTestResult] = []
        
        # Stats
        self.stats = {
            "tests_run": 0,
            "vulnerabilities_found": 0,
            "bola_found": 0,
            "idor_found": 0,
            "privilege_escalation_found": 0,
            "errors": 0,
        }
        
        logger.info("Differential authorization tester initialized")
    
    async def test_endpoint(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
        baseline_role: str = "admin",
    ) -> List[AuthzTestResult]:
        """
        Test an endpoint with all available roles.
        
        Args:
            method: HTTP method
            url: Target URL
            headers: Optional headers
            body: Optional request body
            baseline_role: Role to use as baseline (usually admin)
        
        Returns:
            List of test results
        """
        endpoint = f"{method} {url}"
        logger.debug(f"Testing endpoint: {endpoint}")
        
        # Get baseline response
        baseline_session = await self.session_manager.get_session(baseline_role)
        if not baseline_session:
            logger.warning(f"No session for baseline role: {baseline_role}")
            return []
        
        baseline_response = await self._make_request(
            method=method,
            url=url,
            session=baseline_session,
            headers=headers,
            body=body,
        )
        
        if not baseline_response:
            logger.warning(f"Failed to get baseline response for {endpoint}")
            return []
        
        # Test with other roles
        results = []
        roles = self.session_manager.get_all_roles()
        
        for role in roles:
            if role == baseline_role:
                continue
            
            try:
                result = await self._test_role(
                    method=method,
                    url=url,
                    headers=headers,
                    body=body,
                    test_role=role,
                    baseline_role=baseline_role,
                    baseline_response=baseline_response,
                )
                
                if result:
                    results.append(result)
                    self.results.append(result)
                    
                    if result.is_vulnerable:
                        self.stats["vulnerabilities_found"] += 1
                        
                        if result.vulnerability_type == "BOLA":
                            self.stats["bola_found"] += 1
                        elif result.vulnerability_type == "IDOR":
                            self.stats["idor_found"] += 1
                        elif result.vulnerability_type == "privilege_escalation":
                            self.stats["privilege_escalation_found"] += 1
                
                self.stats["tests_run"] += 1
            
            except Exception as e:
                logger.error(f"Error testing {endpoint} with role {role}: {e}")
                self.stats["errors"] += 1
        
        return results
    
    async def _test_role(
        self,
        method: str,
        url: str,
        test_role: str,
        baseline_role: str,
        baseline_response: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
    ) -> Optional[AuthzTestResult]:
        """Test endpoint with a specific role."""
        # Get session for test role
        test_session = await self.session_manager.get_session(test_role)
        if not test_session:
            logger.warning(f"No session for test role: {test_role}")
            return None
        
        # Make request
        test_response = await self._make_request(
            method=method,
            url=url,
            session=test_session,
            headers=headers,
            body=body,
        )
        
        if not test_response:
            return None
        
        # Analyze responses
        return self._analyze_responses(
            method=method,
            url=url,
            test_role=test_role,
            baseline_role=baseline_role,
            test_response=test_response,
            baseline_response=baseline_response,
        )
    
    async def _make_request(
        self,
        method: str,
        url: str,
        session: SessionState,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make HTTP request with session."""
        try:
            # Merge headers
            req_headers = {**session.headers}
            if headers:
                req_headers.update(headers)
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=req_headers,
                    cookies=session.cookies,
                    content=body,
                    follow_redirects=False,
                )
                
                return {
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.content,
                    "text": response.text,
                }
        
        except Exception as e:
            logger.debug(f"Request failed: {e}")
            return None
    
    def _analyze_responses(
        self,
        method: str,
        url: str,
        test_role: str,
        baseline_role: str,
        test_response: Dict[str, Any],
        baseline_response: Dict[str, Any],
    ) -> AuthzTestResult:
        """
        Analyze responses to detect authorization vulnerabilities.
        
        Detection logic:
        - BOLA: Lower-privilege role gets 200 when accessing resource-specific endpoint
        - IDOR: Response body is similar between roles (same data leaked)
        - Privilege escalation: Lower role gets same/similar response as higher role
        """
        endpoint = f"{method} {url}"
        
        test_status = test_response["status"]
        baseline_status = baseline_response["status"]
        
        test_body = test_response["body"]
        baseline_body = baseline_response["body"]
        
        test_body_hash = hashlib.sha256(test_body).hexdigest()
        baseline_body_hash = hashlib.sha256(baseline_body).hexdigest()
        
        # Analyze vulnerability
        is_vulnerable = False
        vulnerability_type = "none"
        confidence = 0.0
        evidence = {}
        
        # Case 1: Test role gets 200 when baseline gets 200 (potential BOLA/IDOR)
        if test_status == 200 and baseline_status == 200:
            # Check body similarity
            similarity = self._compute_similarity(test_body, baseline_body)
            
            if similarity > 0.8:
                # Very similar responses - likely IDOR
                is_vulnerable = True
                vulnerability_type = "IDOR"
                confidence = similarity
                evidence = {
                    "similarity": similarity,
                    "reason": "Lower-privilege role received similar data as higher-privilege role",
                }
            
            elif similarity > 0.5:
                # Somewhat similar - possible BOLA
                is_vulnerable = True
                vulnerability_type = "BOLA"
                confidence = similarity * 0.8
                evidence = {
                    "similarity": similarity,
                    "reason": "Lower-privilege role accessed resource without proper authorization check",
                }
        
        # Case 2: Test role gets 200 when baseline gets 403/401 (clear privilege escalation)
        elif test_status == 200 and baseline_status in (401, 403):
            is_vulnerable = True
            vulnerability_type = "privilege_escalation"
            confidence = 0.95
            evidence = {
                "reason": "Lower-privilege role bypassed authorization check",
                "baseline_denied": True,
            }
        
        # Case 3: Both get 200 but test role shouldn't have access (check URL patterns)
        elif test_status == 200 and self._is_privileged_endpoint(url):
            is_vulnerable = True
            vulnerability_type = "privilege_escalation"
            confidence = 0.7
            evidence = {
                "reason": "Lower-privilege role accessed privileged endpoint",
                "endpoint_pattern": "admin/privileged",
            }
        
        return AuthzTestResult(
            endpoint=endpoint,
            method=method,
            url=url,
            test_role=test_role,
            baseline_role=baseline_role,
            test_status=test_status,
            baseline_status=baseline_status,
            test_body_hash=test_body_hash,
            baseline_body_hash=baseline_body_hash,
            test_body_length=len(test_body),
            baseline_body_length=len(baseline_body),
            is_vulnerable=is_vulnerable,
            vulnerability_type=vulnerability_type,
            confidence=confidence,
            evidence=evidence,
        )
    
    def _compute_similarity(self, body1: bytes, body2: bytes) -> float:
        """
        Compute similarity between two response bodies.
        Uses simple length ratio and hash comparison.
        """
        if body1 == body2:
            return 1.0
        
        len1 = len(body1)
        len2 = len(body2)
        
        if len1 == 0 or len2 == 0:
            return 0.0
        
        # Length similarity
        length_ratio = min(len1, len2) / max(len1, len2)
        
        # Try JSON comparison if both are JSON
        try:
            json1 = json.loads(body1.decode("utf-8", errors="ignore"))
            json2 = json.loads(body2.decode("utf-8", errors="ignore"))
            
            # Compare keys
            if isinstance(json1, dict) and isinstance(json2, dict):
                keys1 = set(json1.keys())
                keys2 = set(json2.keys())
                
                if keys1 and keys2:
                    key_similarity = len(keys1 & keys2) / len(keys1 | keys2)
                    return (length_ratio + key_similarity) / 2
        
        except Exception:
            pass
        
        # Fallback to length ratio
        return length_ratio
    
    def _is_privileged_endpoint(self, url: str) -> bool:
        """Check if URL looks like a privileged endpoint."""
        privileged_patterns = [
            "/admin", "/dashboard", "/manage", "/console",
            "/settings", "/config", "/users", "/roles"
        ]
        
        url_lower = url.lower()
        return any(pattern in url_lower for pattern in privileged_patterns)
    
    async def test_batch(
        self,
        requests: List[Dict[str, Any]],
        baseline_role: str = "admin",
    ) -> List[AuthzTestResult]:
        """
        Test a batch of requests.
        
        Args:
            requests: List of request dicts with method, url, headers, body
            baseline_role: Baseline role
        
        Returns:
            List of all test results
        """
        logger.info(f"Testing batch of {len(requests)} requests")
        
        all_results = []
        
        for req in requests:
            try:
                results = await self.test_endpoint(
                    method=req.get("method", "GET"),
                    url=req["url"],
                    headers=req.get("headers"),
                    body=req.get("body"),
                    baseline_role=baseline_role,
                )
                
                all_results.extend(results)
            
            except Exception as e:
                logger.error(f"Error testing request {req.get('url')}: {e}")
                self.stats["errors"] += 1
        
        return all_results
    
    def save_results(self, filename: str = "authz_test_results.json"):
        """Save test results to file."""
        output_file = self.output_dir / filename
        
        with open(output_file, "w") as f:
            json.dump([r.to_dict() for r in self.results], f, indent=2)
        
        logger.info(f"Saved {len(self.results)} test results to {output_file}")
    
    def get_vulnerabilities(self) -> List[AuthzTestResult]:
        """Get only vulnerable results."""
        return [r for r in self.results if r.is_vulnerable]
    
    def get_stats(self) -> dict:
        """Get testing statistics."""
        return self.stats
