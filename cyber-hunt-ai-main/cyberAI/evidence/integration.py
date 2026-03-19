"""
Integration hooks for existing crawl and test modules.
Wraps HTTP clients to automatically capture traffic.
"""

from typing import Optional, Callable, Any
from uuid import uuid4

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

from .capture import CaptureSession


class CaptureMiddleware:
    """
    Middleware that intercepts HTTP traffic and captures to WARC.
    Can be used with httpx, playwright, or any HTTP client.
    """
    
    def __init__(self, capture_session: CaptureSession):
        self.session = capture_session
    
    async def intercept_request(self, method: str, url: str, 
                               headers: dict, body: Optional[bytes] = None) -> str:
        """Intercept and capture outgoing request."""
        request_id = str(uuid4())
        warc_ref = self.session.capture_request(request_id, method, url, headers, body)
        logger.debug(f"Captured request {request_id}: {method} {url}")
        return request_id
    
    async def intercept_response(self, request_id: str, url: str, 
                                status_code: int, headers: dict, 
                                body: Optional[bytes] = None) -> str:
        """Intercept and capture response."""
        warc_ref = self.session.capture_response(request_id, url, status_code, headers, body)
        logger.debug(f"Captured response for {request_id}: {status_code}")
        return warc_ref



def wrap_playwright_page(page: Any, middleware: CaptureMiddleware):
    """
    Wrap Playwright page to capture all network traffic.
    """
    request_map = {}
    
    async def on_request(request):
        try:
            headers = await request.all_headers()
            body = request.post_data_buffer if request.post_data_buffer else None
            request_id = await middleware.intercept_request(
                request.method, request.url, headers, body
            )
            request_map[request.url] = request_id
        except Exception as e:
            logger.error(f"Error capturing request: {e}")
    
    async def on_response(response):
        try:
            request_id = request_map.get(response.url)
            if request_id:
                headers = await response.all_headers()
                body = await response.body()
                await middleware.intercept_response(
                    request_id, response.url, response.status, headers, body
                )
        except Exception as e:
            logger.error(f"Error capturing response: {e}")
    
    page.on("request", on_request)
    page.on("response", on_response)
    
    return page
