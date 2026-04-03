import aiohttp
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def list_models():
    api_key = os.getenv("VK_POLZA_API_KEY")
    url = "https://polza.ai/api/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                models = data.get("data", []) if isinstance(data, dict) else data
                print(f"--- Filtered Models List (Count: {len(models)}) ---")
                for m in models:
                    if not isinstance(m, dict): continue
                    m_id = m.get("id", "")
                    name = m.get("name", "")
                    if any(x in m_id.lower() or x in name.lower() for x in ["banana", "seedream", "kling", "recraft", "gemini-3.1"]):
                        print(f"ID: {m_id} | Name: {name}")
            else:
                print(f"Error: {response.status}")
                print(await response.text())

asyncio.run(list_models())
