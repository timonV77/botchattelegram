import database as db
import network

COSTS = {"nanabanana": 5, "seadream": 10}

def cost_for(model: str) -> int:
    return COSTS.get(model, 5)

async def generate(photo_url: str, prompt: str, model: str):
    # network.py должен вернуть (img_bytes, ext)
    return await network.process_with_ai(photo_url, prompt, model)

def has_balance(user_id: int, need: int) -> bool:
    return db.get_balance(user_id) >= need

def charge(user_id: int, amount: int):
    # лучше потом сделать одним update, но пока так
    for _ in range(amount):
        db.use_generation(user_id)
