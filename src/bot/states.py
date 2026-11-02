from aiogram.fsm.state import State, StatesGroup


class ModelSetupStates(StatesGroup):
    """FSM states for configuring AI Model Face & Body references."""
    waiting_for_face = State()
    waiting_for_body = State()


class GeneratePhotoStates(StatesGroup):
    """FSM states for step-by-step photo generation pipeline."""
    waiting_for_pose = State()
    waiting_for_outfit = State()
    waiting_for_background = State()
    waiting_for_extra_prompt = State()
    confirm_generation = State()


class IdeasGeneratorStates(StatesGroup):
    """FSM states for generating 10 photo ideas, prompts, and captions."""
    waiting_for_wishes = State()
