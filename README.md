# EduBridge LTI – LTI 1.3 Tool Provider with Async Grading

## A production-style LTI 1.3 Advantage tool provider built with FastAPI, PostgreSQL, and async workflows.

This project demonstrates how to implement a secure, backend-focused LMS integration including:

- LTI 1.3 OIDC launch validation
- JWT verification using LMS public keys (JWK)
- Assignment ingestion
- Submission processing
- Async grading workflow
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
6. A grade is computed
7. The grade is sent back to the LMS using AGS (Assignment & Grade Services)

The tool is stateless at the protocol level but persists domain data in PostgreSQL.

## Architecture
### Stack

- Python 3.12
- FastAPI (async)
- PostgreSQL
- SQLAlchemy (async)
- httpx (async HTTP client)
- PyJWT
- Docker
- Deployed on Render / Railway / Fly.io

### System Diagram

LMS (Moodle / Blackboard / Canvas)  
↓  
LTI 1.3 Launch (OIDC + JWT)  
↓  
FastAPI Backend  
↓  
PostgreSQL  
↓  
Async Grading Worker  
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

users
- id
- lti_sub
- name
- email
- created_at
courses
- id
- lti_context_id
- title
assignments
- id
- resource_link_id
- course_id
- title
- max_score
submissions
- id
- assignment_id
- user_id
- content
- status (pending, graded)
- created_at
grades
- id
- submission_id
- score
- feedback
- sent_to_lms (boolean)
- created_at

Design goals:
- Clear foreign key relationships
- Separation between submission and grade
- Support for regrading
- Multi-tenant readiness

### 3. Submission Processing

Endpoint:

POST /submit

Flow:
- Stores submission
- Marks status as pending
- Triggers async grading task
- Returns immediate response
No blocking request cycle.

### 4. Async Grading Workflow

Implemented using FastAPI background tasks (can be replaced with Redis / Celery).

Flow:
1. Submission created
2. Async task triggered
3. Grading service evaluates submission
4. Grade stored in database
5. AGS passback triggered

Example grading logic (mock AI):
- Text length heuristic
- Can be replaced with LLM call
- Designed to be AI-service pluggable

### 5. LTI Advantage – Assignment & Grade Services (AGS)

Implements:

OAuth 2.0 Client Credentials Flow

Steps:
1. Exchange client credentials for access token
2. Use token to POST score to LMS AGS endpoint
3. Mark grade as sent_to_lms = true

Score payload includes:
- scoreGiven
- scoreMaximum
- comment
- timestamp
- activityProgress
- gradingProgress

Handles token expiration and retry logic.

## API Endpoints

POST /lti/login  
POST /lti/launch  
POST /submit  
GET /health  

## Local Development
1. Clone

git clone <repo>
cd edubridge-lti

2. Environment Variables

Create .env file:

DATABASE_URL=postgresql+asyncpg://user:pass@localhost/db
LTI_CLIENT_ID=...
LTI_CLIENT_SECRET=...
LTI_ISSUER=...
LTI_JWKS_URL=...
LTI_TOKEN_URL=...

3. Run Database

docker-compose up -d postgres

4. Run App

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
- Async tasks isolated from request lifecycle
- Sensitive credentials stored in environment variables

## Design Principles

- Backend-first, no unnecessary frontend
- Integration clarity over UI polish
- Async by default
- LMS-agnostic implementation
- Extensible AI grading pipeline
- Production-style schema and service separation

## Extensibility

Can be extended with:
- Rubric-based grading
- Structured AI feedback
- Instructor dashboard
- Deep Linking (LTI 1.3)
- NRPS (Names and Roles Provisioning Service)
- Multi-tenant key management
- Keycloak integration

## What This Project Demonstrates

- Understanding of LTI 1.3 protocol
- OIDC and OAuth 2.0 flows
- JWT validation and JWK handling
- Secure third-party platform integration
- Async event-driven backend design
- PostgreSQL schema modeling
- Grade passback via LTI Advantage
- AI-service integration pattern

## Why This Matters

Modern EdTech platforms require:

- Secure LMS interoperability
- Reliable grade synchronization
- Trustworthy AI workflows
- Production-grade integration design

This project demonstrates the architectural foundations required to build and harden such integrations.