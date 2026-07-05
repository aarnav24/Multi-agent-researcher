"""Trace SSE events from a completed research session."""
import asyncio
import json
import httpx

SESSION_ID = "bb1f779e-9a66-4269-aea8-8533f6496008"

async def main():
    async with httpx.AsyncClient(timeout=5) as client:
        # Get research status
        res = await client.get(f"http://localhost:8000/api/v1/research/{SESSION_ID}")
        data = res.json()
        print(f"Status: {data['status']}")
        print(f"Agent count: {data['agent_count']}")
        print(f"Verified claims: {data['verified_claims_count']}")

        # Check the session in the store
        from backend.api.routes import _state_store
        await _state_store.connect()
        session = await _state_store.get(SESSION_ID)
        if session:
            print(f"\nSession in store:")
            print(f"  Status: {session.status}")
            print(f"  Agents: {session.agent_count}")
            print(f"  Verified claims: {len(session.verified_claims)}")
        await _state_store.disconnect()

asyncio.run(main())
