import anthropic
from pydantic import ValidationError

from silverpath_triage.config import ANTHROPIC_API_KEY, MODEL
from silverpath_triage.models.triage import TriageResult
from silverpath_triage.prompts.triage_prompt import TRIAGE_SYSTEM_PROMPT


class TriageError(Exception):
    """The model's response could not be used as a TriageResult."""


def triage_enquiry(enquiry_text: str) -> TriageResult:
    if not enquiry_text.strip():
        raise ValueError("enquiry_text is empty")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=1024,
            system=TRIAGE_SYSTEM_PROMPT,
            output_format=TriageResult,
            messages=[
                {"role": "user", "content": f"<enquiry>\n{enquiry_text}\n</enquiry>"}
            ],
        )
    except ValidationError as e:
        # The SDK validates inside parse(), so a truncated or refused response
        # lands here before stop_reason can be read.
        raise TriageError(
            "Model output did not match the TriageResult schema (possibly "
            f"truncated at max_tokens or refused): {e}"
        ) from e

    if response.stop_reason == "refusal":
        raise TriageError("The model refused to triage this enquiry.")
    if response.stop_reason == "max_tokens":
        raise TriageError("The response hit the token limit and is incomplete.")
    if response.stop_reason != "end_turn":
        raise TriageError(f"Unexpected stop reason: {response.stop_reason!r}.")
    if response.parsed_output is None:
        raise TriageError("The model returned no structured output.")

    return response.parsed_output
