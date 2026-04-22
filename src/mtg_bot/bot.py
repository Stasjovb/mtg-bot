from dataclasses import dataclass


@dataclass
class Bot:
    name: str

    def choose_action(self, game_state: object) -> object:
        raise NotImplementedError("Decision logic has not been implemented yet.")
