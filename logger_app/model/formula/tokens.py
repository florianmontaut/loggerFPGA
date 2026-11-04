
from enum import Enum
from dataclasses import dataclass

class TokenType(Enum):
    NUMBER = 0
    PLUS = 1
    MINUS = 2
    MULTIPLY = 3
    DIVIDE = 4
    LPAREN = 5
    RPAREN = 6
    POWER = 7
    VECTOR = 8
    FUNC = 9
    DELIMITOR =10
    VARIABLE = 11
    ASSIGN = 12
    CHANNEL = 13     # voie nommée entre crochets : [T AMB], [200 W:T AMB]

@dataclass
class Token:
    type: TokenType
    value: any = None

    def __repr__(self):
        return self.type.name + (f":{self.value}" if self.value is not None else "")
