"""
Integration guide for WARC-backed evidence capture during testing.
Shows how to instrument test workers to capture HTTP traffic.
"""

from pathlib import Path
from typing import Optional

from loguru import logger

from cyberAI.models import Finding, ImpactType, ReproductionStep, Severity, TestCategory
from cyberAI.storage import WARCReference, create_warc_writer


class TestWorkerWithEvidence:
    """
    Example test worker that captures HTTP evidence to WARC.
    
    This shows the pattern for integrating WARC capture into
    any testing module (auth_testing, authorization_testing, etc.)
    """
    
    def __init__(self, engagement_id: str, warc_base_dir: Optional[Path] = None):
        """
        Initialize test worker with WARC capture.
        
        Args:
            engagement_id: Unique engagement identifier
            warc_base_dir: Base directory for WARC storage
        """
        self.engagement_id = engagement_id
        self.warc_writer = create_warc_writer(
            engagement_id=engagement_id,
            base_dir=warc_base_dir,
        )
        self.evidence_refs: list[WARCReference] = []
    
    async def test_authorization_bypass(
        self,
        endpoint: str,
        low_priv_token: str,
        high_priv_token: str,
    ) -> Optional[Finding]:
        """
        Test for authorization bypass (BOLA/IDOR).
        Captures all HTTP traffic as evidence.
        
        Args:
            endpoint: Target endpoint (e.g., /api/users/123)
            low_priv_token: Low-privilege auth token
            high_priv_token: High-privilege auth token
            
        Returns:
            Finding if vulnerability detected, None otherwise
        """
        import httpx
        
        # Step 1: Request as high-privilege user (baseline)
        async with httpx.AsyncClient() as client:
            logger.info(f"Testing {endpoint} with high-priv token")
            
            response_high = await client.get(
                endpoint,
                headers={"Authorization": f"Bearer {high_priv_token}"},
            )
            
            # Capture to WARC
            warc_ref_high = self.warc_writer.write_request_response(
                method="GET",
                url=endpoint,
                request_headers={"Authorization": f"Bearer {high_priv_token}"},
                request_body=b"",
                status_code=response_high.status_code,
                reason=response_high.reason_phrase,
                response_headers=dict(response_high.headers),
                response_body=response_high.content,
            )
            self.evidence_refs.append(warc_ref_high)
            
            # Step 2: Request as low-privilege user
            logger.info(f"Testing {endpoint} with low-priv token")
            
            response_low = await client.get(
                endpoint,
                headers={"Authorization": f"Bearer {low_priv_token}"},
            )
            
            # Capture to WARC
            warc_ref_low = self.warc_writer.write_request_response(
                method="GET",
                url=endpoint,
                request_headers={"Authorization": f"Bearer {low_priv_token}"},
                request_body=b"",
                status_code=response_low.status_code,
                reason=response_low.reason_phrase,
                response_headers=dict(response_low.headers),
                response_body=response_low.content,
            )
            self.evidence_refs.append(warc_ref_low)
        
        # Step 3: Compare responses
        if response_low.status_code == 200 and response_high.status_code == 200:
            # Both succeeded - potential BOLA
            if len(response_low.content) > 0:
                logger.warning(f"Potential BOLA detected on {endpoint}")
                
                # Create finding with evidence
                finding = Finding(
                    title=f"Broken Object Level Authorization on {endpoint}",
                    severity=Severity.HIGH,
                    category=TestCategory.AUTHZ,
                    asset=endpoint,
                    affected_roles=["low_privilege_user"],
                    preconditions=[
                        "Valid authentication token",
                        "Knowledge of resource ID",
                    ],
                    reproduction_steps=[
                        ReproductionStep(
                            step_number=1,
                            action=f"Authenticate as low-privilege user",
                            expected_result="Receive auth token",
                            actual_result="Token received",
                        ),
                        ReproductionStep(
                            step_number=2,
                            action=f"Request GET {endpoint} with low-priv token",
                            expected_result="403 Forbidden or filtered response",
                            actual_result=f"{response_low.status_code} with {len(response_low.content)} bytes",
                        ),
                        ReproductionStep(
                            step_number=3,
                            action="Compare with high-privilege response",
                            expected_result="Different data or access denied",
                            actual_result="Same data accessible",
                        ),
                    ],
                    reliability_score=85.0,
                    root_cause="Missing authorization check on resource ID parameter",
                    impact_types=[ImpactType.CONFIDENTIALITY],
                    evidence_warc_refs=[
                        warc_ref_high.to_uri(),
                        warc_ref_low.to_uri(),
                    ],
                )
                
                return finding
        
        return None
    
    def close(self):
        """Close WARC writer and flush all evidence."""
        self.warc_writer.close()
        logger.info(f"Captured {len(self.evidence_refs)} evidence records")


# Example usage in a test module
async def example_integration():
    """
    Example showing how to integrate WARC capture into testing phase.
    """
    from cyberAI.config import get_config
    
    config = get_config()
    
    # Initialize test worker with evidence capture
    worker = TestWorkerWithEvidence(
        engagement_id="test_engagement_001",
        warc_base_dir=config.get_output_path("warc"),
    )
    
    # Run tests
    finding = await worker.test_authorization_bypass(
        endpoint="https://api.example.com/users/123",
        low_priv_token="token_user",
        high_priv_token="token_admin",
    )
    
    if finding:
        logger.info(f"Found vulnerability: {finding.title}")
        logger.info(f"Evidence: {len(finding.evidence_warc_refs)} WARC references")
        
        # Save finding for verification phase
        # ... (existing finding persistence logic)
    
    # Close and flush evidence
    worker.close()


# Integration pattern for existing test modules
def integrate_warc_capture_pattern():
    """
    Pattern for adding WARC capture to existing test modules.
    
    For each test module (auth_testing.py, authorization_testing.py, etc.):
    
    1. Add WARC writer to test class __init__:
       ```python
       from cyberAI.storage import create_warc_writer
       
       class AuthTester:
           def __init__(self, engagement_id: str):
               self.warc_writer = create_warc_writer(engagement_id)
       ```
    
    2. Capture HTTP traffic after each request:
       ```python
       response = await client.get(url, headers=headers)
       
       warc_ref = self.warc_writer.write_request_response(
           method="GET",
           url=url,
           request_headers=headers,
           request_body=b"",
           status_code=response.status_code,
           reason=response.reason_phrase,
           response_headers=dict(response.headers),
           response_body=response.content,
       )
       ```
    
    3. Link WARC refs to findings:
       ```python
       finding = Finding(
           title="...",
           # ... other fields ...
           evidence_warc_refs=[warc_ref.to_uri()],
       )
       ```
    
    4. Close writer when done:
       ```python
       def cleanup(self):
           self.warc_writer.close()
       ```
    """
    pass


if __name__ == "__main__":
    import asyncio
    
    asyncio.run(example_integration())
