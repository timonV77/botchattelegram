from app.network import process_with_polza
import database as db

# Словарь стоимости моделей
# Ключи должны строго совпадать с тем, что приходит из callback_data (после model_)
COSTS = {
    "nanabanana": 1,
    "nanabanana_pro": 5,
    "seadream": 2
}

def cost_for(model: str) -> int:
    """
    Возвращает стоимость генерации для конкретной модели.
    Если модель не найдена в словаре, по умолчанию берет 1.
    """
    return COSTS.get(model, 1)

def has_balance(user_id: int, cost: int) -> bool:
    """
    Проверяет, достаточно ли у пользователя средств для оплаты модели.
    """
    return db.get_balance(user_id) >= cost

def charge(user_id: int, cost: int):
    """
    Списывает стоимость с баланса пользователя.
    Использует функцию update_balance из database.py.
    """
    # Мы передаем отрицательное значение стоимости, чтобы уменьшить баланс
    db.update_balance(user_id, -cost)

async def generate(image_url: str, prompt: str, model: str):
    """
    Основная функция-мост между роутером и сетевым модулем Polza AI.
    """
    # Вызываем функцию из network.py
    return await process_with_polza(prompt, model, image_url)