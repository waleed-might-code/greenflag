"""
Batch Data Analysis - Analyze captured WARC data for vulnerabilities
Demonstrates how to analyze the massive data dump for security findings.
"""

import gzip
import json
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Set
import re


class DataAnalyzer:
    """
    Analyzes captured WARC data to find security vulnerabilities.
    Processes massive data dumps to identify patterns and issues.
    """
    
    def __init__(self, warc_dir: Path):
        self.warc_dir = warc_dir
        self.findings = []
        self.stats = defaultdict(int)
        
        # Patterns for sensitive data
        self.sensitive_patterns = {
            "api_key": re.compile(r'api[_-]?key["\s:=]+([a-zA-Z0-9_-]{20,})'),
            "jwt": re.compile(r'eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+'),
            "email": re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
            "password": re.compile(r'password["\s:=]+([^\s"]+)'),
            "ssn": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
            "credit_card": re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'),
        }
        
        # Vulnerability patterns
        self.vuln_patterns = {
            "sql_error": re.compile(r'(SQL syntax|mysql_fetch|ORA-\d+|PostgreSQL)'),
            "stack_trace": re.compile(r'(Traceback|at\s+[\w.]+\([\w.]+:\d+\))'),
            "debug_info": re.compile(r'(DEBUG|TRACE|Exception in thread)'),
        }
    
    def analyze_all_warcs(self) -> Dict:
        """Analyze all WARC files in directory."""
        print(f"🔍 Analyzing WARC files in {self.warc_dir}\n")
        
        warc_files = list(self.warc_dir.glob("*.warc.gz"))
        print(f"Found {len(warc_files)} WARC files to analyze\n")
        
        for warc_file in warc_files:
            print(f"📄 Analyzing: {warc_file.name}")
            self._analyze_warc_file(warc_file)
        
        self._print_analysis_results()
        return self._generate_report()
    
    def _analyze_warc_file(self, warc_file: Path):
        """Analyze a single WARC file."""
        try:
            with gzip.open(warc_file, 'rb') as f:
                content = f.read().decode('utf-8', errors='ignore')
                
                # Split into records
                records = content.split('WARC/1.0')
                self.stats['total_records'] += len(records)
                
                for record in records:
                    if not record.strip():
                        continue
                    
                    self._analyze_record(record, warc_file.name)
                    
        except Exception as e:
            print(f"   ⚠️  Error analyzing {warc_file.name}: {e}")
    
    def _analyze_record(self, record: str, warc_file: str):
        """Analyze a single WARC record."""
        # Check for sensitive data exposure
        for pattern_name, pattern in self.sensitive_patterns.items():
            matches = pattern.findall(record)
            if matches:
                self.stats[f'sensitive_{pattern_name}'] += len(matches)
                self.findings.append({
                    "type": "sensitive_data_exposure",
                    "category": pattern_name,
                    "warc_file": warc_file,
                    "matches": len(matches),
                    "severity": "high"
                })
        
        # Check for vulnerability indicators
        for vuln_name, pattern in self.vuln_patterns.items():
            if pattern.search(record):
                self.stats[f'vuln_{vuln_name}'] += 1
                self.findings.append({
                    "type": "vulnerability_indicator",
                    "category": vuln_name,
                    "warc_file": warc_file,
                    "severity": "medium"
                })
        
        # Check for IDOR patterns (numeric IDs in URLs)
        if re.search(r'/users?/\d+', record) or re.search(r'/api/\w+/\d+', record):
            self.stats['potential_idor'] += 1
        
        # Check for admin endpoints
        if re.search(r'/(admin|dashboard|manage|control)', record, re.I):
            self.stats['admin_endpoints'] += 1
    
    def _print_analysis_results(self):
        """Print analysis results."""
        print("\n" + "="*60)
        print("📊 DATA ANALYSIS RESULTS")
        print("="*60)
        
        print(f"\n📈 Statistics:")
        print(f"   Total records analyzed: {self.stats['total_records']}")
        print(f"   Findings discovered: {len(self.findings)}")
        print(f"   Potential IDOR endpoints: {self.stats['potential_idor']}")
        print(f"   Admin endpoints found: {self.stats['admin_endpoints']}")
        
        print(f"\n🔐 Sensitive Data Exposure:")
        for key, value in self.stats.items():
            if key.startswith('sensitive_') and value > 0:
                print(f"   {key.replace('sensitive_', '').upper()}: {value} occurrences")
        
        print(f"\n⚠️  Vulnerability Indicators:")
        for key, value in self.stats.items():
            if key.startswith('vuln_') and value > 0:
                print(f"   {key.replace('vuln_', '').upper()}: {value} occurrences")
        
        print("\n" + "="*60)
    
    def _generate_report(self) -> Dict:
        """Generate analysis report."""
        return {
            "stats": dict(self.stats),
            "findings": self.findings,
            "summary": {
                "total_findings": len(self.findings),
                "high_severity": sum(1 for f in self.findings if f.get('severity') == 'high'),
                "medium_severity": sum(1 for f in self.findings if f.get('severity') == 'medium'),
            }
        }
    
    def save_report(self, output_path: Path):
        """Save analysis report to file."""
        report = self._generate_report()
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n💾 Report saved to: {output_path}")


def main():
    """Demo: Analyze captured WARC data."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python data_analyzer.py <warc_directory>")
        print("Example: python data_analyzer.py outputs/evidence/warc")
        sys.exit(1)
    
    warc_dir = Path(sys.argv[1])
    
    if not warc_dir.exists():
        print(f"Error: Directory {warc_dir} does not exist")
        sys.exit(1)
    
    analyzer = DataAnalyzer(warc_dir)
    analyzer.analyze_all_warcs()
    
    # Save report
    report_path = warc_dir.parent / "analysis_report.json"
    analyzer.save_report(report_path)


if __name__ == "__main__":
    main()
