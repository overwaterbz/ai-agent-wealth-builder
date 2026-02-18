import os
import re
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

AI_INTEGRATIONS_OPENAI_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
AI_INTEGRATIONS_OPENAI_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")

# the newest OpenAI model is "gpt-5" which was released August 7, 2025.
# do not change this unless explicitly requested by the user
MODEL = "gpt-4o"

client = None
total_estimated_cost = 0.0


def get_client():
    global client
    if client is None:
        client = OpenAI(
            api_key=AI_INTEGRATIONS_OPENAI_API_KEY,
            base_url=AI_INTEGRATIONS_OPENAI_BASE_URL,
        )
    return client


def is_rate_limit_error(exception):
    error_msg = str(exception)
    return (
        "429" in error_msg
        or "RATELIMIT_EXCEEDED" in error_msg
        or "quota" in error_msg.lower()
        or "rate limit" in error_msg.lower()
        or (hasattr(exception, "status_code") and exception.status_code == 429)
    )


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception(is_rate_limit_error),
    reraise=True,
)
def estimate_fair_probability(market_description):
    """Use GPT-4o to estimate fair yes probability for a prediction market.
    
    Returns float between 0.0 and 1.0, or None on failure.
    """
    global total_estimated_cost

    prompt = (
        f"Estimate the fair 'yes' probability for this prediction market:\n\n"
        f"\"{market_description}\"\n\n"
        f"Consider current news, logic, historical patterns, and available data. "
        f"Output only: fair_yes_prob: 0.XX"
    )

    try:
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert prediction market analyst. "
                        "Estimate the fair probability that the event described will resolve 'Yes'. "
                        "Be calibrated and consider base rates. Output ONLY in format: fair_yes_prob: 0.XX"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=50,
        )

        text = response.choices[0].message.content.strip()

        match = re.search(r"fair_yes_prob:\s*([\d.]+)", text)
        if match:
            prob = float(match.group(1))
            prob = max(0.01, min(0.99, prob))
            total_estimated_cost += 0.002
            return prob
        
        match = re.search(r"(0\.\d+)", text)
        if match:
            prob = float(match.group(1))
            prob = max(0.01, min(0.99, prob))
            total_estimated_cost += 0.002
            return prob

        print(f"[AI] Could not parse probability from: {text}")
        return None

    except Exception as e:
        print(f"[AI] Error estimating probability: {e}")
        raise


def get_total_cost():
    return total_estimated_cost


def reset_cost():
    global total_estimated_cost
    total_estimated_cost = 0.0
