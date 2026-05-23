from aiogram.fsm.state import State, StatesGroup

class AddModel(StatesGroup):
    waiting_for_model_name = State()
    waiting_for_details_count = State()
    waiting_for_detail = State()