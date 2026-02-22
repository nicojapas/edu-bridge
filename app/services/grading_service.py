"""
Grading Service

Provides deterministic AI-style scoring for essay submissions.
Uses a simple heuristic based on word count and keyword detection.
"""

from dataclasses import dataclass

from app.logging_config import get_logger

logger = get_logger(__name__)

# Keywords that indicate relevant content
KEYWORDS = ["ai", "education", "integrity", "learning"]


@dataclass
class GradingResult:
    """Result of grading an essay submission."""
    score: float
    feedback: str
    word_count: int
    keywords_found: list[str]


def grade_essay(essay_text: str) -> GradingResult:
    """
    Grade an essay using a deterministic heuristic.

    Scoring formula:
    - Base score: min(word_count // 5, 80)
    - Keyword bonus: 5 * number_of_detected_keywords
    - Final score: min(base + keyword_bonus, 100)

    Args:
        essay_text: The student's essay submission

    Returns:
        GradingResult with score, feedback, and analysis details
    """
    # Normalize text for analysis
    text_lower = essay_text.lower()

    # Count words
    words = essay_text.split()
    word_count = len(words)

    # Detect keywords
    keywords_found = []
    for keyword in KEYWORDS:
        if keyword in text_lower:
            keywords_found.append(keyword)

    # Calculate score
    base_score = min(word_count // 5, 80)
    keyword_bonus = 5 * len(keywords_found)
    final_score = min(base_score + keyword_bonus, 100)

    # Generate feedback
    feedback = _generate_feedback(
        word_count=word_count,
        keywords_found=keywords_found,
        base_score=base_score,
        keyword_bonus=keyword_bonus,
        final_score=final_score,
    )

    logger.info(
        f"Graded essay: words={word_count}, keywords={keywords_found}, score={final_score}"
    )

    return GradingResult(
        score=float(final_score),
        feedback=feedback,
        word_count=word_count,
        keywords_found=keywords_found,
    )


def _generate_feedback(
    word_count: int,
    keywords_found: list[str],
    base_score: int,
    keyword_bonus: int,
    final_score: int,
) -> str:
    """Generate human-readable feedback for the submission."""
    lines = [
        "## AI Evaluation Report",
        "",
        "### Analysis",
        f"- **Word Count:** {word_count} words",
        f"- **Base Score:** {base_score} points (based on length)",
    ]

    if keywords_found:
        keywords_str = ", ".join(f'"{k}"' for k in keywords_found)
        lines.append(f"- **Keywords Detected:** {keywords_str}")
        lines.append(f"- **Keyword Bonus:** +{keyword_bonus} points")
    else:
        lines.append("- **Keywords Detected:** None")
        lines.append("- **Keyword Bonus:** 0 points")

    lines.extend([
        "",
        f"### Final Score: {final_score}/100",
        "",
    ])

    # Add qualitative feedback based on score
    if final_score >= 90:
        lines.append("**Excellent work!** Your essay demonstrates strong understanding of the topic with comprehensive coverage.")
    elif final_score >= 70:
        lines.append("**Good effort!** Your essay covers the main points well. Consider expanding on key concepts for a higher score.")
    elif final_score >= 50:
        lines.append("**Satisfactory.** Your essay addresses the topic but could benefit from more detail and relevant keywords.")
    else:
        lines.append("**Needs improvement.** Consider expanding your essay with more content and include relevant keywords like: " + ", ".join(KEYWORDS))

    return "\n".join(lines)
