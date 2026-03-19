"""
Session Repair Runner - Orchestrates session repair with retry logic and error recovery.

Features:
- Exponential backoff retry
- Manual pause support for CAPTCHA/2FA
- Detailed repair logs
- Fallback strategies
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List
from pathlib import Path

from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from cyberAI.login_macro import LoginSequence, LoginMacroRunner, StepAction


class RepairStatus(str, Enum):
    """Status of repair attempt."""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    MANUAL_INTERVENTION_REQUIRED = "manual_intervention_required"
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"


@dataclass
class RepairAttempt:
    """Record of a single repair attempt."""
    attempt_number: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: Optional[RepairStatus] = None
    error_message: Optional[str] = None
    steps_completed: int = 0
    total_steps: int = 0
    manual_pause_triggered: bool = False


@dataclass
class RepairResult:
    """Result of session repair operation."""
    success: bool
    status: RepairStatus
    attempts: List[RepairAttempt] = field(default_factory=list)
    cookies: Optional[Dict[str, str]] = None
    headers: Optional[Dict[str, str]] = None
    total_duration_seconds: float = 0.0
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "status": self.status.value,
            "attempts_count": len(self.attempts),
            "cookies_count": len(self.cookies) if self.cookies else 0,
            "total_duration_seconds": self.total_duration_seconds,
            "error_message": self.error_message,
        }


class SessionRepairRunner:
    """
    Orchestrates session repair with retry logic and error recovery.
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay_seconds: float = 2.0,
        max_delay_seconds: float = 30.0,
        headless: bool = True,
    ):
        """
        Initialize repair runner.
        
        Args:
            max_retries: Maximum number of repair attempts
            base_delay_seconds: Initial delay between retries
            max_delay_seconds: Maximum delay between retries
            headless: Run browser in headless mode
        """
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.headless = headless
        
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        
        logger.info(f"Session repair runner initialized (max_retries={max_retries})")
    
    async def repair_session(
        self,
        role: str,
        login_sequence: LoginSequence,
        credentials: Dict[str, str],
        health_check_url: Optional[str] = None,
    ) -> RepairResult:
        """
        Repair a session by executing login sequence with retry logic.
        
        Args:
            role: Role being repaired
            login_sequence: Login sequence to execute
            credentials: Credentials dict (username, password, etc.)
            health_check_url: Optional URL to verify session after repair
        
        Returns:
            RepairResult with status and session data
        """
        start_time = datetime.utcnow()
        attempts: List[RepairAttempt] = []
        
        logger.info(f"Starting session repair for role: {role}")
        
        try:
            async with async_playwright() as p:
                self.browser = await p.chromium.launch(headless=self.headless)
                
                for attempt_num in range(1, self.max_retries + 1):
                    attempt = RepairAttempt(
                        attempt_number=attempt_num,
                        started_at=datetime.utcnow(),
                        total_steps=len(login_sequence.steps)
                    )
                    attempts.append(attempt)
                    
                    logger.info(f"Repair attempt {attempt_num}/{self.max_retries} for {role}")
                    
                    # Execute login sequence
                    result = await self._execute_repair_attempt(
                        login_sequence,
                        credentials,
                        attempt
                    )
                    
                    attempt.completed_at = datetime.utcnow()
                    
                    if result.success:
                        # Verify session if health check URL provided
                        if health_check_url:
                            is_healthy = await self._verify_session(
                                health_check_url,
                                result.cookies,
                                result.headers
                            )
                            
                            if not is_healthy:
                                logger.warning(f"Session repair succeeded but health check failed")
                                attempt.status = RepairStatus.PARTIAL
                                
                                # Retry if not last attempt
                                if attempt_num < self.max_retries:
                                    delay = self._calculate_backoff_delay(attempt_num)
                                    logger.info(f"Retrying after {delay:.1f}s")
                                    await asyncio.sleep(delay)
                                    continue
                        
                        # Success!
                        attempt.status = RepairStatus.SUCCESS
                        end_time = datetime.utcnow()
                        
                        logger.success(f"Session repair succeeded for {role} after {attempt_num} attempt(s)")
                        
                        return RepairResult(
                            success=True,
                            status=RepairStatus.SUCCESS,
                            attempts=attempts,
                            cookies=result.cookies,
                            headers=result.headers,
                            total_duration_seconds=(end_time - start_time).total_seconds()
                        )
                    
                    # Handle manual intervention
                    if attempt.manual_pause_triggered:
                        attempt.status = RepairStatus.MANUAL_INTERVENTION_REQUIRED
                        logger.warning(f"Manual intervention required for {role}")
                        
                        return RepairResult(
                            success=False,
                            status=RepairStatus.MANUAL_INTERVENTION_REQUIRED,
                            attempts=attempts,
                            total_duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                            error_message="Manual intervention required (CAPTCHA/2FA)"
                        )
                    
                    # Failed attempt
                    attempt.status = RepairStatus.FAILED
                    attempt.error_message = result.error_message
                    
                    # Retry with backoff
                    if attempt_num < self.max_retries:
                        delay = self._calculate_backoff_delay(attempt_num)
                        logger.info(f"Retrying after {delay:.1f}s")
                        await asyncio.sleep(delay)
                
                # Max retries exceeded
                logger.error(f"Session repair failed for {role} after {self.max_retries} attempts")
                
                return RepairResult(
                    success=False,
                    status=RepairStatus.MAX_RETRIES_EXCEEDED,
                    attempts=attempts,
                    total_duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                    error_message=f"Max retries ({self.max_retries}) exceeded"
                )
        
        except Exception as e:
            logger.error(f"Session repair exception for {role}: {e}")
            
            return RepairResult(
                success=False,
                status=RepairStatus.FAILED,
                attempts=attempts,
                total_duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                error_message=str(e)
            )
        
        finally:
            if self.browser:
                await self.browser.close()
                self.browser = None
    
    async def _execute_repair_attempt(
        self,
        login_sequence: LoginSequence,
        credentials: Dict[str, str],
        attempt: RepairAttempt,
    ) -> "RepairResult":
        """Execute a single repair attempt."""
        try:
            # Create fresh context
            self.context = await self.browser.new_context()
            page = await self.context.new_page()
            
            # Run login macro
            runner = LoginMacroRunner(page)
            result = await runner.execute(login_sequence, credentials)
            
            attempt.steps_completed = len([s for s in result.step_results if s.success])
            
            if result.success:
                # Extract cookies and headers
                cookies = await self._extract_cookies(page)
                headers = {}  # Could extract from storage if needed
                
                await self.context.close()
                
                return RepairResult(
                    success=True,
                    status=RepairStatus.SUCCESS,
                    cookies=cookies,
                    headers=headers
                )
            
            # Check if manual pause was triggered
            manual_pause_triggered = any(
                step.action == StepAction.MANUAL_PAUSE
                for step in login_sequence.steps
            )
            attempt.manual_pause_triggered = manual_pause_triggered
            
            await self.context.close()
            
            return RepairResult(
                success=False,
                status=RepairStatus.FAILED,
                error_message=result.error_message
            )
        
        except Exception as e:
            logger.error(f"Repair attempt execution failed: {e}")
            
            if self.context:
                await self.context.close()
            
            return RepairResult(
                success=False,
                status=RepairStatus.FAILED,
                error_message=str(e)
            )
    
    async def _extract_cookies(self, page: Page) -> Dict[str, str]:
        """Extract cookies from page context."""
        cookies_list = await page.context.cookies()
        return {cookie["name"]: cookie["value"] for cookie in cookies_list}
    
    async def _verify_session(
        self,
        health_check_url: str,
        cookies: Dict[str, str],
        headers: Optional[Dict[str, str]],
    ) -> bool:
        """Verify session is healthy after repair."""
        try:
            import httpx
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    health_check_url,
                    cookies=cookies,
                    headers=headers or {},
                    timeout=10.0,
                )
                
                return 200 <= response.status_code < 300
        
        except Exception as e:
            logger.debug(f"Session verification failed: {e}")
            return False
    
    def _calculate_backoff_delay(self, attempt_number: int) -> float:
        """Calculate exponential backoff delay."""
        delay = self.base_delay_seconds * (2 ** (attempt_number - 1))
        return min(delay, self.max_delay_seconds)
