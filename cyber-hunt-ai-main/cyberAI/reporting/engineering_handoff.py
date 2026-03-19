"""
Enhanced engineering handoff generator with evidence references.
Provides technical details and remediation guidance for development teams.
"""

from cyberAI.models import PatternCluster, VerifiedFinding


def generate_engineering_handoff(
    findings: list[VerifiedFinding],
    pattern_clusters: list[PatternCluster],
) -> str:
    """
    Generate engineering handoff document.
    
    Args:
        findings: List of verified findings
        pattern_clusters: Grouped findings by pattern
        
    Returns:
        Markdown-formatted engineering handoff
    """
    lines = [
        "# Engineering Handoff",
        "",
        "## Overview",
        "",
        f"This document provides technical details for {len(findings)} verified security findings.",
        "Each finding includes reproduction steps, evidence references, and remediation guidance.",
        "",
        "## Pattern-Based Remediation",
        "",
        "Findings are grouped by root cause to enable efficient batch fixes:",
        "",
    ]
    
    # Pattern clusters
    for cluster in pattern_clusters:
        lines.extend([
            f"### {cluster.pattern_name}",
            "",
            f"**Root Cause:** {cluster.root_cause}",
            f"**Affected Endpoints:** {len(cluster.affected_endpoints)}",
            f"**Fix Complexity:** {cluster.fix_complexity}",
            "",
            f"**Recommended Fix:** {cluster.recommended_fix}",
            "",
            "**Affected Assets:**",
        ])
        for endpoint in cluster.affected_endpoints[:10]:  # Limit to 10
            lines.append(f"- `{endpoint}`")
        if len(cluster.affected_endpoints) > 10:
            lines.append(f"- ... and {len(cluster.affected_endpoints) - 10} more")
        lines.append("")
    
    # Detailed findings
    lines.extend([
        "## Detailed Findings",
        "",
    ])
    
    # Group by severity
    for severity in ["critical", "high", "medium", "low", "info"]:
        severity_findings = [f for f in findings if f.severity.value == severity]
        if not severity_findings:
            continue
        
        lines.extend([
            f"### {severity.upper()} Severity ({len(severity_findings)} findings)",
            "",
        ])
        
        for finding in severity_findings:
            lines.extend([
                f"#### {finding.title}",
                "",
                f"**Finding ID:** `{finding.id}`",
                f"**Asset:** `{finding.asset}`",
                f"**Category:** {finding.category.value}",
                f"**Reliability:** {finding.reliability_score:.0f}%",
                "",
            ])
            
            # Root cause
            if finding.root_cause:
                lines.extend([
                    "**Root Cause:**",
                    finding.root_cause,
                    "",
                ])
            
            # Reproduction
            if finding.reproduction_steps:
                lines.extend([
                    "**Reproduction:**",
                ])
                for step in finding.reproduction_steps[:5]:  # First 5 steps
                    lines.append(f"{step.step_number}. {step.action}")
                lines.append("")
            
            # Evidence
            if finding.evidence_warc_refs:
                lines.extend([
                    f"**Evidence:** {len(finding.evidence_warc_refs)} WARC records available",
                    f"Evidence pack: `evidence_{finding.id}.zip`",
                    "",
                ])
            
            # Verification status
            if hasattr(finding, 'cross_role_confirmed') and finding.cross_role_confirmed:
                lines.append("✅ **Cross-role verified**")
            if hasattr(finding, 'false_positive_ruled_out') and finding.false_positive_ruled_out:
                lines.append("✅ **False positive ruled out**")
            
            lines.append("")
            lines.append("---")
            lines.append("")
    
    # Evidence access instructions
    lines.extend([
        "## Evidence Access",
        "",
        "### WARC Archives",
        "",
        "All HTTP traffic is archived in WARC format (ISO 28500 standard).",
        "Evidence packs are generated per finding and include:",
        "",
        "- Request/response headers (JSON)",
        "- Response bodies (JSON or binary)",
        "- Raw WARC records for audit",
        "- Screenshots (if available)",
        "",
        "### Extracting Evidence",
        "",
        "```bash",
        "# List evidence packs",
        "ls outputs/reports/evidence_packs/",
        "",
        "# Extract a specific pack",
        "unzip outputs/reports/evidence_packs/evidence_<finding_id>.zip -d evidence/",
        "",
        "# View manifest",
        "cat evidence/manifest.json",
        "```",
        "",
    ])
    
    return "\n".join(lines)
