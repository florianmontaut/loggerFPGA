from enum import Enum,auto

class itemType(Enum):

    FILE=auto()
    RAW=auto()
    MODIF=auto()
    MODEL=auto()

class qSignalType(Enum):

    LOAD=auto()
    FILTER=auto()
    REF=auto()
    DELTA_T=auto()
    MODEL=auto()
    DEL=auto()
    SELECT=auto()
    CHECK=auto()
    OPTIONS=auto()
    CONNECT=auto()
    DISCONNECT=auto()
    PAUSE=auto()

class fileType(Enum):

    GL=auto()
    TXT=auto()
    CSV=auto()
    VCD=auto()
    JSON=auto()


class modelType(Enum):

    POLY=auto()
    EXP=auto()
    FIRST_ORDER=auto()
    SECOND_ORDER=auto()


class degree(Enum):

    FARENHEIT=auto()
    CELSIUS=auto()
