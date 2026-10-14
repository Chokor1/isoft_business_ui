"""Column type helpers.

Column ``type`` drives how the browser formats a value and how the Excel export
writes it. Keeping formatting out of the model's hands is deliberate: the model
writes prose, the UI renders numbers.
"""


def col(key, label, type="data"):
    return {"key": key, "label": label, "type": type}


def currency(key, label):
    return col(key, label, "currency")


def number(key, label):
    return col(key, label, "float")


def integer(key, label):
    return col(key, label, "int")


def date(key, label):
    return col(key, label, "date")


def text(key, label):
    return col(key, label, "data")


def percent(key, label):
    return col(key, label, "percent")
