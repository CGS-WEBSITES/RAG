from flask_restx import Namespace, Resource, fields

from api.services.document_service import (
    create_document,
    delete_document,
    get_all_documents,
    get_document_by_id,
)

ns = Namespace("documents", description="Gestão de documentos")

document_input = ns.model(
    "DocumentInput",
    {
        "title": fields.String(
            required=True,
            description="Título do documento",
            example="Introdução ao pgai",
        ),
        "content": fields.String(
            required=True,
            description="Conteúdo textual do documento",
            example=(
                "pgai é uma biblioteca Python que transforma "
                "PostgreSQL em um motor de busca vetorial."
            ),
        ),
        "metadata": fields.Raw(
            description="Dados adicionais em JSON",
            default={},
            example={"autor": "Leandro", "categoria": "tecnologia"},
        ),
    },
)

document_output = ns.model(
    "DocumentOutput",
    {
        "id": fields.Integer(description="ID do documento"),
        "title": fields.String(description="Título"),
        "content": fields.String(description="Conteúdo"),
        "metadata": fields.Raw(description="Metadata JSON"),
    },
)


@ns.route("/")
class DocumentList(Resource):
    @ns.marshal_list_with(document_output)
    def get(self):
        return get_all_documents()

    @ns.expect(document_input, validate=True)
    @ns.marshal_with(document_output, code=201)
    def post(self):
        data = ns.payload
        doc = create_document(
            title=data["title"],
            content=data["content"],
            metadata=data.get("metadata", {}),
        )
        return doc, 201


@ns.route("/<int:doc_id>")
@ns.param("doc_id", "ID do documento")
class DocumentDetail(Resource):
    @ns.marshal_with(document_output)
    @ns.response(404, "Documento não encontrado")
    def get(self, doc_id: int):
        doc = get_document_by_id(doc_id)
        if not doc:
            ns.abort(404, "Documento não encontrado")
        return doc

    @ns.response(204, "Documento removido")
    @ns.response(404, "Documento não encontrado")
    def delete(self, doc_id: int):
        deleted = delete_document(doc_id)
        if not deleted:
            ns.abort(404, "Documento não encontrado")
        return "", 204
