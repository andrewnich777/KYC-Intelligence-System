"""
PDF Generator - Converts markdown briefs to professionally styled PDFs.

Uses fpdf2 for pure Python PDF generation (no external dependencies).
"""

import logging
import re
import unicodedata
from datetime import datetime
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

logger = logging.getLogger(__name__)


# Color schemes for KYC document types
COLORS = {
    "Compliance": {
        "primary": (30, 58, 138),       # Deep blue
        "secondary": (29, 78, 216),
        "accent": (219, 234, 254),
        "highlight": (59, 130, 246),
    },
    "Onboarding": {
        "primary": (22, 101, 52),       # Green
        "secondary": (21, 128, 61),
        "accent": (220, 252, 231),
        "highlight": (34, 197, 94),
    },
    "AML": {
        "primary": (30, 58, 138),       # Deep blue (investigative)
        "secondary": (29, 78, 216),
        "accent": (219, 234, 254),
        "highlight": (59, 130, 246),
    },
    "Risk": {
        "primary": (180, 83, 9),        # Amber
        "secondary": (217, 119, 6),
        "accent": (254, 243, 199),
        "highlight": (245, 158, 11),
    },
    "Regulatory": {
        "primary": (88, 28, 135),       # Purple
        "secondary": (126, 34, 206),
        "accent": (243, 232, 255),
        "highlight": (168, 85, 247),
    },
}

# Risk level color bands for KYC
RISK_LEVEL_COLORS = {
    "LOW": (34, 197, 94),       # Green
    "MEDIUM": (234, 179, 8),    # Yellow
    "HIGH": (249, 115, 22),     # Orange
    "CRITICAL": (220, 38, 38),  # Red
}

# Evidence classification badge colors (V/S/I/U system)
EVIDENCE_COLORS = {
    "V": {"bg": (220, 252, 231), "text": (22, 101, 52), "label": "[V] Verified"},
    "S": {"bg": (254, 249, 195), "text": (133, 77, 14), "label": "[S] Sourced"},
    "I": {"bg": (219, 234, 254), "text": (30, 64, 175), "label": "[I] Inferred"},
    "U": {"bg": (243, 244, 246), "text": (107, 114, 128), "label": "[U] Unknown"},
}

# Source tier badges
SOURCE_TIER_LABELS = {
    "TIER_0": {"label": "Official", "color": (22, 101, 52)},
    "TIER_1": {"label": "Verified", "color": (30, 64, 175)},
    "TIER_2": {"label": "Inferred", "color": (107, 114, 128)},
}


