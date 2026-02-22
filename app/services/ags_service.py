"""
Assignment and Grade Services (AGS) Service

Handles:
- OAuth 2.0 client credentials flow with Moodle
- Grade submission to LMS
"""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from authlib.jose import JsonWebToken

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# In-memory token cache
_token_cache: dict[str, Any] = {}

# AGS content types
CONTENT_TYPE_LINEITEM = "application/vnd.ims.lis.v2.lineitem+json"
CONTENT_TYPE_SCORE = "application/vnd.ims.lis.v1.score+json"


def _build_ags_headers(
    access_token: str,
    content_type: str | None = None,
    accept: str | None = None,
) -> dict[str, str]:
    """Build headers for AGS API requests."""
    headers = {"Authorization": f"Bearer {access_token}"}
    if content_type:
        headers["Content-Type"] = content_type
    if accept:
        headers["Accept"] = accept
    return headers


def _generate_client_assertion() -> str:
    """
    Generate a signed JWT for client credentials authentication.

    This JWT proves our identity to the LMS token endpoint.
    """
    now = int(time.time())

    header = {"alg": "RS256", "typ": "JWT", "kid": "edubridge-1"}

    payload = {
        "iss": settings.LTI_CLIENT_ID,  # We are the issuer
        "sub": settings.LTI_CLIENT_ID,  # We are the subject
        "aud": settings.ACCESS_TOKEN_URL,  # Token endpoint is the audience
        "iat": now,
        "exp": now + 300,  # 5 minutes
        "jti": str(uuid.uuid4()),  # Unique token ID
    }

    jwt = JsonWebToken(["RS256"])
    token = jwt.encode(header, payload, settings.LTI_PRIVATE_KEY)

    return token.decode("utf-8") if isinstance(token, bytes) else token


async def get_access_token(scopes: list[str]) -> str:
    """
    Get an access token from the LMS using client credentials flow.

    Caches the token until it expires.
    """
    global _token_cache

    scope_key = " ".join(sorted(scopes))

    # Check cache
    cached = _token_cache.get(scope_key)
    if cached and cached["expires_at"] > time.time() + 60:  # 60s buffer
        logger.debug("Using cached access token")
        return cached["access_token"]

    logger.info("Requesting new access token from LMS")

    # Generate client assertion
    client_assertion = _generate_client_assertion()

    # Request token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.ACCESS_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": client_assertion,
                "scope": scope_key,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )

        if response.status_code != 200:
            logger.error(f"Token request failed: {response.status_code} {response.text}")
            raise ValueError(f"Failed to get access token: {response.text}")

        data = response.json()

    # Cache token
    _token_cache[scope_key] = {
        "access_token": data["access_token"],
        "expires_at": time.time() + data.get("expires_in", 3600),
    }

    logger.info("Access token obtained successfully")
    return data["access_token"]


async def get_lineitem(lineitem_url: str) -> dict[str, Any]:
    """
    Fetch lineitem details from the LMS.
    """
    scopes = [
        "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem",
    ]

    access_token = await get_access_token(scopes)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            lineitem_url,
            headers=_build_ags_headers(access_token, accept=CONTENT_TYPE_LINEITEM),
            timeout=10.0,
        )

        logger.info(f"Lineitem response: status={response.status_code}, body={response.text}")

        if response.status_code != 200:
            raise ValueError(f"Failed to fetch lineitem: {response.text}")

        return response.json()


async def submit_score(
    lineitem_url: str,
    user_sub: str,
    score_given: float,
    score_maximum: float | None = None,  # If None, fetch from lineitem
    activity_progress: str = "Completed",
    grading_progress: str = "FullyGraded",
) -> dict[str, Any]:
    """
    Submit a score to the LMS via AGS.

    Posts to {lineitem_url}/scores
    """
    # Fetch the actual scoreMaximum from the lineitem if not provided
    if score_maximum is None:
        lineitem = await get_lineitem(lineitem_url)
        logger.info(f"Lineitem data: {lineitem}")
        score_maximum = float(lineitem.get("scoreMaximum", 100.0))
        logger.info(f"Fetched lineitem scoreMaximum: {score_maximum}")

    # Handle URLs with query strings - insert /scores before the query
    if "?" in lineitem_url:
        base, query = lineitem_url.split("?", 1)
        scores_url = f"{base}/scores?{query}"
    else:
        scores_url = f"{lineitem_url}/scores"

    # Required scopes for score submission
    scopes = [
        "https://purl.imsglobal.org/spec/lti-ags/scope/score",
    ]

    access_token = await get_access_token(scopes)

    # Moodle expects timestamp with Z suffix, not +00:00
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    # Don't scale - user enters raw score value
    # (We'll add proper scaling later if needed)
    logger.info(f"Score: {score_given} (max: {score_maximum})")

    payload = {
        "timestamp": timestamp,
        "scoreGiven": float(score_given),
        "scoreMaximum": float(score_maximum),
        "activityProgress": activity_progress,
        "gradingProgress": grading_progress,
        "userId": user_sub,
    }

    logger.info(f"Submitting score to {scores_url}: {score_given}/{score_maximum}")
    logger.info(f"Score payload: {payload}")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            scores_url,
            json=payload,
            headers=_build_ags_headers(access_token, content_type=CONTENT_TYPE_SCORE),
            timeout=10.0,
        )

        logger.info(f"Score response: status={response.status_code}, body={response.text}")

        if response.status_code not in (200, 201, 204):
            logger.error(f"Score submission failed: {response.status_code} {response.text}")
            raise ValueError(f"Failed to submit score (HTTP {response.status_code}): {response.text}")

    logger.info("Score submitted successfully")
    return {"status": "success", "score_given": score_given}


async def create_lineitem(
    lineitems_url: str,
    label: str,
    score_maximum: float = 100.0,
    resource_link_id: str | None = None,
) -> str:
    """
    Create a new line item in the LMS gradebook.

    Returns the URL of the created line item.
    """
    scopes = [
        "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem",
    ]

    access_token = await get_access_token(scopes)

    payload = {
        "label": label,
        "scoreMaximum": score_maximum,
    }

    if resource_link_id:
        payload["resourceLinkId"] = resource_link_id

    logger.info(f"Creating line item at {lineitems_url}")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            lineitems_url,
            json=payload,
            headers=_build_ags_headers(access_token, content_type=CONTENT_TYPE_LINEITEM),
            timeout=10.0,
        )

        if response.status_code not in (200, 201):
            logger.error(f"Line item creation failed: {response.status_code} {response.text}")
            raise ValueError(f"Failed to create line item: {response.text}")

        data = response.json()

    lineitem_url = data.get("id")
    logger.info(f"Line item created: {lineitem_url}")
    return lineitem_url


def extract_ags_claim(claims: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extract AGS endpoint information from launch claims.

    Returns None if AGS is not available in this launch.
    """
    ags_claim = claims.get("https://purl.imsglobal.org/spec/lti-ags/claim/endpoint")

    if not ags_claim:
        return None

    return {
        "lineitem": ags_claim.get("lineitem"),  # Specific line item URL
        "lineitems": ags_claim.get("lineitems"),  # Collection URL
        "scope": ags_claim.get("scope", []),  # Available scopes
    }


def is_instructor(roles: list[str]) -> bool:
    """
    Check if user has instructor/teacher role.
    """
    instructor_roles = [
        "Instructor",
        "Teacher",
        "TeachingAssistant",
        "Administrator",
        "ContentDeveloper",
    ]

    for role in roles:
        for instructor_role in instructor_roles:
            if instructor_role in role:
                return True

    return False
