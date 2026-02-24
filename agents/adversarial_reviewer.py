"""
Adversarial Reviewer Agent.

A red-team agent that challenges synthesis findings by asking:
- What would a sophisticated actor do to make this look clean?
- What evidence is missing that would change this conclusion?

Toolless (pure reasoning), uses Opus for deep analysis.
"""

import json

from agents.base import BaseAgent, load_prompt_template
from logger import get_logger

logger = get_logger(__name__)


class AdversarialReviewerAgent(BaseAgent):
    """Red-team agent that challenges KYC findings."""

    @property
    def name(self) -> str:
        return "AdversarialReviewer"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("adversarial_reviewer")

    @property
    def tools(self) -> list[str]:
        return []  # Pure reasoning, no tools

    async def review(
        self,
        synthesis_output: dict,
        evidence_store: list[dict],
        client_summary: str = "",
    ) -> list[dict]:
        """Challenge synthesis findings and return adversarial challenges.

        Args:
            synthesis_output: KYCSynthesisOutput as dict.
            evidence_store: Evidence records as list of dicts.
            client_summary: Brief client profile summary.

        Returns:
            List of adversarial challenge dicts, each with:
            target_finding, challenge, missing_evidence, confidence_impact.
        """
        prompt = f"""Review the following KYC synthesis output and evidence store.
Challenge every disposition — both matches AND clears.

## Client Summary
{client_summary}

## Synthesis Output
```json
{json.dumps(synthesis_output, indent=2, default=str)}
```

## Evidence Store ({len(evidence_store)} records)
```json
{json.dumps(evidence_store, indent=2, default=str)}
```

For each finding, produce an adversarial challenge. Focus on:
1. Findings marked CLEAR or FALSE_POSITIVE — what could make them wrong?
2. Missing evidence that wasn't searched for
3. Name variations or jurisdictions not checked
4. Assumptions that a sophisticated actor could exploit

Return your analysis as a JSON object with an "adversarial_challenges" array."""

        result = await self.run(prompt)
        return self._parse_challenges(result)

    def _parse_challenges(self, result: dict) -> list[dict]:
        """Parse adversarial challenges from agent output."""
        data = result.get("json", {})
        if not data:
            return []

        challenges = data.get("adversarial_challenges", [])
        if not isinstance(challenges, list):
            return []

        parsed = []
        for c in challenges:
            if not isinstance(c, dict):
                continue
            parsed.append({
                "target_finding": str(c.get("target_finding", "")),
                "challenge": str(c.get("challenge", "")),
                "missing_evidence": str(c.get("missing_evidence", "")),
                "confidence_impact": str(c.get("confidence_impact", "MEDIUM")),
            })

        return parsed
