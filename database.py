import os
import logging
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)


def get_users_count():
    """Возвращает общее количество пользователей."""
    try:
        response = supabase.table("users").select("*", count="exact").execute()
        return response.count if response.count is not None else 0
    except Exception as e:
        logging.error(f"❌ Ошибка Supabase при подсчете пользователей: {e}")
        return 0


def create_new_user(user_id: int, referrer_id: int = None):
    """Вспомогательная функция для регистрации нового пользователя."""
    try:
        user_id = int(user_id)
        # Проверяем еще раз, нет ли его, чтобы не дублировать
        check = supabase.table("users").select("user_id").eq("user_id", user_id).execute()
        if not check.data:
            data = {
                "user_id": user_id,
                "balance": 1,
                "referrer_id": int(referrer_id) if referrer_id else None
            }
            supabase.table("users").insert(data).execute()
            logging.info(f"👤 Новый пользователь {user_id} зарегистрирован (Ref: {referrer_id})")
            return True
        return False
    except Exception as e:
        logging.error(f"❌ Ошибка при создании пользователя {user_id}: {e}")
        return False


def get_balance(user_id: int):
    """Получает баланс. Если пользователя нет — создает его."""
    try:
        user_id = int(user_id)
        response = supabase.table("users").select("balance").eq("user_id", user_id).execute()

        if not response.data:
            # Если данных нет, регистрируем
            create_new_user(user_id)
            return 1

        return int(response.data[0]["balance"])
    except Exception as e:
        logging.error(f"❌ Ошибка get_balance для {user_id}: {e}")
        return 0


def update_balance(user_id: int, amount: int):
    """Универсальная функция изменения баланса."""
    try:
        user_id = int(user_id)
        current_balance = get_balance(user_id)
        new_balance = int(max(0, current_balance + amount))

        supabase.table("users").update({"balance": new_balance}).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка update_balance для {user_id}: {e}")
        return False


def use_generation(user_id: int):
    return update_balance(user_id, -1)


def add_balance(user_id: int, count: int):
    return update_balance(user_id, count)


def log_payment(user_id: int, amount: int, status: str, order_id: str, raw_data: dict):
    try:
        return supabase.table("payment_logs").insert({
            "user_id": int(user_id),
            "amount": amount,
            "status": status,
            "order_id": order_id,
            "raw_data": raw_data
        }).execute()
    except Exception as e:
        logging.error(f"❌ Ошибка log_payment: {e}")


def set_referrer(user_id: int, referrer_id: int):
    """Устанавливает пригласившего для нового пользователя."""
    try:
        user_id = int(user_id)
        referrer_id = int(referrer_id)

        if user_id == referrer_id:
            return

        res = supabase.table("users").select("user_id", "referrer_id").eq("user_id", user_id).execute()

        if not res.data:
            # Если юзера нет в базе — создаем его сразу с реферером
            create_new_user(user_id, referrer_id)
        else:
            # Если юзер есть, но у него еще нет реферера — обновляем
            if res.data[0].get("referrer_id") is None:
                supabase.table("users").update({"referrer_id": referrer_id}).eq("user_id", user_id).execute()
    except Exception as e:
        logging.error(f"❌ ОШИБКА set_referrer: {e}")


def get_referrer(user_id: int):
    try:
        res = supabase.table("users").select("referrer_id").eq("user_id", int(user_id)).execute()
        if res.data and res.data[0].get("referrer_id"):
            return int(res.data[0]["referrer_id"])
    except Exception as e:
        logging.error(f"❌ Ошибка get_referrer: {e}")
    return None


def get_referrals_count(user_id: int):
    try:
        res = supabase.table("users").select("*", count="exact").eq("referrer_id", int(user_id)).execute()
        return res.count if res.count is not None else 0
    except Exception as e:
        logging.error(f"❌ Ошибка get_referrals_count: {e}")
        return 0