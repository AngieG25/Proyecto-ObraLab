"""ObraLab — prototipo local del segundo avance del PMV.

Aplicación web mínima: autenticación, proyectos, ítems, metrados, APU,
presupuesto consolidado y exportación CSV. Base de datos SQLite local.
"""

import csv
import io
import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    Response,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from calculos import costo_unitario, pesos, presupuesto, valor_parcial

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "obralab.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "obralab-pmv-local-cambio-recomendado"
app.config["DATABASE"] = DATABASE

TIPOS_RECURSO = ("material", "mano_obra", "equipo")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            correo TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            creado TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proyectos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            cliente TEXT NOT NULL DEFAULT '',
            estado TEXT NOT NULL DEFAULT 'activo',
            actualizado TEXT NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proyecto_id INTEGER NOT NULL,
            codigo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            unidad TEXT NOT NULL,
            metrado REAL NOT NULL DEFAULT 0,
            actualizado TEXT NOT NULL,
            FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS recursos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            cantidad REAL NOT NULL,
            precio REAL NOT NULL,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    db.close()


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def login_requerido(vista):
    @wraps(vista)
    def envuelta(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return vista(*args, **kwargs)

    return envuelta


def proyecto_de_usuario(proyecto_id):
    fila = get_db().execute(
        "SELECT * FROM proyectos WHERE id = ? AND usuario_id = ?",
        (proyecto_id, session["usuario_id"]),
    ).fetchone()
    return fila


def item_de_usuario(item_id):
    return get_db().execute(
        """
        SELECT items.*, proyectos.usuario_id, proyectos.nombre AS proyecto_nombre
        FROM items
        JOIN proyectos ON proyectos.id = items.proyecto_id
        WHERE items.id = ? AND proyectos.usuario_id = ?
        """,
        (item_id, session["usuario_id"]),
    ).fetchone()


def recursos_de_item(item_id):
    filas = get_db().execute(
        "SELECT * FROM recursos WHERE item_id = ? ORDER BY id",
        (item_id,),
    ).fetchall()
    return [dict(fila) for fila in filas]


def tocar_proyecto(db, proyecto_id):
    db.execute(
        "UPDATE proyectos SET actualizado = ? WHERE id = ?",
        (ahora(), proyecto_id),
    )


def resumen_items(proyecto_id):
    db = get_db()
    items = db.execute(
        "SELECT * FROM items WHERE proyecto_id = ? ORDER BY codigo, id",
        (proyecto_id,),
    ).fetchall()
    salida = []
    for item in items:
        recursos = recursos_de_item(item["id"])
        costo = costo_unitario(recursos)
        parcial = valor_parcial(item["metrado"], costo)
        salida.append(
            {
                "id": item["id"],
                "codigo": item["codigo"],
                "descripcion": item["descripcion"],
                "unidad": item["unidad"],
                "metrado": item["metrado"],
                "costo_unitario": costo,
                "valor_parcial": parcial,
                "actualizado": item["actualizado"],
            }
        )
    return salida


@app.route("/")
def inicio():
    if "usuario_id" in session:
        return redirect(url_for("proyectos"))
    return redirect(url_for("login"))


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        correo = request.form.get("correo", "").strip().lower()
        clave = request.form.get("clave", "")
        if not nombre or not correo or len(clave) < 6:
            flash("Escribe nombre, correo y una clave de al menos 6 caracteres.")
            return render_template("registro.html")
        db = get_db()
        existe = db.execute(
            "SELECT id FROM usuarios WHERE correo = ?", (correo,)
        ).fetchone()
        if existe:
            flash("Ese correo ya está registrado.")
            return render_template("registro.html")
        db.execute(
            "INSERT INTO usuarios (nombre, correo, password_hash, creado) VALUES (?, ?, ?, ?)",
            (nombre, correo, generate_password_hash(clave), ahora()),
        )
        db.commit()
        flash("Cuenta creada. Ya puedes iniciar sesión.")
        return redirect(url_for("login"))
    return render_template("registro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("correo", "").strip().lower()
        clave = request.form.get("clave", "")
        usuario = get_db().execute(
            "SELECT * FROM usuarios WHERE correo = ?", (correo,)
        ).fetchone()
        if usuario is None or not check_password_hash(usuario["password_hash"], clave):
            flash("Correo o clave incorrectos.")
            return render_template("login.html")
        session.clear()
        session["usuario_id"] = usuario["id"]
        session["nombre"] = usuario["nombre"]
        return redirect(url_for("proyectos"))
    return render_template("login.html")


@app.route("/salir")
def salir():
    session.clear()
    return redirect(url_for("login"))


@app.route("/proyectos")
@login_requerido
def proyectos():
    filas = get_db().execute(
        """
        SELECT * FROM proyectos
        WHERE usuario_id = ?
        ORDER BY estado, actualizado DESC
        """,
        (session["usuario_id"],),
    ).fetchall()
    activos = [fila for fila in filas if fila["estado"] == "activo"]
    archivados = [fila for fila in filas if fila["estado"] != "activo"]
    return render_template("proyectos.html", activos=activos, archivados=archivados)


@app.route("/proyectos/nuevo", methods=["POST"])
@login_requerido
def proyecto_nuevo():
    nombre = request.form.get("nombre", "").strip()
    cliente = request.form.get("cliente", "").strip()
    if not nombre:
        flash("El proyecto necesita un nombre.")
        return redirect(url_for("proyectos"))
    db = get_db()
    db.execute(
        """
        INSERT INTO proyectos (usuario_id, nombre, cliente, estado, actualizado)
        VALUES (?, ?, ?, 'activo', ?)
        """,
        (session["usuario_id"], nombre, cliente, ahora()),
    )
    db.commit()
    return redirect(url_for("proyectos"))


@app.route("/proyectos/<int:proyecto_id>", methods=["GET", "POST"])
@login_requerido
def proyecto_detalle(proyecto_id):
    proyecto = proyecto_de_usuario(proyecto_id)
    if proyecto is None:
        flash("No se encontró el proyecto.")
        return redirect(url_for("proyectos"))
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        cliente = request.form.get("cliente", "").strip()
        if not nombre:
            flash("El proyecto necesita un nombre.")
        else:
            db = get_db()
            db.execute(
                "UPDATE proyectos SET nombre = ?, cliente = ?, actualizado = ? WHERE id = ?",
                (nombre, cliente, ahora(), proyecto_id),
            )
            db.commit()
            flash("Proyecto actualizado.")
        return redirect(url_for("proyecto_detalle", proyecto_id=proyecto_id))
    items = resumen_items(proyecto_id)
    total = presupuesto(items)
    return render_template(
        "proyecto.html",
        proyecto=proyecto,
        items=items,
        total=total,
        pesos=pesos,
    )


@app.route("/proyectos/<int:proyecto_id>/archivar", methods=["POST"])
@login_requerido
def proyecto_archivar(proyecto_id):
    proyecto = proyecto_de_usuario(proyecto_id)
    if proyecto is None:
        return redirect(url_for("proyectos"))
    nuevo = "activo" if proyecto["estado"] != "activo" else "archivado"
    db = get_db()
    db.execute(
        "UPDATE proyectos SET estado = ?, actualizado = ? WHERE id = ?",
        (nuevo, ahora(), proyecto_id),
    )
    db.commit()
    return redirect(url_for("proyectos"))


@app.route("/proyectos/<int:proyecto_id>/items", methods=["POST"])
@login_requerido
def item_nuevo(proyecto_id):
    if proyecto_de_usuario(proyecto_id) is None:
        return redirect(url_for("proyectos"))
    codigo = request.form.get("codigo", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    unidad = request.form.get("unidad", "").strip()
    try:
        metrado = float(request.form.get("metrado", "0").replace(",", "."))
    except ValueError:
        metrado = -1
    if not codigo or not descripcion or not unidad or metrado < 0:
        flash("Revisa código, descripción, unidad y metrado.")
        return redirect(url_for("proyecto_detalle", proyecto_id=proyecto_id))
    db = get_db()
    db.execute(
        """
        INSERT INTO items (proyecto_id, codigo, descripcion, unidad, metrado, actualizado)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (proyecto_id, codigo, descripcion, unidad, metrado, ahora()),
    )
    tocar_proyecto(db, proyecto_id)
    db.commit()
    return redirect(url_for("proyecto_detalle", proyecto_id=proyecto_id))


@app.route("/items/<int:item_id>", methods=["GET", "POST"])
@login_requerido
def item_detalle(item_id):
    item = item_de_usuario(item_id)
    if item is None:
        flash("No se encontró el ítem.")
        return redirect(url_for("proyectos"))
    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        unidad = request.form.get("unidad", "").strip()
        try:
            metrado = float(request.form.get("metrado", "0").replace(",", "."))
        except ValueError:
            metrado = -1
        if not codigo or not descripcion or not unidad or metrado < 0:
            flash("Revisa los datos del ítem.")
        else:
            db = get_db()
            db.execute(
                """
                UPDATE items
                SET codigo = ?, descripcion = ?, unidad = ?, metrado = ?, actualizado = ?
                WHERE id = ?
                """,
                (codigo, descripcion, unidad, metrado, ahora(), item_id),
            )
            tocar_proyecto(db, item["proyecto_id"])
            db.commit()
            flash("Ítem actualizado.")
        return redirect(url_for("item_detalle", item_id=item_id))
    recursos = recursos_de_item(item_id)
    costo = costo_unitario(recursos)
    parcial = valor_parcial(item["metrado"], costo)
    return render_template(
        "item.html",
        item=item,
        recursos=recursos,
        costo=costo,
        parcial=parcial,
        tipos=TIPOS_RECURSO,
        pesos=pesos,
    )


@app.route("/items/<int:item_id>/recursos", methods=["POST"])
@login_requerido
def recurso_nuevo(item_id):
    item = item_de_usuario(item_id)
    if item is None:
        return redirect(url_for("proyectos"))
    tipo = request.form.get("tipo", "")
    descripcion = request.form.get("descripcion", "").strip()
    try:
        cantidad = float(request.form.get("cantidad", "0").replace(",", "."))
        precio = float(request.form.get("precio", "0").replace(",", "."))
    except ValueError:
        cantidad, precio = -1, -1
    if tipo not in TIPOS_RECURSO or not descripcion or cantidad < 0 or precio < 0:
        flash("Revisa tipo, descripción, cantidad y precio del recurso.")
        return redirect(url_for("item_detalle", item_id=item_id))
    db = get_db()
    db.execute(
        """
        INSERT INTO recursos (item_id, tipo, descripcion, cantidad, precio)
        VALUES (?, ?, ?, ?, ?)
        """,
        (item_id, tipo, descripcion, cantidad, precio),
    )
    db.execute(
        "UPDATE items SET actualizado = ? WHERE id = ?",
        (ahora(), item_id),
    )
    tocar_proyecto(db, item["proyecto_id"])
    db.commit()
    return redirect(url_for("item_detalle", item_id=item_id))


@app.route("/recursos/<int:recurso_id>/eliminar", methods=["POST"])
@login_requerido
def recurso_eliminar(recurso_id):
    fila = get_db().execute(
        """
        SELECT recursos.id, recursos.item_id, proyectos.id AS proyecto_id
        FROM recursos
        JOIN items ON items.id = recursos.item_id
        JOIN proyectos ON proyectos.id = items.proyecto_id
        WHERE recursos.id = ? AND proyectos.usuario_id = ?
        """,
        (recurso_id, session["usuario_id"]),
    ).fetchone()
    if fila is None:
        return redirect(url_for("proyectos"))
    db = get_db()
    db.execute("DELETE FROM recursos WHERE id = ?", (recurso_id,))
    db.execute("UPDATE items SET actualizado = ? WHERE id = ?", (ahora(), fila["item_id"]))
    tocar_proyecto(db, fila["proyecto_id"])
    db.commit()
    return redirect(url_for("item_detalle", item_id=fila["item_id"]))


@app.route("/items/<int:item_id>/duplicar", methods=["POST"])
@login_requerido
def item_duplicar(item_id):
    item = item_de_usuario(item_id)
    if item is None:
        return redirect(url_for("proyectos"))
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO items (proyecto_id, codigo, descripcion, unidad, metrado, actualizado)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            item["proyecto_id"],
            item["codigo"] + "-COPIA",
            item["descripcion"],
            item["unidad"],
            item["metrado"],
            ahora(),
        ),
    )
    nuevo_id = cursor.lastrowid
    for recurso in recursos_de_item(item_id):
        db.execute(
            """
            INSERT INTO recursos (item_id, tipo, descripcion, cantidad, precio)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                nuevo_id,
                recurso["tipo"],
                recurso["descripcion"],
                recurso["cantidad"],
                recurso["precio"],
            ),
        )
    tocar_proyecto(db, item["proyecto_id"])
    db.commit()
    flash("Ítem duplicado con su APU.")
    return redirect(url_for("proyecto_detalle", proyecto_id=item["proyecto_id"]))


@app.route("/proyectos/<int:proyecto_id>/exportar")
@login_requerido
def exportar(proyecto_id):
    proyecto = proyecto_de_usuario(proyecto_id)
    if proyecto is None:
        return redirect(url_for("proyectos"))
    items = resumen_items(proyecto_id)
    total = presupuesto(items)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Proyecto", proyecto["nombre"]])
    writer.writerow(["Cliente", proyecto["cliente"]])
    writer.writerow(["Actualizado", proyecto["actualizado"]])
    writer.writerow([])
    writer.writerow(
        ["Código", "Descripción", "Unidad", "Metrado", "Costo unitario", "Valor parcial"]
    )
    for item in items:
        writer.writerow(
            [
                item["codigo"],
                item["descripcion"],
                item["unidad"],
                item["metrado"],
                item["costo_unitario"],
                item["valor_parcial"],
            ]
        )
    writer.writerow([])
    writer.writerow(["", "", "", "", "Presupuesto", total])
    contenido = "\ufeff" + buffer.getvalue()
    nombre = f"presupuesto_{proyecto_id}.csv"
    return Response(
        contenido,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nombre}"},
    )


init_db()


if __name__ == "__main__":
    app.run(debug=True)
