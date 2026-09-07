"""
Serviço de Notificações Push via OneSignal.
Gerencia o disparo de alertas globais para os usuários conectados ao aplicativo.
"""

import os
from uuid import UUID
import requests

ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID")
ONESIGNAL_API_KEY = os.getenv("ONESIGNAL_API_KEY")

# FUNÇÃO: Enviar Notificação Global
def enviar_notificacao(titulo: str, mensagem: str) -> dict:
    # Validação de Credenciais do Sistema
    if not ONESIGNAL_APP_ID or not ONESIGNAL_API_KEY:
        return {"sucesso": False, "erro": "credenciais_ausentes"}

    # Montagem do Payload para Segmento Global
    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "included_segments": ["All"],
        "target_channel": "push",
        "headings": {"pt": titulo, "en": titulo},
        "contents": {"pt": mensagem, "en": mensagem},
    }

    # Cabeçalhos de Autenticação da API Externa
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Key {ONESIGNAL_API_KEY}",
    }

    try:
        # Disparo de Requisição POST com Limite de Tempo de Resposta
        response = requests.post(
            "https://api.onesignal.com/notifications",
            json=payload,
            headers=headers,
            timeout=5,
            allow_redirects=False,
        )
        # Intercepção de Erros de Status HTTP
        if not 200 <= response.status_code < 300:
            return {"sucesso": False, "erro": "erro_http", "status_code": response.status_code}

    # Tratamento de Exceções de Rede e Integração
    except requests.Timeout:
        return {"sucesso": False, "erro": "timeout"}
    except requests.ConnectionError:
        return {"sucesso": False, "erro": "erro_conexao"}
    except requests.RequestException:
        return {"sucesso": False, "erro": "erro_requisicao"}

    try:
        dados = response.json()
    except ValueError:
        return {"sucesso": False, "erro": "json_invalido"}
    if not isinstance(dados, dict):
        return {"sucesso": False, "erro": "resposta_inesperada"}
    notification_id = dados.get("id")
    if notification_id is None or notification_id == "":
        return {"sucesso": False, "erro": "notificacao_nao_criada"}
    try:
        if not isinstance(notification_id, str) or UUID(notification_id).version != 4:
            return {"sucesso": False, "erro": "resposta_inesperada"}
    except ValueError:
        return {"sucesso": False, "erro": "resposta_inesperada"}
    return {"sucesso": True, "notification_id": notification_id}
