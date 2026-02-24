"""
Business Adverse Media Screening Agent.
Entity-specific searches including trade compliance, environmental, labor violations.
"""

from agents.adverse_media_base import AdverseMediaParserMixin
from agents.base import BaseAgent, load_prompt_template
from logger import get_logger
from models import AdverseMediaResult

logger = get_logger(__name__)


class BusinessAdverseMediaAgent(AdverseMediaParserMixin, BaseAgent):
    """Screen business entities for adverse media."""

    @property
    def name(self) -> str:
        return "BusinessAdverseMedia"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("business_adverse_media")

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, legal_name: str, industry: str = None,
                       countries: list = None) -> AdverseMediaResult:
        """Screen a business entity for adverse media."""
        prompt = f"""Screen this business for adverse media:

Entity: {legal_name}
Industry: {industry or 'Not provided'}
Countries: {', '.join(countries or ['Not provided'])}

Run ALL mandatory searches and classify findings by severity."""

        result = await self.run(prompt)
        return self._parse_result(result, legal_name)

    def _parse_result(self, result: dict, entity_name: str) -> AdverseMediaResult:
        return self._parse_adverse_media_result(
            result, entity_name, id_prefix="adv_biz", claim_prefix="Business adverse media",
        )
