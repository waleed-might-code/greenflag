"""
Evidence Pack Generator with WARC Integration.
Generates comprehensive evidence packages for verified findings.
"""

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from cyberAI.models import VerifiedFinding
from cyberAI.reporting.warc_evidence_extractor import WARCEvidenceExtractor


class EvidencePackGenerator:
    """
    Generates evidence packs with WARC-backed HTTP captures.
    
    Evidence pack structure:
    - finding_metadata.json: Finding details
    - http_captures/: HTTP request/response pairs from WARC
    - screenshots/: UI screenshots from reproduction steps
    - reproduction_steps.md: Step-by-step reproduction guide
    - evidence_summary.md: Executive summary of evidence
    """
    
    def __init__(self, warc_base_dir: Path | str, output_dir: Path | str):
        """
        Initialize evidence pack generator.
        
        Args:
            warc_base_dir: Base directory containing WARC files
            output_dir: Output directory for evidence packs
        """
        self.warc_extractor = WARCEvidenceExtractor(warc_base_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_pack(
        self,
        finding: VerifiedFinding,
        include_screenshots: bool = True,
        include_http_captures: bool = True,
    ) -> Optional[Path]:
        """
        Generate evidence pack for a finding.
        
        Args:
            finding: Verified finding with WARC references
            include_screenshots: Include screenshots in pack
            include_http_captures: Extract and include HTTP captures from WARC
            
        Returns:
            Path to generated evidence pack ZIP file
        """
        try:
            pack_name = f"evidence_{finding.id}.zip"
            pack_path = self.output_dir / pack_name
            
            with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 1. Finding metadata
                self._add_finding_metadata(zf, finding)
                
                # 2. HTTP captures from WARC
                if include_http_captures and finding.evidence_warc_refs:
                    self._add_http_captures(zf, finding)
                
                # 3. Screenshots
                if include_screenshots:
                    self._add_screenshots(zf, finding)
                
                # 4. Reproduction guide
                self._add_reproduction_guide(zf, finding)
                
                # 5. Evidence summary
                self._add_evidence_summary(zf, finding)
            
            logger.info(f"Generated evidence pack: {pack_path}")
            return pack_path
        
        except Exception as e:
            logger.error(f"Failed to generate evidence pack for {finding.id}: {e}")
            return None
    
    def _add_finding_metadata(self, zf: zipfile.ZipFile, finding: VerifiedFinding):
        """Add finding metadata JSON to pack."""
        metadata = {
            "finding_id": finding.id,
            "title": finding.title,
            "severity": finding.severity.value,
            "category": finding.category.value,
            "asset": finding.asset,
            "status": finding.status.value,
            "reliability_score": finding.reliability_score,
            "affected_roles": finding.affected_roles,
            "impact_types": [i.value for i in finding.impact_types],
            "cvss_score": finding.cvss_score,
            "cwe_ids": finding.cwe_ids,
            "owasp_categories": finding.owasp_categories,
            "root_cause": finding.root_cause,
            "business_impact": finding.business_impact,
            "technical_impact": finding.technical_impact,
            "preconditions": finding.preconditions,
            "evidence_warc_refs": finding.evidence_warc_refs,
            "generated_at": datetime.utcnow().isoformat(),
        }
        
        zf.writestr("finding_metadata.json", json.dumps(metadata, indent=2))
    
    def _add_http_captures(self, zf: zipfile.ZipFile, finding: VerifiedFinding):
        """Extract and add HTTP captures from WARC."""
        captures = self.warc_extractor.extract_multiple(finding.evidence_warc_refs)
        
        for i, capture in enumerate(captures):
            # Add request
            request_content = self._format_http_request(capture)
            zf.writestr(f"http_captures/{i+1:03d}_request.txt", request_content)
            
            # Add response
            response_content = self._format_http_response(capture)
            zf.writestr(f"http_captures/{i+1:03d}_response.txt", response_content)
            
            # Add JSON representation
            zf.writestr(
                f"http_captures/{i+1:03d}_capture.json",
                json.dumps(capture.to_dict(), indent=2)
            )
        
        logger.debug(f"Added {len(captures)} HTTP captures to evidence pack")
    
    def _format_http_request(self, capture) -> str:
        """Format HTTP request for text display."""
        lines = [
            f"{capture.method} {capture.url}",
            "",
            "Request Headers:",
        ]
        
        for key, value in capture.request_headers.items():
            lines.append(f"  {key}: {value}")
        
        lines.append("")
        
        if capture.request_body:
            lines.append("Request Body:")
            body_str = capture.request_body.decode("utf-8", errors="replace")
            lines.append(body_str[:2000])  # Truncate large bodies
            if len(capture.request_body) > 2000:
                lines.append(f"\n... (truncated, {len(capture.request_body)} bytes total)")
        
        return "\n".join(lines)
    
    def _format_http_response(self, capture) -> str:
        """Format HTTP response for text display."""
        lines = [
            f"HTTP {capture.status_code} {capture.reason}",
            "",
            "Response Headers:",
        ]
        
        for key, value in capture.response_headers.items():
            lines.append(f"  {key}: {value}")
        
        lines.append("")
        
        if capture.response_body:
            lines.append("Response Body:")
            body_str = capture.response_body.decode("utf-8", errors="replace")
            lines.append(body_str[:2000])  # Truncate large bodies
            if len(capture.response_body) > 2000:
                lines.append(f"\n... (truncated, {len(capture.response_body)} bytes total)")
        
        return "\n".join(lines)
    
    def _add_screenshots(self, zf: zipfile.ZipFile, finding: VerifiedFinding):
        """Add screenshots from reproduction steps."""
        screenshot_count = 0
        
        for step in finding.reproduction_steps:
            if step.screenshot_path:
                screenshot_path = Path(step.screenshot_path)
                if screenshot_path.exists():
                    # Add screenshot with step number in filename
                    zf.write(
                        screenshot_path,
                        f"screenshots/step_{step.step_number:02d}_{screenshot_path.name}"
                    )
                    screenshot_count += 1
        
        if screenshot_count > 0:
            logger.debug(f"Added {screenshot_count} screenshots to evidence pack")
    
    def _add_reproduction_guide(self, zf: zipfile.ZipFile, finding: VerifiedFinding):
        """Add step-by-step reproduction guide."""
        lines = [
            f"# Reproduction Guide: {finding.title}",
            "",
            f"**Finding ID:** {finding.id}",
            f"**Severity:** {finding.severity.value.upper()}",
            f"**Asset:** {finding.asset}",
            "",
            "## Prerequisites",
            "",
        ]
        
        if finding.preconditions:
            for precondition in finding.preconditions:
                lines.append(f"- {precondition}")
        else:
            lines.append("- No special prerequisites")
        
        lines.extend([
            "",
            "## Reproduction Steps",
            "",
        ])
        
        for step in finding.reproduction_steps:
            lines.append(f"### Step {step.step_number}: {step.action}")
            lines.append("")
            
            if step.expected_result:
                lines.append(f"**Expected:** {step.expected_result}")
            
            if step.actual_result:
                lines.append(f"**Actual:** {step.actual_result}")
            
            if step.screenshot_path:
                screenshot_name = Path(step.screenshot_path).name
                lines.append(f"**Screenshot:** `screenshots/step_{step.step_number:02d}_{screenshot_name}`")
            
            lines.append("")
        
        lines.extend([
            "## State Comparison",
            "",
            "### Before State",
            f"```json",
            json.dumps(finding.before_state, indent=2) if finding.before_state else "{}",
            "```",
            "",
            "### After State",
            f"```json",
            json.dumps(finding.after_state, indent=2) if finding.after_state else "{}",
            "```",
        ])
        
        zf.writestr("reproduction_guide.md", "\n".join(lines))
    
    def _add_evidence_summary(self, zf: zipfile.ZipFile, finding: VerifiedFinding):
        """Add executive evidence summary."""
        lines = [
            f"# Evidence Summary: {finding.title}",
            "",
            f"**Finding ID:** {finding.id}",
            f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "## Overview",
            "",
            f"**Severity:** {finding.severity.value.upper()}",
            f"**Category:** {finding.category.value}",
            f"**Reliability Score:** {finding.reliability_score:.2f}/1.0",
            f"**Status:** {finding.status.value}",
            "",
            "## Impact",
            "",
            f"**Business Impact:** {finding.business_impact}",
            "",
            f"**Technical Impact:** {finding.technical_impact}",
            "",
            f"**Affected Roles:** {', '.join(finding.affected_roles) if finding.affected_roles else 'All users'}",
            "",
            "## Evidence Artifacts",
            "",
        ]
        
        # List HTTP captures
        if finding.evidence_warc_refs:
            lines.append(f"- **HTTP Captures:** {len(finding.evidence_warc_refs)} request/response pairs")
            lines.append("  - See `http_captures/` directory for full details")
        
        # List screenshots
        screenshot_count = sum(1 for step in finding.reproduction_steps if step.screenshot_path)
        if screenshot_count > 0:
            lines.append(f"- **Screenshots:** {screenshot_count} UI captures")
            lines.append("  - See `screenshots/` directory")
        
        lines.extend([
            "",
            "## WARC References",
            "",
        ])
        
        if finding.evidence_warc_refs:
            for i, ref in enumerate(finding.evidence_warc_refs, 1):
                lines.append(f"{i}. `{ref}`")
        else:
            lines.append("No WARC references available.")
        
        lines.extend([
            "",
            "## Remediation Priority",
            "",
            f"**Root Cause:** {finding.root_cause or 'Not specified'}",
            "",
            f"**CVSS Score:** {finding.cvss_score or 'Not calculated'}",
            "",
            "**CWE IDs:**",
        ])
        
        if finding.cwe_ids:
            for cwe in finding.cwe_ids:
                lines.append(f"- {cwe}")
        else:
            lines.append("- Not mapped")
        
        lines.extend([
            "",
            "**OWASP Categories:**",
        ])
        
        if finding.owasp_categories:
            for cat in finding.owasp_categories:
                lines.append(f"- {cat}")
        else:
            lines.append("- Not mapped")
        
        zf.writestr("evidence_summary.md", "\n".join(lines))


def generate_evidence_pack(
    finding: VerifiedFinding,
    warc_base_dir: Path | str,
    output_dir: Path | str,
) -> Optional[Path]:
    """
    Convenience function to generate an evidence pack.
    
    Args:
        finding: Verified finding with WARC references
        warc_base_dir: Base directory containing WARC files
        output_dir: Output directory for evidence pack
        
    Returns:
        Path to generated evidence pack ZIP file
    """
    generator = EvidencePackGenerator(warc_base_dir, output_dir)
    return generator.generate_pack(finding)
