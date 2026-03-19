"""
Login Macro System - Reliable Login Sequence Recording and Replay

Handles complex login flows with:
- Step-based sequences (navigate, fill, click, wait, assert)
- Selector-based targeting (not coordinates)
- Parameterized credentials
- Manual pause for CAPTCHA/2FA
- Retry logic and error recovery
"""

import asyncio
import json
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from datetime import datetime

from loguru import logger
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout


class StepAction(str, Enum):
    """Available actions in a login sequence."""
    NAVIGATE = "navigate"
    FILL = "fill"
    CLICK = "click"
    WAIT = "wait"
    WAIT_FOR_SELECTOR = "wait_for_selector"
    WAIT_FOR_URL = "wait_for_url"
    ASSERT_URL = "assert_url"
    ASSERT_TEXT = "assert_text"
    EXTRACT_COOKIES = "extract_cookies"
    EXTRACT_TOKEN = "extract_token"
    MANUAL_PAUSE = "manual_pause"
    SCREENSHOT = "screenshot"


@dataclass
class LoginStep:
    """Single step in a login sequence."""
    action: StepAction
    selector: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    timeout_ms: int = 30000
    description: Optional[str] = None
    required: bool = True
    retry_count: int = 0
    
    # For parameterized values
    value_ref: Optional[str] = None  # e.g., "{{username}}", "{{password}}"
    
    # For assertions
    expected: Optional[str] = None
    
    # For token extraction
    token_name: Optional[str] = None
    token_source: Optional[str] = None  # "cookie", "localstorage", "header", "selector"
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "LoginStep":
        if "action" in data and isinstance(data["action"], str):
            data["action"] = StepAction(data["action"])
        return cls(**data)


@dataclass
class LoginSequence:
    """Complete login sequence definition."""
    name: str
    role: str
    steps: List[LoginStep]
    success_indicators: List[Dict[str, str]]  # [{"type": "url_contains", "value": "/dashboard"}]
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> dict:
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> "LoginSequence":
        steps = [LoginStep.from_dict(s) for s in data.get("steps", [])]
        data["steps"] = steps
        return cls(**data)
    
    def save(self, path: Path):
        """Save sequence to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"Saved login sequence to {path}")
    
    @classmethod
    def load(cls, path: Path) -> "LoginSequence":
        """Load sequence from JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        return cls.from_dict(data)


