"""
Integration Module: Connects Parsing Pipeline to Existing CyberAI System

This module bridges the new parsing pipeline with the existing crawler,
storage, and testing components.
"""

import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from cyberAI.parsing import ParsingPipeline, InsertionPoint


class CrawlerParsingIntegration:
    """
    Integrates parsing pipeline with the crawler.
    
    Processes captured HTTP traffic and extracts insertion points
    for security testing.
    """
    
    def __init__(self, storage_backend: str = "memory", redis_client=None):
        """
        Initialize integration.
        
        Args:
            storage_backend: "memory" or "redis" for novelty tracking
            redis_client: Redis client (if using redis backend)
        """
        self.pipeline = ParsingPipeline(storage_backend, redis_client)
        self.processed_requests = []
        self.all_insertion_points = []
    
    def process_captured_request(self, capture: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a captured HTTP request from the crawler.
        
        Args:
            capture: Dict with keys: method, url, headers, body, timestamp, source
        
        Returns:
            Processing result with insertion points and metadata
        """
        result = self.pipeline.process_request(
            method=capture.get('method', 'GET'),
            url=capture['url'],
            headers=capture.get('headers', {}),
            body=capture.get('body')
        )
        
        # Add metadata
        result['capture_metadata'] = {
            'timestamp': capture.get('timestamp', datetime.now().isoformat()),
            'source': capture.get('source', 'unknown'),
            'warc_ref': capture.get('warc_ref')
        }
        
        # Store for later analysis
        self.processed_requests.append(result)
        self.all_insertion_points.extend(result['insertion_points'])
        
        return result
    
    def process_batch_from_crawler(self, captures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process a batch of captured requests.
        
        Args:
            captures: List of capture dicts
        
        Returns:
            List of processing results
        """
        results = []
        for capture in captures:
            result = self.process_captured_request(capture)
            results.append(result)
        
        return results
    
    def get_testable_insertion_points(self, min_priority: float = 0.0,
                                     security_relevant_only: bool = False) -> List[InsertionPoint]:
        """
        Get insertion points ready for security testing.
        
        Args:
            min_priority: Minimum priority score
            security_relevant_only: Only return security-relevant points
        
        Returns:
            List of insertion points ready for testing
        """
        points = self.all_insertion_points
        
        if security_relevant_only:
            points = [ip for ip in points if ip.is_security_relevant]
        
        # Filter protected parameters (CSRF/nonce)
        points = [ip for ip in points if not ip.metadata.get('is_protected')]
        
        return points
    
    def export_for_testing(self, output_file: str):
        """
        Export insertion points to JSON for external testing tools.
        
        Args:
            output_file: Path to output JSON file
        """
        export_data = {
            'metadata': {
                'exported_at': datetime.now().isoformat(),
                'total_requests': len(self.processed_requests),
                'total_insertion_points': len(self.all_insertion_points),
                'statistics': self.pipeline.get_statistics()
            },
            'insertion_points': self.pipeline.export_insertion_points(self.all_insertion_points)
        }
        
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2)
    
    def get_coverage_report(self) -> Dict[str, Any]:
        """
        Generate coverage report.
        
        Returns:
            Dict with coverage statistics
        """
        canonical_requests = [r['canonical_request'] for r in self.processed_requests]
        coverage = self.pipeline.analyze_endpoint_coverage(canonical_requests)
        stats = self.pipeline.get_statistics()
        
        return {
            'summary': {
                'total_requests': len(self.processed_requests),
                'unique_endpoints': coverage['unique_endpoints'],
                'total_insertion_points': len(self.all_insertion_points),
                'novel_insertion_points': stats['novel_insertion_points'],
                'security_relevant_points': sum(1 for ip in self.all_insertion_points if ip.is_security_relevant),
                'nested_encoding_points': sum(1 for ip in self.all_insertion_points if len(ip.encoding_layers) > 0)
            },
            'coverage': coverage,
            'statistics': stats
        }


