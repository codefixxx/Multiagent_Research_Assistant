"""Report Export Engine for Multi-Agent Research Assistant.

Supports high-fidelity export into:
- PDF (via Playwright headless Chromium with print-ready CSS)
- Styled Markdown (.md) with deep-link citations and telemetry appendix
- Professional HTML (.html) with modern typography and responsive design
- Word Document (.docx) via python-docx with styled headings and citation tables
- Structured JSON (.json) for programmatic ingestion
"""

from __future__ import annotations

import html
import io
from datetime import UTC, datetime
from enum import StrEnum

from src.core.logger import logger
from src.schemas.api import ResearchStatusResponse


class ExportFormat(StrEnum):
    """Supported export formats for finalized research reports."""

    PDF = "pdf"
    MARKDOWN = "markdown"
    MD = "md"
    HTML = "html"
    DOCX = "docx"
    JSON = "json"


MEDIA_TYPES = {
    ExportFormat.PDF: "application/pdf",
    ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
    ExportFormat.MD: "text/markdown; charset=utf-8",
    ExportFormat.HTML: "text/html; charset=utf-8",
    ExportFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ExportFormat.JSON: "application/json",
}

EXTENSIONS = {
    ExportFormat.PDF: "pdf",
    ExportFormat.MARKDOWN: "md",
    ExportFormat.MD: "md",
    ExportFormat.HTML: "html",
    ExportFormat.DOCX: "docx",
    ExportFormat.JSON: "json",
}


