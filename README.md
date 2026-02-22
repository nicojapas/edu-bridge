# EduBridge LTI – LTI 1.3 Tool Provider with Auto-Grading

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

> A production-style LTI 1.3 Advantage tool that integrates with learning management systems to provide AI-ready essay grading with automatic grade passback.

**[Live Demo](https://edu-bridge-rlur.onrender.com)** | **[Moodle Integration](https://edubridge.moodlecloud.com/)**

This project demonstrates how to implement a secure, backend-focused LMS integration including:

- LTI 1.3 OIDC launch validation
- JWT verification using LMS public keys (JWK)
- Essay submission and auto-grading
- LTI Advantage AGS grade passback
- PostgreSQL schema design
- Dockerized deployment

It is intentionally backend-centric and integration-driven.

## High-Level Overview

EduBridge LTI is an external tool that integrates with LMS platforms (Moodle, Blackboard, Canvas) using LTI 1.3 Advantage.

When a student launches the tool from the LMS:
1. The LMS performs an OIDC login initiation
2. The LMS sends a signed id_token (JWT) to our backend
3. The backend:
    - Validates the JWT signature
    - Verifies nonce and state
    - Extracts user, course, and assignment context
4. The student can submit an assignment
5. The backend processes the submission asynchronously
6. A grade is computed (currently heuristic-based, designed for AI integration)
7. The grade is sent back to the LMS using AGS (Assignment & Grade Services)

The tool is stateless at the protocol level but persists domain data in PostgreSQL.


## Architecture
### Stack

- Python 3.11
- FastAPI (async)
- PostgreSQL
- SQLAlchemy (async)
- httpx (async HTTP client)
- Authlib (JWT/JWK handling)
- Docker

### System Diagram

LMS (Moodle / Blackboard / Canvas)  
↓  
LTI 1.3 Launch (OIDC + JWT)  
↓  
FastAPI Backend
↓
PostgreSQL + Async Grading Service
↓
LTI Advantage AGS Grade Passback  
↓  
LMS Gradebook

## Core Features
### 1. LTI 1.3 OIDC Launch

Endpoint:

POST /lti/launch

Flow:
- Receives id_token
- Fetches LMS public keys from JWK endpoint
- Verifies:
  - Signature
  - Audience
  - Issuer
  - Expiration
  - Nonce
- Extracts LTI claims:
  - sub (user id)
  - roles
  - context (course)
  - resource_link (assignment)
  - AGS endpoint URLs
- Stores launch context in database

Security considerations:
  - Nonce replay protection
  - Audience validation
  - Issuer validation
  - JWK key rotation support

### 2. Domain Model (PostgreSQL)
Tables

lti_launches
- id
- user_sub
- context_id
- resource_link_id
- deployment_id
- lineitem_url (AGS endpoint)
- lineitems_url (AGS endpoint)
- ags_scopes (JSON)
- user_name
- user_email
- roles (JSON)
- created_at

submissions
- id
- launch_id (FK to lti_launches)
- user_sub
- essay_text
- score
- feedback
- created_at

Design goals:
- Clear foreign key relationships
- Launch context preserved for grade passback
- Inline scoring with submission record

### 3. Submission Processing

Endpoint:

POST /submission/evaluate

Flow:
- Receives essay text and launch context
- Triggers async grading (currently heuristic, designed for AI)
- Stores submission with score and feedback
- Pushes grade to LMS via AGS
- Returns feedback to student

### 4. Async Grading Service

Designed for async AI grading integration. Currently uses a deterministic heuristic as a placeholder.

Current scoring formula (placeholder):
- Base score: min(word_count / 5, 80)
- Keyword bonus: +5 per detected keyword (ai, education, integrity, learning)
- Final score: min(base + bonus, 100)

The grading service is async-ready and can be replaced with an LLM API call.

### 5. LTI Advantage – Assignment & Grade Services (AGS)

Implements:

OAuth 2.0 Client Credentials Flow

Steps:
1. Generate signed JWT client assertion
2. Exchange for access token via client credentials flow
3. POST score to LMS AGS endpoint

Score payload includes:
- scoreGiven
- scoreMaximum
- timestamp
- activityProgress
- gradingProgress
- userId

Caches access tokens until expiration.

## API Endpoints

GET|POST /lti/login - OIDC login initiation
POST /lti/launch - OIDC redirect URI (receives id_token)
GET /lti/config - Tool configuration helper
POST /submission/evaluate - Submit essay for AI grading
GET /submission/instructor/{launch_id} - Instructor submissions view
POST /grades/submit - Manual grade submission
GET /health - Health check
GET /.well-known/jwks.json - Tool public key  

## Local Development
1. Clone

git clone https://github.com/YOUR_USERNAME/edu-bridge.git
cd edu-bridge

2. Environment Variables

Create .env file:

DATABASE_URL=postgresql://user:pass@localhost/db
LTI_CLIENT_ID=...
LTI_ISSUER=...
LTI_AUTHORIZATION_ENDPOINT=...
LTI_JWKS_URL=...
LTI_DEPLOYMENT_ID=...
ACCESS_TOKEN_URL=...
LTI_PRIVATE_KEY=...
APP_BASE_URL=http://localhost:8000

3. Run with Docker Compose

docker-compose up

Or run separately:

docker-compose up -d db
uvicorn app.main:app --reload

## Docker

Build:

docker build -t edubridge-lti .

Run:

docker run -p 8000:8000 edubridge-lti

## Testing with Moodle

1. Create MoodleCloud trial
2. Add External Tool
3. Register tool with:
   - Launch URL
   - Client ID
   - Public key
4. Add tool to course
5. Launch as student
6. Submit assignment
7. Verify grade in gradebook

## Security Considerations

- JWT signature verification using LMS JWK endpoint
- Nonce validation to prevent replay attacks
- Strict issuer and audience checking
- No trust in client-side data
- Sensitive credentials stored in environment variables

## Design Principles

- Backend-first, minimal frontend (Jinja2 templates)
- Integration clarity over UI polish
- Async-first design for AI service integration
- LMS-agnostic implementation
- Production-style schema and service separation


## Diagrams

### 1️⃣ LTI 1.3 Launch Flow (OIDC Authentication)
```
┌─────────┐         ┌──────────────┐           ┌────────────┐
│  User   │         │     LMS      │           │    Tool    │
│(Browser)│         │  (Moodle)    │           │ (FastAPI)  │
└────┬────┘         └──────┬───────┘           └────┬───────┘
     │                     │                        │
     │ Click LTI activity  │                        │
     │────────────────────>│                        │
     │                     │ Redirect to tool       │
     │                     │───────────────────────>│
     │                     │     GET /lti/login     │
     │                     │ (iss, login_hint, ...) │
     │                     │                        │
     │                     │        Validate issuer │
     │                     │        Generate state  │
     │                     │        + nonce         │
     │                     │<───────────────────────│
     │ 302 Redirect to LMS │                        │
     │<────────────────────│                        │
     │                     │                        │
     │ Authenticate user   │                        │
     │────────────────────>│                        │
     │                     │ POST /lti/launch       │
     │                     │ (id_token, state)      │
     │                     │───────────────────────>│
     │                     │                        │
     │                     │   Verify state + nonce │
     │                     │   Validate JWT (JWKS)  │
     │                     │   Extract LTI claims   │
     │                     │   Persist launch       │
     │                     │<───────────────────────│
     │ Render launch page  │                        │
     │<─────────────────────────────────────────────│
```

### 2️⃣ Essay Evaluation + AGS Grade Passback Flow

```
┌─────────┐         ┌──────────────┐           ┌────────────┐
│  User   │         │     LMS      │           │    Tool    │
│(Browser)│         │  (Moodle)    │           │ (FastAPI)  │
└────┬────┘         └──────┬───────┘           └────┬───────┘
     │                     │                        │
     │ Submit Essay        │                        │
     │─────────────────────────────────────────────>│
     │                     │                        │
     │                     │   Evaluate essay       │
     │                     │   Compute score        │
     │                     │   Store submission     │
     │                     │                        │
     │                     │ POST /mod/lti/token.php│
     │                     │<───────────────────────│
     │                     │   access_token         │
     │                     │───────────────────────>│
     │                     │                        │
     │                     │ POST {lineitem}/scores │
     │                     │ (Bearer access_token)  │
     │                     │<───────────────────────│
     │                     │   200 OK               │
     │                     │───────────────────────>│
     │                     │                        │
     │                     │  Grade stored in LMS   │
     │                     │                        │
     │ Show feedback       │                        │
     │<─────────────────────────────────────────────│
```

## Roadmap

- [ ] Integration tests with pytest
- [ ] LLM-based grading (OpenAI/Claude API)
- [ ] Deep Linking support (LTI 1.3)
- [ ] NRPS integration (Names and Roles Provisioning Service)
- [ ] Multi-tenant deployment with separate key management

## What This Project Demonstrates

- Understanding of LTI 1.3 protocol
- OIDC and OAuth 2.0 flows
- JWT validation and JWK handling
- Secure third-party platform integration
- PostgreSQL schema modeling
- Grade passback via LTI Advantage
- Async-ready AI grading pipeline

## Why This Matters

Modern EdTech platforms require:

- Secure LMS interoperability
- Reliable grade synchronization
- Trustworthy AI workflows
- Production-grade integration design

This project demonstrates the architectural foundations required to build and harden such integrations.

## License

MIT