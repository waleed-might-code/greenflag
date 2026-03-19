"""
Main integration layer - orchestrates the complete ASRTS pipeline.
Combines crawling, data mining, insertion point extraction, and authorization testing.
"""

import asyncio
from pathlib import Path
from typing import Optional, List, Dict

from loguru import logger

from ..governance.engagement_config import EngagementConfig
from ..governance.scope_validator import ScopeValidator
from ..crawl.enhanced_orchestrator import EnhancedCrawler, CrawlConfig
from ..pipeline.batch_processor import BatchDataProcessor
from ..identity.multi_role_manager import MultiRoleSessionManager, SessionCredentials
from ..testing.differential_authz import DifferentialAuthzTester


class ASRTSPipeline:
    """
    Complete Authorized Security Reconnaissance and Testing System pipeline.
    
    Workflow:
    1. Load engagement config and initialize scope validator
    2. Initialize multi-role sessions
    3. Run intelligent crawler with priority frontier
    4. Process captured data and extract insertion points
    5. Run differential authorization tests
    6. Generate reports with evidence
    """
    
    def __init__(
        self,
        engagement_config_path: str,
        output_dir: Optional[str] = None,
    ):
        """
        Initialize ASRTS pipeline.
        
        Args:
            engagement_config_path: Path to engagement config YAML
            output_dir: Output directory for all results
        """
        self.config_path = Path(engagement_config_path)
        self.output_dir = Path(output_dir or "outputs/asrts")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load engagement config
        self.engagement_config = EngagementConfig.from_yaml(str(self.config_path))
        logger.info(f"Loaded engagement config: {self.engagement_config.name}")
        
        # Initialize scope validator
        self.scope_validator = ScopeValidator(
            target_domains=self.engagement_config.target_domains,
            out_of_scope_patterns=self.engagement_config.out_of_scope_patterns,
            allowed_schemes=self.engagement_config.allowed_schemes,
        )
        
        # Components (initialized later)
        self.crawler: Optional[EnhancedCrawler] = None
        self.session_manager: Optional[MultiRoleSessionManager] = None
        self.batch_processor: Optional[BatchDataProcessor] = None
        self.authz_tester: Optional[DifferentialAuthzTester] = None
        
        # Results
        self.crawl_results: Optional[Path] = None
        self.enriched_data: Optional[Path] = None
        self.authz_results: List = []
        
        logger.info(f"ASRTS pipeline initialized, output: {self.output_dir}")
    
    async def run_full_pipeline(
        self,
        seed_urls: Optional[List[str]] = None,
        crawl_config: Optional[CrawlConfig] = None,
    ):
        """
        Run the complete pipeline from crawling to testing.
        
        Args:
            seed_urls: Optional seed URLs (uses config if not provided)
            crawl_config: Optional crawl configuration
        """
        logger.info("=" * 80)
        logger.info("STARTING ASRTS FULL PIPELINE")
        logger.info("=" * 80)
        
        # Phase 1: Initialize sessions
        logger.info("\n[PHASE 1] Initializing multi-role sessions...")
        await self._initialize_sessions()
        
        # Phase 2: Intelligent crawling
        logger.info("\n[PHASE 2] Running intelligent crawler...")
        await self._run_crawler(seed_urls, crawl_config)
        
        # Phase 3: Data processing and enrichment
        logger.info("\n[PHASE 3] Processing and enriching captured data...")
        await self._process_data()
        
        # Phase 4: Differential authorization testing
        logger.info("\n[PHASE 4] Running differential authorization tests...")
        await self._run_authz_tests()
        
        # Phase 5: Generate reports
        logger.info("\n[PHASE 5] Generating reports...")
        self._generate_reports()
        
        logger.info("\n" + "=" * 80)
        logger.info("PIPELINE COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Results saved to: {self.output_dir}")
    
    async def _initialize_sessions(self):
        """Initialize multi-role session manager."""
        if not self.engagement_config.test_identities:
            logger.warning("No test identities configured, skipping session initialization")
            return
        
        # Get base URL from target domains
        base_url = self.engagement_config.target_domains[0]
        
        self.session_manager = MultiRoleSessionManager(
            base_url=base_url,
            health_check_url=f"{base_url}/api/me",
        )
        
        # Register identities from config
        for identity in self.engagement_config.test_identities:
            role = identity.get("role")
            creds_data = identity.get("credentials", {})
            
            credentials = SessionCredentials(
                role=role,
                username=creds_data.get("username"),
                password=creds_data.get("password"),
                token=creds_data.get("token"),
            )
            
            # Get login sequence if available
            login_seq_ref = identity.get("login_sequence_ref")
            login_sequence = None
            
            if login_seq_ref:
                # Load login sequence from file
                seq_path = Path(login_seq_ref)
                if seq_path.exists():
                    import json
                    with open(seq_path) as f:
                        login_sequence = json.load(f)
            
            self.session_manager.register_identity(
                role=role,
                credentials=credentials,
                login_sequence=login_sequence,
            )
        
        # Initialize all sessions
        await self.session_manager.initialize_sessions()
        
        logger.info(f"Initialized {len(self.session_manager.get_all_roles())} role sessions")
    
    async def _run_crawler(
        self,
        seed_urls: Optional[List[str]],
        crawl_config: Optional[CrawlConfig],
    ):
        """Run the intelligent crawler."""
        # Use seed URLs from config if not provided
        if not seed_urls:
            seed_urls = self.engagement_config.target_domains
        
        # Create crawler
        config = crawl_config or CrawlConfig(
            max_pages=10000,
            max_depth=10,
            max_concurrent=5,
        )
        
        crawl_output = self.output_dir / "crawl"
        self.crawler = EnhancedCrawler(
            scope_validator=self.scope_validator,
            config=config,
            output_dir=crawl_output,
        )
        
        # Get session cookies if available
        session_cookies = None
        if self.session_manager:
            # Use admin session for crawling
            admin_session = await self.session_manager.get_session("admin")
            if admin_session:
                session_cookies = [
                    {"name": k, "value": v, "domain": "", "path": "/"}
                    for k, v in admin_session.cookies.items()
                ]
        
        # Run crawler
        await self.crawler.crawl(seed_urls, session_cookies)
        
        self.crawl_results = crawl_output / "captured_requests.json"
        
        logger.info(f"Crawl complete: {self.crawler.stats.pages_crawled} pages")
    
    async def _process_data(self):
        """Process captured data and extract insertion points."""
        if not self.crawl_results or not self.crawl_results.exists():
            logger.warning("No crawl results to process")
            return
        
        process_output = self.output_dir / "processed"
        self.batch_processor = BatchDataProcessor(
            output_dir=process_output,
            batch_size=100,
            enable_warc=True,
        )
        
        # Process captured requests
        self.enriched_data = await self.batch_processor.process_captured_requests(
            requests_file=self.crawl_results,
            engagement_id=self.engagement_config.engagement_id,
        )
        
        stats = self.batch_processor.get_stats()
        logger.info(
            f"Processing complete: {stats['requests_processed']} requests, "
            f"{stats['insertion_points_extracted']} insertion points"
        )
    
    async def _run_authz_tests(self):
        """Run differential authorization tests."""
        if not self.session_manager:
            logger.warning("No session manager, skipping authorization tests")
            return
        
        if not self.enriched_data or not self.enriched_data.exists():
            logger.warning("No enriched data, skipping authorization tests")
            return
        
        # Create authz tester
        authz_output = self.output_dir / "authz_tests"
        self.authz_tester = DifferentialAuthzTester(
            session_manager=self.session_manager,
            output_dir=authz_output,
        )
        
        # Load enriched requests
        import json
        with open(self.enriched_data) as f:
            enriched_requests = json.load(f)
        
        logger.info(f"Testing {len(enriched_requests)} endpoints for authorization issues")
        
        # Test each endpoint
        for req in enriched_requests[:100]:  # Limit for demo
            try:
                await self.authz_tester.test_endpoint(
                    method=req["method"],
                    url=req["url"],
                    headers=req.get("headers"),
                    body=req.get("body", "").encode() if req.get("body") else None,
                    baseline_role="admin",
                )
            except Exception as e:
                logger.debug(f"Error testing {req['url']}: {e}")
        
        # Save results
        self.authz_tester.save_results()
        
        stats = self.authz_tester.get_stats()
        logger.info(
            f"Authorization testing complete: {stats['tests_run']} tests, "
            f"{stats['vulnerabilities_found']} vulnerabilities found"
        )
        
        self.authz_results = self.authz_tester.get_vulnerabilities()
    
    def _generate_reports(self):
        """Generate final reports."""
        report_dir = self.output_dir / "reports"
        report_dir.mkdir(exist_ok=True)
        
        # Executive summary
        summary = self._create_executive_summary()
        summary_file = report_dir / "executive_summary.md"
        with open(summary_file, "w") as f:
            f.write(summary)
        
        logger.info(f"Executive summary: {summary_file}")
        
        # Vulnerability report
        if self.authz_results:
            vuln_report = self._create_vulnerability_report()
            vuln_file = report_dir / "vulnerabilities.md"
            with open(vuln_file, "w") as f:
                f.write(vuln_report)
            
            logger.info(f"Vulnerability report: {vuln_file}")
    
    def _create_executive_summary(self) -> str:
        """Create executive summary report."""
        lines = [
            "# ASRTS Executive Summary",
            "",
            f"**Engagement:** {self.engagement_config.name}",
            f"**Target:** {', '.join(self.engagement_config.target_domains)}",
            f"**Date:** {self.engagement_config.engagement_id}",
            "",
            "## Coverage",
            "",
        ]
        
        if self.crawler:
            lines.extend([
                f"- **Pages Crawled:** {self.crawler.stats.pages_crawled}",
                f"- **APIs Discovered:** {self.crawler.stats.apis_discovered}",
                f"- **Forms Found:** {self.crawler.stats.forms_found}",
                f"- **Network Requests:** {self.crawler.stats.network_requests_captured}",
                "",
            ])
        
        if self.batch_processor:
            stats = self.batch_processor.get_stats()
            lines.extend([
                "## Data Analysis",
                "",
                f"- **Requests Processed:** {stats['requests_processed']}",
                f"- **Insertion Points:** {stats['insertion_points_extracted']}",
                f"- **WARC Records:** {stats['warc_records_written']}",
                "",
            ])
        
        if self.authz_tester:
            stats = self.authz_tester.get_stats()
            lines.extend([
                "## Security Findings",
                "",
                f"- **Authorization Tests:** {stats['tests_run']}",
                f"- **Vulnerabilities Found:** {stats['vulnerabilities_found']}",
                f"  - BOLA: {stats['bola_found']}",
                f"  - IDOR: {stats['idor_found']}",
                f"  - Privilege Escalation: {stats['privilege_escalation_found']}",
                "",
            ])
        
        return "\n".join(lines)
    
    def _create_vulnerability_report(self) -> str:
        """Create detailed vulnerability report."""
        lines = [
            "# Vulnerability Report",
            "",
            f"**Total Vulnerabilities:** {len(self.authz_results)}",
            "",
        ]
        
        for i, vuln in enumerate(self.authz_results, 1):
            lines.extend([
                f"## {i}. {vuln.vulnerability_type.upper()}",
                "",
                f"**Endpoint:** `{vuln.endpoint}`",
                f"**URL:** {vuln.url}",
                f"**Confidence:** {vuln.confidence:.2%}",
                "",
                "**Details:**",
                f"- Test Role: {vuln.test_role}",
                f"- Baseline Role: {vuln.baseline_role}",
                f"- Test Status: {vuln.test_status}",
                f"- Baseline Status: {vuln.baseline_status}",
                "",
                "**Evidence:**",
                f"```json",
                f"{vuln.evidence}",
                f"```",
                "",
                "---",
                "",
            ])
        
        return "\n".join(lines)
    
    def get_summary(self) -> Dict:
        """Get pipeline summary statistics."""
        summary = {
            "engagement": self.engagement_config.name,
            "target_domains": self.engagement_config.target_domains,
        }
        
        if self.crawler:
            summary["crawl"] = self.crawler.stats.__dict__
        
        if self.batch_processor:
            summary["processing"] = self.batch_processor.get_stats()
        
        if self.authz_tester:
            summary["authorization"] = self.authz_tester.get_stats()
        
        if self.session_manager:
            summary["sessions"] = self.session_manager.get_stats()
        
        return summary
