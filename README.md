# Photo Geolocator

This is an automated entry for the `make.fun` photo-geolocator bounty, designed to maximize accuracy while adhering to strict budget constraints.

## Strategy: Intelligent Budget Management

To achieve optimal performance within budget limits, the entry employs a two-tier model strategy and an intelligent processing order:

1. **Size-Sorted Processing**: Photos are fetched and processed in order of their byte size (smallest first). Smaller images typically contain less complex metadata and visual data, allowing us to gauge model performance and confidence earlier.
2. **Two-Model Fallback**:
   - **Primary Model (`gpt-6-sol`)**: High-capability, higher-cost model. Used for primary analysis.
   - **Fallback Model (`gpt-6-luna`)**: Lower-cost, high-efficiency model. Automatically invoked if `gpt-6-sol` returns an error (e.g., rate limits, server refusals) or if the budget is deemed exhausted.
3. **Budget Rationale**: The prompt structure and token limit are optimized to balance reasoning quality against cost. By using the cheaper `gpt-6-luna` as a fallback, the entry maintains a high submission rate even when the primary model encounters issues.

## Requirements

- Python 3.13
- Environment variables: 
  - `MAKEFUN_ENV_URL`: Base URL for the environment API.
  - `OPENAI_BASE_URL`: Base URL for the LLM API.
  - `OPENAI_API_KEY`: API key for model authentication.

## Running the Entry

The entry is designed to be run within the `make.fun` container environment:

```bash
python3 -P -s /bot/main.py
```
