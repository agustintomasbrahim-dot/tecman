import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class ReglaMaterialesSoriaTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        tecman.USE_DB = False
        tecman.TICKETS_FILE = root / "tickets.json"
        tecman.UPLOADS_DIR = root / "uploads"
        tecman.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        tecman.save_tickets([])
        self.client = tecman.app.test_client()

    def tearDown(self):
        tecman.USE_DB = False
        self.temp.cleanup()

    @staticmethod
    def _material_ticket(ticket_id=1, **overrides):
        ticket = {
            "id": ticket_id,
            "sucursal": "Sucursal 142",
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "tipo": "materiales",
            "descripcion": "Reposición operativa",
            "estado": "Nuevo",
            "asignado": "Soria",
            "prioridad": 2,
            "observaciones": "",
            "creado": "2026-09-18T10:00:00",
            "actualizado": "2026-09-18T10:00:00",
            "notas": [{"autor": "Sistema", "texto": "Historial previo"}],
        }
        ticket.update(overrides)
        return ticket

    def _branch_session(self, sucursal):
        with self.client.session_transaction() as session:
            session.clear()
            session["suc_user"] = "sucursal-test"
            session["suc_nombre"] = sucursal

    def _admin_session(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["user"] = "agustin-test"
            session["nombre"] = "Agustín Test"
            session["rol"] = "admin"
            session["_csrf_token"] = "csrf-test"

    @staticmethod
    def _material_form():
        return {
            "categoria": "Materiales",
            "subcategoria": "Solicitud de materiales",
            "descripcion": "Pedido de lámparas",
            "solicitante_nombre": "Sucursal",
            "solicitante_apellido": "Test",
            "categoria_mat": "Luminaria",
            "subitem_mat": "Lámparas AR111",
            "cantidad_mat": "2",
            "zona_afectada": "Salón",
        }

    def test_predicado_usa_solo_campos_estructurados(self):
        libre = {
            "categoria": "Otro",
            "subcategoria": "Otro",
            "tipo": "incidente",
            "descripcion": "Necesitamos un pedido de materiales y luminarias",
            "estado": "Nuevo",
            "asignado": "Julio Fuga (JRF)",
        }
        self.assertFalse(tecman._ticket_es_pedido_materiales(libre))
        before = copy.deepcopy(libre)
        tecman._normalizar_responsable_materiales([libre])
        self.assertEqual(libre, before)

        luminaria = {
            "categoria": "Problema Eléctrico",
            "subcategoria": "Luminarias",
            "descripcion": "Cambiar artefactos",
            "estado": "Nuevo",
        }
        self.assertEqual(
            tecman.auto_assign("Luminarias", "Sucursal 142", "Problema Eléctrico"),
            "Soria",
        )
        self.assertFalse(tecman._ticket_es_pedido_materiales(luminaria))
        self.assertNotIn("tipo", luminaria)

    def test_creacion_luminarias_va_a_soria_sin_reclasificarse_como_materiales(self):
        self._branch_session("Sucursal 142")
        response = self.client.post("/nuevo", data={
            "categoria": "Problema Eléctrico",
            "subcategoria": "Luminarias",
            "descripcion": "Cambiar luminarias del salón",
            "solicitante_nombre": "Sucursal",
            "solicitante_apellido": "Test",
        })
        self.assertEqual(response.status_code, 200)
        saved = tecman.load_tickets()[0]
        self.assertEqual(saved["asignado"], "Soria")
        self.assertEqual(saved["categoria"], "Problema Eléctrico")
        self.assertEqual(saved["subcategoria"], "Luminarias")
        self.assertNotIn("tipo", saved)
        self.assertFalse(tecman._ticket_es_pedido_materiales(saved))

    def test_texto_libre_no_convierte_un_ticket_en_pedido(self):
        self._branch_session("Sucursal 145")
        response = self.client.post("/nuevo", data={
            "categoria": "Otro",
            "subcategoria": "Otro",
            "descripcion": "Parece un pedido de materiales para luminarias",
            "solicitante_nombre": "Sucursal",
            "solicitante_apellido": "Test",
        })
        self.assertEqual(response.status_code, 200)
        saved = tecman.load_tickets()[0]
        self.assertEqual(saved["asignado"], tecman.ASIGNACION_DEFAULT)
        self.assertEqual(saved["categoria"], "Otro")
        self.assertNotIn("tipo", saved)
        self.assertFalse(tecman._ticket_es_pedido_materiales(saved))

    def test_auto_assign_materiales_prevalece_sobre_abono_zona_y_cierre(self):
        casos = [
            ("Sucursal 142", "CEYH"),
            ("Sucursal 126", "Julio Fuga (JRF)"),
            ("Sucursal 215", tecman.ASIGNACION_DEFAULT),
        ]
        for sucursal, asignacion_no_material in casos:
            with self.subTest(sucursal=sucursal):
                self.assertEqual(
                    tecman.auto_assign("Solicitud de materiales", sucursal, "Materiales"),
                    "Soria",
                )
                self.assertEqual(
                    tecman.auto_assign("Tablero", sucursal, "Problema Eléctrico"),
                    asignacion_no_material,
                )

    def test_nuevo_pedido_en_sucursal_con_abono_y_zona_regional_va_a_soria(self):
        for sucursal in ("Sucursal 142", "Sucursal 126"):
            with self.subTest(sucursal=sucursal):
                tecman.save_tickets([])
                self._branch_session(sucursal)
                response = self.client.post("/nuevo", data=self._material_form())
                self.assertEqual(response.status_code, 200)
                saved = tecman.load_tickets()
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0]["asignado"], "Soria")
                self.assertNotIn("asignado_proveedor", saved[0])

    def test_nuevo_pedido_operativo_de_sucursal_cerrada_se_normaliza_a_soria(self):
        ticket = self._material_ticket(
            sucursal="Sucursal 215",
            asignado=tecman.ASIGNACION_DEFAULT,
            asignado_proveedor="Proveedor cerrado",
        )
        tecman.save_tickets([ticket])
        saved = json.loads(tecman.TICKETS_FILE.read_text())[0]
        self.assertEqual(saved["asignado"], "Soria")
        self.assertNotIn("asignado_proveedor", saved)
        self.assertEqual(saved["proveedor_origen"], "Proveedor cerrado")

    def test_carga_json_normaliza_material_y_preserva_origen_e_historial(self):
        historial = [{"autor": "Proveedor", "texto": "Pedido originado externamente"}]
        payload = [self._material_ticket(
            asignado="Julio Fuga (JRF)",
            asignado_proveedor="JRF",
            proveedor_origen="CEYH",
            notas=historial,
        )]
        tecman.TICKETS_FILE.write_text(json.dumps(payload), encoding="utf-8")

        loaded = tecman.load_tickets()[0]
        self.assertEqual(loaded["asignado"], "Soria")
        self.assertNotIn("asignado_proveedor", loaded)
        self.assertEqual(loaded["proveedor_origen"], "CEYH")
        self.assertEqual(loaded["notas"][0], historial[0])
        self.assertEqual(
            len([n for n in loaded["notas"] if "Migración automática" in n.get("texto", "")]),
            1,
        )
        self.assertEqual(json.loads(tecman.TICKETS_FILE.read_text())[0], loaded)

    def test_carga_db_normaliza_material_mal_asignado(self):
        payload = [self._material_ticket(
            asignado="Julio Fuga (JRF)",
            asignado_proveedor="JRF",
        )]
        fake_model = object()
        with (
            patch.object(tecman, "USE_DB", True),
            patch.object(tecman, "TicketDB", fake_model, create=True),
            patch.object(tecman, "_db_list", return_value=copy.deepcopy(payload)) as db_list,
            patch.object(tecman, "_db_replace") as db_replace,
        ):
            loaded = tecman.load_tickets()[0]

        db_list.assert_called_once_with(fake_model)
        db_replace.assert_called_once_with(fake_model, [loaded])
        self.assertEqual(loaded["asignado"], "Soria")
        self.assertNotIn("asignado_proveedor", loaded)
        self.assertEqual(loaded["proveedor_origen"], "JRF")

    def test_guardado_json_y_db_aplica_la_misma_invariante(self):
        payload = [self._material_ticket(
            asignado="Proveedor externo",
            asignado_proveedor="Proveedor externo",
        )]
        fake_model = object()
        with (
            patch.object(tecman, "USE_DB", True),
            patch.object(tecman, "TicketDB", fake_model, create=True),
            patch.object(tecman, "_db_replace") as db_replace,
        ):
            tecman.save_tickets(payload)

        persisted = db_replace.call_args.args[1][0]
        self.assertEqual(persisted["asignado"], "Soria")
        self.assertNotIn("asignado_proveedor", persisted)
        self.assertEqual(persisted["proveedor_origen"], "Proveedor externo")
        self.assertEqual(json.loads(tecman.TICKETS_FILE.read_text())[0], persisted)

    def test_import_de_app_ejecuta_migracion_automaticamente(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            uploads_dir = root / "uploads"
            data_dir.mkdir()
            ticket = self._material_ticket(
                ticket_id=900,
                asignado="Proveedor de arranque",
                asignado_proveedor="Proveedor de arranque",
                proveedor_nombre="Proveedor de arranque",
            )
            (data_dir / "tickets.json").write_text(json.dumps([ticket]), encoding="utf-8")
            env = os.environ.copy()
            env["TECMAN_DATA_DIR"] = str(data_dir)
            env["TECMAN_UPLOADS_DIR"] = str(uploads_dir)
            env.pop("DATABASE_URL", None)
            result = subprocess.run(
                [sys.executable, "-c", "import app"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            migrated = next(
                item for item in json.loads((data_dir / "tickets.json").read_text())
                if item.get("id") == 900
            )
            self.assertEqual(migrated["asignado"], "Soria")
            self.assertNotIn("asignado_proveedor", migrated)
            self.assertNotIn("proveedor_nombre", migrated)
            self.assertEqual(migrated["proveedor_origen"], "Proveedor de arranque")
            self.assertEqual(
                len([n for n in migrated["notas"] if "Migración automática" in n.get("texto", "")]),
                1,
            )

    def test_migracion_json_persiste_auditoria_una_sola_vez_y_preserva_presupuesto(self):
        ticket = self._material_ticket(
            asignado="Julio Fuga (JRF)",
            asignado_proveedor="jrf",
            proveedor_nombre="Julio Fuga (JRF)",
            proveedor_presupuesto="Presupuestos SRL",
            presupuestos=[{"proveedor": "Presupuestos SRL", "monto": "150000"}],
            notas=[{"autor": "Proveedor", "texto": "Historial original"}],
        )
        tecman.TICKETS_FILE.write_text(json.dumps([ticket]), encoding="utf-8")

        with patch.object(tecman, "_atomic_write", wraps=tecman._atomic_write) as atomic_write:
            migrated = tecman.load_tickets()[0]
            first_bytes = tecman.TICKETS_FILE.read_bytes()
            loaded_again = tecman.load_tickets()[0]

        atomic_write.assert_called_once()
        self.assertEqual(loaded_again, migrated)
        self.assertEqual(migrated["asignado"], "Soria")
        self.assertNotIn("asignado_proveedor", migrated)
        self.assertNotIn("proveedor_nombre", migrated)
        self.assertEqual(migrated["proveedor_origen"], "Julio Fuga (JRF)")
        self.assertEqual(migrated["proveedor_presupuesto"], "Presupuestos SRL")
        self.assertEqual(migrated["presupuestos"], [{"proveedor": "Presupuestos SRL", "monto": "150000"}])
        self.assertEqual(migrated["notas"][0]["texto"], "Historial original")
        notas_migracion = [
            nota for nota in migrated["notas"]
            if "Migración automática" in nota.get("texto", "")
        ]
        self.assertEqual(len(notas_migracion), 1)
        self.assertEqual(
            migrated["migracion_responsable_materiales"],
            tecman.MIGRACION_MATERIALES_SORIA_VERSION,
        )

        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), first_bytes)

    def test_migracion_db_persiste_e_idempotente(self):
        backing = [self._material_ticket(
            asignado="CEYH",
            asignado_proveedor="CEYH",
            proveedor_nombre="CEYH",
        )]
        fake_model = object()

        def fake_list(model):
            self.assertIs(model, fake_model)
            return copy.deepcopy(backing)

        def fake_replace(model, items):
            self.assertIs(model, fake_model)
            backing[:] = copy.deepcopy(items)

        with (
            patch.object(tecman, "USE_DB", True),
            patch.object(tecman, "TicketDB", fake_model, create=True),
            patch.object(tecman, "_db_list", side_effect=fake_list),
            patch.object(tecman, "_db_replace", side_effect=fake_replace) as db_replace,
        ):
            first = tecman.load_tickets()[0]
            second = tecman.load_tickets()[0]

        self.assertEqual(second, first)

        db_replace.assert_called_once()
        migrated = backing[0]
        self.assertEqual(migrated["asignado"], "Soria")
        self.assertNotIn("asignado_proveedor", migrated)
        self.assertNotIn("proveedor_nombre", migrated)
        self.assertEqual(migrated["proveedor_origen"], "CEYH")
        self.assertEqual(
            len([n for n in migrated["notas"] if "Migración automática" in n.get("texto", "")]),
            1,
        )

    def test_fallo_persistencia_json_se_propaga_y_no_reemplaza_snapshot(self):
        ticket = self._material_ticket(
            asignado="Proveedor externo",
            asignado_proveedor="Proveedor externo",
        )
        tecman.TICKETS_FILE.write_text(json.dumps([ticket]), encoding="utf-8")
        before = tecman.TICKETS_FILE.read_bytes()

        with patch.object(tecman, "_atomic_write", side_effect=OSError("fallo simulado")):
            with self.assertRaisesRegex(OSError, "fallo simulado"):
                tecman.load_tickets()

        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)

    def test_fallo_persistencia_db_se_propaga_y_no_escribe_snapshot_json(self):
        payload = [self._material_ticket(
            asignado="Proveedor externo",
            asignado_proveedor="Proveedor externo",
        )]
        fake_model = object()
        with (
            patch.object(tecman, "USE_DB", True),
            patch.object(tecman, "TicketDB", fake_model, create=True),
            patch.object(tecman, "_db_list", return_value=copy.deepcopy(payload)),
            patch.object(tecman, "_db_replace", side_effect=RuntimeError("db caída")),
            patch.object(tecman, "_atomic_write") as atomic_write,
        ):
            with self.assertRaisesRegex(RuntimeError, "db caída"):
                tecman.load_tickets()

        atomic_write.assert_not_called()

    def test_migracion_no_persiste_finalizados_ni_inferidos_por_texto(self):
        finalizado = self._material_ticket(
            ticket_id=50,
            estado="Cerrado",
            asignado="Proveedor histórico",
            asignado_proveedor="Proveedor histórico",
        )
        texto_libre = {
            "id": 51,
            "categoria": "Otro",
            "subcategoria": "Otro",
            "tipo": "incidente",
            "descripcion": "Pedido de materiales para luminarias",
            "estado": "Nuevo",
            "asignado": "CEYH",
            "asignado_proveedor": "CEYH",
            "notas": [],
        }
        payload = [finalizado, texto_libre]
        tecman.TICKETS_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        before = tecman.TICKETS_FILE.read_bytes()

        self.assertEqual(tecman.load_tickets(), payload)
        self.assertEqual(tecman.TICKETS_FILE.read_bytes(), before)
        self.assertEqual(json.loads(before), payload)

    def test_normalizacion_conserva_proveedor_de_retiro_logistico(self):
        ticket = self._material_ticket(
            asignado="Proveedor externo",
            asignado_proveedor="Proveedor externo",
            proveedor_nombre="Transporte Logístico",
            retiro_tipo="proveedor",
            retiro_proveedor=True,
        )
        tecman.TICKETS_FILE.write_text(json.dumps([ticket]), encoding="utf-8")

        migrated = tecman.load_tickets()[0]
        self.assertEqual(json.loads(tecman.TICKETS_FILE.read_text())[0], migrated)
        self.assertEqual(migrated["asignado"], "Soria")
        self.assertNotIn("asignado_proveedor", migrated)
        self.assertEqual(migrated["proveedor_nombre"], "Transporte Logístico")
        self.assertEqual(migrated["proveedor_origen"], "Proveedor externo")

    def test_pedido_generado_desde_proveedor_queda_en_soria_con_origen(self):
        origen = {
            "id": 20,
            "sucursal": "Sucursal 142",
            "prioridad": 2,
            "estado": "En progreso",
            "asignado": "CEYH",
            "notas": [],
        }
        tickets = [origen]
        pedido = tecman._crear_ticket_materiales_desde_ceyh(
            tickets, origen, "CEYH", "2 reflectores", "Para salón"
        )
        tecman.save_tickets(tickets)

        self.assertEqual(pedido["asignado"], "Soria")
        self.assertNotIn("asignado_proveedor", pedido)
        self.assertEqual(pedido["proveedor_origen"], "CEYH")
        self.assertEqual(pedido["origen_ticket_id"], 20)
        self.assertFalse(tecman._ticket_es_de_proveedor(pedido, ["CEYH"]))

    def test_intento_admin_de_asignar_proveedor_no_modifica_pedido(self):
        tecman.save_tickets([self._material_ticket(ticket_id=33)])
        self._admin_session()
        response = self.client.post("/admin/ticket/33", data={
            "accion": "asignar_proveedor_presupuesto",
            "proveedor_presupuesto": "Julio Fuga (JRF)",
            "asignado": "Julio Fuga (JRF)",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin/pedido/33"))
        saved = tecman.load_tickets()[0]
        self.assertEqual(saved["asignado"], "Soria")
        self.assertNotIn("asignado_proveedor", saved)

    def test_ticket_no_material_no_se_altera(self):
        ticket = {
            "id": 40,
            "categoria": "Problema Eléctrico",
            "subcategoria": "Tablero",
            "tipo": "incidente",
            "descripcion": "Revisar tablero",
            "estado": "Nuevo",
            "asignado": "CEYH",
            "asignado_proveedor": "CEYH",
            "notas": [{"texto": "Original"}],
        }
        before = copy.deepcopy(ticket)
        tecman.save_tickets([ticket])
        self.assertEqual(json.loads(tecman.TICKETS_FILE.read_text())[0], before)

    def test_finalizados_no_se_reescriben(self):
        for estado in ("Resuelto", "Cerrado", "Rechazado"):
            with self.subTest(estado=estado):
                ticket = self._material_ticket(
                    estado=estado,
                    asignado="Proveedor histórico",
                    asignado_proveedor="Proveedor histórico",
                    proveedor_origen="Origen histórico",
                )
                before = copy.deepcopy(ticket)
                tecman._normalizar_responsable_materiales([ticket])
                self.assertEqual(ticket, before)


if __name__ == "__main__":
    unittest.main()