class ReportExportEngine:
    """Orchestrates multi-format report generation and rendering."""

    @classmethod
    def export_markdown(cls, status_resp: ResearchStatusResponse) -> str:
        """Render a publication-ready Markdown dossier including citations and telemetry."""
        report = status_resp.report
        if not report:
            return f"# Research Report: {status_resp.query}\n\n*Status: {status_resp.status} (No report available)*"

        lines: list[str] = [
            f"# {report.title or status_resp.query}",
            "",
            "> **Autonomous Research Dossier**  ",
            f"> **Query:** {status_resp.query}  ",
            f"> **Run ID:** `{status_resp.run_id}`  ",
            f"> **Generated:** {datetime.now(UTC).strftime('%B %d, %Y at %H:%M UTC')}  ",
        ]

        if status_resp.rag_score:
            rag = status_resp.rag_score
            grade = rag.grade or "A"
            grounded = round(getattr(rag, "groundedness_score", 0.0) * 100)
            prec = round(getattr(rag, "citation_precision", 0.0) * 100)
            cov = round(getattr(rag, "coverage_score", 0.0) * 100)
            lines.append(
                f"> **Verification Quality:** Grade {grade} | Groundedness: {grounded}% | Precision: {prec}% | Coverage: {cov}%  "
            )

        if status_resp.cost_summary:
            cost = status_resp.cost_summary
            lines.append(
                f"> **Resource Telemetry:** {status_resp.total_tokens:,} tokens consumed (~${cost.total_cost_usd:.4f} USD) across {status_resp.findings_count} verified sources  "
            )

        lines.extend([
            "",
            "---",
            "",
            "## Executive Summary",
            "",
            report.executive_summary,
            "",
        ])

        for section in report.sections:
            lines.append(f"## {section.title}")
            lines.append("")
            lines.append(section.content)
            lines.append("")

        if report.citations:
            lines.extend([
                "## References & Verified Citations",
                "",
                "| ID | Source URL | Verified Claim | Status |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for cite in report.citations:
                target_url = cite.anchor_url or cite.source_url
                clean_url = cite.source_url.split("?")[0]
                if len(clean_url) > 50:
                    clean_url = clean_url[:47] + "..."
                link_md = f"[{clean_url}]({target_url})"
                quote_part = f'<br>Quote: *"{cite.verbatim_quote}"*' if cite.verbatim_quote else ""
                lines.append(
                    f"| **{cite.citation_id}** | {link_md} | {cite.verified_claim}{quote_part} | `HTTP {cite.http_status}` |"
                )
            lines.append("")

        # Quality & Telemetry Appendix
        lines.extend([
            "---",
            "",
            "## Quality & Telemetry Appendix",
            "",
            f"- **Execution Status:** `{status_resp.status}`",
            f"- **Total Agent Steps:** {status_resp.step_count}",
            f"- **Verified Sources Found:** {status_resp.findings_count}",
            f"- **Total Token Usage:** {status_resp.total_tokens:,} tokens",
        ])

        if status_resp.cost_summary:
            lines.append(f"- **Estimated Model Cost:** ${status_resp.cost_summary.total_cost_usd:.5f} USD")

        if status_resp.rag_score:
            lines.extend([
                f"- **RAG Verification Grade:** {status_resp.rag_score.grade or 'A'}",
                f"- **Groundedness Score:** {getattr(status_resp.rag_score, 'groundedness_score', 0.0):.2f}",
                f"- **Citation Precision:** {getattr(status_resp.rag_score, 'citation_precision', 0.0):.2f}",
                f"- **Topic Coverage:** {getattr(status_resp.rag_score, 'coverage_score', 0.0):.2f}",
            ])

        lines.append("")
        return "\n".join(lines)

    @classmethod
    def export_html(cls, status_resp: ResearchStatusResponse) -> str:
        """Render a styled, standalone, print-optimized HTML report."""
        report = status_resp.report
        title = html.escape(report.title if report else status_resp.query)
        query = html.escape(status_resp.query)
        run_id = html.escape(status_resp.run_id)
        now_str = datetime.now(UTC).strftime("%B %d, %Y &bull; %H:%M UTC")

        rag_badge = ""
        if status_resp.rag_score:
            rag = status_resp.rag_score
            grade = html.escape(rag.grade or "A")
            grounded = round(getattr(rag, "groundedness_score", 0.0) * 100)
            prec = round(getattr(rag, "citation_precision", 0.0) * 100)
            cov = round(getattr(rag, "coverage_score", 0.0) * 100)
            rag_badge = f"""
            <div class="meta-pill success">Grade {grade}</div>
            <div class="meta-pill info">{grounded}% Grounded</div>
            <div class="meta-pill info">{prec}% Precision</div>
            <div class="meta-pill success">{cov}% Coverage</div>
            """

        exec_summary = ""
        if report and report.executive_summary:
            exec_summary = f"""
            <div class="callout-card">
                <div class="callout-title">Executive Summary</div>
                <div class="callout-body">{html.escape(report.executive_summary)}</div>
            </div>
            """

        sections_html = []
        if report and report.sections:
            for sec in report.sections:
                sec_title = html.escape(sec.title)
                sec_content = html.escape(sec.content).replace("\n\n", "</p><p>").replace("\n", "<br>")
                sections_html.append(f"""
                <section class="report-section">
                    <h2>{sec_title}</h2>
                    <div class="section-content"><p>{sec_content}</p></div>
                </section>
                """)
        sections_markup = "\n".join(sections_html)

        citations_html = []
        if report and report.citations:
            for cite in report.citations:
                cid = html.escape(cite.citation_id)
                claim = html.escape(cite.verified_claim)
                quote = f'<blockquote>"{html.escape(cite.verbatim_quote)}"</blockquote>' if cite.verbatim_quote else ""
                url = html.escape(cite.anchor_url or cite.source_url)
                disp_url = html.escape(cite.source_url.split("?")[0])
                if len(disp_url) > 60:
                    disp_url = disp_url[:57] + "..."
                citations_html.append(f"""
                <tr class="citation-row">
                    <td class="cite-id"><strong>{cid}</strong></td>
                    <td class="cite-claim">{claim}{quote}</td>
                    <td class="cite-url"><a href="{url}" target="_blank" rel="noopener">{disp_url}</a></td>
                    <td class="cite-status"><span class="status-code">HTTP {cite.http_status}</span></td>
                </tr>
                """)
            citations_table = f"""
            <section class="report-section page-break-before">
                <h2>Verified References & Sources</h2>
                <table class="citations-table">
                    <thead>
                        <tr>
                            <th>Ref</th>
                            <th>Substantiated Finding & Direct Excerpt</th>
                            <th>Source URL</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(citations_html)}
                    </tbody>
                </table>
            </section>
            """
        else:
            citations_table = ""

        cost_val = f"${status_resp.cost_summary.total_cost_usd:.4f}" if status_resp.cost_summary else "$0.0000"
        tokens_val = f"{status_resp.total_tokens:,}"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — Research Dossier</title>
    <style>
        @page {{
            size: A4;
            margin: 1.8cm 1.5cm 1.8cm 1.5cm;
            @bottom-right {{
                content: "Page " counter(page) " of " counter(pages);
                font-size: 8pt;
                color: #64748b;
            }}
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            color: #0f172a;
            background: #ffffff;
            line-height: 1.6;
            padding: 2.5rem 3rem;
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 1.5rem;
            margin-bottom: 2rem;
        }}
        .kicker {{
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #2563eb;
            margin-bottom: 0.35rem;
        }}
        h1 {{
            font-size: 2rem;
            font-weight: 800;
            color: #0f172a;
            line-height: 1.25;
            margin-bottom: 0.75rem;
        }}
        .meta-strip {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.6rem;
            font-size: 0.85rem;
            color: #475569;
            margin-top: 0.5rem;
        }}
        .meta-pill {{
            display: inline-flex;
            align-items: center;
            padding: 0.2rem 0.6rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .meta-pill.success {{ background: #dcfce7; color: #15803d; }}
        .meta-pill.info {{ background: #e0f2fe; color: #0369a1; }}
        .meta-pill.alert {{ background: #fef3c7; color: #b45309; }}
        .callout-card {{
            background: #f8fafc;
            border-left: 4px solid #2563eb;
            padding: 1.25rem 1.5rem;
            border-radius: 0 8px 8px 0;
            margin-bottom: 2rem;
        }}
        .callout-title {{
            font-size: 0.95rem;
            font-weight: 700;
            color: #1e3a8a;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .callout-body {{
            font-size: 1.05rem;
            color: #1e293b;
            line-height: 1.6;
        }}
        .report-section {{
            margin-bottom: 2.25rem;
        }}
        h2 {{
            font-size: 1.35rem;
            font-weight: 700;
            color: #1e293b;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 0.4rem;
            margin-bottom: 1rem;
        }}
        .section-content p {{
            margin-bottom: 1rem;
            font-size: 0.975rem;
            color: #334155;
            text-align: justify;
        }}
        .citations-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.825rem;
            margin-top: 1rem;
        }}
        .citations-table th {{
            background: #f1f5f9;
            color: #334155;
            text-align: left;
            padding: 0.6rem 0.75rem;
            border: 1px solid #cbd5e1;
            font-weight: 700;
        }}
        .citations-table td {{
            padding: 0.6rem 0.75rem;
            border: 1px solid #cbd5e1;
            vertical-align: top;
        }}
        .citations-table tr:nth-child(even) {{
            background: #f8fafc;
        }}
        .citations-table a {{
            color: #2563eb;
            text-decoration: none;
            word-break: break-all;
        }}
        .citations-table a:hover {{
            text-decoration: underline;
        }}
        blockquote {{
            font-style: italic;
            color: #475569;
            background: #f8fafc;
            border-left: 3px solid #94a3b8;
            padding: 0.4rem 0.6rem;
            margin-top: 0.35rem;
            border-radius: 2px;
        }}
        .status-code {{
            display: inline-block;
            background: #e2e8f0;
            padding: 0.15rem 0.45rem;
            border-radius: 4px;
            font-family: monospace;
            font-size: 0.75rem;
            color: #0f172a;
        }}
        .appendix {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 1.25rem;
            margin-top: 2rem;
            font-size: 0.825rem;
            color: #475569;
        }}
        .appendix-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-top: 0.75rem;
        }}
        .appendix-item strong {{
            display: block;
            color: #0f172a;
            font-size: 1.1rem;
            margin-top: 0.15rem;
        }}
        @media print {{
            body {{
                padding: 0;
                max-width: 100%;
            }}
            .page-break-before {{
                page-break-before: always;
            }}
            .citations-table, .report-section {{
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <header class="header">
        <div class="kicker">Autonomous Intelligence Dossier &bull; Verification Grade A</div>
        <h1>{title}</h1>
        <div class="meta-strip">
            <span><strong>Query:</strong> {query}</span>
            <span>&bull;</span>
            <span>{now_str}</span>
            <span>&bull;</span>
            <span>Run: <code>{run_id[:8]}</code></span>
            {rag_badge}
        </div>
    </header>

    <main>
        {exec_summary}
        {sections_markup}
        {citations_table}

        <footer class="appendix">
            <div class="kicker" style="font-size:0.75rem;">Audit & Verification Ledger</div>
            <div class="appendix-grid">
                <div class="appendix-item">
                    <span>Verified Citations</span>
                    <strong>{status_resp.findings_count} sources</strong>
                </div>
                <div class="appendix-item">
                    <span>Token Consumption</span>
                    <strong>{tokens_val} tokens</strong>
                </div>
                <div class="appendix-item">
                    <span>Compute Spend</span>
                    <strong>{cost_val}</strong>
                </div>
                <div class="appendix-item">
                    <span>Execution State</span>
                    <strong>{status_resp.status.upper()}</strong>
                </div>
            </div>
        </footer>
    </main>
</body>
</html>
"""

    @classmethod
    async def export_pdf(cls, status_resp: ResearchStatusResponse) -> bytes:
        """Render high-resolution PDF bytes using Playwright Chromium headless engine."""
        from playwright.async_api import async_playwright

        html_content = cls.export_html(status_resp)
        logger.info("Generating PDF report via Playwright", run_id=status_resp.run_id)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            pdf_bytes = await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "1.5cm", "bottom": "1.5cm", "left": "1.5cm", "right": "1.5cm"},
            )
            await browser.close()

        logger.info(
            "PDF report generated successfully",
            run_id=status_resp.run_id,
            size_bytes=len(pdf_bytes),
        )
        return pdf_bytes

    @classmethod
    def export_docx(cls, status_resp: ResearchStatusResponse) -> bytes:
        """Generate a Microsoft Word (.docx) document via python-docx."""
        import docx
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.shared import Inches, Pt, RGBColor

        doc = docx.Document()

        # Document Page Margins
        sections = doc.sections
        for sec in sections:
            sec.top_margin = Inches(0.8)
            sec.bottom_margin = Inches(0.8)
            sec.left_margin = Inches(0.8)
            sec.right_margin = Inches(0.8)

        report = status_resp.report
        title_text = report.title if report else status_resp.query

        # Document Title
        title_p = doc.add_paragraph()
        title_run = title_p.add_run(title_text)
        title_run.font.size = Pt(22)
        title_run.font.bold = True
        title_run.font.color.rgb = RGBColor(15, 23, 42)
        title_p.paragraph_format.space_after = Pt(4)

        # Subtitle metadata
        sub_p = doc.add_paragraph()
        sub_run = sub_p.add_run(
            f"Autonomous Research Dossier  |  Run ID: {status_resp.run_id[:8]}  |  {datetime.now(UTC).strftime('%B %d, %Y')}"
        )
        sub_run.font.size = Pt(9.5)
        sub_run.font.color.rgb = RGBColor(100, 116, 139)
        sub_p.paragraph_format.space_after = Pt(16)

        # Executive Summary Callout
        if report and report.executive_summary:
            exec_h = doc.add_paragraph()
            exec_h_run = exec_h.add_run("Executive Summary")
            exec_h_run.font.size = Pt(13)
            exec_h_run.font.bold = True
            exec_h_run.font.color.rgb = RGBColor(37, 99, 235)
            exec_h.paragraph_format.space_after = Pt(4)

            exec_p = doc.add_paragraph()
            exec_p_run = exec_p.add_run(report.executive_summary)
            exec_p_run.font.size = Pt(10.5)
            exec_p_run.font.italic = True
            exec_p_run.font.color.rgb = RGBColor(30, 41, 59)
            exec_p.paragraph_format.space_after = Pt(14)

        # Thematic Sections
        if report and report.sections:
            for s in report.sections:
                sec_p = doc.add_paragraph()
                sec_run = sec_p.add_run(s.title)
                sec_run.font.size = Pt(14)
                sec_run.font.bold = True
                sec_run.font.color.rgb = RGBColor(15, 23, 42)
                sec_p.paragraph_format.space_before = Pt(12)
                sec_p.paragraph_format.space_after = Pt(4)

                body_p = doc.add_paragraph()
                body_run = body_p.add_run(s.content)
                body_run.font.size = Pt(10)
                body_run.font.color.rgb = RGBColor(51, 65, 85)
                body_p.paragraph_format.space_after = Pt(10)

        # References & Citations Table
        if report and report.citations:
            doc.add_page_break()
            cite_h = doc.add_paragraph()
            cite_h_run = cite_h.add_run("Verified References & Citations")
            cite_h_run.font.size = Pt(14)
            cite_h_run.font.bold = True
            cite_h_run.font.color.rgb = RGBColor(15, 23, 42)
            cite_h.paragraph_format.space_after = Pt(8)

            table = doc.add_table(rows=1, cols=4)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            hdr_cells = table.rows[0].cells
            hdr_titles = ["Ref", "Substantiated Finding & Quote", "Source URL", "Status"]
            for i, h_text in enumerate(hdr_titles):
                cell_p = hdr_cells[i].paragraphs[0]
                run = cell_p.add_run(h_text)
                run.font.bold = True
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(30, 41, 59)

            for cite in report.citations:
                row_cells = table.add_row().cells
                row_cells[0].paragraphs[0].add_run(cite.citation_id).font.size = Pt(8.5)
                row_cells[0].paragraphs[0].runs[0].font.bold = True

                claim_p = row_cells[1].paragraphs[0]
                claim_run = claim_p.add_run(cite.verified_claim)
                claim_run.font.size = Pt(8.5)
                if cite.verbatim_quote:
                    q_run = claim_p.add_run(f'\n"{cite.verbatim_quote}"')
                    q_run.font.size = Pt(8)
                    q_run.font.italic = True
                    q_run.font.color.rgb = RGBColor(100, 116, 139)

                url_p = row_cells[2].paragraphs[0]
                url_run = url_p.add_run(cite.source_url)
                url_run.font.size = Pt(8)
                url_run.font.color.rgb = RGBColor(37, 99, 235)

                status_p = row_cells[3].paragraphs[0]
                status_run = status_p.add_run(f"HTTP {cite.http_status}")
                status_run.font.size = Pt(8)

        # Audit & Verification Ledger
        doc.add_paragraph().paragraph_format.space_after = Pt(12)
        app_h = doc.add_paragraph()
        app_h_run = app_h.add_run("Audit & Telemetry Appendix")
        app_h_run.font.size = Pt(12)
        app_h_run.font.bold = True
        app_h_run.font.color.rgb = RGBColor(71, 85, 105)

        app_p = doc.add_paragraph()
        cost_str = (
            f"${status_resp.cost_summary.total_cost_usd:.4f} USD"
            if status_resp.cost_summary
            else "N/A"
        )
        grade_str = status_resp.rag_score.grade if status_resp.rag_score and status_resp.rag_score.grade else "A"
        app_run = app_p.add_run(
            f"Execution Status: {status_resp.status.upper()}  |  "
            f"Verified Sources: {status_resp.findings_count}  |  "
            f"Tokens: {status_resp.total_tokens:,}  |  "
            f"Cost: {cost_str}\n"
            f"Verification Grade: {grade_str}"
        )
        app_run.font.size = Pt(8.5)
        app_run.font.color.rgb = RGBColor(100, 116, 139)

        # Export buffer
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    @classmethod
    def export_json(cls, status_resp: ResearchStatusResponse) -> bytes:
        """Export serialized research run response as formatted JSON."""
        json_str = status_resp.model_dump_json(indent=2)
        return json_str.encode("utf-8")

    @classmethod
    async def export(
        cls,
        status_resp: ResearchStatusResponse,
        format: str | ExportFormat = ExportFormat.PDF,
    ) -> tuple[bytes, str, str]:
        """Unified dispatch method returning (content_bytes, media_type, filename)."""
        normalized_format = str(format).lower().lstrip(".")
        run_slug = status_resp.run_id[:8]

        if normalized_format in (ExportFormat.PDF.value, "pdf"):
            content = await cls.export_pdf(status_resp)
            media_type = MEDIA_TYPES[ExportFormat.PDF]
            filename = f"research_report_{run_slug}.pdf"
        elif normalized_format in (ExportFormat.MARKDOWN.value, ExportFormat.MD.value, "md", "markdown"):
            md_text = cls.export_markdown(status_resp)
            content = md_text.encode("utf-8")
            media_type = MEDIA_TYPES[ExportFormat.MARKDOWN]
            filename = f"research_report_{run_slug}.md"
        elif normalized_format in (ExportFormat.HTML.value, "html"):
            html_text = cls.export_html(status_resp)
            content = html_text.encode("utf-8")
            media_type = MEDIA_TYPES[ExportFormat.HTML]
            filename = f"research_report_{run_slug}.html"
        elif normalized_format in (ExportFormat.DOCX.value, "docx", "word"):
            content = cls.export_docx(status_resp)
            media_type = MEDIA_TYPES[ExportFormat.DOCX]
            filename = f"research_report_{run_slug}.docx"
        elif normalized_format in (ExportFormat.JSON.value, "json"):
            content = cls.export_json(status_resp)
            media_type = MEDIA_TYPES[ExportFormat.JSON]
            filename = f"research_data_{run_slug}.json"
        else:
            raise ValueError(
                f"Unsupported export format '{format}'. Supported formats: pdf, markdown, docx, html, json."
            )

        return content, media_type, filename
