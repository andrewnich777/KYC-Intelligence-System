"""
Individual Adverse Media Screening Agent.
6 search queries covering fraud, money laundering, regulatory, employer, bankruptcy, ICIJ.
"""

from agents.adverse_media_base import AdverseMediaParserMixin
from agents.base import BaseAgent, load_prompt_template
from logger import get_logger
from models import AdverseMediaResult

logger = get_logger(__name__)


class IndividualAdverseMediaAgent(AdverseMediaParserMixin, BaseAgent):
    """Screen individuals for negative news and adverse media."""

    @property
    def name(self) -> str:
        return "IndividualAdverseMedia"

    @property
    def system_prompt(self) -> str:
        return load_prompt_template("individual_adverse_media")

    @property
    def tools(self) -> list[str]:
        return ["web_search", "web_fetch"]

    async def research(self, full_name: str, employer: str = None,
                       citizenship: str = None) -> AdverseMediaResult:
        """Screen an individual for adverse media."""
        employer_line = "\nEmployer: " + employer if employer else ""
        employer_query = " " + employer if employer else ""

        prompt = f"""Screen this individual for adverse media / negative news:

Name: {full_name}
Citizenship: {citizenship or 'Not provided'}""" + employer_line + f"""

Run ALL 6 mandatory search queries:
1. "{full_name}" fraud OR lawsuit OR criminal
2. "{full_name}" money laundering OR corruption OR bribery
3. "{full_name}" regulatory action OR sanctions
4. "{full_name}"{employer_query} controversy OR investigation
5. "{full_name}" bankruptcy OR insolvency
6. "{full_name}" site:offshoreleaks.icij.org

Then search CanLII for Canadian court records.
For each finding, classify severity and relevance."""

        result = await self.run(prompt)
        return self._parse_result(result, full_name)

    def _parse_result(self, result: dict, entity_name: str) -> AdverseMediaResult:
        return self._parse_adverse_media_result(
            result, entity_name, id_prefix="adv_ind", claim_prefix="Adverse media",
        )
