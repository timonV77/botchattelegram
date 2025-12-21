import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)


def get_balance(user_id: int):
    response = supabase.table("users").select("balance").eq("user_id", user_id).execute()

    if not response.data:
        # Если пользователь новый — даём 100 токенов
        supabase.table("users").insert({"user_id": user_id, "balance": 100}).execute()
        return 100

    return response.data[0]["balance"]

def use_generation(user_id: int):
    current_balance = get_balance(user_id)
    if current_balance > 0:
        supabase.table("users").update({"balance": current_balance - 1}).eq("user_id", user_id).execute()


def add_balance(user_id: int, count: int):
    current_balance = get_balance(user_id)
    supabase.table("users").update({"balance": current_balance + count}).eq("user_id", user_id).execute()