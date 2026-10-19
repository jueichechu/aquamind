"""Local AquaMind agent entry point; loads ignored root .env.local without printing secrets."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
ENV_FILE = Path(__file__).resolve().parents[2] / '.env.local'


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('text', nargs='?')
    parser.add_argument('--check-config', action='store_true')
    args = parser.parse_args()
    load_dotenv(ENV_FILE, override=False)
    key, model = os.environ.get('OPENAI_API_KEY', '').strip(), os.environ.get('OPENAI_MODEL', '').strip()
    if args.check_config:
        print('OPENAI_API_KEY is configured' if key else 'OPENAI_API_KEY is missing')
        print('OPENAI_MODEL is configured' if model else 'OPENAI_MODEL is missing')
        return
    if not key or not model:
        parser.error('Configure OPENAI_API_KEY and OPENAI_MODEL in the ignored root .env.local')
    if not args.text:
        parser.error('Provide a water-usage question')
    from mcp import Client
    from openai import AsyncOpenAI
    from .agent import AgentConfig, run_agent
    from .agent_tools import McpAgentTools
    from .mcp_server import create_server

    config = AgentConfig(model=model)
    # Local smoke host: synthetic weather and illustrative utility reads only.
    allowed = frozenset({'get_weather_context', 'get_utility_rate', 'estimate_water_cost', 'estimate_conservation_savings'})
    async with AsyncOpenAI(api_key=key, base_url='https://api.openai.com/v1', max_retries=0, timeout=30) as provider:
        async with Client(create_server(None, frozenset({'weather:read', 'utility:read'}))) as mcp:
            outcome = await run_agent(args.text, provider, McpAgentTools(mcp, allowed), config)
            print(json.dumps(outcome.public_dict(), indent=2, allow_nan=False))


if __name__ == '__main__':
    asyncio.run(main())
