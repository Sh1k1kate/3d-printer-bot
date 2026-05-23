from aiogram.fsm.state import State, StatesGroup

class AddModel(StatesGroup):
    waiting_for_model_name = State()
    waiting_for_details_count = State()
    waiting_for_detail = State()

class EditModel(StatesGroup):
    waiting_for_new_value = State()   # общее состояние для ввода нового значения параметра
    # в data будем хранить: model_name, det_name, param, current_value
