"""
Grade Submission Endpoint

Allows instructors to submit grades back to the LMS.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import LtiLaunch
from app.services import ags_service
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/grades", tags=["Grades"])


class ScoreSubmission(BaseModel):
    launch_id: int
    user_sub: str  # The student to grade
    score: float  # 0-100


@router.post("/submit")
async def submit_grade(
    submission: ScoreSubmission,
    session: AsyncSession = Depends(get_session),
):
    """
    Submit a grade to the LMS.

    Requires a valid launch_id with AGS support.
    """
    logger.info(f"Grade submission: launch_id={submission.launch_id}, score={submission.score}")

    # Get launch context
    result = await session.execute(
        select(LtiLaunch).where(LtiLaunch.id == submission.launch_id)
    )
    launch = result.scalar_one_or_none()

    if not launch:
        raise HTTPException(status_code=404, detail="Launch not found")

    if not launch.lineitem_url and not launch.lineitems_url:
        raise HTTPException(status_code=400, detail="This launch does not support AGS")

    try:
        # If we have a direct lineitem URL, use it
        if launch.lineitem_url:
            # Let submit_score fetch the actual scoreMaximum from the lineitem
            result = await ags_service.submit_score(
                lineitem_url=launch.lineitem_url,
                user_sub=submission.user_sub,
                score_given=submission.score,
            )
        else:
            # Need to create a line item first - we control the scoreMaximum here
            lineitem_url = await ags_service.create_lineitem(
                lineitems_url=launch.lineitems_url,
                label="EduBridge Grade",
                score_maximum=100.0,
                resource_link_id=launch.resource_link_id,
            )

            result = await ags_service.submit_score(
                lineitem_url=lineitem_url,
                user_sub=submission.user_sub,
                score_given=submission.score,
                score_maximum=100.0,  # We just created it with 100
            )

        return {"message": "Grade submitted successfully", "result": result}

    except ValueError as e:
        logger.error(f"Grade submission failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