class StorageIntegration:
    """
    Integrates parsing results with WARC storage and evidence system.
    """
    
    @staticmethod
    def attach_insertion_points_to_warc(warc_ref: str, insertion_points: List[InsertionPoint]) -> Dict:
        """
        Attach insertion point metadata to WARC record.
        
        Args:
            warc_ref: WARC reference ID
            insertion_points: List of insertion points
        
        Returns:
            Metadata dict to store alongside WARC record
        """
        return {
            'warc_ref': warc_ref,
            'insertion_point_count': len(insertion_points),
            'insertion_points': [
                {
                    'id': ip.insertion_id,
                    'location': ip.location,
                    'parameter': ip.parameter_name,
                    'type': ip.inferred_type,
                    'encoding_layers': ip.encoding_layers,
                    'security_relevant': ip.is_security_relevant
                }
                for ip in insertion_points
            ],
            'security_relevant_count': sum(1 for ip in insertion_points if ip.is_security_relevant),
            'nested_encoding_count': sum(1 for ip in insertion_points if len(ip.encoding_layers) > 0)
        }
    
    @staticmethod
    def create_finding_with_insertion_point(insertion_point: InsertionPoint,
                                           test_payload: str,
                                           response_data: Dict) -> Dict:
        """
        Create a finding record that references the insertion point.
        
        Args:
            insertion_point: The tested insertion point
            test_payload: The payload that triggered the finding
            response_data: Response data from the test
        
        Returns:
            Finding dict with full context
        """
        return {
            'finding_id': f"finding_{insertion_point.insertion_id}_{datetime.now().timestamp()}",
            'insertion_point': {
                'id': insertion_point.insertion_id,
                'location': insertion_point.location,
                'parameter': insertion_point.parameter_name,
                'parent_path': insertion_point.parent_path,
                'encoding_layers': insertion_point.encoding_layers
            },
            'test_details': {
                'payload': test_payload,
                'encoded_payload': insertion_point.get_payload_with_encoding(test_payload) if insertion_point.encoding_layers else test_payload
            },
            'response': response_data,
            'timestamp': datetime.now().isoformat()
        }


class TestingIntegration:
    """
    Integrates parsing results with security testing workers.
    """
    
    def __init__(self, pipeline: ParsingPipeline):
        self.pipeline = pipeline
    
    def generate_test_cases(self, insertion_point: InsertionPoint,
                           attack_type: str = "xss") -> List[Dict]:
        """
        Generate test cases for an insertion point.
        
        Args:
            insertion_point: The insertion point to test
            attack_type: Type of attack (xss, sqli, idor, etc.)
        
        Returns:
            List of test case dicts
        """
        # Base payloads by attack type
        payload_sets = {
            'xss': [
                '<script>alert(1)</script>',
                '"><script>alert(1)</script>',
                "javascript:alert(1)",
                '<img src=x onerror=alert(1)>'
            ],
            'sqli': [
                "' OR 1=1--",
                "1' OR '1'='1",
                "admin'--",
                "1 UNION SELECT NULL--"
            ],
            'idor': [
                '0', '1', '999999',
                '../', '../../',
                'admin', 'root'
            ],
            'command_injection': [
                '; ls -la',
                '| whoami',
                '`id`',
                '$(cat /etc/passwd)'
            ]
        }
        
        payloads = payload_sets.get(attack_type, ['test'])
        
        # Generate encoded payloads
        encoded_payloads = self.pipeline.generate_test_payloads(insertion_point, payloads)
        
        test_cases = []
        for original, encoded in zip(payloads, encoded_payloads):
            test_cases.append({
                'insertion_point_id': insertion_point.insertion_id,
                'location': insertion_point.location,
                'parameter': insertion_point.parameter_name,
                'attack_type': attack_type,
                'original_payload': original,
                'encoded_payload': encoded,
                'encoding_layers': insertion_point.encoding_layers,
                'original_value': insertion_point.original_value
            })
        
        return test_cases
    
    def prioritize_for_testing(self, insertion_points: List[InsertionPoint]) -> List[InsertionPoint]:
        """
        Prioritize insertion points for testing.
        
        Returns insertion points sorted by testing priority.
        """
        return self.pipeline.extractor.prioritize(insertion_points)


def integrate_with_existing_crawler(crawler_output_dir: str, output_file: str):
    """
    Helper function to integrate with existing crawler output.
    
    Args:
        crawler_output_dir: Directory with crawler output files
        output_file: Where to save the parsing results
    """
    import os
    import glob
    
    integration = CrawlerParsingIntegration(storage_backend="memory")
    
    # Process all JSON files from crawler
    json_files = glob.glob(os.path.join(crawler_output_dir, "*.json"))
    
    for json_file in json_files:
        with open(json_file, 'r') as f:
            try:
                data = json.load(f)
                
                # Handle different crawler output formats
                if isinstance(data, list):
                    captures = data
                elif isinstance(data, dict) and 'requests' in data:
                    captures = data['requests']
                else:
                    captures = [data]
                
                integration.process_batch_from_crawler(captures)
            except Exception as e:
                print(f"Error processing {json_file}: {e}")
    
    # Export results
    integration.export_for_testing(output_file)
    
    # Print report
    report = integration.get_coverage_report()
    print("\n" + "=" * 80)
    print("PARSING INTEGRATION REPORT")
    print("=" * 80)
    print(f"Total requests processed: {report['summary']['total_requests']}")
    print(f"Unique endpoints: {report['summary']['unique_endpoints']}")
    print(f"Total insertion points: {report['summary']['total_insertion_points']}")
    print(f"Novel insertion points: {report['summary']['novel_insertion_points']}")
    print(f"Security-relevant points: {report['summary']['security_relevant_points']}")
    print(f"Nested encoding points: {report['summary']['nested_encoding_points']}")
    print("=" * 80 + "\n")
    
    return report
