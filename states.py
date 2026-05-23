from aiogram.fsm.state import State, StatesGroup

class AddModel(StatesGroup):
    waiting_for_model_name = State()
    waiting_for_details_count = State()
    waiting_for_detail = State()

class EditModel(StatesGroup):
    waiting_for_new_value = State()

class CreateOrder(StatesGroup):
    waiting_for_model = State()
    waiting_for_quantity = State()
    waiting_for_deadline = State()   # вызов календаря

class EditOrder(StatesGroup):
    waiting_for_new_printed = State()
