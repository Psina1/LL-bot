from aiogram.fsm.state import State, StatesGroup


class UserFlow(StatesGroup):
    waiting_for_training_question = State()
    waiting_for_categorized_question = State()
    waiting_for_project_context = State()
    waiting_for_user_file = State()
    waiting_for_file_question = State()
    waiting_for_followup = State()
    waiting_for_project_help_question = State()
    waiting_for_homework_help_question = State()


class AdminFlow(StatesGroup):
    waiting_for_material_season = State()
    waiting_for_material_module = State()
    waiting_for_material_date = State()
    waiting_for_material_type = State()
    waiting_for_homework_link = State()
    waiting_for_global_file = State()
    waiting_for_media_type = State()
    waiting_for_media_module = State()
    waiting_for_media_date = State()
    waiting_for_media_file = State()
    waiting_for_bot_text = State()
    waiting_for_bot_text_confirm = State()
    waiting_for_reminder_text = State()
    waiting_for_notification_ics = State()
