"""
Parsing and Insertion Point Extraction Module

This module provides enterprise-grade request parsing, canonicalization,
and insertion point extraction with support for nested encoding layers.
"""

from .request_canonicalizer import RequestCanonicalizer, CanonicalRequest
from .insertion_point_extractor import InsertionPointExtractor, InsertionPoint
from .encoding_detectors import EncodingDetector, EncodingLayer
from .novelty_tracker import NoveltyTracker
from .pipeline import ParsingPipeline

__all__ = [
    'RequestCanonicalizer',
    'CanonicalRequest',
    'InsertionPointExtractor',
    'InsertionPoint',
    'EncodingDetector',
    'EncodingLayer',
    'NoveltyTracker',
    'ParsingPipeline',
]
