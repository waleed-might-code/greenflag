"""
Integration utilities for WARC storage in the CyberAI pipeline.
Provides helpers to automatically capture HTTP traffic to WARC during recon and testing.
"""

from typing import Optional
from loguru import logger

from cyberAI.storage import WARCWriter, WARCReference
from cyberAI.models import RequestRecord


class WARCIntegration:
    """
    Integration layer for automatic WARC capture.
    
    Usage in recon/testing modules:
        warc = WARCIntegration.get_writer(engagement_id)
        ref = warc.capture_request(request_record)
        # ref.to_uri() is now available for linking to findings
    """
    
    _writers: dict[str, WARCWriter] = {}
    
    @classmethod
    def get_writer(cls, engagement_id: str) -> WARCWriter:
        """Get or create WARC writer for an engagement."""
        if engagement_id not in cls._writers:
            from cyberAI.storage import create_warc_writer
            cls._writers[engagement_id] = create_warc_writer(engagement_id)
            logger.info(f"Created WARC writer for engagement: {engagement_id}")
        return cls._writers[engagement_id]
    
    @classmethod
    def capture_request(
        cls,
        engagement_id: str,
        request_record: RequestRecord,
    ) -> Optional[WARCReference]:
        """
        Capture a RequestRecord to WARC.
        
        Args:
            engagement_id: Engagement identifier
            request_record: RequestRecord to capture
            
        Returns:
            WARCReference or None if capture fails
        """
        try:
            writer = cls.get_writer(engagement_id)
            
            # Convert RequestRecord to WARC format
            ref = writer.write_request_response(
                method=request_record.method.value,
                url=request_record.url,
                request_headers=request_record.headers,
                request_body=(request_record.body or "").encode("utf-8"),
                status_code=request_record.response_status,
                response_headers=request_record.response_headers,
                response_body=(request_record.response_body or "").encode("utf-8"),
            )
            
            # Update the request record with WARC ref
            request_record.warc_ref = ref.to_uri()
            
            return ref
            
        except Exception as e:
            logger.error(f"Failed to capture request to WARC: {e}")
            return None
    
    @classmethod
    def close_all(cls) -> None:
        """Close all WARC writers."""
        for engagement_id, writer in cls._writers.items():
            writer.close()
            logger.info(f"Closed WARC writer for engagement: {engagement_id}")
        cls._writers.clear()
    
    @classmethod
    def close_writer(cls, engagement_id: str) -> None:
        """Close WARC writer for a specific engagement."""
        if engagement_id in cls._writers:
            cls._writers[engagement_id].close()
            del cls._writers[engagement_id]
            logger.info(f"Closed WARC writer for engagement: {engagement_id}")


def capture_to_warc(
    engagement_id: str,
    method: str,
    url: str,
    request_headers: dict,
    request_body: bytes,
    status_code: int,
    response_headers: dict,
    response_body: bytes,
) -> Optional[str]:
    """
    Convenience function to capture HTTP traffic to WARC.
    
    Returns:
        WARC URI string or None if capture fails
    """
    try:
        writer = WARCIntegration.get_writer(engagement_id)
        ref = writer.write_request_response(
            method=method,
            url=url,
            request_headers=request_headers,
            request_body=request_body,
            status_code=status_code,
            response_headers=response_headers,
            response_body=response_body,
        )
        return ref.to_uri()
    except Exception as e:
        logger.error(f"Failed to capture to WARC: {e}")
        return None
