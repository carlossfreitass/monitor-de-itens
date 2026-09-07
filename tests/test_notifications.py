import io
import os
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch

import requests
from flask import Flask

from app.database import db
from app.models import Item
from app.routes import register_blueprints
from app.services import onesignal


NOTIFICATION_ID = "3c90c3cc-0d44-4b50-8888-8dd25736052a"


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://")
        db.init_app(self.app)
        register_blueprints(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        db.session.add_all([
            Item(uid="01", nome="Carteira", obrigatorio=True),
            Item(uid="02", nome="Chaves", obrigatorio=True),
            Item(uid="03", nome="Guarda-chuva", obrigatorio=False),
        ])
        db.session.commit()
        self.client = self.app.test_client()
        self.credentials = patch.multiple(
            onesignal, ONESIGNAL_APP_ID="test-app", ONESIGNAL_API_KEY="test-key"
        )
        self.credentials.start()
        self.addCleanup(self.credentials.stop)
        self.post_patch = patch.object(onesignal.requests, "post")
        self.post = self.post_patch.start()
        self.addCleanup(self.post_patch.stop)
        self.post.return_value = Mock(status_code=200)
        self.post.return_value.json.return_value = {"id": NOTIFICATION_ID}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def processar(self, uids):
        return self.client.post("/processar", json={"uids_lidos": uids})

    def test_presentes_e_opcional_ausente(self):
        for uids in (["01", "02", "03"], ["01", "02"]):
            with self.subTest(uids=uids):
                response = self.processar(uids)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["status"], "ok")
                self.assertEqual(response.json["itens_faltando"], [])
        self.post.assert_not_called()

    def test_alerta_singular_e_payload(self):
        response = self.processar(["02"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "alerta")
        self.assertEqual(response.json["itens_faltando"], [{"uid": "01", "nome": "Carteira"}])
        self.assertEqual(response.json["mensagem"], "Você está saindo sem: Carteira.")
        self.assertTrue(response.json["notificacao_enviada"])
        self.assertEqual(response.json["onesignal_notification_id"], NOTIFICATION_ID)
        self.post.assert_called_once_with(
            "https://api.onesignal.com/notifications",
            json={
                "app_id": "test-app", "included_segments": ["Total Subscriptions"],
                "target_channel": "push",
                "headings": {"pt": "⚠️ Item esquecido!", "en": "⚠️ Item esquecido!"},
                "contents": {"pt": "Você está saindo sem: Carteira.", "en": "Você está saindo sem: Carteira."},
            },
            headers={"Content-Type": "application/json", "Authorization": "Key test-key"},
            timeout=5, allow_redirects=False,
        )

    def test_alerta_plural(self):
        response = self.processar([])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["itens_faltando"]), 2)
        self.assertEqual(response.json["mensagem"], "Você está saindo sem: Carteira e Chaves.")
        self.post.assert_called_once()
        self.assertEqual(self.post.call_args.kwargs["json"]["headings"],
                         {"pt": "⚠️ 2 itens esquecidos!", "en": "⚠️ 2 itens esquecidos!"})

    def test_entrada_invalida(self):
        for body in ({}, [], ["uids_lidos"], {"uids_lidos": None},
                     {"uids_lidos": "01"}, {"uids_lidos": 1}, {"uids_lidos": {}}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/processar", json=body).status_code, 400)
        self.post.assert_not_called()

    def assert_failure(self, error):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            response = self.processar(["02"])
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json["status"], "erro_notificacao")
        self.assertFalse(response.json["notificacao_enviada"])
        self.assertEqual(response.json["erro_notificacao"], error)
        self.assertEqual(response.json["itens_faltando"], [{"uid": "01", "nome": "Carteira"}])
        self.assertNotIn("test-key", output.getvalue() + response.get_data(as_text=True))
        self.assertNotIn("onesignal_notification_id", response.json)

    def test_credenciais_ausentes(self):
        for field in ("ONESIGNAL_APP_ID", "ONESIGNAL_API_KEY"):
            with self.subTest(field=field), patch.object(onesignal, field, None):
                self.assert_failure("credenciais_ausentes")
        self.post.assert_not_called()

    def test_erros_http(self):
        for status in (301, 400, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.post.return_value.status_code = status
                result = onesignal.enviar_notificacao("titulo", "mensagem")
                self.assertEqual(result, {"sucesso": False, "erro": "erro_http", "status_code": status})
                self.assert_failure("erro_http")

    def test_erros_rede(self):
        for exception, error in ((requests.Timeout, "timeout"),
                                 (requests.ConnectionError, "erro_conexao"),
                                 (requests.RequestException, "erro_requisicao")):
            with self.subTest(error=error):
                self.post.reset_mock()
                self.post.side_effect = exception("test-key")
                self.assert_failure(error)
                self.post.assert_called_once()

    def test_json_invalido(self):
        self.post.return_value.json.side_effect = ValueError("test-key")
        self.assert_failure("json_invalido")

    def test_respostas_inesperadas_e_sem_id(self):
        for body, error in (([], "resposta_inesperada"), (None, "resposta_inesperada"),
                            ({}, "notificacao_nao_criada"),
                            ({"id": "", "errors": ["No subscribers"]}, "notificacao_nao_criada"),
                            ({"id": None}, "notificacao_nao_criada"),
                            ({"id": 123}, "resposta_inesperada"),
                            ({"id": "invalid"}, "resposta_inesperada")):
            with self.subTest(body=body):
                self.post.return_value.json.return_value = body
                self.assert_failure(error)

    def test_sucesso_com_avisos(self):
        self.post.return_value.json.return_value = {"id": NOTIFICATION_ID, "errors": {"invalid_aliases": {}}}
        self.assertEqual(onesignal.enviar_notificacao("titulo", "mensagem"),
                         {"sucesso": True, "notification_id": NOTIFICATION_ID})

    def test_inicializacao_e_leituras(self):
        from app import create_app
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite://"}):
            app = create_app()
            client = app.test_client()
            self.assertEqual(client.get("/itens").status_code, 200)
            self.assertEqual(client.get("/ler-uid").status_code, 200)


if __name__ == "__main__":
    unittest.main()
