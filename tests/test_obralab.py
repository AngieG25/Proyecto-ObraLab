import os
import tempfile
import unittest

from calculos import costo_unitario, presupuesto, valor_parcial


class CalculosTest(unittest.TestCase):
    def test_costo_unitario_suma_recursos(self):
        recursos = [
            {"cantidad": 2, "precio": 1500},
            {"cantidad": 0.5, "precio": 40000},
            {"cantidad": 1, "precio": 8000},
        ]
        self.assertEqual(costo_unitario(recursos), 31000)

    def test_presupuesto_suma_parciales(self):
        items = [{"valor_parcial": 100000}, {"valor_parcial": 25000.5}]
        self.assertEqual(presupuesto(items), 125000.5)

    def test_valor_parcial(self):
        self.assertEqual(valor_parcial(12.5, 8000), 100000)


class FlujoWebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["OBRALAB_TEST"] = "1"
        import app as aplicacion

        aplicacion.app.config["DATABASE"] = os.path.join(self.tmp.name, "test.db")
        aplicacion.app.config["TESTING"] = True
        aplicacion.init_db()
        self.client = aplicacion.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_registro_proyecto_apu_y_exportacion(self):
        self.client.post(
            "/registro",
            data={"nombre": "Ana", "correo": "ana@obralab.test", "clave": "secreto1"},
        )
        self.client.post(
            "/login",
            data={"correo": "ana@obralab.test", "clave": "secreto1"},
        )
        self.client.post(
            "/proyectos/nuevo",
            data={"nombre": "Casa Suba", "cliente": "Cliente demo"},
        )
        self.client.post(
            "/proyectos/1/items",
            data={
                "codigo": "01",
                "descripcion": "Muro en ladrillo",
                "unidad": "m2",
                "metrado": "10",
            },
        )
        self.client.post(
            "/items/1/recursos",
            data={
                "tipo": "material",
                "descripcion": "Ladrillo",
                "cantidad": "2",
                "precio": "1500",
            },
        )
        respuesta = self.client.get("/proyectos/1")
        self.assertIn("3.000,00".encode(), respuesta.data)
        self.assertIn("30.000,00".encode(), respuesta.data)
        csv = self.client.get("/proyectos/1/exportar")
        self.assertEqual(csv.status_code, 200)
        texto = csv.data.decode("utf-8-sig")
        self.assertIn("Muro en ladrillo", texto)
        self.assertIn("30000", texto.replace(".0", "").replace(",", ""))


if __name__ == "__main__":
    unittest.main()
