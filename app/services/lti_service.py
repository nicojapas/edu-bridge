"""
LTI 1.3 Service

Handles OIDC login flow and JWT validation for LTI 1.3 tool launches.

LTI 1.3 uses OIDC for authentication:
1. LMS initiates login by redirecting to tool's /lti/login
2. Tool redirects back to LMS authorization endpoint with OIDC params
3. LMS authenticates user and POSTs id_token to tool's /lti/launch
4. Tool validates the JWT and extracts launch data
"""

import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebToken
from authlib.jose.errors import JoseError

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# In-memory storage for state/nonce (sufficient for single-instance dev)
# Production would use Redis or database
_state_store: dict[str, dict[str, Any]] = {}

# In-memory JWKS cache
_jwks_cache: dict[str, Any] = {}
_jwks_cache_time: float = 0
JWKS_CACHE_TTL: int = 3600  # 1 hour


def generate_state_and_nonce(login_hint: str, target_link_uri: str) -> tuple[str, str]:
    """
    Generate and store state + nonce for OIDC flow.

    State: Ties the login request to the launch callback (CSRF protection)
    Nonce: Prevents token replay attacks
    """
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # Store with timestamp for potential cleanup
    _state_store[state] = {
        "nonce": nonce,
        "login_hint": login_hint,
        "target_link_uri": target_link_uri,
        "created_at": time.time(),
    }

    logger.info(f"Generated state for login_hint={login_hint}")
    return state, nonce


def build_auth_redirect_url(
    login_hint: str,
    state: str,
    nonce: str,
    lms_login_hint: str | None = None,
) -> str:
    """
    Build the URL to redirect user to LMS authorization endpoint.

    This follows OIDC Authorization Code flow (implicit with id_token).
    The LMS will authenticate the user and POST the id_token back to us.
    """
    params = {
        # OIDC required params
        "response_type": "id_token",  # LTI 1.3 uses implicit flow with id_token
        "response_mode": "form_post",  # Token comes via POST, not URL fragment
        "scope": "openid",  # Minimal scope for LTI
        "client_id": settings.LTI_CLIENT_ID,
        "redirect_uri": settings.lti_redirect_uri,
        "login_hint": login_hint,  # User identifier from LMS
        "state": state,  # CSRF protection
        "nonce": nonce,  # Replay protection
        "prompt": "none",  # User already authenticated in LMS
    }

    # Some LMS send lti_message_hint which must be forwarded
    if lms_login_hint:
        params["lti_message_hint"] = lms_login_hint

    url = f"{settings.LTI_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"
    logger.debug(f"Built auth redirect URL: {url}")
    return url


def verify_state(state: str) -> dict[str, Any] | None:
    """
    Verify state exists and return stored data.

    Removes state after verification (one-time use).
    """
    stored = _state_store.pop(state, None)
    if not stored:
        logger.warning(f"State not found: {state[:16]}...")
        return None

    # Check if state is too old (5 minute expiry)
    if time.time() - stored["created_at"] > 300:
        logger.warning("State expired")
        return None

    return stored


async def fetch_jwks() -> dict[str, Any]:
    """
    Fetch JWKS from LMS for JWT signature verification.

    Caches the JWKS to avoid fetching on every request.
    """
    global _jwks_cache, _jwks_cache_time

    # Return cached if still valid
    if _jwks_cache and (time.time() - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    logger.info(f"Fetching JWKS from {settings.LTI_JWKS_URL}")

    async with httpx.AsyncClient() as client:
        response = await client.get(settings.LTI_JWKS_URL, timeout=10.0)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_time = time.time()

    return _jwks_cache


async def validate_and_decode_id_token(
    id_token: str,
    expected_nonce: str,
) -> dict[str, Any]:
    """
    Validate the LTI launch id_token (JWT).

    Validation steps:
    1. Fetch JWKS from LMS
    2. Verify JWT signature using JWKS
    3. Validate standard claims (iss, aud, exp)
    4. Validate nonce matches what we sent

    Returns decoded token claims on success.
    Raises exception on validation failure.
    """
    # Fetch JWKS for signature verification
    jwks = await fetch_jwks()

    # Create JWT instance and decode
    jwt = JsonWebToken(["RS256"])

    try:
        # Decode and verify signature
        claims = jwt.decode(
            id_token,
            key=jwks,
            claims_options={
                "iss": {"essential": True, "value": settings.LTI_ISSUER},
                "aud": {"essential": True, "value": settings.LTI_CLIENT_ID},
                "exp": {"essential": True},
                "nonce": {"essential": True, "value": expected_nonce},
            },
        )

        # Validate claims (checks exp, iss, aud, nonce)
        claims.validate()

        logger.info(f"Token validated for sub={claims.get('sub')}")
        return dict(claims)

    except JoseError as e:
        logger.error(f"JWT validation failed: {e}")
        raise ValueError(f"Invalid token: {e}") from e


def extract_launch_data(claims: dict[str, Any]) -> dict[str, Any]:
    """
    Extract relevant LTI launch data from validated token claims.

    LTI 1.3 uses namespaced claims for LTI-specific data.
    """
    # Standard OIDC claims
    launch_data = {
        "sub": claims.get("sub"),  # User ID
        "name": claims.get("name"),
        "given_name": claims.get("given_name"),
        "family_name": claims.get("family_name"),
        "email": claims.get("email"),
    }

    # LTI-specific claims (namespaced)
    # https://www.imsglobal.org/spec/lti/v1p3#required-message-claims

    # Context (course) information
    context = claims.get("https://purl.imsglobal.org/spec/lti/claim/context", {})
    launch_data["context_id"] = context.get("id")
    launch_data["context_title"] = context.get("title")
    launch_data["context_label"] = context.get("label")

    # Roles
    launch_data["roles"] = claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/roles", []
    )

    # Resource link (the specific placement)
    resource_link = claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/resource_link", {}
    )
    launch_data["resource_link_id"] = resource_link.get("id")
    launch_data["resource_link_title"] = resource_link.get("title")

    # Platform instance info
    tool_platform = claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/tool_platform", {}
    )
    launch_data["platform_name"] = tool_platform.get("name")

    # Message type and version
    launch_data["message_type"] = claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/message_type"
    )
    launch_data["lti_version"] = claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/version"
    )

    return launch_data


