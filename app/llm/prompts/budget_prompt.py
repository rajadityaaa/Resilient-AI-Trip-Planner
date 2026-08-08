"""
Prompt template for Budget Agent.
Instructs LLM to allocate trip budget across categories.
"""

def build_budget_prompt(budget_total: float, budget_currency: str, num_days: int, travelers: int, trip_type: str) -> str:
    return f"""You are a travel financial advisor.
Allocate a total budget of {budget_currency} {budget_total:.2f} across the following 5 categories for a {num_days}-day {trip_type} trip for {travelers} traveler(s):
1. lodging
2. food
3. attractions
4. transport
5. buffer

CRITICAL INSTRUCTION: The values of the 5 categories MUST sum up to EXACTLY {budget_total:.2f}.

Respond ONLY in valid JSON matching this exact structure with no markdown fences, no code blocks, and no preamble text:
{{
  "lodging": 600.0,
  "food": 400.0,
  "attractions": 250.0,
  "transport": 150.0,
  "buffer": 100.0
}}
"""
