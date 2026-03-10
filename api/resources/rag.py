from flask_restx import Namespace, Resource, fields

from api.services.rag_service import generate_rag_response

ns = Namespace("rag", description="RAG - Perguntas e respostas com IA")

rag_input = ns.model(
    "RAGInput",
    {
        "question": fields.String(
            required=True,
            description="Pergunta em linguagem natural",
            example="Meu pedido está atrasado, o que eu faço?",
        ),
        "max_chunks": fields.Integer(
            default=3,
            description="Máximo de tickets de contexto (1-10)",
            example=3,
        ),
    },
)

source_model = ns.model(
    "Source",
    {
        "id": fields.Integer(description="ID do documento fonte"),
        "title": fields.String(description="Título do documento"),
        "chunk": fields.String(description="Trecho usado como contexto"),
        "distance": fields.Float(description="Distância semântica"),
    },
)

rag_output = ns.model(
    "RAGOutput",
    {
        "question": fields.String(description="Pergunta original"),
        "answer": fields.String(description="Resposta gerada pelo LLM"),
        "sources": fields.List(fields.Nested(source_model)),
        "model": fields.String(description="Modelo LLM utilizado"),
    },
)


@ns.route("/tickets")
class RAGTickets(Resource):
    @ns.doc("rag_tickets")
    @ns.expect(rag_input, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        data = ns.payload
        question = data["question"]
        max_chunks = min(max(data.get("max_chunks", 3), 1), 10)

        try:
            return generate_rag_response(
                question=question,
                max_chunks=max_chunks,
            )
        except ConnectionError as e:
            ns.abort(503, str(e))
        except RuntimeError as e:
            ns.abort(500, str(e))
        except Exception as e:
            ns.abort(500, f"Erro inesperado: {str(e)}")


# ============================================================
# Game Comments (desabilitado)
# ============================================================
# _base_fields_game = {
#     "question": fields.String(
#         required=True,
#         description="Pergunta sobre jogos",
#         example="What do people think about Gloomhaven?",
#     ),
#     "max_chunks": fields.Integer(
#         default=3,
#         description="Máximo de trechos de contexto (1-10)",
#         example=3,
#     ),
# }
#
# rag_input_game_comments = ns.model("RAGInputGameComments", _base_fields_game)
#
# @ns.route("/game-comments")
# class RAGGameComments(Resource):
#     @ns.doc("rag_game_comments")
#     @ns.expect(rag_input_game_comments, validate=True)
#     @ns.marshal_with(rag_output)
#     def post(self):
#         """RAG sobre comentários e avaliações de jogos"""
#         data = ns.payload
#         question = data["question"]
#         max_chunks = min(max(data.get("max_chunks", 3), 1), 10)
#         try:
#             return generate_rag_response(
#                 question=question,
#                 max_chunks=max_chunks,
#                 source="game_comments",
#             )
#         except ConnectionError as e:
#             ns.abort(503, str(e))
#         except RuntimeError as e:
#             ns.abort(500, str(e))
#         except Exception as e:
#             ns.abort(500, f"Erro inesperado: {str(e)}")
