from flask_restx import Namespace, Resource, fields

from api.services.rag_service import generate_rag_response

ns = Namespace("rag", description="RAG - Perguntas e respostas com IA")

rag_input = ns.model(
    "RAGInput",
    {
        "question": fields.String(
            required=True,
            description="Pergunta em linguagem natural",
            example="O que é pgai?",
        ),
        "max_chunks": fields.Integer(
            default=5,
            description="Máximo de trechos de contexto (1-10)",
            example=5,
        ),
        "model": fields.String(
            default="llama3.2",
            description="Modelo LLM do Ollama para gerar a resposta",
            example="llama3.2",
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
        "sources": fields.List(
            fields.Nested(source_model),
            description="Documentos usados como contexto",
        ),
        "model": fields.String(description="Modelo LLM utilizado"),
    },
)


@ns.route("/")
class RAGQuery(Resource):
    @ns.expect(rag_input, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        data = ns.payload
        question = data["question"]
        max_chunks = min(max(data.get("max_chunks", 5), 1), 10)
        model = data.get("model")

        try:
            result = generate_rag_response(
                question=question,
                max_chunks=max_chunks,
                model=model,
            )
        except ConnectionError as e:
            ns.abort(503, str(e))
        except RuntimeError as e:
            ns.abort(500, str(e))
        except Exception as e:
            ns.abort(500, f"Erro inesperado: {str(e)}")

        return result
