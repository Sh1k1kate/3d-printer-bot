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
    waiting_for_deadline = State()

class EditOrder(StatesGroup):
    waiting_for_new_printed = State()

class AddKit(StatesGroup):
    waiting_for_kit_name = State()
    waiting_for_item = State()
    waiting_for_quantity_for_item = State()
    waiting_for_price = State()
    waiting_for_description = State()

class EditKit(StatesGroup):
    waiting_for_new_value = State()
    waiting_for_item_edit = State()
    waiting_for_quantity_edit = State()

class CreateTask(StatesGroup):
    waiting_for_title = State()
    waiting_for_deadline = State()
    waiting_for_time = State()
    waiting_for_assignee_selection = State()   # выбор из списка
    waiting_for_assignee_manual = State()      # ручной ввод