def render_launch_page(
    launch_data: dict[str, Any],
    launch_id: int | None = None,
    has_ags: bool = False,
    is_instructor: bool = False,
) -> str:
    """
    Render a simple HTML page showing launch information.

    If AGS is available and user is instructor, show link to submissions view.
    If AGS is available and user is student, show essay submission form.
    """
    # Format roles nicely
    roles = launch_data.get("roles", [])
    role_items = "".join(f"<li>{role.split('#')[-1]}</li>" for role in roles)

    # Build AGS section based on role
    ags_section = ""
    if has_ags:
        if is_instructor:
            # Instructor view: link to submissions and manual grade form
            ags_section = f"""
            <div class="ags-section">
                <h2>Instructor Tools</h2>
                <p>
                    <a href="/submission/instructor/{launch_id}"
                       style="display: inline-block; padding: 10px 20px; background: #3182ce; color: white; text-decoration: none; border-radius: 4px;">
                        View Student Submissions
                    </a>
                </p>

                <h3 style="margin-top: 24px; font-size: 16px;">Manual Grade Override</h3>
                <form id="gradeForm">
                    <input type="hidden" name="launch_id" value="{launch_id}">
                    <div class="field">
                        <label class="label">Student ID (sub):</label>
                        <input type="text" name="user_sub" placeholder="Enter student sub" required
                               style="width: 100%; padding: 8px; margin-top: 4px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>
                    <div class="field">
                        <label class="label">Score (0-100):</label>
                        <input type="number" name="score" min="0" max="100" required
                               style="width: 100%; padding: 8px; margin-top: 4px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>
                    <button type="submit" style="margin-top: 12px; padding: 10px 20px; background: #718096; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        Submit Manual Grade
                    </button>
                </form>
                <div id="result" style="margin-top: 12px;"></div>
                <script>
                    document.getElementById('gradeForm').addEventListener('submit', async (e) => {{
                        e.preventDefault();
                        const form = e.target;
                        const resultDiv = document.getElementById('result');
                        resultDiv.innerHTML = 'Submitting...';

                        try {{
                            const response = await fetch('/grades/submit', {{
                                method: 'POST',
                                headers: {{ 'Content-Type': 'application/json' }},
                                body: JSON.stringify({{
                                    launch_id: parseInt(form.launch_id.value),
                                    user_sub: form.user_sub.value,
                                    score: parseFloat(form.score.value)
                                }})
                            }});

                            const data = await response.json();
                            if (response.ok) {{
                                resultDiv.innerHTML = '<span style="color: #38a169;">Grade submitted successfully!</span>';
                            }} else {{
                                resultDiv.innerHTML = '<span style="color: #e53e3e;">Error: ' + data.detail + '</span>';
                            }}
                        }} catch (err) {{
                            resultDiv.innerHTML = '<span style="color: #e53e3e;">Error: ' + err.message + '</span>';
                        }}
                    }});
                </script>
            </div>
            """
        else:
            # Student view: essay submission form
            ags_section = f"""
            <div class="ags-section">
                <h2>Submit Your Essay</h2>
                <p style="color: #718096; margin-bottom: 16px;">
                    Write your essay below. It will be evaluated by our AI grading system and your score will be automatically submitted.
                </p>
                <form id="essayForm">
                    <input type="hidden" name="launch_id" value="{launch_id}">
                    <div class="field">
                        <label class="label">Your Essay:</label>
                        <textarea name="essay_text" rows="10" required
                                  placeholder="Write about AI in education, learning integrity, or related topics..."
                                  style="width: 100%; padding: 12px; margin-top: 4px; border: 1px solid #ccc; border-radius: 4px; font-family: inherit; resize: vertical;"></textarea>
                    </div>
                    <p style="color: #718096; font-size: 12px; margin: 8px 0;">
                        Tip: Include keywords like "ai", "education", "integrity", "learning" for bonus points!
                    </p>
                    <button type="submit" id="submitBtn" style="margin-top: 12px; padding: 12px 24px; background: #38a169; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px;">
                        Submit for AI Evaluation
                    </button>
                </form>
                <div id="result" style="margin-top: 20px;"></div>
                <script>
                    document.getElementById('essayForm').addEventListener('submit', async (e) => {{
                        e.preventDefault();
                        const form = e.target;
                        const resultDiv = document.getElementById('result');
                        const submitBtn = document.getElementById('submitBtn');

                        submitBtn.disabled = true;
                        submitBtn.innerHTML = 'Evaluating...';
                        resultDiv.innerHTML = '<p style="color: #718096;">Processing your submission...</p>';

                        try {{
                            const response = await fetch('/submission/evaluate', {{
                                method: 'POST',
                                headers: {{ 'Content-Type': 'application/json' }},
                                body: JSON.stringify({{
                                    launch_id: parseInt(form.launch_id.value),
                                    essay_text: form.essay_text.value
                                }})
                            }});

                            const data = await response.json();
                            if (response.ok) {{
                                const feedbackHtml = data.feedback.replace(/\\n/g, '<br>').replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
                                resultDiv.innerHTML = `
                                    <div style="background: #f0fff4; border: 1px solid #9ae6b4; border-radius: 8px; padding: 16px;">
                                        <h3 style="color: #276749; margin: 0 0 16px 0;">Evaluation Complete!</h3>
                                        <div style="background: white; padding: 16px; border-radius: 4px; margin-bottom: 12px;">
                                            ${{feedbackHtml}}
                                        </div>
                                        <p style="color: #718096; font-size: 12px; margin: 0;">
                                            Grade passback: ${{data.grade_passback_status}}
                                        </p>
                                    </div>
                                `;
                                submitBtn.innerHTML = 'Submitted!';
                                submitBtn.style.background = '#718096';
                            }} else {{
                                resultDiv.innerHTML = '<p style="color: #e53e3e;">Error: ' + data.detail + '</p>';
                                submitBtn.disabled = false;
                                submitBtn.innerHTML = 'Submit for AI Evaluation';
                            }}
                        }} catch (err) {{
                            resultDiv.innerHTML = '<p style="color: #e53e3e;">Error: ' + err.message + '</p>';
                            submitBtn.disabled = false;
                            submitBtn.innerHTML = 'Submit for AI Evaluation';
                        }}
                    }});
                </script>
            </div>
            """
    else:
        ags_section = """
        <div class="ags-section">
            <p style="color: #718096; font-size: 14px;">This launch does not support AGS (grading).</p>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>LTI Launch Successful</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 600px;
                margin: 40px auto;
                padding: 20px;
                background: #f5f5f5;
            }}
            .card {{
                background: white;
                border-radius: 8px;
                padding: 24px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }}
            h1 {{
                color: #2d3748;
                margin-top: 0;
            }}
            h2 {{
                color: #2d3748;
                margin-top: 0;
                font-size: 18px;
            }}
            h3 {{
                color: #4a5568;
            }}
            .field {{
                margin: 12px 0;
            }}
            .label {{
                font-weight: 600;
                color: #4a5568;
            }}
            .value {{
                color: #2d3748;
            }}
            ul {{
                margin: 4px 0;
                padding-left: 20px;
            }}
            .success {{
                color: #38a169;
                font-size: 14px;
            }}
            .ags-section {{
                margin-top: 20px;
                padding-top: 20px;
                border-top: 1px solid #e2e8f0;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <p class="success">LTI 1.3 Launch Successful</p>
            <h1>Welcome, {launch_data.get('name') or 'User'}!</h1>

            <div class="field">
                <span class="label">Email:</span>
                <span class="value">{launch_data.get('email') or 'Not provided'}</span>
            </div>

            <div class="field">
                <span class="label">Course:</span>
                <span class="value">{launch_data.get('context_title') or 'Not provided'}</span>
            </div>

            <div class="field">
                <span class="label">Roles:</span>
                <ul>{role_items or '<li>None</li>'}</ul>
            </div>

            <div class="field">
                <span class="label">Your Sub (User ID):</span>
                <span class="value" style="font-family: monospace;">{launch_data.get('sub') or 'Unknown'}</span>
            </div>

            {ags_section}
        </div>
    </body>
    </html>
    """


def get_tool_configuration() -> dict[str, Any]:
    """
    Return tool configuration for manual LMS registration.

    This helps when setting up the tool in Moodle's external tool config.
    """
    return {
        "title": settings.APP_NAME,
        "description": "EduBridge LTI 1.3 Tool",
        "oidc_initiation_url": settings.lti_login_url,
        "target_link_uri": settings.lti_redirect_uri,
        "client_id": settings.LTI_CLIENT_ID,
        "issuer": settings.LTI_ISSUER,
        "platform_jwks_url": settings.LTI_JWKS_URL,
        "tool_jwks_url": f"{settings.APP_BASE_URL}/.well-known/jwks.json",
        "deployment_id": settings.LTI_DEPLOYMENT_ID,
        "public_key_type": "URL",
        "lti_version": "1.3.0",
    }
