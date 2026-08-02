"""
Report CRUD and Export API Endpoints
Provides endpoints for creating, reading, updating, deleting reports and exporting them in various formats.
"""
from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import base64
import io
from pathlib import Path

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..routers.analytics import get_active_brand_id


# Main reports router with /reports prefix
router = APIRouter(
    prefix="/reports",
    tags=["Reports"]
)

# Separate router for the how-tales-works endpoint (no prefix)
how_tales_works_router = APIRouter(
    tags=["Export"]
)


@router.post("/", response_model=schemas.Report, status_code=201)
def create_report(
    report: schemas.ReportCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new report for the current user."""
    return crud.create_report(db=db, report=report, user_id=current_user.id)


@router.get("/", response_model=List[schemas.Report])
def read_reports(
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Retrieve a list of reports for the current user's active brand (including shared brands)."""
    # Import brand_access utility
    from app.utils.brand_access import get_data_owner_user_id

    # Get the data owner user_id (for shared brands, this is the brand owner's ID)
    data_owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    return crud.get_reports(db, user_id=data_owner_user_id, brand_id=brand_id, skip=skip, limit=limit)


def get_report_with_brand_access(db: Session, report_id: int, current_user_id: int, brand_id: Optional[int]) -> models.Report:
    """
    Helper function to get a report with brand access validation.
    Works for both owned and shared brands.
    """
    from app.utils.brand_access import get_data_owner_user_id

    # Get the data owner user_id (for shared brands, this is the brand owner's ID)
    data_owner_user_id = get_data_owner_user_id(db, brand_id, current_user_id)

    # Get the report using the data owner's user_id
    db_report = crud.get_report(db, report_id=report_id, user_id=data_owner_user_id)
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    return db_report


@router.get("/{report_id}", response_model=schemas.Report)
def read_report(
    report_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Retrieve a single report by its ID (supports shared brands)."""
    return get_report_with_brand_access(db, report_id, current_user.id, brand_id)


@router.put("/{report_id}", response_model=schemas.Report)
def update_report(
    report_id: int,
    report_update: schemas.ReportUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Update a report (supports shared brands)."""
    from app.utils.brand_access import get_data_owner_user_id

    # Get the data owner user_id (for shared brands, this is the brand owner's ID)
    data_owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    db_report = crud.update_report(
        db,
        report_id=report_id,
        report_update=report_update,
        user_id=data_owner_user_id
    )
    if db_report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return db_report


@router.delete("/{report_id}", response_model=schemas.Report)
def delete_report(
    report_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Delete a report (supports shared brands)."""
    from app.utils.brand_access import get_data_owner_user_id

    # Get the data owner user_id (for shared brands, this is the brand owner's ID)
    data_owner_user_id = get_data_owner_user_id(db, brand_id, current_user.id)

    deleted_report = crud.delete_report(db, report_id=report_id, user_id=data_owner_user_id)
    if deleted_report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return deleted_report


@router.post("/upload-charts")
async def upload_chart_images(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """
    Upload chart images (as base64 strings) and save them to disk.
    Accepts any number of chart images as form data.

    Format: {brand_name}_{chart_type}_{timestamp}.png
    This matches the format users see when downloading images from the website.
    """
    if not brand_id:
        raise HTTPException(status_code=400, detail="No active brand found")

    # Get brand name
    brand = db.query(models.BrandInfo).filter(models.BrandInfo.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    # Format brand name for filename (spaces to underscores, remove special chars)
    brand_name_formatted = brand.brand_name.replace(' ', '_').replace('-', '_')
    brand_name_formatted = ''.join(c for c in brand_name_formatted if c.isalnum() or c == '_')

    # Create report_charts directory if it doesn't exist
    charts_dir = Path("frontend/public/report_charts")
    charts_dir.mkdir(parents=True, exist_ok=True)

    # Parse form data
    form_data = await request.form()

    chart_paths = {}
    timestamp = form_data.get('timestamp', '')

    # Process each chart image
    for field_name, value in form_data.items():
        if field_name == 'timestamp':
            continue

        try:
            base64_data = str(value)

            # Remove the data:image/png;base64, prefix if present
            if ',' in base64_data:
                base64_data = base64_data.split(',')[1]

            # Decode base64 to binary
            image_data = base64.b64decode(base64_data)

            # Create filename matching website download format
            # Format: {BrandName}_{chart_type}_{timestamp}.png
            filename = f"{brand_name_formatted}_{field_name}_{timestamp}.png"
            filepath = charts_dir / filename

            # Write file
            with open(filepath, 'wb') as f:
                f.write(image_data)

            # Store relative path
            chart_paths[field_name] = f"report_charts/{filename}"

        except Exception as e:
            print(f"Error saving {field_name} chart: {e}")
            continue

    return {
        "success": True,
        "chart_paths": chart_paths,
        "message": f"Uploaded {len(chart_paths)} chart(s) for report generation",
        "brand_name": brand.brand_name
    }


@router.get("/{report_id}/export/word")
def export_report_to_word(
    report_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Export a report to Word document format with embedded charts (supports shared brands)."""
    from app.services.report_export import export_to_word_with_charts
    from app.utils.brand_access import get_data_owner_user_id

    # Get the report with brand access validation
    db_report = get_report_with_brand_access(db, report_id, current_user.id, brand_id)

    # Scope to the report's own brand and period, and resolve the data owner
    # rather than the requesting user, so a shared brand exports real numbers
    # instead of zeros.
    report_brand_id = db_report.brand_id if db_report.brand_id is not None else brand_id
    owner_user_id = get_data_owner_user_id(db, report_brand_id, current_user.id)

    word_file = export_to_word_with_charts(
        db_report.report_content,
        db_report.title,
        db,
        user_id=owner_user_id,
        brand_id=report_brand_id,
        start_date=db_report.start_date,
        end_date=db_report.end_date,
    )

    # Create safe filename
    safe_filename = "".join(c for c in db_report.title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    filename = f"{safe_filename}.docx"

    return StreamingResponse(
        word_file,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/{report_id}/export/pptx")
def export_report_to_pptx(
    report_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Export a report to PowerPoint slideshow with embedded PNG charts (supports shared brands)."""
    from app.services.report_slideshow import generate_slideshow

    # Get the report with brand access validation
    db_report = get_report_with_brand_access(db, report_id, current_user.id, brand_id)

    # Generate PowerPoint slideshow
    pptx_file = generate_slideshow(
        db_report.report_content,
        db_report.title,
        db,
        user_id=current_user.id,
        brand_id=brand_id
    )

    # Create safe filename
    safe_filename = "".join(c for c in db_report.title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    filename = f"{safe_filename}.pptx"

    return StreamingResponse(
        pptx_file,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/{report_id}/export/csv")
def export_report_data_to_csv(
    report_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    brand_id: Optional[int] = Depends(get_active_brand_id)
):
    """Export all response data for a report's date range as CSV spreadsheet."""
    import csv
    from app.utils.brand_access import get_data_owner_user_id

    from app.services.metrics_core import MENTION_VALUES

    # Get the report with brand access validation
    db_report = get_report_with_brand_access(db, report_id, current_user.id, brand_id)

    # Scope to the brand the REPORT belongs to, not whichever brand happens to be
    # active in the UI. Previously you could open a January report for brand A,
    # switch to brand B, and export brand B's responses under brand A's title.
    # Legacy reports predate the column, so fall back to the active brand.
    report_brand_id = db_report.brand_id if db_report.brand_id is not None else brand_id

    # Get the data owner user_id
    data_owner_user_id = get_data_owner_user_id(db, report_brand_id, current_user.id)

    # Get all responses for this user/brand
    # If report has date range, filter by it; otherwise get all responses
    query = db.query(models.Response).filter(
        models.Response.user_id == data_owner_user_id,
        models.Response.brand_id == report_brand_id
    )

    # Filter by report's date range if available.
    # NOTE: the `<=` here is inclusive while scripts/admin/generate_report.py uses
    # an exclusive `<` against a first-of-next-month end_date, and both
    # conventions are present in the reports table. Unifying on a half-open
    # [start, end) window changes which rows land in a period, so it is deferred
    # to the timezone work rather than slipped in with the export fixes.
    if db_report.start_date:
        query = query.filter(models.Response.timestamp >= db_report.start_date)
    if db_report.end_date:
        query = query.filter(models.Response.timestamp <= db_report.end_date)

    responses = query.order_by(models.Response.timestamp.desc()).all()

    # Rows can be present here and still absent from the published metrics, for
    # four different reasons. The export has to say which, otherwise there is no
    # way to get from this spreadsheet back to the number printed in the report.
    brand_queries = db.query(models.Query).filter(
        models.Query.user_id == data_owner_user_id,
        models.Query.brand_id == report_brand_id,
    ).all()
    branded_query_ids = {q.query_id for q in brand_queries if q.brand_in_query}
    known_query_ids = {q.query_id for q in brand_queries}

    def exclusion_reason(response) -> str:
        """Why this row is not in the metrics, matching metrics_core exactly."""
        if response.query_id not in known_query_ids:
            # Branded-ness cannot be determined without the query, so the row
            # cannot be correctly placed either way.
            return 'Query no longer exists'
        if response.query_id in branded_query_ids:
            return 'Brand named in the question'
        if response.analyzed_at is None:
            return 'Not analyzed'
        if response.brand_mentioned not in MENTION_VALUES:
            return 'Unrecognized analysis result'
        return ''

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header row
    writer.writerow([
        'ID',
        # The dashboard scopes by batch, so without this column a spreadsheet
        # cannot be reconciled against anything shown on screen.
        'Batch ID',
        'Query ID',
        'Query Text',
        'Platform',
        'Response Text',
        'Timestamp (UTC)',
        'Brand Mentioned',
        'Brand Position',
        'Sentiment',
        'Descriptors',
        'Competitors',
        'Sources',
        'Notes',
        'Analyzed At (UTC)',
        # Whether this row is behind the published number, and if not, why not.
        'Brand In Query',
        'Counted In Metrics',
        'Excluded Because',
    ])

    # Write data rows
    for response in responses:
        is_branded = response.query_id in branded_query_ids
        reason = exclusion_reason(response)
        writer.writerow([
            response.id,
            response.batch_id if response.batch_id is not None else '',
            response.query_id,
            response.query_text or '',
            response.platform,
            response.response_text,
            response.timestamp.isoformat() if response.timestamp else '',
            response.brand_mentioned or '',
            response.brand_position or '',
            response.sentiment or '',
            response.descriptors or '',
            response.competitors or '',
            response.sources or '',
            response.notes or '',
            response.analyzed_at.isoformat() if response.analyzed_at else '',
            'Yes' if is_branded else 'No',
            'No' if reason else 'Yes',
            reason,
        ])

    # Prepare response
    output.seek(0)
    # utf-8-sig, not utf-8. Without the byte-order mark Excel opens the file in
    # the system codepage, so every curly quote, em dash and accented character
    # in an AI-written answer arrives as mojibake.
    csv_content = output.getvalue().encode('utf-8-sig')

    # Create safe filename
    safe_filename = "".join(c for c in db_report.title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    filename = f"{safe_filename}_data.csv"

    return StreamingResponse(
        io.BytesIO(csv_content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@how_tales_works_router.get("/export/how-tales-works/word")
def export_how_tales_works_word(
    current_user: models.User = Depends(get_current_user)
):
    """Export How Tales Works methodology page as Word document."""
    from app.services.report_export import export_to_word

    # Methodology content
    methodology_content = """# How Tales Works

## Data Collection Methods

The analysis of your brand's AI reputation is conducted using the Tales platform, which employs a systematic multi-platform AI querying methodology. Data is collected by submitting strategically designed queries to major large language models. These queries are automatically generated using AI to cover relevant topic areas including leadership and reputation, technology and innovation, and industry positioning.

Critically, most queries are designed as "visibility tests" that deliberately exclude your brand name, allowing the study to measure organic mentions—instances where AI platforms independently reference your organization when answering relevant questions. A list of descriptive words ideally included in AI responses to describe your brand are also automatically generated by AI, as well as a list of your competitors. The queries, descriptors and competitors are all reviewed by a human and edited to ensure they fit your brand's needs. All responses are collected via API with timestamps and platform metadata, enabling temporal and cross-platform comparative analysis.

**Note:** While the Tales platform allows users to assign priority levels (High, Medium, Low) to queries and descriptors for organizational purposes, these priority designations do not impact the quantitative analysis or metric calculations in any way—all queries and descriptors are weighted equally in the analysis.

## Analytical Framework

The collected responses undergo a two-stage analysis process combining structured data extraction with AI-powered insight generation. In the first stage, Gemini 2.5 Pro analyzes each response to extract structured data including mention type (direct, indirect, or absent), brand positioning (categorized as leader, top 3, featured, listed, or not mentioned), sentiment classification (very positive, positive, neutral, negative, or mixed), associated descriptors and adjectives, competitor mentions, and cited sources.

This extraction process is context-aware, incorporating your brand's industry context, strategic messaging, target descriptors, and known competitors to ensure relevant and accurate classification. In the second stage, Gemini 2.5 Pro synthesizes these structured findings with real-time industry news and comprehensive brand context to generate strategic insights, explicitly connecting each finding to specific performance gaps and opportunities.

## Key Performance Metrics

The study calculates multiple quantitative metrics to assess your brand's AI reputation:

- **Mention Rate:** Measures the percentage of responses where the brand is referenced when not explicitly included in the query, indicating organic visibility in AI responses.
- **Sentiment Distribution:** Tracks the breakdown of positive, neutral, and negative associations across all mentions.
- **Brand Positioning:** Analyzes where your brand appears in AI-generated lists and discussions, calculating an average positioning score and leadership visibility percentage.
- **Descriptor Match Rate:** Compares target descriptors that your brand aims to be associated with against descriptors actually used by AI platforms, identifying alignment gaps.
- **Share of Voice:** Quantifies your brand's mentions relative to total organization mentions across all responses, including competitors, with weighting based on positioning strength.

All metrics are segmented by platform to identify which AI systems perform better or worse for your brand.

## Mathematical Formulas for Metric Calculations

### Brand Mentions (Mention Rate)

The mention rate quantifies how frequently your brand is referenced by AI platforms when the brand name is not explicitly included in the query, measuring organic visibility.

**Formula:**

Mention Rate (%) = (Number of Mentions / Total Qualifying Responses) × 100

| Component | Definition |
|-----------|------------|
| Numerator | Count of responses where brand_mentioned field equals 'Yes' OR 'Indirect' |
| Denominator | Total count of all responses in the analysis period |
| Critical Exclusion | Both numerator and denominator exclude responses from queries where brand_in_query = True |
| Rationale | Excluding branded queries prevents inflated mention rates and isolates organic AI platform behavior |

**Example:** If there were 85 total responses from non-branded queries, and your brand was mentioned (directly or indirectly) in 34 of them, the mention rate would be (34/85) × 100 = 40.0%

### Positioning Score

The positioning metric evaluates where your brand appears in AI-generated responses, with higher scores indicating more prominent placement.

**Average Positioning Score Formula:**

Average Positioning Score = (Sum of Individual Position Scores) / Total Responses

**Position Scoring System:**

| Position Category | Point Value |
|-------------------|-------------|
| Leader | 5 points |
| Top 3 | 4 points |
| Featured | 3 points |
| Listed | 2 points |
| Not Mentioned | 1 point |

Each response receives a score (1-5) based on how your brand was positioned. The scores are summed across all qualifying responses and divided by total response count to produce an average (range: 1.0 to 5.0). Responses from queries where brand_in_query = True are excluded.

**Leadership Visibility (Sub-metric):**

Leadership Visibility (%) = ((Leader Count + Top 3 Count) / Total Responses) × 100

This metric specifically measures high-quality visibility by combining the top two positioning categories.

### Share of Voice

Share of Voice quantifies your brand's relative visibility compared to all organizations (including competitors) mentioned across AI responses.

**Formula:**

Share of Voice (%) = (Brand Mentions / Total All Organization Mentions) × 100

| Component | Definition |
|-----------|------------|
| Brand Mentions (Numerator) | Count of responses where your brand achieved positioning of 'Leader', 'Top 3', 'Featured', or 'Listed' |
| Total Mentions (Denominator) | Sum of all organization mentions including: (1) your brand mentions and (2) all competitor mentions |
| Competitor Counting | The competitors field contains comma-separated organization names; each occurrence increments that competitor's mention count |
| Exclusion | Only responses from queries where brand_in_query = False are included |

**Example:** If your brand appeared in 34 responses with qualifying positioning, and competitors appeared in a combined 56 responses, the total mentions would be 90. Your share of voice would be (34/90) × 100 = 37.8%

### Target Descriptor Adoption

Target descriptor adoption measures how successfully your brand has become associated with the specific descriptors and attributes it aims to own strategically.

**Formula:**

Descriptor Match Rate (%) = (Number of Target Descriptors Found / Total Target Descriptors) × 100

| Component | Definition |
|-----------|------------|
| Total Target Descriptors | Count of all descriptors configured as strategic targets for your brand in the platform |
| Target Descriptors Found | Count of unique target descriptors that appear in at least one AI response |
| Matching Logic | Case-insensitive matching; a target descriptor is counted as "found" if it appears in any response where your brand was mentioned |
| Inclusion | This calculation INCLUDES responses from queries where brand_in_query = True (quality of associations matters regardless of query type) |

**Example:** If your brand has 20 target descriptors and 13 of those descriptors appeared in at least one response, the descriptor match rate would be (13/20) × 100 = 65.0%

### Competitive Threat Analysis

Competitive threat analysis combines quantitative scoring with AI-powered qualitative analysis to identify and explain strategic competitive risks.

**Formula:**
```
Threat Score = (mention_count × 0.7) + (negative_overlap × 2.0) + (positive_competitor × 1.5)
```

**Threat Level Thresholds:**
- **High Threat (score > 50):** Requires immediate strategic attention
- **Medium Threat (score 20-50):** Requires monitoring
- **Low Threat (score < 20):** Minimal competitive pressure

**Process:**

1. **Quantitative Ranking:** All competitors are scored using the threat formula above, and the top 3 threats are identified based on their scores.

2. **Data Collection Phase:** For the top 3 threats, the system gathers Share of Voice data, identifies specific query-response pairs where your brand was not mentioned but competitors were, and extracts "competitive loss" examples.

3. **AI Analysis Phase:** Submits concrete response examples and competitive data for the top 3 threats to Gemini 2.5 Pro, which generates qualitative narrative analysis explaining why each competitor is a threat, what specific queries they are winning, what descriptors and positioning they have claimed, strategic implications, and recommended counter-actions.

4. **Output:** Quantitative threat scores and rankings for all competitors, plus qualitative descriptions of top 3 competitive threats with specific examples, strategic implications, and recommended counter-actions.

**Rationale:** The quantitative threat score efficiently identifies which competitors pose the greatest risk, while the AI-generated qualitative analysis provides strategic context and concrete examples that a formula alone cannot deliver.

### Summary of Metric Calculation Approaches

| Metric | Type | Includes Branded Queries? | Rationale |
|--------|------|---------------------------|-----------|
| Mention Rate | Quantitative Formula | No (Excluded) | Measures organic visibility without bias |
| Positioning Score | Quantitative Formula | No (Excluded) | Assesses natural positioning |
| Share of Voice | Quantitative Formula | No (Excluded) | Compares competitive visibility organically |
| Descriptor Match | Quantitative Formula | Yes (Included) | Quality of associations matters regardless of query type |
| Sentiment Distribution | Quantitative Formula | Yes (Included) | Sentiment reflects perception across all contexts |
| Competitive Threats | Qualitative AI Analysis | Context-dependent | Strategic nuance requires pattern recognition |

## Competitive Intelligence Analysis

Competitor analysis forms a critical component of the methodology, examining how your brand performs relative to other organizations in AI-generated discourse. The system tracks pre-configured competitors with metadata including organization type, focus areas, and key descriptors, while also automatically extracting mentions of organizations not initially identified as competitors.

Co-occurrence analysis reveals which competitors frequently appear alongside your brand in AI responses, and comparative share of voice calculations quantify relative visibility. The analysis identifies specific queries where competitors received more favorable positioning than your brand, extracts the descriptors and positioning competitors own, and examines concrete response examples showing competitive advantages. These findings surface where the competitive gaps are and which strategic positioning is currently owned by rivals.

## Working With the Findings

Tales reports describe what the data shows; they do not prescribe what to do about it. Reports and the accompanying spreadsheet exports are designed to be read directly, or handed to an AI assistant of your choosing along with whatever strategic context matters to your organization, so that any recommendations reflect priorities Tales has no visibility into.

## Limitations and Considerations

Several important limitations should be considered when interpreting these findings. AI platform responses can vary over time due to model updates, training data changes, and index refreshes, meaning that findings represent a snapshot rather than static characteristics. Finally, while the analysis identifies correlations between content strategies and AI reputation metrics, establishing direct causation requires controlled longitudinal studies that account for confounding variables such as broader industry trends, news coverage, and publication timing effects.
"""

    # Generate Word document
    word_file = export_to_word(methodology_content, "How Tales Works")

    return StreamingResponse(
        word_file,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=How_Tales_Works.docx"}
    )
