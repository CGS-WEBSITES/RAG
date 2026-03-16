from flask_restx import Namespace, Resource, fields
from flask import request

from api.services.history_service import (
    get_history,
    update_feedback,
    get_dashboard_stats,
)

ns = Namespace("history", description="Histórico e métricas")

feedback_input = ns.model(
    "FeedbackInput",
    {
        "feedback": fields.String(
            required=True,
            description="up ou down",
            enum=["up", "down"],
        ),
    },
)

history_item = ns.model(
    "HistoryItem",
    {
        "id": fields.Integer,
        "question": fields.String,
        "answer": fields.String,
        "category": fields.String,
        "model": fields.String,
        "feedback": fields.String,
        "created_at": fields.DateTime,
    },
)

feedback_stats = ns.model(
    "FeedbackStats",
    {
        "positive": fields.Integer,
        "negative": fields.Integer,
        "no_feedback": fields.Integer,
    },
)

token_stats = ns.model(
    "TokenStats",
    {
        "total_in": fields.Integer,
        "total_out": fields.Integer,
        "total": fields.Integer,
    },
)

category_stat = ns.model(
    "CategoryStat",
    {
        "category": fields.String,
        "count": fields.Integer,
    },
)

daily_stat = ns.model(
    "DailyStat",
    {
        "day": fields.String,
        "count": fields.Integer,
    },
)

dashboard_output = ns.model(
    "DashboardOutput",
    {
        "total_conversations": fields.Integer,
        "today": fields.Integer,
        "last_7_days": fields.Integer,
        "feedback": fields.Nested(feedback_stats),
        "top_categories": fields.List(fields.Nested(category_stat)),
        "tokens": fields.Nested(token_stats),
        "daily": fields.List(fields.Nested(daily_stat)),
        "avg_tokens_per_conversation": fields.Integer,
    },
)


@ns.route("/chat/<string:session_id>")
class ChatHistory(Resource):
    @ns.doc("get_history")
    @ns.marshal_list_with(history_item)
    def get(self, session_id):
        limit = request.args.get("limit", 50, type=int)
        return get_history(session_id, limit=min(limit, 200))


@ns.route("/feedback/<int:chat_id>")
class ChatFeedback(Resource):
    @ns.doc("update_feedback")
    @ns.expect(feedback_input, validate=True)
    def put(self, chat_id):
        data = ns.payload
        ok = update_feedback(chat_id, data["feedback"])
        if ok:
            return {"message": "Feedback atualizado", "chat_id": chat_id}
        ns.abort(404, "Interação não encontrada")


@ns.route("/dashboard")
class Dashboard(Resource):
    @ns.doc("get_dashboard")
    @ns.marshal_with(dashboard_output)
    def get(self):
        try:
            return get_dashboard_stats()
        except Exception as e:
            ns.abort(500, f"Erro ao buscar métricas: {str(e)}")
