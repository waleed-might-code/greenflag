"""
DOM hashing and similarity detection using SimHash.
Handles state deduplication and near-duplicate detection.
"""

import hashlib
import re
from typing import Optional
from simhash import Simhash
from bs4 import BeautifulSoup
from loguru import logger


class DOMHasher:
    """
    Handles DOM hashing for state identification and similarity detection.
    Uses SimHash for near-duplicate detection and SHA-256 for exact matching.
    """
    
    def __init__(self, similarity_threshold: int = 3):
        """
        Initialize DOM hasher.
        
        Args:
            similarity_threshold: Hamming distance threshold for considering states similar (0-64)
        """
        self.similarity_threshold = similarity_threshold
        self._seen_hashes: dict[int, str] = {}  # simhash -> state_id
        
    def extract_meaningful_dom(self, html: str) -> str:
        """
        Extract meaningful DOM structure, stripping dynamic content.
        
        Removes:
        - Script and style tags
        - Timestamps and random IDs
        - CSRF tokens
        - Dynamic attributes (data-reactid, etc.)
        """
        soup = BeautifulSoup(html, 'lxml')
        
        # Remove scripts, styles, comments
        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()
        
        # Strip dynamic attributes
        dynamic_attrs = [
            'data-reactid', 'data-react-checksum', 'data-reactroot',
            'data-v-', 'ng-', '_ngcontent-', '_nghost-',
            'data-timestamp', 'data-nonce', 'data-csrf'
        ]
        
        for tag in soup.find_all(True):
            attrs_to_remove = []
            for attr in tag.attrs:
                # Remove dynamic attributes
                if any(attr.startswith(prefix) for prefix in dynamic_attrs):
                    attrs_to_remove.append(attr)
                # Remove attributes with timestamps or UUIDs
                elif attr in ['id', 'class', 'name']:
                    value = str(tag.attrs[attr])
                    if re.search(r'\d{10,}|[a-f0-9]{8}-[a-f0-9]{4}', value, re.I):
                        attrs_to_remove.append(attr)
            
            for attr in attrs_to_remove:
                del tag.attrs[attr]
        
        # Get text representation with structure
        return self._serialize_dom(soup)
    
    def _serialize_dom(self, soup: BeautifulSoup) -> str:
        """Serialize DOM to canonical string representation."""
        parts = []
        
        for tag in soup.find_all(True):
            # Include tag name and meaningful attributes
            tag_repr = tag.name
            if tag.attrs:
                # Sort attributes for consistency
                attrs = sorted(tag.attrs.items())
                attr_str = ' '.join(f'{k}={v}' for k, v in attrs if k not in ['style'])
                if attr_str:
                    tag_repr += f'[{attr_str}]'
            
            # Include text content (normalized)
            text = tag.get_text(strip=True)
            if text and len(text) < 100:  # Avoid huge text blocks
                text = re.sub(r'\s+', ' ', text)
                tag_repr += f':{text}'
            
            parts.append(tag_repr)
        
        return '\n'.join(parts)
    
    def compute_simhash(self, html: str) -> int:
        """
        Compute SimHash for DOM content.
        
        Returns:
            64-bit SimHash value
        """
        meaningful_dom = self.extract_meaningful_dom(html)
        return Simhash(meaningful_dom).value
    
    def compute_sha256(self, html: str) -> str:
        """Compute SHA-256 hash for exact matching."""
        meaningful_dom = self.extract_meaningful_dom(html)
        return hashlib.sha256(meaningful_dom.encode()).hexdigest()
    
    def is_similar(self, simhash1: int, simhash2: int) -> bool:
        """
        Check if two SimHash values are similar.
        
        Args:
            simhash1: First SimHash value
            simhash2: Second SimHash value
            
        Returns:
            True if Hamming distance <= threshold
        """
        distance = bin(simhash1 ^ simhash2).count('1')
        return distance <= self.similarity_threshold
    
    def find_similar_state(self, simhash: int) -> Optional[str]:
        """
        Find if a similar state already exists.
        
        Args:
            simhash: SimHash value to check
            
        Returns:
            state_id of similar state, or None
        """
        for existing_hash, state_id in self._seen_hashes.items():
            if self.is_similar(simhash, existing_hash):
                return state_id
        return None
    
    def register_state(self, simhash: int, state_id: str) -> bool:
        """
        Register a new state hash.
        
        Args:
            simhash: SimHash value
            state_id: State identifier
            
        Returns:
            True if state is new, False if similar state exists
        """
        similar = self.find_similar_state(simhash)
        if similar:
            logger.debug(f"State {state_id} is similar to existing state {similar}")
            return False
        
        self._seen_hashes[simhash] = state_id
        return True
    
    def get_state_count(self) -> int:
        """Get number of unique states registered."""
        return len(self._seen_hashes)
    
    def clear(self) -> None:
        """Clear all registered states."""
        self._seen_hashes.clear()
