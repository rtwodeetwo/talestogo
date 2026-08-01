"""
Report Export Service
Provides Word export functionality with proper table formatting.
"""

import io
import re
from typing import Optional
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from sqlalchemy.orm import Session


def export_to_word(markdown_content: str, title: str) -> io.BytesIO:
    """
    Convert markdown report to Word document with proper formatting.

    Args:
        markdown_content: The markdown content to convert
        title: The report title

    Returns:
        BytesIO object containing the Word document
    """
    doc = Document()

    # Set document margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # Parse markdown line by line
    lines = markdown_content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        # H1 Headers
        if line.startswith('# '):
            text = line[2:].strip()
            heading = doc.add_heading(text, level=1)
            heading.alignment = WD_ALIGN_PARAGRAPH.LEFT

        # H2 Headers
        elif line.startswith('## '):
            text = line[3:].strip()
            heading = doc.add_heading(text, level=2)
            heading.alignment = WD_ALIGN_PARAGRAPH.LEFT

        # H3 Headers
        elif line.startswith('### '):
            text = line[4:].strip()
            heading = doc.add_heading(text, level=3)
            heading.alignment = WD_ALIGN_PARAGRAPH.LEFT

        # Horizontal rules
        elif line.startswith('---') or line.startswith('***'):
            doc.add_paragraph('_' * 80)

        # Tables
        elif line.startswith('|'):
            # Collect all table lines
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            i -= 1  # Back up one since we'll increment at the end

            # Parse table
            if len(table_lines) >= 2:  # Header + separator minimum
                # Parse header
                header = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]

                # Skip separator line
                # Parse data rows (skip separator)
                data_rows = []
                for row_line in table_lines[2:]:  # Skip header and separator
                    cells = [cell.strip() for cell in row_line.split('|')[1:-1]]
                    data_rows.append(cells)

                # Create Word table
                if data_rows:
                    table = doc.add_table(rows=1 + len(data_rows), cols=len(header))
                    table.style = 'Light Grid Accent 1'

                    # Add header
                    header_cells = table.rows[0].cells
                    for idx, header_text in enumerate(header):
                        header_cells[idx].text = header_text
                        # Make header bold
                        for paragraph in header_cells[idx].paragraphs:
                            for run in paragraph.runs:
                                run.font.bold = True

                    # Add data rows
                    for row_idx, row_data in enumerate(data_rows, start=1):
                        cells = table.rows[row_idx].cells
                        for col_idx, cell_data in enumerate(row_data):
                            # Remove markdown formatting from cell content
                            clean_text = cell_data.replace('**', '')
                            cells[col_idx].text = clean_text

        # Bullet points
        elif line.startswith('- ') or line.startswith('* '):
            text = line[2:].strip()
            # Remove markdown formatting
            text = text.replace('**', '')
            doc.add_paragraph(text, style='List Bullet')

        # Numbered lists
        elif re.match(r'^\d+\.\s', line):
            text = re.sub(r'^\d+\.\s+', '', line)
            # Remove markdown formatting
            text = text.replace('**', '')
            doc.add_paragraph(text, style='List Number')

        # Regular paragraphs
        else:
            # Remove markdown formatting
            text = line.replace('**', '')
            if text:
                para = doc.add_paragraph(text)
                para.alignment = WD_ALIGN_PARAGRAPH.LEFT

        i += 1

    # Save to BytesIO
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)

    return output


