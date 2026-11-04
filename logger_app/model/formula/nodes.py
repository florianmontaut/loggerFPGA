
from dataclasses import dataclass, field

# Dataclasses : __eq__ et __repr__ générés, ce qui permet de comparer des arbres dans les tests.

@dataclass
class NumberNode:
    value: float

@dataclass
class VariableNode:
    name: str

@dataclass
class ChannelNode:
    # voie nommée entre crochets : [T AMB]
    name: str

@dataclass
class AssignmentNode:
    name: str
    expr: object

@dataclass
class AddNode:
    node_a: object
    node_b: object

@dataclass
class SubtractNode:
    node_a: object
    node_b: object

@dataclass
class MultiplyNode:
    node_a: object
    node_b: object

@dataclass
class DivideNode:
    node_a: object
    node_b: object

@dataclass
class PowerNode:
    node_a: object
    node_b: object

@dataclass
class PlusNode:
    node: object

@dataclass
class MinusNode:
    node: object

@dataclass
class FuncNode:
    func: str
    args: list = field(default_factory=list)
