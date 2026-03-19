"""
Kafka topic definitions for the data pipeline.
"""

class Topics:
    """Kafka topic names."""
    RAW_CAPTURES = "raw_captures"
    PARSED_REQUESTS = "parsed_requests"
    INSERTION_POINTS = "insertion_points"
    TEST_EVENTS = "test_events"
    FINDINGS = "findings"
    SEED_URLS = "seed_urls"
    
    @classmethod
    def all(cls):
        """Get all topic names."""
        return [
            cls.RAW_CAPTURES,
            cls.PARSED_REQUESTS,
            cls.INSERTION_POINTS,
            cls.TEST_EVENTS,
            cls.FINDINGS,
            cls.SEED_URLS,
        ]
