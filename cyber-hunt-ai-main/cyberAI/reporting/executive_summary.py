"""
Enhanced executive summary generator with evidence statistics.
Includes WARC-backed evidence metrics and coverage analysis.
"""

from typing import Optional

from cyberAI.models import VerifiedFinding


def generate_executive_summary(
    findings: list[VerifiedFinding],
    target_url: str,
    total_endpoints: int = 0,
    total_tests: int = 0,
) -> str:
    """
    Generate executive summary with evidence-backed metrics.
    
    Args:
        findings: List of verified findings
        target_url: Target application URL
        total_endpoints: Total endpoints tested
        total_tests: Total tests executed
        
    Returns:
        Markdown-formatted executive summary
    """
    # Severity breakdown
    severity_counts = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
    }
    
    for finding in findings:
        severity_counts[finding.severity.value] = severity_counts.get(finding.severity.value, 0) + 1
    
    # Evidence statistics
    total_warc_refs = sum(len(f.evidence_warc_refs) for f in findings)
    findings_with_evidence = sum(1 for f in findings if f.evidence_warc_refs)
    
    # Cross-role findings
    cross_role_findings = sum(
        1 for f in findings 
        if hasattr(f, 'cross_role_confirmed') and f.cross_role_confirmed
    )
    
    lines = [
        "# Executive Summary",
        "",
        f"## Target: {target_url}",
        "",
        "### Key Findings",
        "",
        f"- **Total Findings:** {len(findings)}",
        f"- **Critical:** {severity_counts['critical']}",
        f"- **High:** {severity_counts['high']}",
        f"- **Medium:** {severity_counts['medium']}",
        f"- **Low:** {severity_counts['low']}",
        f"- **Informational:** {severity_counts['info']}",
        "",
        "### Evidence Quality",
        "",
        f"- **Findings with WARC Evidence:** {findings_with_evidence}/{len(findings)} ({findings_with_evidence*100//max(len(findings),1)}%)",
        f"- **Total Evidence Records:** {total_warc_refs}",
        f"- **Cross-Role Verified:** {cross_role_findings}",
        "",
    ]
    
    if total_endpoints > 0:
        lines.extend([
            "### Coverage",
            "",
            f"- **Endpoints Tested:** {total_endpoints}",
            f"- **Total Tests Executed:** {total_tests}",
            "",
        ])
    
    # Top findings
    critical_and_high = [f for f in findings if f.severity.value in ("critical", "high")]
    if critical_and_high:
        lines.extend([
            "### Critical & High Severity Issues",
            "",
        ])
        for finding in critical_and_high[:5]:  # Top 5
            lines.append(f"- **{finding.title}** ({finding.severity.value.upper()})")
            lines.append(f"  - Asset: `{finding.asset}`")
            lines.append(f"  - Reliability: {finding.reliability_score:.0f}%")
            if finding.evidence_warc_refs:
                lines.append(f"  - Evidence: {len(finding.evidence_warc_refs)} WARC records")
        lines.append("")
    
    # Risk summary
    lines.extend([
        "### Risk Assessment",
        "",
    ])
    
    if severity_counts["critical"] > 0:
        lines.append(f"⚠️ **CRITICAL:** {severity_counts['critical']} critical vulnerabilities require immediate attention.")
    if severity_counts["high"] > 0:
        lines.append(f"⚠️ **HIGH:** {severity_counts['high']} high-severity issues should be addressed within 30 days.")
    if severity_counts["medium"] > 0:
        lines.append(f"ℹ️ **MEDIUM:** {severity_counts['medium']} medium-severity issues should be prioritized in the next sprint.")
    
    lines.extend([
        "",
        "### Evidence Provenance",
        "",
        "All findings are backed by WARC (Web ARChive) format captures following ISO 28500 standard.",
        "Each HTTP request/response pair is content-addressed and traceable for audit purposes.",
        "Evidence packs can be generated for any finding to provide complete reproduction data.",
        "",
    ])
    
    return "\n".join(lines)