class LoginMacroExecutor:
    """
    Executes login sequences with retry logic and error recovery.
    """
    
    def __init__(self, max_retries: int = 3, step_delay_ms: int = 500):
        self.max_retries = max_retries
        self.step_delay_ms = step_delay_ms
        self._execution_log: List[Dict[str, Any]] = []
    
    async def execute(
        self,
        page: Page,
        sequence: LoginSequence,
        credentials: Dict[str, str],
        screenshot_dir: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Execute a login sequence.
        
        Args:
            page: Playwright page
            sequence: Login sequence to execute
            credentials: Dict with credential values (username, password, etc.)
            screenshot_dir: Optional directory for debug screenshots
        
        Returns:
            Dict with cookies, headers, tokens, and execution log
        """
        self._execution_log = []
        logger.info(f"Executing login sequence: {sequence.name} for role: {sequence.role}")
        
        result = {
            "success": False,
            "cookies": [],
            "headers": {},
            "tokens": {},
            "execution_log": [],
            "error": None
        }
        
        try:
            for idx, step in enumerate(sequence.steps):
                step_num = idx + 1
                logger.debug(f"Step {step_num}/{len(sequence.steps)}: {step.action.value}")
                
                # Substitute credential references
                step_value = self._substitute_credentials(step.value, credentials)
                step_url = self._substitute_credentials(step.url, credentials)
                
                # Execute step with retry
                step_result = await self._execute_step_with_retry(
                    page, step, step_value, step_url, step_num, screenshot_dir
                )
                
                self._execution_log.append(step_result)
                
                if not step_result["success"] and step.required:
                    result["error"] = f"Step {step_num} failed: {step_result.get('error')}"
                    result["execution_log"] = self._execution_log
                    return result
                
                # Small delay between steps
                await asyncio.sleep(self.step_delay_ms / 1000)
            
            # Check success indicators
            success = await self._check_success_indicators(page, sequence.success_indicators)
            
            if success:
                # Extract session data
                result["cookies"] = await page.context.cookies()
                result["tokens"] = await self._extract_all_tokens(page, sequence)
                result["success"] = True
                logger.info(f"Login sequence completed successfully for {sequence.role}")
            else:
                result["error"] = "Success indicators not met"
                logger.warning(f"Login sequence completed but success indicators not met")
            
        except Exception as e:
            logger.error(f"Login sequence execution failed: {e}")
            result["error"] = str(e)
        
        result["execution_log"] = self._execution_log
        return result
    
    async def _execute_step_with_retry(
        self,
        page: Page,
        step: LoginStep,
        value: Optional[str],
        url: Optional[str],
        step_num: int,
        screenshot_dir: Optional[Path]
    ) -> Dict[str, Any]:
        """Execute a single step with retry logic."""
        attempts = 0
        last_error = None
        
        while attempts <= self.max_retries:
            try:
                result = await self._execute_single_step(page, step, value, url, step_num, screenshot_dir)
                result["attempts"] = attempts + 1
                return result
            except Exception as e:
                attempts += 1
                last_error = str(e)
                logger.warning(f"Step {step_num} attempt {attempts} failed: {e}")
                
                if attempts <= self.max_retries:
                    await asyncio.sleep(1)  # Wait before retry
        
        return {
            "step": step_num,
            "action": step.action.value,
            "success": False,
            "error": last_error,
            "attempts": attempts
        }
    
    async def _execute_single_step(
        self,
        page: Page,
        step: LoginStep,
        value: Optional[str],
        url: Optional[str],
        step_num: int,
        screenshot_dir: Optional[Path]
    ) -> Dict[str, Any]:
        """Execute a single step (one attempt)."""
        result = {
            "step": step_num,
            "action": step.action.value,
            "success": False,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        try:
            if step.action == StepAction.NAVIGATE:
                await page.goto(url, wait_until="networkidle", timeout=step.timeout_ms)
                result["url"] = page.url
                result["success"] = True
            
            elif step.action == StepAction.FILL:
                await page.fill(step.selector, value, timeout=step.timeout_ms)
                result["selector"] = step.selector
                result["success"] = True
            
            elif step.action == StepAction.CLICK:
                await page.click(step.selector, timeout=step.timeout_ms)
                result["selector"] = step.selector
                result["success"] = True
            
            elif step.action == StepAction.WAIT:
                await asyncio.sleep(float(value or 1))
                result["duration_s"] = float(value or 1)
                result["success"] = True
            
            elif step.action == StepAction.WAIT_FOR_SELECTOR:
                await page.wait_for_selector(step.selector, timeout=step.timeout_ms)
                result["selector"] = step.selector
                result["success"] = True
            
            elif step.action == StepAction.WAIT_FOR_URL:
                await page.wait_for_url(value, timeout=step.timeout_ms)
                result["url"] = page.url
                result["success"] = True
            
            elif step.action == StepAction.ASSERT_URL:
                current_url = page.url
                if step.expected in current_url:
                    result["success"] = True
                    result["url"] = current_url
                else:
                    result["error"] = f"URL assertion failed: expected '{step.expected}' in '{current_url}'"
            
            elif step.action == StepAction.ASSERT_TEXT:
                element = await page.query_selector(step.selector)
                if element:
                    text = await element.text_content()
                    if step.expected in text:
                        result["success"] = True
                    else:
                        result["error"] = f"Text assertion failed: expected '{step.expected}' in '{text}'"
                else:
                    result["error"] = f"Element not found: {step.selector}"
            
            elif step.action == StepAction.EXTRACT_COOKIES:
                cookies = await page.context.cookies()
                result["cookies"] = cookies
                result["success"] = True
            
            elif step.action == StepAction.EXTRACT_TOKEN:
                token = await self._extract_token(page, step)
                result["token_name"] = step.token_name
                result["token_value"] = token
                result["success"] = token is not None
            
            elif step.action == StepAction.MANUAL_PAUSE:
                logger.warning(f"MANUAL PAUSE: {step.description}")
                logger.warning("Waiting 60 seconds for manual intervention (CAPTCHA/2FA)...")
                await asyncio.sleep(60)
                result["success"] = True
                result["note"] = "Manual pause completed"
            
            elif step.action == StepAction.SCREENSHOT:
                if screenshot_dir:
                    screenshot_path = screenshot_dir / f"step_{step_num}_{step.action.value}.png"
                    await page.screenshot(path=str(screenshot_path))
                    result["screenshot"] = str(screenshot_path)
                result["success"] = True
            
            else:
                result["error"] = f"Unknown action: {step.action}"
        
        except PlaywrightTimeout as e:
            result["error"] = f"Timeout: {str(e)}"
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    def _substitute_credentials(self, template: Optional[str], credentials: Dict[str, str]) -> Optional[str]:
        """Replace {{key}} placeholders with credential values."""
        if not template:
            return template
        
        result = template
        for key, value in credentials.items():
            result = result.replace(f"{{{{{key}}}}}", value)
        
        return result
    
    async def _extract_token(self, page: Page, step: LoginStep) -> Optional[str]:
        """Extract token from various sources."""
        try:
            if step.token_source == "cookie":
                cookies = await page.context.cookies()
                for cookie in cookies:
                    if cookie["name"] == step.token_name:
                        return cookie["value"]
            
            elif step.token_source == "localstorage":
                token = await page.evaluate(f"localStorage.getItem('{step.token_name}')")
                return token
            
            elif step.token_source == "selector":
                element = await page.query_selector(step.selector)
                if element:
                    return await element.text_content()
            
        except Exception as e:
            logger.error(f"Token extraction failed: {e}")
        
        return None
    
    async def _extract_all_tokens(self, page: Page, sequence: LoginSequence) -> Dict[str, str]:
        """Extract all tokens defined in the sequence."""
        tokens = {}
        
        for step in sequence.steps:
            if step.action == StepAction.EXTRACT_TOKEN and step.token_name:
                token = await self._extract_token(page, step)
                if token:
                    tokens[step.token_name] = token
        
        return tokens
    
    async def _check_success_indicators(self, page: Page, indicators: List[Dict[str, str]]) -> bool:
        """Check if success indicators are met."""
        if not indicators:
            return True
        
        for indicator in indicators:
            indicator_type = indicator.get("type")
            expected_value = indicator.get("value")
            
            try:
                if indicator_type == "url_contains":
                    if expected_value not in page.url:
                        return False
                
                elif indicator_type == "url_equals":
                    if page.url != expected_value:
                        return False
                
                elif indicator_type == "selector_exists":
                    element = await page.query_selector(expected_value)
                    if not element:
                        return False
                
                elif indicator_type == "text_contains":
                    content = await page.content()
                    if expected_value not in content:
                        return False
            
            except Exception as e:
                logger.error(f"Success indicator check failed: {e}")
                return False
        
        return True
    
    def get_execution_log(self) -> List[Dict[str, Any]]:
        """Get the execution log from the last run."""
        return self._execution_log


class LoginMacroRecorder:
    """
    Records user interactions to create login sequences.
    (Simplified version - full implementation would use Playwright's recorder API)
    """
    
    def __init__(self):
        self.recorded_steps: List[LoginStep] = []
    
    def add_navigate(self, url: str, description: str = None):
        """Record a navigation step."""
        self.recorded_steps.append(LoginStep(
            action=StepAction.NAVIGATE,
            url=url,
            description=description or f"Navigate to {url}"
        ))
    
    def add_fill(self, selector: str, value_ref: str, description: str = None):
        """Record a fill step with credential reference."""
        self.recorded_steps.append(LoginStep(
            action=StepAction.FILL,
            selector=selector,
            value_ref=value_ref,
            description=description or f"Fill {selector}"
        ))
    
    def add_click(self, selector: str, description: str = None):
        """Record a click step."""
        self.recorded_steps.append(LoginStep(
            action=StepAction.CLICK,
            selector=selector,
            description=description or f"Click {selector}"
        ))
    
    def add_wait_for_selector(self, selector: str, timeout_ms: int = 30000):
        """Record a wait for selector step."""
        self.recorded_steps.append(LoginStep(
            action=StepAction.WAIT_FOR_SELECTOR,
            selector=selector,
            timeout_ms=timeout_ms,
            description=f"Wait for {selector}"
        ))
    
    def add_assert_url(self, expected: str):
        """Record a URL assertion."""
        self.recorded_steps.append(LoginStep(
            action=StepAction.ASSERT_URL,
            expected=expected,
            description=f"Assert URL contains {expected}"
        ))
    
    def add_manual_pause(self, description: str = "Manual intervention required"):
        """Record a manual pause for CAPTCHA/2FA."""
        self.recorded_steps.append(LoginStep(
            action=StepAction.MANUAL_PAUSE,
            description=description,
            required=False
        ))
    
    def build_sequence(
        self,
        name: str,
        role: str,
        success_indicators: List[Dict[str, str]]
    ) -> LoginSequence:
        """Build a login sequence from recorded steps."""
        now = datetime.utcnow().isoformat()
        return LoginSequence(
            name=name,
            role=role,
            steps=self.recorded_steps,
            success_indicators=success_indicators,
            created_at=now,
            updated_at=now
        )
