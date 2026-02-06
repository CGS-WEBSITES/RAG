"""Resource de busca semântica.

Endpoint para buscar documentos por similaridade semântica usando embeddings
e pgvector.
"""

from flask_restx import Namespace, Resource, fields, reqparse

from api.services.search_service import semantic_search

ns = Namespace("search", description="Busca semântica nos documentos")

search_result = ns.model(
    "SearchResult",
    {
        "id": fields.Integer(description="ID do documento"),
        "title": fields.String(description="Título do documento"),
        "chunk": fields.String(description="Trecho relevante encontrado"),
        "distance": fields.Float(description="Distância (menor = mais similar)"),
    },
)

search_response = ns.model(
    "SearchResponse",
    {
        "query": fields.String(description="Texto da busca original"),
        "results": fields.List(fields.Nested(search_result)),
        "total": fields.Integer(description="Total de resultados retornados"),
    },
)

search_parser = reqparse.RequestParser()
search_parser.add_argument("q", type=str, required=True, location="args")
search_parser.add_argument("limit", type=int, default=5, location="args")
search_parser.add_argument(
    "max_distance",
    type=float,
    default=1.5,
    location="args",
    help="Distância máxima para resultados (menor = mais restritivo).",
)


@ns.route("/")
class SemanticSearch(Resource):
    @ns.expect(search_parser)
    @ns.marshal_with(search_response)
    def get(self):
        """Busca semântica nos documentos usando embeddings.

        Pesquise qualquer termo ou frase. A busca é por significado,
        não por palavra exata. Retorna os trechos mais relevantes
        dos documentos armazenados.
        """
        args = search_parser.parse_args()
        query = args["q"]
        limit = min(max(args["limit"], 1), 20)
        max_distance = args["max_distance"]

        try:
            results = semantic_search(query, limit=limit, max_distance=max_distance)
        except Exception as e:
            ns.abort(500, f"Erro na busca: {str(e)}")

        return {"query": query, "results": results, "total": len(results)}
