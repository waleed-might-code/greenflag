"""
Data Mining Pipeline - Orchestrates massive-scale data extraction.

Integrates:
- Enhanced crawler with adaptive state management
- Insertion point extraction
- API discovery
- WARC evidence storage
- Real-time metrics and monitoring
"""

import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
from loguru import logger

from .enhanced_crawler import EnhancedCrawler
from .api_discovery import APIDiscovery
from ..insertion_points import NestedInsertionPointExtractor, NoveltyTracker
from ..storage.warc_writer import WARCWriter
from ..parsing.encoding_detectors import EncodingDetector


class DataMiningPipeline:
    """
    Complete data mining pipeline for massive-scale extraction.
    
    Capabilities:
    - Multi-phase crawling (sitemap → state-flow → deep forms)
    - API discovery from specs and traffic
    - Nested insertion point extraction
    - WARC evidence with provenance
    - Real-time metrics and progress tracking
    """
    
    def __init__(
        self,
        target_url: str,
        engagement_id: str,
        output_dir: Optional[Path] = None,
        config: Optional[Dict] = None,
    ):
        """
        Initialize data mining pipeline.
        
        Args:
            target_url: Target URL
            engagement_id: Engagement identifier
            output_dir: Output directory
            config: Configuration dict
        """
        self.target_url = target_url
        self.engagement_id = engagement_id
        self.output_dir = output_dir or Path(f"outputs/mining/{engagement_id}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Configuration
        self.config = config or self._default_config()
        
        # Components
        self.crawler = None
        self.api_discovery = APIDiscovery()
        self.insertion_extractor = NestedInsertionPointExtractor(max_depth=3)
        self.novelty_tracker = NoveltyTracker()
        
        # Aggregated data
        self.all_endpoints: List[Dict] = []
        self.all_insertion_points: List[Dict] = []
        self.all_api_specs: List[Dict] = []
        self.captured_traffic: List[Dict] = []
        
        # Metrics
        self.pipeline_metrics = {
            'start_time': None,
            'end_time': None,
            'phases_completed': 0,
            'total_data_points': 0,
            'unique_endpoints': 0,
            'unique_insertion_points': 0,
            'apis_discovered': 0,
        }
    
    def _default_config(self) -> Dict:
        """Get default configuration."""
        return {
            'max_states': 10000,
            'max_depth': 10,
            'enable_api_discovery': True,
            'enable_form_mining': True,
            'enable_js_analysis': True,
            'headless': True,
            'phases': ['api_discovery', 'crawl', 'deep_forms', 'analysis'],
        }
    
    async def run(self) -> Dict[str, Any]:
        """
        Run complete data mining pipeline.
        
        Returns:
            Complete results with all extracted data
        """
        self.pipeline_metrics['start_time'] = datetime.utcnow().isoformat()
        
        logger.info("=" * 80)
        logger.info("🔥 DATA MINING PIPELINE STARTED")
        logger.info("=" * 80)
        logger.info(f"Target: {self.target_url}")
        logger.info(f"Engagement: {self.engagement_id}")
        logger.info(f"Phases: {', '.join(self.config['phases'])}")
        logger.info("=" * 80)
        
        results = {}
        
        # Phase 1: API Discovery
        if 'api_discovery' in self.config['phases']:
            logger.info("\n🔍 PHASE 1: API Discovery")
            api_results = await self._phase_api_discovery()
            results['api_discovery'] = api_results
            self.pipeline_metrics['phases_completed'] += 1
        
        # Phase 2: Enhanced Crawl
        if 'crawl' in self.config['phases']:
            logger.info("\n🕷️  PHASE 2: Enhanced Crawl")
            crawl_results = await self._phase_crawl()
            results['crawl'] = crawl_results
            self.pipeline_metrics['phases_completed'] += 1
        
        # Phase 3: Deep Form Mining
        if 'deep_forms' in self.config['phases']:
            logger.info("\n📝 PHASE 3: Deep Form Mining")
            form_results = await self._phase_deep_forms()
            results['deep_forms'] = form_results
            self.pipeline_metrics['phases_completed'] += 1
        
        # Phase 4: Analysis & Aggregation
        if 'analysis' in self.config['phases']:
            logger.info("\n📊 PHASE 4: Analysis & Aggregation")
            analysis_results = await self._phase_analysis()
            results['analysis'] = analysis_results
            self.pipeline_metrics['phases_completed'] += 1
        
        # Finalize
        self.pipeline_metrics['end_time'] = datetime.utcnow().isoformat()
        results['pipeline_metrics'] = self.pipeline_metrics
        
        # Export everything
        self._export_complete_dataset(results)
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ DATA MINING PIPELINE COMPLETE")
        logger.info("=" * 80)
        self._log_final_summary()
        logger.info("=" * 80)
        
        return results
    
    async def _phase_api_discovery(self) -> Dict[str, Any]:
        """Phase 1: Discover APIs from specs and common paths."""
        logger.info("Discovering APIs from specs and common endpoints...")
        
        try:
            # Discover from common paths
            apis = await self.api_discovery.discover_from_target(self.target_url)
            
            self.all_api_specs.extend(apis)
            self.pipeline_metrics['apis_discovered'] = len(apis)
            
            logger.info(f"✓ Discovered {len(apis)} API endpoints")
            
            return {
                'apis_found': len(apis),
                'specs': apis,
            }
            
        except Exception as e:
            logger.error(f"API discovery error: {e}")
            return {'apis_found': 0, 'error': str(e)}
    
    async def _phase_crawl(self) -> Dict[str, Any]:
        """Phase 2: Run enhanced crawler with adaptive state management."""
        logger.info("Starting enhanced crawl with adaptive state management...")
        
        try:
            self.crawler = EnhancedCrawler(
                target_url=self.target_url,
                engagement_id=self.engagement_id,
                max_states=self.config['max_states'],
                max_depth=self.config['max_depth'],
                output_dir=self.output_dir / "crawl",
                headless=self.config['headless'],
            )
            
            crawl_results = await self.crawler.crawl()
            
            # Aggregate data
            self.pipeline_metrics['total_data_points'] += crawl_results['metrics']['pages_crawled']
            
            logger.info(f"✓ Crawled {crawl_results['metrics']['pages_crawled']} pages")
            logger.info(f"✓ Found {crawl_results['metrics']['insertion_points_found']} insertion points")
            
            return crawl_results
            
        except Exception as e:
            logger.error(f"Crawl error: {e}")
            return {'error': str(e)}
    
    async def _phase_deep_forms(self) -> Dict[str, Any]:
        """Phase 3: Deep form mining and parameter extraction."""
        logger.info("Mining forms and extracting parameters...")
        
        try:
            # This would integrate with form extraction
            # For now, aggregate from crawler results
            
            forms_found = 0
            params_extracted = 0
            
            if self.crawler:
                forms_found = self.crawler.metrics.get('forms_discovered', 0)
                params_extracted = self.crawler.metrics.get('inputs_discovered', 0)
            
            logger.info(f"✓ Mined {forms_found} forms")
            logger.info(f"✓ Extracted {params_extracted} parameters")
            
            return {
                'forms_found': forms_found,
                'parameters_extracted': params_extracted,
            }
            
        except Exception as e:
            logger.error(f"Form mining error: {e}")
            return {'error': str(e)}
    
    async def _phase_analysis(self) -> Dict[str, Any]:
        """Phase 4: Analyze and aggregate all extracted data."""
        logger.info("Analyzing extracted data...")
        
        try:
            # Count unique endpoints
            unique_urls = set()
            if self.crawler:
                # Would extract from crawler state manager
                pass
            
            # Count unique insertion points
            novelty_stats = self.novelty_tracker.get_stats() if self.novelty_tracker else {}
            
            self.pipeline_metrics['unique_endpoints'] = len(unique_urls)
            self.pipeline_metrics['unique_insertion_points'] = novelty_stats.get('novel_shapes', 0)
            
            # Calculate data density
            total_data_points = (
                self.pipeline_metrics.get('total_data_points', 0) +
                len(self.all_api_specs) +
                len(self.all_insertion_points)
            )
            
            self.pipeline_metrics['total_data_points'] = total_data_points
            
            logger.info(f"✓ Total data points extracted: {total_data_points}")
            
            return {
                'total_data_points': total_data_points,
                'unique_endpoints': len(unique_urls),
                'unique_insertion_points': novelty_stats.get('novel_shapes', 0),
                'novelty_stats': novelty_stats,
            }
            
        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return {'error': str(e)}
    
    def _export_complete_dataset(self, results: Dict[str, Any]) -> None:
        """Export complete dataset to JSON."""
        try:
            # Main results file
            results_path = self.output_dir / "complete_dataset.json"
            with open(results_path, 'w') as f:
                json.dump(results, f, indent=2)
            
            logger.info(f"📦 Complete dataset exported to {results_path}")
            
            # Separate files for different data types
            if self.all_api_specs:
                api_path = self.output_dir / "api_endpoints.json"
                with open(api_path, 'w') as f:
                    json.dump(self.all_api_specs, f, indent=2)
                logger.info(f"📦 API endpoints exported to {api_path}")
            
            if self.all_insertion_points:
                ip_path = self.output_dir / "insertion_points.json"
                with open(ip_path, 'w') as f:
                    json.dump(self.all_insertion_points, f, indent=2)
                logger.info(f"📦 Insertion points exported to {ip_path}")
            
        except Exception as e:
            logger.error(f"Export error: {e}")
    
    def _log_final_summary(self) -> None:
        """Log final summary of data mining."""
        logger.info("📈 PIPELINE SUMMARY:")
        logger.info(f"   Phases completed: {self.pipeline_metrics['phases_completed']}")
        logger.info(f"   Total data points: {self.pipeline_metrics['total_data_points']}")
        logger.info(f"   Unique endpoints: {self.pipeline_metrics['unique_endpoints']}")
        logger.info(f"   Unique insertion points: {self.pipeline_metrics['unique_insertion_points']}")
        logger.info(f"   APIs discovered: {self.pipeline_metrics['apis_discovered']}")
        
        if self.crawler:
            logger.info(f"   Data captured: {self.crawler.metrics['bytes_captured'] / 1024 / 1024:.2f} MB")
            logger.info(f"   WARC records: {self.crawler.metrics['warc_records_written']}")
