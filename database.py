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
        # Если пользователя нет в базе — это его первый вход.
        # Дарим ровно 1 приветственную генерацию.
        initial_balance = 1
        supabase.table("users").insert({"user_id": user_id, "balance": initial_balance}).execute()
        return initial_balance

    return response.data[0]["balance"]


def update_balance(user_id: int, amount: int):
    """
    Универсальная функция изменения баланса.
    amount может быть положительным (пополнение) или отрицательным (списание).
    """
    current_balance = get_balance(user_id)
    new_balance = current_balance + amount

    # Чтобы баланс не уходил в минус (на всякий случай)
    if new_balance < 0:
        new_balance = 0

    return supabase.table("users").update({"balance": new_balance}).eq("user_id", user_id).execute()


def use_generation(user_id: int):
    """Старая функция для совместимости (вычитает 1)"""
    return update_balance(user_id, -1)


def add_balance(user_id: int, count: int):
    """Старая функция для совместимости (прибавляет count)"""
    return update_balance(user_id, count)

def log_payment(user_id: int, amount: int, status: str, order_id: str, raw_data: dict):
    """Записывает данные о платеже в таблицу payment_logs"""
    return supabase.table("payment_logs").insert({
        "user_id": user_id,
        "amount": amount,
        "status": status,
        "order_id": order_id,
        "raw_data": raw_data
    }).execute()