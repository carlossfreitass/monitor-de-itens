"""
Módulo de Processamento e Verificação de Itens.
Valida as leituras enviadas pelo Raspberry e gerencia notificações em caso de itens obrigatórios ausentes.
"""

from flask import Blueprint, request, jsonify
from app.models import Item
from app.services.onesignal import enviar_notificacao

processar_bp = Blueprint("processar", __name__)

# ROTA: Processar Leituras e Validar Itens
@processar_bp.route("/processar", methods=["POST"])
def processar():
    dados = request.get_json()

    # Validação de Segurança
    if not isinstance(dados, dict) or "uids_lidos" not in dados:
        return jsonify({"erro": "O campo 'uids_lidos' é obrigatório."}), 400

    uids_lidos = dados["uids_lidos"]
    if not isinstance(uids_lidos, list):
        return jsonify({"erro": "O campo 'uids_lidos' deve ser uma lista."}), 400

    # Consulta de Regras de Negócio no Banco de Dados
    itens_obrigatorios = Item.query.filter_by(obrigatorio=True).all()

    # Filtro de Itens Ausentes
    itens_faltando = [
        {"uid": item.uid, "nome": item.nome}
        for item in itens_obrigatorios
        if item.uid not in uids_lidos
    ]

    if itens_faltando:
        quantidade = len(itens_faltando)
        nomes = [item["nome"] for item in itens_faltando]

        # Formatação Dinâmica de Texto
        if quantidade == 1:
            titulo = "⚠️ Item esquecido!"
            corpo = f"Você está saindo sem: {nomes[0]}."
        else:
            lista_nomes = ", ".join(nomes[:-1]) + f" e {nomes[-1]}"
            titulo = f"⚠️ {quantidade} itens esquecidos!"
            corpo = f"Você está saindo sem: {lista_nomes}."

        # Disparo do Alerta para o OneSignal
        notificacao = enviar_notificacao(titulo, corpo)

        if not notificacao["sucesso"]:
            return jsonify({
                "status": "erro_notificacao",
                "itens_faltando": itens_faltando,
                "mensagem": corpo,
                "notificacao_enviada": False,
                "erro_notificacao": notificacao["erro"],
            }), 502

        return jsonify({
            "status": "alerta",
            "itens_faltando": itens_faltando,
            "mensagem": corpo,
            "notificacao_enviada": True,
            "onesignal_notification_id": notificacao["notification_id"],
        }), 200

    return jsonify({
        "status": "ok",
        "itens_faltando": [],
        "mensagem": "Todos os itens obrigatórios estão presentes."
    }), 200
