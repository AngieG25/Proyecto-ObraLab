"""Cálculos de APU y presupuesto de ObraLab.

El costo unitario de un ítem es la suma de cantidad × precio de sus recursos
(materiales, mano de obra y equipo). El valor parcial del ítem es metrado ×
costo unitario. El presupuesto del proyecto es la suma de los valores parciales.
"""


def costo_unitario(recursos):
    total = 0.0
    for recurso in recursos:
        cantidad = float(recurso["cantidad"])
        precio = float(recurso["precio"])
        total += cantidad * precio
    return round(total, 2)


def valor_parcial(metrado, costo):
    return round(float(metrado) * float(costo), 2)


def presupuesto(items):
    total = 0.0
    for item in items:
        total += float(item["valor_parcial"])
    return round(total, 2)


def pesos(valor):
    texto = f"{float(valor):,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")
