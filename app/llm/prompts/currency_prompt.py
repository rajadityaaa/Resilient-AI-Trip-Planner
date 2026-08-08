"""
Prompt template for Currency Agent.
Instructs LLM to generate localized cash and tipping guidance.
"""

def build_currency_prompt(country: str, local_currency: str) -> str:
    return f"""You are a global financial advisor for international travelers.
Destination Country: {country}
Local Currency: {local_currency}

Provide concise 1-2 sentence advice on card acceptance vs cash requirement and tipping norms in {country}.

Respond ONLY in plain text (1-2 sentences) with no markdown, no quotes, and no JSON wrapping.
"""