def export_to_word_with_charts(
    markdown_content: str,
    title: str,
    db: Session,
    user_id: int,
    brand_id: Optional[int] = None
) -> io.BytesIO:
    """
    Convert markdown report to Word document with embedded chart images.

    Args:
        markdown_content: The markdown content to convert
        title: The report title
        db: Database session for fetching analytics data
        user_id: User ID for fetching analytics data
        brand_id: Optional brand ID for filtering data

    Returns:
        BytesIO object containing the Word document with charts
    """
    import os
    from app import analytics
    from app import models

    # Fetch analytics data for placeholder replacement
    sentiment_data = analytics.get_sentiment_breakdown(db, user_id=user_id, brand_id=brand_id) or {}
    sov_data = analytics.get_share_of_voice(db, user_id=user_id, brand_id=brand_id)

    # Handle share_of_voice being either dict or list
    if isinstance(sov_data, list):
        # If it's a list, we can't use it for placeholders
        brand_sov = 0
    elif isinstance(sov_data, dict):
        brand_sov = sov_data.get('brand_sov', 0)
    else:
        brand_sov = 0

    # Get brand name
    brand_name = "Your Brand"  # Default
    if brand_id:
        brand = db.query(models.BrandInfo).filter(models.BrandInfo.id == brand_id).first()
        if brand:
            brand_name = brand.brand_name

    # Calculate positive sentiment rate (very_positive + positive)
    positive_sentiment_rate = sentiment_data.get('very_positive_pct', 0) + sentiment_data.get('positive_pct', 0)

    # Replace placeholders in markdown content
    markdown_content = markdown_content.replace('{brand_name}', brand_name)
    markdown_content = markdown_content.replace('{positive_sentiment_rate}', str(positive_sentiment_rate))
    markdown_content = markdown_content.replace('{descriptor_match_rate}', str(sentiment_data.get('descriptor_match_rate', 0)))
    markdown_content = markdown_content.replace('{share_of_voice[\'brand_sov\']}', str(brand_sov))

    doc = Document()

    # Set document margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # Add title
    title_para = doc.add_heading(title, level=0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()  # Spacer

    # Extract chart paths from markdown content (no need to regenerate)
    # Chart images are already generated and stored in frontend/public/report_charts/

    # Parse markdown content directly (no extra sections)
    lines = markdown_content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        # H1 Headers
        if line.startswith('# '):
            text = line[2:].strip()
            heading = doc.add_heading(text, level=1)
            heading.alignment = WD_ALIGN_PARAGRAPH.LEFT

        # H2 Headers
        elif line.startswith('## '):
            text = line[3:].strip()
            heading = doc.add_heading(text, level=2)
            heading.alignment = WD_ALIGN_PARAGRAPH.LEFT

        # H3 Headers
        elif line.startswith('### '):
            text = line[4:].strip()
            heading = doc.add_heading(text, level=3)
            heading.alignment = WD_ALIGN_PARAGRAPH.LEFT

        # Images (markdown format: ![alt text](path))
        elif line.startswith('![') and '](' in line:
            # Extract image path from markdown: ![Description](report_charts/filename.png)
            try:
                # Find the path between parentheses
                start = line.find('](') + 2
                end = line.find(')', start)
                if start > 1 and end > start:
                    image_path = line[start:end]

                    # Convert web path to filesystem path
                    if image_path.startswith('report_charts/'):
                        # Path is relative to frontend/public/
                        full_path = os.path.join('frontend', 'public', image_path)

                        # Check if file exists and embed it
                        if os.path.exists(full_path):
                            doc.add_picture(full_path, width=Inches(5.5))
                            doc.add_paragraph()  # Add spacing after image
                        else:
                            print(f"Warning: Chart image not found at {full_path}")
                    elif os.path.exists(image_path):
                        # Direct filesystem path
                        doc.add_picture(image_path, width=Inches(5.5))
                        doc.add_paragraph()

            except Exception as e:
                print(f"Error embedding image: {e}")
                # Skip the image if there's an error

        # Horizontal rules
        elif line.startswith('---') or line.startswith('***'):
            doc.add_paragraph('_' * 80)

        # Tables
        elif line.startswith('|'):
            # Collect all table lines
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            i -= 1

            # Parse table
            if len(table_lines) >= 2:
                header = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]
                data_rows = []
                for row_line in table_lines[2:]:
                    cells = [cell.strip() for cell in row_line.split('|')[1:-1]]
                    data_rows.append(cells)

                if data_rows:
                    table = doc.add_table(rows=1 + len(data_rows), cols=len(header))
                    table.style = 'Light Grid Accent 1'

                    # Add header
                    header_cells = table.rows[0].cells
                    for idx, header_text in enumerate(header):
                        header_cells[idx].text = header_text
                        for paragraph in header_cells[idx].paragraphs:
                            for run in paragraph.runs:
                                run.font.bold = True

                    # Add data rows
                    for row_idx, row_data in enumerate(data_rows, start=1):
                        cells = table.rows[row_idx].cells
                        for col_idx, cell_data in enumerate(row_data):
                            clean_text = cell_data.replace('**', '')
                            cells[col_idx].text = clean_text

        # Bullet points
        elif line.startswith('- ') or line.startswith('* '):
            text = line[2:].strip().replace('**', '')
            doc.add_paragraph(text, style='List Bullet')

        # Numbered lists
        elif re.match(r'^\d+\.\s', line):
            text = re.sub(r'^\d+\.\s+', '', line).replace('**', '')
            doc.add_paragraph(text, style='List Number')

        # Regular paragraphs
        else:
            text = line.replace('**', '')
            if text:
                para = doc.add_paragraph(text)
                para.alignment = WD_ALIGN_PARAGRAPH.LEFT

        i += 1

    # Save to BytesIO
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)

    return output

