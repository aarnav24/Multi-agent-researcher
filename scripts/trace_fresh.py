"""Start a trace a NEW research in real-time."""
import asyncio
import json
import httpx

async def main():
    async with httpx.AsyncClient(timeout=None) as client:
        # Start
        res = await client.post("http://localhost:8000/api/v1/research",
            json={"query": "test query hello world", "max_agents": 5},
            headers={"Authorization": "Bearer testuser123"}
        )
        data = res.json()
        session_id = data["session_id"]
        print(f"Session: {session_id}")

        # Stream for 30s
        import time
        start = time.time()
        async with client.stream("GET", f"http://localhost:8000/api/v1/research/{session_id}/stream") as res:
            async for line in res.aiter_lines():
                if time.time() - start > 60:
                    break
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                    print(f"\n[{event_type}]", end=" ")
                elif line.startswith("data:"):
                    try:
                        event_data = json.loads(line[5:].strip())
                        print(json.dumps(event_data, default=str)[:200])
                    except:
                        print(line)

asyncio.run(main())
