Analyze the energy market situation. Pull current LMPs / load / generation
mix from gridstatus.io via `get_market_data`. Cross-reference with the
knowledge graph for any active outages, transmission constraints, or
scheduled maintenance in the relevant region.

Report:
- Current spread vs. day-ahead
- Drivers (weather, generator availability, demand shape)
- Short-term direction (next 4-12 hours) with confidence level
- One actionable recommendation, with the main tradeoff in a sentence