def sanitize_text(text: str) -> str:
    """Sanitize text for PDF output - replace problematic Unicode chars."""
    replacements = {
        '\u2014': '-',   # em-dash
        '\u2013': '-',   # en-dash
        '\u2018': "'",   # left single quote
        '\u2019': "'",   # right single quote
        '\u201c': '"',   # left double quote
        '\u201d': '"',   # right double quote
        '\u2026': '...', # ellipsis
        '\u00a0': ' ',   # non-breaking space
        '\u2022': '*',   # bullet
        '\u2023': '>',   # triangular bullet
        '\u25cf': '*',   # black circle
        '\u2192': '->',  # right arrow
        '\u2190': '<-',  # left arrow
        '\u2122': '(TM)', # trademark
        '\u00ae': '(R)',  # registered
        '\u00a9': '(C)',  # copyright
        '\U0001F7E2': '[V]',  # green circle -> Verified
        '\U0001F7E1': '[S]',  # yellow circle -> Sourced
        '\U0001F534': '[U]',  # red circle -> Unknown
        '\U0001F7E0': '[I]',  # orange circle -> Inferred
        '\u26AA': '[?]',      # white circle
        '\u2705': '[v]',      # check mark
        '\u274C': '[x]',      # cross mark
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Normalize Unicode (e.g. ligatures, accented chars) then strip non-latin1
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('latin-1', errors='replace').decode('latin-1')
    return text


class BriefPDF(FPDF):
    """Custom PDF class for KYC compliance documents."""

    def __init__(self, brief_type: str = "Compliance", title: str = "KYC Report"):
        super().__init__()
        self.brief_type = brief_type
        self.doc_title = sanitize_text(title)
        self.colors = COLORS.get(brief_type, COLORS["Compliance"])

        # Set up fonts
        self.add_page()
        self.set_auto_page_break(auto=True, margin=25)

    def header(self):
        """Add header to each page."""
        if self.page_no() == 1:
            # First page header with colored banner
            self.set_fill_color(*self.colors["primary"])
            self.rect(0, 0, 210, 35, 'F')

            self.set_text_color(255, 255, 255)
            self.set_font("Helvetica", "B", 20)
            self.set_xy(15, 10)
            self.cell(0, 10, f"{self.doc_title}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            self.set_font("Helvetica", "", 11)
            self.set_xy(15, 22)
            self.cell(0, 6, f"{self.brief_type} Report | KYC Onboarding Intelligence", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            self.set_text_color(0, 0, 0)
            self.ln(15)
        else:
            # Subsequent pages - simple header
            self.set_font("Helvetica", "I", 9)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, f"{self.doc_title} - {self.brief_type} Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_text_color(0, 0, 0)
            self.ln(5)

    def footer(self):
        """Add footer to each page."""
        self.set_y(-20)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)

        # Page number
        self.cell(0, 10, f"Page {self.page_no()}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Generation timestamp on first page
        if self.page_no() == 1:
            self.set_y(-15)
            self.set_font("Helvetica", "I", 7)
            timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
            self.cell(0, 5, f"Generated by KYC Onboarding Intelligence System | {timestamp}", align="C")

        self.set_text_color(0, 0, 0)

    def section_header(self, text: str, level: int = 2):
        """Add a section header."""
        text = sanitize_text(text)
        self.ln(5)

        if level == 1:
            self.set_font("Helvetica", "B", 16)
            self.set_text_color(*self.colors["primary"])
        elif level == 2:
            self.set_font("Helvetica", "B", 13)
            self.set_text_color(31, 41, 55)
            # Add underline
            self.cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_draw_color(229, 231, 235)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(3)
            self.set_text_color(0, 0, 0)
            return
        elif level == 3:
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(55, 65, 81)
        else:
            self.set_font("Helvetica", "B", 10)
            self.set_text_color(75, 85, 99)

        self.cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def paragraph(self, text: str):
        """Add a paragraph of text."""
        self.set_font("Helvetica", "", 10)
        self.set_text_color(31, 41, 55)
        self.set_x(self.l_margin)
        self.multi_cell(0, 5, sanitize_text(text))
        self.ln(2)
        self.set_text_color(0, 0, 0)

    def bullet_point(self, text: str, indent: int = 0):
        """Add a bullet point."""
        self.set_font("Helvetica", "", 10)
        x = self.l_margin + (indent * 5)
        self.set_x(x)

        # Bullet character
        self.set_text_color(*self.colors["primary"])
        self.cell(5, 5, "*", new_x=XPos.RIGHT)

        # Text
        self.set_text_color(31, 41, 55)
        remaining_width = self.w - self.r_margin - self.get_x()
        self.multi_cell(remaining_width, 5, sanitize_text(text))
        self.set_text_color(0, 0, 0)

    def quote_block(self, text: str, source: str = None):
        """Add a styled quote block."""
        self.ln(3)

        text = sanitize_text(text)
        if source:
            source = sanitize_text(source)

        start_y = self.get_y()

        # Quote text with background fill
        self.set_fill_color(*self.colors["accent"])
        self.set_x(self.l_margin + 5)
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(30, 64, 175)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 10, 5, f'"{text}"', fill=True)

        # Source attribution
        if source:
            self.set_font("Helvetica", "", 8)
            self.set_text_color(107, 114, 128)
            self.set_x(self.l_margin + 5)
            self.set_fill_color(*self.colors["accent"])
            self.cell(0, 5, f"- {source}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)

        end_y = self.get_y()

        # Draw left border accent line
        self.set_draw_color(*self.colors["primary"])
        self.set_line_width(1)
        self.line(self.l_margin, start_y, self.l_margin, end_y)

        self.set_text_color(0, 0, 0)
        self.set_line_width(0.2)
        self.ln(3)

    def table_start(self, headers: list[str]):
        """Start a table with headers."""
        self._row_count = 0
        self.ln(3)
        col_width = (self.w - self.l_margin - self.r_margin) / len(headers)

        # Header row
        self.set_fill_color(243, 244, 246)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(55, 65, 81)

        for header in headers:
            self.cell(col_width, 8, sanitize_text(header), border=1, align="L", fill=True)
        self.ln()

        self.set_font("Helvetica", "", 9)
        self.set_text_color(0, 0, 0)
        self._table_col_width = col_width
        self._table_cols = len(headers)

    def table_row(self, cells: list[str]):
        """Add a row to the current table."""
        col_width = self._table_col_width

        if hasattr(self, '_row_count'):
            self._row_count += 1
        else:
            self._row_count = 0

        if self._row_count % 2 == 1:
            self.set_fill_color(249, 250, 251)
            fill = True
        else:
            fill = False

        for cell in cells:
            cell_text = sanitize_text(str(cell))
            if len(cell_text) > 40:
                cell_text = cell_text[:37] + "..."
            self.cell(col_width, 7, cell_text, border=1, align="L", fill=fill)
        self.ln()

    def table_end(self):
        """End the current table."""
        self._row_count = 0
        self.ln(3)

    def evidence_badge(self, level: str, x: float = None, y: float = None):
        """Draw an evidence classification badge (V/S/I/U)."""
        if x is None:
            x = self.get_x()
        if y is None:
            y = self.get_y()

        style = EVIDENCE_COLORS.get(level, EVIDENCE_COLORS["U"])

        badge_width = 28
        badge_height = 5

        self.set_fill_color(*style["bg"])
        self.rect(x, y, badge_width, badge_height, 'F')

        self.set_font("Helvetica", "B", 6)
        self.set_text_color(*style["text"])
        self.set_xy(x, y + 0.5)
        self.cell(badge_width, badge_height - 1, style["label"], align="C")

        self.set_text_color(0, 0, 0)
        return badge_width

    def risk_level_badge(self, risk_level: str):
        """Draw a risk level indicator badge."""
        color = RISK_LEVEL_COLORS.get(risk_level, (128, 128, 128))
        self.set_fill_color(*color)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(255, 255, 255)
        self.set_x(self.l_margin)
        self.cell(50, 8, f"  RISK: {risk_level}  ", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(5)

    def source_tier_badge(self, tier: str, x: float = None, y: float = None):
        """Draw a source tier badge."""
        if x is None:
            x = self.get_x()
        if y is None:
            y = self.get_y()

        tier_style = SOURCE_TIER_LABELS.get(tier, SOURCE_TIER_LABELS["TIER_2"])

        self.set_font("Helvetica", "I", 6)
        self.set_text_color(*tier_style["color"])
        self.set_xy(x, y)
        self.cell(25, 4, tier_style["label"])

        self.set_text_color(0, 0, 0)


def parse_markdown_to_pdf(md_content: str, pdf: BriefPDF):
    """Parse markdown content and add to PDF."""
    lines = md_content.split('\n')
    i = 0
    in_table = False

    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        # Headers
        if line.startswith('# '):
            # Skip the main title (handled in header)
            i += 1
            continue
        elif line.startswith('## '):
            if in_table:
                pdf.table_end()
                in_table = False
            pdf.section_header(line[3:], 2)
        elif line.startswith('### '):
            if in_table:
                pdf.table_end()
                in_table = False
            pdf.section_header(line[4:], 3)
        elif line.startswith('#### '):
            if in_table:
                pdf.table_end()
                in_table = False
            pdf.section_header(line[5:], 4)

        # Blockquotes
        elif line.startswith('>'):
            if in_table:
                pdf.table_end()
                in_table = False

            quote_text = line[1:].strip()
            source = None

            if i + 1 < len(lines) and lines[i + 1].strip().startswith('>'):
                next_line = lines[i + 1].strip()[1:].strip()
                if next_line.startswith('\u2014') or next_line.startswith('-'):
                    source = next_line.lstrip('\u2014- ').strip()
                    i += 1

            pdf.quote_block(quote_text, source)

        # Tables
        elif line.startswith('|'):
            # Handle escaped pipes inside table cells
            line_for_split = line.replace('\\|', '\x00')
            cells = [c.strip().replace('\x00', '|') for c in line_for_split.split('|')[1:-1]]

            if all(c.replace('-', '').replace(':', '') == '' for c in cells):
                i += 1
                continue

            if not in_table:
                pdf.table_start(cells)
                in_table = True
            else:
                pdf.table_row(cells)

        # Bullet points
        elif line.startswith('- ') or line.startswith('* '):
            if in_table:
                pdf.table_end()
                in_table = False
            text = line[2:].strip()
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            pdf.bullet_point(text)

        # Numbered lists
        elif re.match(r'^\d+\.\s', line):
            if in_table:
                pdf.table_end()
                in_table = False
            text = re.sub(r'^\d+\.\s*', '', line)
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            pdf.bullet_point(text)

        # Horizontal rules
        elif line.startswith('---') or line.startswith('***'):
            if in_table:
                pdf.table_end()
                in_table = False
            pdf.ln(5)

        # Bold text line
        elif line.startswith('**') and line.endswith('**'):
            if in_table:
                pdf.table_end()
                in_table = False
            text = sanitize_text(line.strip('*'))
            try:
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, 5, text)
                pdf.set_font("Helvetica", "", 10)
            except Exception as e:
                logger.warning("PDF bold text rendering failed: %s", e)

        # Regular paragraph
        elif not line.startswith('*Generated'):
            if in_table:
                pdf.table_end()
                in_table = False
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            text = re.sub(r'\^\S+\d+\^', '', text)
            if text.strip():
                try:
                    pdf.paragraph(text)
                except Exception as e:
                    logger.warning("PDF paragraph rendering failed: %s", e)

        i += 1

    if in_table:
        pdf.table_end()


def _build_executive_summary_page(pdf: BriefPDF, kyc_output: "Any") -> None:
    """Add a one-page executive risk summary to the PDF.

    This is the "glanceable" page 1 that compliance officers use
    to make quick approve/escalate/reject decisions.
    """
    cd = kyc_output.client_data or {}
    client_name = cd.get("full_name") or cd.get("legal_name", "Unknown")

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*pdf.colors["primary"])
    pdf.cell(0, 10, "EXECUTIVE RISK SUMMARY", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Separator line
    pdf.set_draw_color(*pdf.colors["primary"])
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)

    # Client info block
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(31, 41, 55)
    pdf.cell(0, 6, f"Client: {sanitize_text(client_name)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 6, f"Type: {kyc_output.client_type.value.upper()}    ID: {kyc_output.client_id}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 6, f"Date: {kyc_output.generated_at.strftime('%Y-%m-%d')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    # Risk level badge (large)
    risk_level = "N/A"
    risk_score = 0
    if kyc_output.synthesis and kyc_output.synthesis.revised_risk_assessment:
        ra = kyc_output.synthesis.revised_risk_assessment
        risk_level = ra.risk_level.value
        risk_score = ra.total_score
    elif kyc_output.intake_classification and kyc_output.intake_classification.preliminary_risk:
        ra = kyc_output.intake_classification.preliminary_risk
        risk_level = ra.risk_level.value
        risk_score = ra.total_score

    color = RISK_LEVEL_COLORS.get(risk_level, (128, 128, 128))
    pdf.set_fill_color(*color)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(60, 12, f"  RISK: {risk_level}  ", fill=True)

    pdf.set_text_color(31, 41, 55)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(5, 12, "")  # spacer
    pdf.cell(0, 12, f"Overall Risk Score: {risk_score}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Evidence quality + decision
    evidence_grade = "N/A"
    if kyc_output.review_intelligence and kyc_output.review_intelligence.confidence:
        conf = kyc_output.review_intelligence.confidence
        evidence_grade = f"Grade {conf.overall_confidence_grade} (V:{conf.verified_pct:.0f}% S:{conf.sourced_pct:.0f}% I:{conf.inferred_pct:.0f}% U:{conf.unknown_pct:.0f}%)"

    decision = kyc_output.final_decision.value if kyc_output.final_decision else "PENDING"

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Evidence Quality: {evidence_grade}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 6, f"Decision: {decision}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    # Key findings
    if kyc_output.synthesis and kyc_output.synthesis.key_findings:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*pdf.colors["primary"])
        findings_count = len(kyc_output.synthesis.key_findings)
        pdf.cell(0, 7, f"KEY FINDINGS ({findings_count}):", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(31, 41, 55)
        pdf.set_font("Helvetica", "", 10)

        for finding in kyc_output.synthesis.key_findings[:6]:
            pdf.set_x(pdf.l_margin + 3)
            pdf.multi_cell(0, 5, f"* {sanitize_text(finding)}")
        pdf.ln(3)

    # Critical actions required
    actions: list[str] = []
    if kyc_output.synthesis:
        if kyc_output.synthesis.senior_management_approval_needed:
            actions.append("Senior management approval required")
        for cond in kyc_output.synthesis.conditions[:5]:
            actions.append(sanitize_text(cond))

    if kyc_output.review_intelligence and kyc_output.review_intelligence.discussion_points:
        for dp in kyc_output.review_intelligence.discussion_points:
            if dp.severity.value in ("CRITICAL", "HIGH"):
                actions.append(f"{dp.severity.value}: {sanitize_text(dp.title)}")

    if actions:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(220, 38, 38)  # Red
        pdf.cell(0, 7, "CRITICAL ACTIONS REQUIRED:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(31, 41, 55)
        pdf.set_font("Helvetica", "", 10)
        for action in actions[:6]:
            pdf.set_x(pdf.l_margin + 3)
            pdf.multi_cell(0, 5, f"* {action}")
        pdf.ln(3)

    # Evidence at a glance
    if kyc_output.synthesis and kyc_output.synthesis.evidence_graph:
        eg = kyc_output.synthesis.evidence_graph
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*pdf.colors["primary"])
        pdf.cell(0, 7, "EVIDENCE AT A GLANCE:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(31, 41, 55)
        pdf.cell(0, 6,
                 f"[V] {eg.verified_count}  [S] {eg.sourced_count}  "
                 f"[I] {eg.inferred_count}  [U] {eg.unknown_count}  "
                 f"Total: {eg.total_evidence_records}",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 6,
                 f"Contradictions: {len(eg.contradictions)}  Corroborations: {len(eg.corroborations)}",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

    # Analyst / review info
    if kyc_output.review_session:
        officer = kyc_output.review_session.officer_name or "Not specified"
        finalized = "Yes" if kyc_output.review_session.finalized else "No"
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(107, 114, 128)
        pdf.cell(0, 5, f"Analyst: {officer}  |  Review Finalized: {finalized}  |  "
                        f"Generated: {kyc_output.generated_at.strftime('%Y-%m-%d %H:%M')}",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if kyc_output.is_degraded:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(220, 38, 38)
        pdf.cell(0, 6, "WARNING: Investigation degraded — some agents failed. Results may be incomplete.",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_text_color(0, 0, 0)


def _build_signoff_block(pdf: BriefPDF) -> None:
    """Add a regulatory signoff section to the current page.

    Provides blank lines for officer signature, date, and a jurisdiction
    attestation footer. Configurable via REPORTING_ENTITY env vars.
    """
    import os

    pdf.ln(10)

    # Separator
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(31, 41, 55)
    pdf.cell(0, 7, "COMPLIANCE OFFICER SIGNOFF", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(55, 65, 81)

    # Signature lines
    line_width = 80
    pdf.cell(35, 7, "Reviewed by:")
    pdf.set_draw_color(100, 100, 100)
    pdf.line(pdf.get_x(), pdf.get_y() + 6, pdf.get_x() + line_width, pdf.get_y() + 6)
    pdf.ln(10)

    pdf.cell(35, 7, "Title:")
    pdf.line(pdf.get_x(), pdf.get_y() + 6, pdf.get_x() + line_width, pdf.get_y() + 6)
    pdf.ln(10)

    pdf.cell(35, 7, "Date:")
    pdf.line(pdf.get_x(), pdf.get_y() + 6, pdf.get_x() + line_width, pdf.get_y() + 6)
    pdf.ln(10)

    pdf.cell(35, 7, "Signature:")
    pdf.line(pdf.get_x(), pdf.get_y() + 6, pdf.get_x() + line_width, pdf.get_y() + 6)
    pdf.ln(12)

    # Attestation
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(107, 114, 128)
    institution = os.environ.get("REPORTING_ENTITY_NAME", "[Institution Name]")
    pdf.multi_cell(
        0, 4,
        f"This report was generated by KYC Onboarding Intelligence System on behalf of {institution} "
        "and reviewed by the above officer. The contents reflect the automated investigation findings "
        "and the officer's professional judgment."
    )
    pdf.ln(2)

    # Jurisdiction footer
    pdf.set_font("Helvetica", "I", 7)
    pdf.multi_cell(
        0, 4,
        "Prepared in accordance with PCMLTFA and applicable FINTRAC guidance. "
        "This document may contain privileged and confidential information. "
        "Unauthorized disclosure is prohibited."
    )

    pdf.set_text_color(0, 0, 0)


def generate_kyc_pdf(
    md_content: str,
    output_path: str,
    doc_type: str = "compliance_officer_brief",
    risk_level: str = None,
    kyc_output: "Any" = None,
) -> bool:
    """
    Generate a KYC PDF from markdown content.

    Args:
        md_content: Markdown content
        output_path: Path to save the PDF
        doc_type: Document type (compliance_officer_brief, onboarding_summary)
        risk_level: Risk level for color coding (LOW, MEDIUM, HIGH, CRITICAL)
        kyc_output: Optional KYCOutput for executive summary page

    Returns:
        True if successful
    """
    try:
        brief_type_map = {
            "compliance_officer_brief": "Compliance",
            "aml_operations_brief": "AML",
            "risk_assessment_brief": "Risk",
            "regulatory_actions_brief": "Regulatory",
            "onboarding_summary": "Onboarding",
            "onboarding_decision_brief": "Onboarding",
        }
        brief_type = brief_type_map.get(doc_type, "Compliance")
        title_map = {
            "compliance_officer_brief": "KYC Compliance Brief",
            "aml_operations_brief": "AML Operations Brief",
            "risk_assessment_brief": "Risk Assessment Brief",
            "regulatory_actions_brief": "Regulatory Actions Brief",
            "onboarding_summary": "Onboarding Decision Brief",
            "onboarding_decision_brief": "Onboarding Decision Brief",
        }
        title = title_map.get(doc_type, "KYC Report")

        pdf = BriefPDF(brief_type=brief_type, title=title)

        # Add executive summary page if kyc_output is provided
        if kyc_output is not None:
            _build_executive_summary_page(pdf, kyc_output)
            pdf.add_page()  # Start brief content on new page

        # Add risk level indicator if provided
        if risk_level and risk_level in RISK_LEVEL_COLORS:
            pdf.risk_level_badge(risk_level)

        parse_markdown_to_pdf(md_content, pdf)

        # Add signoff block — ensure enough space or start new page
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        _build_signoff_block(pdf)

        pdf.output(output_path)
        return True

    except Exception as e:
        from logger import get_logger
        get_logger(__name__).exception(f"Error generating KYC PDF: {e}")
        return False
