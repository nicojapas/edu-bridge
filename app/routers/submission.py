"""
Submission Router

Handles student essay submissions and AI auto-grading.
Also provides instructor view of submissions.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import LtiLaunch, Submission
from app.services import ags_service
from app.services.grading_service import grade_essay
from app.logging_config import get_logger

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

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


@router.get("/instructor/{launch_id}")
async def instructor_view(
    request: Request,
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

    return templates.TemplateResponse(
        request=request,
        name="instructor_submissions.html",
        context={
            "context_id": launch.context_id,
            "submissions": submissions,
        },
    )
