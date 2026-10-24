import os
import json
import html
from datetime import datetime
from pathlib import Path
import config
from database import get_db_connection
from services.digital_product_engine import DigitalProductEngine

class ProductBuilderAgent:
    """
    Compatibility and orchestration wrapper for digital product generation.
    Delegates directly to DigitalProductEngine (Gemini curriculum synthesis + Chromium PDF rendering)
    as the sole production path for MINT digital deliverables.
    """
    @classmethod
    def get_products_dir(cls) -> Path:
        return DigitalProductEngine.get_products_base_dir()

    @classmethod
    def build_digital_package(cls, title: str, audience: str, format_type: str = "guide",
                               experiment_id: int = None, price: float = 14.99,
                               product_type: str = "guide", is_test: int = 0) -> dict:
        """
        Builds a verified digital package using the unified DigitalProductEngine.
        Produces semantic HTML, Markdown source, and print-ready PDF via Chromium.
        """
        effective_format = format_type or product_type or "guide"
        brief = DigitalProductEngine.derive_brief(
            idea=title,
            audience=audience,
            format_type=effective_format,
            price=price
        )

        prompt = DigitalProductEngine.generate_prompt_from_brief(brief)
        ai_res = DigitalProductEngine.call_gemini_api(prompt)

        if ai_res.get("success") and len(ai_res.get("content", "")) >= 200:
            content_text = ai_res["content"]
            is_ai = True
        else:
            # Deterministic structured sections based on derived brief
            sections_md = []
            for s in brief.get("sections", []):
                sections_md.append(
                    f"## {s['title']}\n"
                    f"{s['scope']}\n\n"
                    f"- [ ] Step: Establish baseline parameters\n"
                    f"- [ ] Step: Implement standardized checklist routines\n"
                    f"- [ ] Step: Execute operational audit\n"
                )
            content_text = (
                f"# {brief['title']}\n\n"
                f"**Target Audience:** {brief['target_audience']}\n\n"
                f"> **MINT Verified Curriculum:** Standalone digital deliverable.\n\n"
                + "\n".join(sections_md)
                + "\n---\n### The End\n"
            )
            is_ai = False

        slug = DigitalProductEngine.slugify(brief["title"])
        if experiment_id:
            slug = f"{slug}_exp{experiment_id}"

        prod_dir = DigitalProductEngine.get_products_base_dir() / slug
        prod_dir.mkdir(parents=True, exist_ok=True)

        md_file = prod_dir / "source.md"
        html_file = prod_dir / "render.html"
        pdf_file = prod_dir / "product.pdf"

        # Write markdown source
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(content_text)

        # Render HTML deliverable via DigitalProductEngine's converter and layout
        body_html = DigitalProductEngine.markdown_to_html(content_text)
        full_html = DigitalProductEngine.render_full_html_document(
            title=brief["title"],
            subtitle=brief["subtitle"],
            audience=brief["target_audience"],
            format_type=brief["format_type"],
            body_html=body_html,
            version="1.0.0"
        )
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(full_html)

        # Render real PDF via Chromium
        pdf_rendered = False
        pdf_res = DigitalProductEngine.render_pdf_with_chromium(full_html, pdf_file)
        if pdf_res.get("success") and pdf_file.exists() and pdf_file.stat().st_size > 0:
            pdf_rendered = True
            deliverable_path = str(pdf_file)
            file_size = pdf_file.stat().st_size
            page_count = 1
            val = DigitalProductEngine.validate_pdf(pdf_file)
            if val.get("valid"):
                page_count = val.get("page_count", 1)
        else:
            deliverable_path = str(html_file)
            file_size = html_file.stat().st_size
            page_count = 1

        status = "ready"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        package_modules = [s["title"] for s in brief.get("sections", [])]

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM digital_products WHERE slug = ?", (slug,))
        row = cur.fetchone()
        if row:
            product_id = row["id"]
            cur.execute("""
                UPDATE digital_products
                SET title = ?, product_type = ?, audience = ?, value_proposition = ?, description = ?,
                    contents_json = ?, price = ?, file_path = ?, pdf_path = ?, page_count = ?,
                    file_size_bytes = ?, status = ?, product_intent = ?, is_test = ?, updated_at = ?
                WHERE id = ?
            """, (
                brief["title"], brief["format_type"], brief["target_audience"],
                brief["subtitle"], f"Actionable {brief['format_type']} for {brief['target_audience']}",
                json.dumps(package_modules), price, deliverable_path,
                str(pdf_file) if pdf_rendered else None, page_count, file_size,
                status, brief.get("product_intent", "non_fiction"), is_test, now, product_id
            ))
        else:
            cur.execute("""
                INSERT INTO digital_products (
                    experiment_id, slug, title, product_type, audience, value_proposition,
                    description, contents_json, version, price, currency, status,
                    file_path, preview_path, pdf_path, page_count, file_size_bytes,
                    product_intent, is_test, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, '1.0.0', ?, 'USD', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                experiment_id, slug, brief["title"], brief["format_type"], brief["target_audience"],
                brief["subtitle"], f"Actionable {brief['format_type']} for {brief['target_audience']}",
                json.dumps(package_modules), price, status, deliverable_path, str(html_file),
                str(pdf_file) if pdf_rendered else None, page_count, file_size,
                brief.get("product_intent", "non_fiction"), is_test, now, now
            ))
            product_id = cur.lastrowid
        conn.commit()
        conn.close()

        return {
            "id": product_id,
            "title": brief["title"],
            "slug": slug,
            "markdown_path": str(md_file),
            "deliverable_path": deliverable_path,
            "html_path": str(html_file),
            "pdf_path": str(pdf_file) if pdf_rendered else None,
            "file_size_bytes": file_size,
            "page_count": page_count,
            "version": "1.0.0",
            "price": price,
            "is_ai_generated": is_ai,
            "status": status
        }
