from aiogram.fsm.state import State, StatesGroup

class AddModel(StatesGroup):
    waiting_for_model_name = State()          # ввод названия модели
    choosing_action = State()                 # главное меню добавления (добавить деталь / завершить)
    waiting_for_detail_name = State()         # ввод названия детали
    choosing_param = State()                  # выбор параметра для редактирования (после ввода названия детали)
    waiting_for_on_pallet = State()           # ввод кол-ва на палете
    waiting_for_per_unit = State()            # ввод кол-ва на единицу
    waiting_for_time = State()                # ввод времени (часы минуты)
    waiting_for_grams = State()               # ввод граммовки

class EditModel(StatesGroup):
    choosing_part = State()                   # выбор детали для редактирования
    choosing_param = State()                  # выбор параметра для изменения
    waiting_for_new_value = State()           # ввод нового значения

# остальные состояния без изменений
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
    waiting_for_assignee_selection = State()
    waiting_for_assignee_manual = State()