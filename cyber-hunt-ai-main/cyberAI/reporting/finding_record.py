"""
Step 20.1: Finding Record - Generate detailed finding write-ups with evidence provenance.
"""

from cyberAI.models import VerifiedFinding


def generate_finding_record(finding: VerifiedFinding) -> str:
    """
    Generate detailed markdown record for a verified finding.
    Includes WARC evidence references for full audit trail.
    
    Args:
        finding: Verified finding with evidence
        
    Returns:
        Markdown-formatted finding record
    """
    lines = [
        f"# {finding.title}",
        "",
        f"**Finding ID:** `{finding.id}`",
        f"**Severity:** {finding.severity.value.upper()}",
        f"**Category:** {finding.category.value}",
        f"**Asset:** {finding.asset}",
        f"**Reliability Score:** {finding.reliability_score:.1f}/100",
        "",
    ]
    
    # Affected roles and states
    if finding.affected_roles:
        lines.append(f"**Affected Roles:** {', '.join(finding.affected_roles)}")
    if finding.affected_states:
        lines.append(f"**Affected States:** {', '.join(finding.affected_states)}")
    
    lines.append("")
    
    # Description and impact
    lines.extend([
        "## Description",
        "",
        finding.confirmed_impact if hasattr(finding, 'confirmed_impact') and finding.confirmed_impact else "Security vulnerability detected.",
        "",
    ])
    
    # Impact types
    if finding.impact_types:
        lines.extend([
            "## Impact",
            "",
        ])
        for impact in finding.impact_types:
            lines.append(f"- **{impact.value.title()}** impact")
        lines.append("")
    
    # Reproduction steps
    if finding.reproduction_steps:
        lines.extend([
            "## Reproduction Steps",
            "",
        ])
        for step in finding.reproduction_steps:
            lines.append(f"{step.step_number}. {step.action}")
            if step.expected_result:
                lines.append(f"   - Expected: {step.expected_result}")
            if step.actual_result:
                lines.append(f"   - Actual: {step.actual_result}")
        lines.append("")
    
    # Evidence and provenance
    if finding.evidence_warc_refs:
        lines.extend([
            "## Evidence Trail",
            "",
            "All HTTP traffic for this finding is archived in WARC format for audit purposes:",
            "",
        ])
        for idx, ref in enumerate(finding.evidence_warc_refs, 1):
            lines.append(f"{idx}. `{ref}`")
        lines.append("")
        lines.append("*Evidence can be extracted using the evidence pack generator.*")
        lines.append("")
    
    # Exploit chain
    if hasattr(finding, 'exploit_chain') and finding.exploit_chain:
        lines.extend([
            "## Exploit Chain",
            "",
        ])
        for idx, step in enumerate(finding.exploit_chain, 1):
            lines.append(f"{idx}. {step}")
        lines.append("")
    
    # Root cause
    if finding.root_cause:
        lines.extend([
            "## Root Cause",
            "",
            finding.root_cause,
            "",
        ])
    
    # Verification details
    if hasattr(finding, 'verification_method') and finding.verification_method:
        lines.extend([
            "## Verification",
            "",
            f"**Method:** {finding.verification_method}",
        ])
        if hasattr(finding, 'cross_role_confirmed') and finding.cross_role_confirmed:
            lines.append("**Cross-Role Confirmed:** Yes")
        if hasattr(finding, 'false_positive_ruled_out') and finding.false_positive_ruled_out:
            lines.append("**False Positive Ruled Out:** Yes")
        lines.append("")
    
    # Preconditions
    if finding.preconditions:
        lines.extend([
            "## Preconditions",
            "",
        ])
        for precond in finding.preconditions:
            lines.append(f"- {precond}")
        lines.append("")
    
    # CWE/CVSS
    if finding.cwe_id or finding.cvss_score:
        lines.extend([
            "## Classification",
            "",
        ])
        if finding.cwe_id:
            lines.append(f"**CWE:** {finding.cwe_id}")
        if finding.cvss_score:
            lines.append(f"**CVSS Score:** {finding.cvss_score}")
        lines.append("")
    
    return "\n".join(lines)
