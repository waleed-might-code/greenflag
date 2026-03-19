"""
Integration with security test workers.
Provides insertion points and replay capabilities to test workers.
"""

import asyncio
from typing import Any, Callable, Optional
from dataclasses import dataclass

from loguru import logger

from .canonicalizer import RequestCanonicalizer
from .extractor import InsertionPointExtractor
from .payload_encoder import PayloadGenerator
from .replay_engine import ReplayEngine, ReplayRequest, ReplayResult


@dataclass
class TestJob:
    """Represents a test job for a worker."""
    job_id: str
    canonical_request: Any
    insertion_points: list[Any]
    priority: float
    test_type: str  # "authz", "injection", "fuzzing", etc.


class TestWorkerIntegration:
    """
    Integrates insertion point extraction with security test workers.
    Provides a queue of test jobs and handles replay execution.
    """
    
    def __init__(self, max_depth: int = 3):
        """
        Initialize test worker integration.
        
        Args:
            max_depth: Maximum encoding depth for extraction
        """
        self.canonicalizer = RequestCanonicalizer()
        self.extractor = InsertionPointExtractor(enable_nested_encoding=True)
        self.payload_generator = PayloadGenerator()
        self.replay_engine = ReplayEngine()
        
        self.test_queue: list[TestJob] = []
        self.completed_tests = 0
        self.failed_tests = 0
    
    def process_captured_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: Optional[str | bytes] = None,
        priority_boost: float = 0.0,
    ) -> TestJob:
        """
        Process a captured request and create test jobs.
        
        Args:
            method: HTTP method
            url: Request URL
            headers: Request headers
            body: Request body
            priority_boost: Additional priority for this request
        
        Returns:
            TestJob ready for workers
        """
        # Canonicalize the request
        canonical = self.canonicalizer.canonicalize(method, url, headers, body)
        
        # Extract insertion points
        insertion_points = self.extractor.extract_from_request(method, url, headers, body)
        
        # Calculate priority based on novelty and insertion point count
        novelty_score = 1.0 if not self.canonicalizer.is_duplicate(canonical) else 0.3
        insertion_score = min(len(insertion_points) / 10.0, 1.0)
        priority = (novelty_score * 0.6 + insertion_score * 0.4 + priority_boost)
        
        # Create test job
        job = TestJob(
            job_id=canonical.request_id,
            canonical_request=canonical,
            insertion_points=insertion_points,
            priority=priority,
            test_type="comprehensive",
        )
        
        self.test_queue.append(job)
        self.test_queue.sort(key=lambda j: j.priority, reverse=True)
        
        logger.info(
            f"Created test job {job.job_id}: "
            f"{len(insertion_points)} insertion points, "
            f"priority={priority:.2f}"
        )
        
        return job
    
    def get_next_test_job(self) -> Optional[TestJob]:
        """Get the next highest-priority test job."""
        if self.test_queue:
            return self.test_queue.pop(0)
        return None
    
    async def execute_test_job(
        self,
        job: TestJob,
        http_client: Callable,
        test_types: list[str] = None,
    ) -> list[ReplayResult]:
        """
        Execute a test job by replaying requests with test payloads.
        
        Args:
            job: Test job to execute
            http_client: Async HTTP client function (method, url, headers, body) -> response
            test_types: Types of tests to run (default: all)
        
        Returns:
            List of replay results
        """
        if test_types is None:
            test_types = ["injection", "boundary", "authz"]
        
        results = []
        
        for insertion_point in job.insertion_points:
            # Skip CSRF tokens (they need special handling)
            if insertion_point.is_csrf_token:
                logger.debug(f"Skipping CSRF token: {insertion_point.location}")
                continue
            
            # Generate test payloads
            test_suite = self.payload_generator.generate_test_suite(
                insertion_point.location,
                insertion_point.encoding_layers,
                insertion_point.inferred_type,
            )
            
            # Execute each test
            for test_name, encoded_payload in test_suite:
                try:
                    # Build replay request
                    replay_req = self.replay_engine.build_replay_request(
                        job.canonical_request,
                        insertion_point,
                        encoded_payload,
                        test_name,
                    )
                    
                    # Execute the request
                    start_time = asyncio.get_event_loop().time()
                    response = await http_client(
                        replay_req.method,
                        replay_req.url,
                        replay_req.headers,
                        replay_req.body,
                    )
                    end_time = asyncio.get_event_loop().time()
                    
                    # Record result
                    result = ReplayResult(
                        request=replay_req,
                        success=True,
                        status_code=response.get("status_code"),
                        response_body=response.get("body"),
                        response_time_ms=(end_time - start_time) * 1000,
                    )
                    results.append(result)
                    self.completed_tests += 1
                    
                except Exception as e:
                    logger.error(f"Test failed: {test_name} on {insertion_point.location}: {e}")
                    result = ReplayResult(
                        request=replay_req,
                        success=False,
                        error=str(e),
                    )
                    results.append(result)
                    self.failed_tests += 1
        
        logger.info(
            f"Completed test job {job.job_id}: "
            f"{len(results)} tests executed"
        )
        
        return results
    
    def analyze_results(self, results: list[ReplayResult]) -> dict[str, Any]:
        """
        Analyze test results for security findings.
        
        Args:
            results: List of replay results
        
        Returns:
            Analysis with potential findings
        """
        findings = []
        
        for result in results:
            if not result.success:
                continue
            
            # Check for interesting responses
            if result.status_code == 200:
                # Successful injection might indicate vulnerability
                if "injection" in result.request.test_name:
                    findings.append({
                        "severity": "high",
                        "type": "injection",
                        "location": result.request.insertion_point.location,
                        "test_name": result.request.test_name,
                        "status_code": result.status_code,
                    })
            
            elif result.status_code == 500:
                # Server error might indicate successful attack
                findings.append({
                    "severity": "medium",
                    "type": "error_induced",
                    "location": result.request.insertion_point.location,
                    "test_name": result.request.test_name,
                    "status_code": result.status_code,
                })
        
        return {
            "total_tests": len(results),
            "successful_tests": sum(1 for r in results if r.success),
            "findings": findings,
            "avg_response_time_ms": sum(
                r.response_time_ms for r in results if r.response_time_ms
            ) / len(results) if results else 0,
        }
    
    def get_stats(self) -> dict[str, Any]:
        """Get integration statistics."""
        return {
            "test_queue_size": len(self.test_queue),
            "completed_tests": self.completed_tests,
            "failed_tests": self.failed_tests,
            "canonicalizer_stats": self.canonicalizer.get_stats(),
            "extractor_stats": self.extractor.get_novelty_stats(),
            "payload_generator_stats": self.payload_generator.get_stats(),
            "replay_engine_stats": self.replay_engine.get_stats(),
        }
