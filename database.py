import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)


def get_users_count():
    """Возвращает общее количество пользователей в таблице users."""
    try:
        response = supabase.table("users").select("*", count="exact").execute()
        return response.count if response.count is not None else 0
    except Exception as e:
        print(f"❌ Ошибка Supabase при подсчете пользователей: {e}")
        return 0


def get_balance(user_id: int):
    """Получает баланс. Если пользователя нет — создает его."""
    try:
        response = supabase.table("users").select("balance").eq("user_id", user_id).execute()

        if not response.data:
            # Если пользователя нет, создаем запись.
            # Поле referrer_id будет NULL по умолчанию, если не было заполнено функцией set_referrer ранее.
            initial_balance = 1
            supabase.table("users").insert({"user_id": user_id, "balance": initial_balance}).execute()
            return initial_balance

        return response.data[0]["balance"]
    except Exception as e:
        print(f"❌ Ошибка get_balance: {e}")
        return 0


def update_balance(user_id: int, amount: int):
    """Универсальная функция изменения баланса."""
    current_balance = get_balance(user_id)
    new_balance = max(0, current_balance + amount)
    return supabase.table("users").update({"balance": new_balance}).eq("user_id", user_id).execute()


def use_generation(user_id: int):
    return update_balance(user_id, -1)


def add_balance(user_id: int, count: int):
    return update_balance(user_id, count)


def log_payment(user_id: int, amount: int, status: str, order_id: str, raw_data: dict):
    return supabase.table("payment_logs").insert({
        "user_id": user_id,
        "amount": amount,
        "status": status,
        "order_id": order_id,
        "raw_data": raw_data
    }).execute()


def set_referrer(user_id: int, referrer_id: int):
    if user_id == referrer_id:
        return

    try:
        # Проверяем, есть ли уже такой юзер
        res = supabase.table("users").select("referrer_id").eq("user_id", user_id).execute()

        if not res.data:
            # Если юзера ВООБЩЕ нет — создаем его сразу с реферером
            supabase.table("users").insert({
                "user_id": user_id,
                "balance": 1,
                "referrer_id": referrer_id
            }).execute()
        else:
            # Если юзер есть, но referrer_id пустой (NULL) — обновляем его
            if res.data[0].get("referrer_id") is None:
                supabase.table("users").update({"referrer_id": referrer_id}).eq("user_id", user_id).execute()
    except Exception as e:
        print(f"ОШИБКА set_referrer: {e}")


def get_referrer(user_id: int):
    """Возвращает ID того, кто пригласил этого пользователя"""
    try:
        res = supabase.table("users").select("referrer_id").eq("user_id", user_id).execute()
        if res.data and res.data[0].get("referrer_id"):
            return int(res.data[0]["referrer_id"])
    except Exception as e:
        print(f"❌ Ошибка get_referrer: {e}")
    return None


def get_referrals_count(user_id: int):
    """Считает сколько человек пригласил пользователь"""
    try:
        res = supabase.table("users").select("*", count="exact").eq("referrer_id", user_id).execute()
        return res.count if res.count is not None else 0
    except Exception as e:
        print(f"❌ Ошибка get_referrals_count: {e}")
        return 0