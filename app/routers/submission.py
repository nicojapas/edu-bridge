"""
Submission Router

Handles student essay submissions and AI auto-grading.
Also provides instructor view of submissions.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import LtiLaunch, Submission
from app.services import ags_service
from app.services.grading_service import grade_essay
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/submission", tags=["Submission"])


class EssaySubmission(BaseModel):
    launch_id: int
    essay_text: str


class EvaluationResponse(BaseModel):
    submission_id: int
    score: float
    feedback: str
    grade_passback_status: str


@router.post("/evaluate", response_model=EvaluationResponse)
async def evaluate_submission(
    submission: EssaySubmission,
    session: AsyncSession = Depends(get_session),
):
    """
    Evaluate a student essay submission.

    1. Retrieve launch context
    2. Grade the essay using AI heuristics
    3. Store submission in database
    4. Push grade to Moodle via AGS
    5. Return feedback to student
    """
    logger.info(f"Essay submission received: launch_id={submission.launch_id}")

    # Get launch context
    result = await session.execute(
        select(LtiLaunch).where(LtiLaunch.id == submission.launch_id)
    )
    launch = result.scalar_one_or_none()

    if not launch:
        raise HTTPException(status_code=404, detail="Launch not found")

    if not launch.lineitem_url and not launch.lineitems_url:
        raise HTTPException(status_code=400, detail="This launch does not support AGS")

    # Grade the essay
    grading_result = grade_essay(submission.essay_text)

    # Store submission
    submission_record = Submission(
        launch_id=launch.id,
        user_sub=launch.user_sub,
        essay_text=submission.essay_text,
        score=grading_result.score,
        feedback=grading_result.feedback,
    )
    session.add(submission_record)
    await session.commit()
    await session.refresh(submission_record)

    logger.info(f"Submission stored with id={submission_record.id}, score={grading_result.score}")

    # Push grade to Moodle via AGS
    grade_passback_status = "success"
    try:
        if launch.lineitem_url:
            await ags_service.submit_score(
                lineitem_url=launch.lineitem_url,
                user_sub=launch.user_sub,
                score_given=grading_result.score,
            )
        else:
            # Create lineitem first
            lineitem_url = await ags_service.create_lineitem(
                lineitems_url=launch.lineitems_url,
                label="EduBridge AI Essay",
                score_maximum=100.0,
                resource_link_id=launch.resource_link_id,
            )
            await ags_service.submit_score(
                lineitem_url=lineitem_url,
                user_sub=launch.user_sub,
                score_given=grading_result.score,
                score_maximum=100.0,
            )
        logger.info("Grade pushed to Moodle successfully")
    except ValueError as e:
        logger.error(f"Grade passback failed: {e}")
        grade_passback_status = f"failed: {str(e)}"

    return EvaluationResponse(
        submission_id=submission_record.id,
        score=grading_result.score,
        feedback=grading_result.feedback,
        grade_passback_status=grade_passback_status,
    )


@router.get("/instructor/{launch_id}", response_class=HTMLResponse)
async def instructor_view(
    launch_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Instructor view: list all submissions for a given context.
    """
    # Get launch context to verify and get context_id
    result = await session.execute(
        select(LtiLaunch).where(LtiLaunch.id == launch_id)
    )
    launch = result.scalar_one_or_none()

    if not launch:
        raise HTTPException(status_code=404, detail="Launch not found")

    # Get all launches with same context_id (all students in same course/activity)
    result = await session.execute(
        select(LtiLaunch.id).where(LtiLaunch.context_id == launch.context_id)
    )
    context_launch_ids = [row[0] for row in result.fetchall()]

    # Get all submissions for those launches
    result = await session.execute(
        select(Submission)
        .where(Submission.launch_id.in_(context_launch_ids))
        .order_by(Submission.created_at.desc())
    )
    submissions = result.scalars().all()

    # Build HTML table
    rows = ""
    for sub in submissions:
        # Escape feedback for HTML display (convert markdown to simple text)
        feedback_preview = sub.feedback[:100] + "..." if len(sub.feedback) > 100 else sub.feedback
        feedback_preview = feedback_preview.replace("<", "&lt;").replace(">", "&gt;")

        rows += f"""
        <tr>
            <td style="font-family: monospace; font-size: 12px;">{sub.user_sub[:20]}...</td>
            <td style="font-weight: bold; color: {'#38a169' if sub.score >= 70 else '#e53e3e' if sub.score < 50 else '#d69e2e'};">
                {sub.score:.0f}/100
            </td>
            <td style="font-size: 12px;">{sub.created_at.strftime('%Y-%m-%d %H:%M')}</td>
            <td>
                <button onclick="showFeedback({sub.id})" style="padding: 4px 8px; cursor: pointer;">
                    View Details
                </button>
            </td>
        </tr>
        <tr id="feedback-{sub.id}" style="display: none;">
            <td colspan="4" style="background: #f7fafc; padding: 16px;">
                <strong>Essay:</strong>
                <pre style="white-space: pre-wrap; background: white; padding: 8px; border: 1px solid #e2e8f0; margin: 8px 0;">{sub.essay_text[:500]}{'...' if len(sub.essay_text) > 500 else ''}</pre>
                <strong>Feedback:</strong>
                <pre style="white-space: pre-wrap; background: white; padding: 8px; border: 1px solid #e2e8f0; margin: 8px 0;">{sub.feedback}</pre>
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Instructor View - Submissions</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 900px;
                margin: 40px auto;
                padding: 20px;
                background: #f5f5f5;
            }}
            .card {{
                background: white;
                border-radius: 8px;
                padding: 24px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #2d3748;
                margin-top: 0;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 16px;
            }}
            th, td {{
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #e2e8f0;
            }}
            th {{
                background: #f7fafc;
                font-weight: 600;
                color: #4a5568;
            }}
            .back-link {{
                display: inline-block;
                margin-bottom: 16px;
                color: #3182ce;
                text-decoration: none;
            }}
            .back-link:hover {{
                text-decoration: underline;
            }}
            .empty {{
                color: #718096;
                padding: 40px;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Student Submissions</h1>
            <p style="color: #718096;">Context: {launch.context_id}</p>

            {f'''
            <table>
                <thead>
                    <tr>
                        <th>Student ID</th>
                        <th>Score</th>
                        <th>Submitted</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
            ''' if submissions else '<div class="empty">No submissions yet.</div>'}
        </div>

        <script>
            function showFeedback(id) {{
                const row = document.getElementById('feedback-' + id);
                if (row.style.display === 'none') {{
                    row.style.display = 'table-row';
                }} else {{
                    row.style.display = 'none';
                }}
            }}
        </script>
    </body>
    </html>
    """

    return HTMLResponse(content=html)
