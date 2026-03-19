"""
Kafka client wrapper for event streaming.
"""

import json
import os
from typing import Callable, Dict, Optional

from kafka import KafkaProducer as KafkaProducerClient
from kafka import KafkaConsumer as KafkaConsumerClient
from loguru import logger


class KafkaProducer:
    """Kafka producer for publishing events."""
    
    def __init__(self, bootstrap_servers: str = None):
        if bootstrap_servers is None:
            bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        
        self.producer = KafkaProducerClient(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            acks='all',
            retries=3,
        )
        logger.info(f"Kafka producer connected to {bootstrap_servers}")
    
    def send(self, topic: str, value: Dict, key: Optional[str] = None):
        """Send event to topic."""
        future = self.producer.send(topic, value=value, key=key)
        return future
    
    def flush(self):
        """Flush pending messages."""
        self.producer.flush()
    
    def close(self):
        """Close producer."""
        self.producer.close()


class KafkaConsumer:
    """Kafka consumer for processing events."""
    
    def __init__(
        self,
        topics: list,
        group_id: str,
        bootstrap_servers: str = None,
        auto_offset_reset: str = "earliest"
    ):
        if bootstrap_servers is None:
            bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        
        self.consumer = KafkaConsumerClient(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            auto_offset_reset=auto_offset_reset,
            enable_auto_commit=True,
        )
        logger.info(f"Kafka consumer subscribed to {topics} (group: {group_id})")
    
    def consume(self, handler: Callable[[Dict], None]):
        """Consume messages and call handler."""
        try:
            for message in self.consumer:
                try:
                    handler(message.value)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
        except KeyboardInterrupt:
            logger.info("Consumer interrupted")
        finally:
            self.consumer.close()


_kafka_producer = None

def get_kafka_producer() -> KafkaProducer:
    """Get or create Kafka producer singleton."""
    global _kafka_producer
    if _kafka_producer is None:
        _kafka_producer = KafkaProducer()
    return _kafka_producer
