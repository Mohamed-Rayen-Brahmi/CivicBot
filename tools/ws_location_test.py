import asyncio
import json
import websockets


async def main() -> None:
    payload = {
        "type": "location",
        "source": "manual-test",
        "latitude": 37.7749,
        "longitude": -122.4194,
    }
    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        await ws.send(json.dumps(payload))
        await asyncio.sleep(0.3)


if __name__ == "__main__":
    asyncio.run(main())
