"""
Event-driven data pipeline using Kafka.
Decouples crawling, parsing, testing, and storage.
"""

from .kafka_client import KafkaProducer, KafkaConsumer, get_kafka_producer
from .topics import Topics
from .events import RawCapture, ParsedRequest, InsertionPointEvent, TestEvent, FindingEvent

__all__ = [
    "KafkaProducer",
    "KafkaConsumer",
    "get_kafka_producer",
    "Topics",
    "RawCapture",
    "ParsedRequest",
    "InsertionPointEvent",
    "TestEvent",
    "FindingEvent",
]
