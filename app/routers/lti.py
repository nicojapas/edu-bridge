"""
LTI 1.3 Endpoints

Implements the OIDC-based LTI 1.3 launch flow:
1. /lti/login  - OIDC Login Initiation (GET from LMS)
2. /lti/launch - OIDC Redirect URI (POST with id_token)
3. /lti/config - Tool configuration helper
"""

from fastapi import APIRouter, Form, Query, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse

from app.services import lti_service
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/lti", tags=["LTI"])


@router.get("/login")
async def lti_login(
    iss: str = Query(..., description="Issuer (LMS platform identifier)"),
    login_hint: str = Query(..., description="User identifier from LMS"),
    target_link_uri: str = Query(..., description="Where to redirect after auth"),
    lti_message_hint: str | None = Query(None, description="Optional LMS context"),
    client_id: str | None = Query(None, description="Client ID (for multi-tenant)"),
):
    """
    OIDC Login Initiation Endpoint.

    Step 1 of LTI 1.3 launch:
    - LMS redirects user here to start authentication
    - We generate state/nonce for security
    - We redirect to LMS authorization endpoint

    The LMS will authenticate the user and POST back to /lti/launch.
    """
    logger.info(f"LTI login initiated: iss={iss}, login_hint={login_hint}")

    # Generate state (CSRF) and nonce (replay protection)
    state, nonce = lti_service.generate_state_and_nonce(
        login_hint=login_hint,
        target_link_uri=target_link_uri,
    )

    # Build redirect URL to LMS authorization endpoint
    auth_url = lti_service.build_auth_redirect_url(
        login_hint=login_hint,
        state=state,
        nonce=nonce,
        lms_login_hint=lti_message_hint,
    )

    logger.info(f"Redirecting to LMS auth endpoint")
    return RedirectResponse(url=auth_url, status_code=302)


@router.post("/launch", response_class=HTMLResponse)
async def lti_launch(
    id_token: str = Form(..., description="JWT from LMS"),
    state: str = Form(..., description="State we sent in login"),
):
    """
    OIDC Redirect URI / Launch Endpoint.

    Step 2 of LTI 1.3 launch:
    - LMS POSTs the id_token here after user authentication
    - We verify state matches what we sent
    - We validate the JWT (signature + claims)
    - We extract launch data and display it

    In a real app, this would establish a session and redirect to the tool UI.
    """
    logger.info("LTI launch received")

    # Step 1: Verify state exists and get stored data
    stored_data = lti_service.verify_state(state)
    if not stored_data:
        logger.warning("Invalid or expired state")
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    # Step 2: Validate JWT and extract claims
    try:
        claims = await lti_service.validate_and_decode_id_token(
            id_token=id_token,
            expected_nonce=stored_data["nonce"],
        )
    except ValueError as e:
        logger.error(f"Token validation failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))

    # Step 3: Extract launch data from validated claims
    launch_data = lti_service.extract_launch_data(claims)
    logger.info(f"Launch successful for user: {launch_data.get('name')}")

    # Step 4: Render launch page
    # In production, you'd create a session and redirect to your app
    html = lti_service.render_launch_page(launch_data)
    return HTMLResponse(content=html)


@router.get("/config", response_class=JSONResponse)
async def lti_config():
    """
    Tool Configuration Endpoint.

    Returns JSON with tool configuration to help with manual
    registration in Moodle or other LMS platforms.

    This is not part of the LTI spec, just a helper.
    """
    config = lti_service.get_tool_configuration()
    return JSONResponse(content=config)
