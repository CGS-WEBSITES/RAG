"""Resource de sistema.

Endpoints para setup inicial (criar tabela e vectorizer),
carga de dados de exemplo (Wikipedia) e monitoramento.
"""

import logging

import requests as req
from flask_restx import Namespace, Resource, fields

from api.config import Config
from api.database import get_cursor

logger = logging.getLogger(__name__)

ns = Namespace("system", description="Setup e monitoramento do sistema")

# ──────────────────────────────────────────────────
# Models Swagger
# ──────────────────────────────────────────────────

setup_response = ns.model(
    "SetupResponse",
    {
        "message": fields.String(description="Resultado do setup"),
        "table_created": fields.Boolean(description="Tabela foi criada/já existia"),
        "vectorizer_created": fields.Boolean(
            description="Vectorizer foi criado/já existia"
        ),
    },
)

seed_response = ns.model(
    "SeedResponse",
    {
        "message": fields.String(description="Resultado da carga"),
        "articles_inserted": fields.Integer(description="Número de artigos inseridos"),
    },
)

vectorizer_status_model = ns.model(
    "VectorizerStatus",
    {
        "id": fields.Integer(description="ID do vectorizer"),
        "source_table": fields.String(description="Tabela fonte"),
        "target_table": fields.String(description="Tabela de embeddings"),
        "pending_items": fields.Integer(description="Itens aguardando embedding"),
    },
)

health_model = ns.model(
    "Health",
    {
        "database": fields.String(description="Status do banco de dados"),
        "ollama": fields.String(description="Status do Ollama"),
    },
)


# ──────────────────────────────────────────────────
# Artigos da Wikipedia para seed
# ──────────────────────────────────────────────────

WIKI_ARTICLES = [
    # --- Batch 1: AI e Banco de Dados ---
    {
        "url": "https://en.wikipedia.org/wiki/PostgreSQL",
        "title": "PostgreSQL",
        "content": (
            "PostgreSQL, also known as Postgres, is a free and open-source "
            "relational database management system (RDBMS) emphasizing "
            "extensibility and SQL compliance. PostgreSQL features transactions "
            "with atomicity, consistency, isolation, durability (ACID) "
            "properties, automatically updatable views, materialized views, "
            "triggers, foreign keys, and stored procedures. It is designed to "
            "handle a range of workloads, from single machines to data "
            "warehouses or web services with many concurrent users. It is the "
            "default database for macOS Server and is also available for "
            "Linux, FreeBSD, OpenBSD, and Windows."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "title": "Artificial intelligence",
        "content": (
            "Artificial intelligence (AI) is the intelligence of machines or "
            "software, as opposed to the intelligence of humans or animals. "
            "It is a field of study in computer science that develops and "
            "studies intelligent machines. Such machines may be called AIs. "
            "AI technology is widely used throughout industry, government, "
            "and science. Some high-profile applications are advanced web "
            "search engines, recommendation systems, interacting via human "
            "speech, self-driving cars, generative and creative tools, and "
            "superhuman play and analysis in strategy games."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Machine_learning",
        "title": "Machine learning",
        "content": (
            "Machine learning (ML) is a field of study in artificial "
            "intelligence concerned with the development and study of "
            "statistical algorithms that can learn from data and generalize "
            "to unseen data, and thus perform tasks without explicit "
            "instructions. Recently, generative artificial neural networks "
            "have been able to surpass many previous approaches in performance. "
            "Machine learning approaches have been applied to many fields "
            "including natural language processing, computer vision, speech "
            "recognition, email filtering, agriculture, and medicine."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Natural_language_processing",
        "title": "Natural language processing",
        "content": (
            "Natural language processing (NLP) is an interdisciplinary "
            "subfield of computer science and artificial intelligence. It is "
            "primarily concerned with providing computers with the ability to "
            "process data encoded in natural language and is thus closely "
            "related to information retrieval, knowledge representation, and "
            "computational linguistics. Typical NLP tasks include text "
            "classification, named entity recognition, sentiment analysis, "
            "machine translation, question answering, and summarization."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Vector_database",
        "title": "Vector database",
        "content": (
            "A vector database is a type of database that stores data as "
            "high-dimensional vectors, which are mathematical representations "
            "of features or attributes. Each vector has a certain number of "
            "dimensions, which can range from tens to thousands, depending on "
            "the complexity of the data being represented. Vector databases "
            "are used in similarity search, recommendation systems, and "
            "anomaly detection. They use distance metrics like cosine "
            "similarity, Euclidean distance, or dot product to find the most "
            "similar vectors to a given query vector."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)",
        "title": "Transformer (deep learning)",
        "content": (
            "A transformer is a deep learning architecture developed by "
            "researchers at Google and based on the multi-head attention "
            "mechanism, proposed in the 2017 paper 'Attention Is All You "
            "Need'. Text is converted to numerical representations called "
            "tokens, and each token is converted into a vector via looking up "
            "from a word embedding table. At each layer, each token is then "
            "contextualized within the scope of the context window with other "
            "tokens via a parallel multi-head attention mechanism. "
            "Transformers have the advantage of having no recurrent units, "
            "and therefore require less training time than earlier recurrent "
            "neural architectures."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Large_language_model",
        "title": "Large language model",
        "content": (
            "A large language model (LLM) is a computational model notable "
            "for its ability to achieve general-purpose language generation "
            "and other natural language processing tasks such as "
            "classification. LLMs acquire these abilities by learning "
            "statistical relationships from vast amounts of text during a "
            "computationally intensive self-supervised and semi-supervised "
            "training process. LLMs can be used for text generation, a form "
            "of generative AI, by taking an input text and repeatedly "
            "predicting the next token or word. Notable examples include "
            "OpenAI's GPT models, Meta's LLaMA models, and Google's Gemini."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
        "title": "Retrieval-augmented generation",
        "content": (
            "Retrieval-augmented generation (RAG) is a technique that "
            "combines information retrieval with text generation models to "
            "produce more accurate and contextually relevant responses. In "
            "RAG, when a query is received, the system first retrieves "
            "relevant documents or passages from a knowledge base, then uses "
            "these retrieved texts as additional context for the language "
            "model to generate its response. This approach helps reduce "
            "hallucinations, keeps responses grounded in factual information, "
            "and allows the model to access knowledge beyond its training "
            "data without expensive retraining."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Semantic_search",
        "title": "Semantic search",
        "content": (
            "Semantic search denotes search with meaning, as distinguished "
            "from lexical search where the search engine looks for literal "
            "matches of the query words. Semantic search seeks to improve "
            "search accuracy by understanding the searcher's intent and the "
            "contextual meaning of terms as they appear in the searchable "
            "dataspace. Semantic search uses vector embeddings to represent "
            "both queries and documents in a high-dimensional space where "
            "semantically similar items are positioned close together. "
            "Technologies like pgvector enable semantic search directly "
            "within PostgreSQL databases."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Word_embedding",
        "title": "Word embedding",
        "content": (
            "In natural language processing, a word embedding is a "
            "representation of a word. The embedding is used in text analysis. "
            "Typically, the representation is a real-valued vector that "
            "encodes the meaning of the word in such a way that the words "
            "that are closer in the vector space are expected to be similar "
            "in meaning. Word embeddings can be obtained using language "
            "modeling and feature learning techniques, where words or phrases "
            "from the vocabulary are mapped to vectors of real numbers. "
            "Methods to generate this mapping include neural networks, "
            "dimensionality reduction, and probabilistic models."
        ),
    },
    # --- Batch 2: Mais temas ---
    {
        "url": "https://en.wikipedia.org/wiki/Deep_learning",
        "title": "Deep learning",
        "content": (
            "Deep learning is a subset of machine learning that uses "
            "artificial neural networks with multiple layers to model and "
            "understand complex patterns in data. Deep learning architectures "
            "such as deep neural networks, recurrent neural networks, "
            "convolutional neural networks, and transformers have been applied "
            "to fields including computer vision, speech recognition, natural "
            "language processing, machine translation, bioinformatics, drug "
            "design, medical image analysis, and board game programs, where "
            "they have produced results comparable to and sometimes surpassing "
            "human expert performance."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Neural_network_(machine_learning)",
        "title": "Neural network",
        "content": (
            "In machine learning, a neural network is a model inspired by "
            "the structure and function of biological neural networks in "
            "animal brains. A neural network consists of connected units or "
            "nodes called artificial neurons, which loosely model the neurons "
            "in the brain. These are connected by edges, which model the "
            "synapses. Each artificial neuron receives signals from connected "
            "neurons, then processes them and sends a signal to other "
            "connected neurons. The signal at each connection is a real "
            "number, and the output of each neuron is computed by some "
            "non-linear function of the sum of its inputs."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Computer_vision",
        "title": "Computer vision",
        "content": (
            "Computer vision is an interdisciplinary scientific field that "
            "deals with how computers can gain high-level understanding from "
            "digital images or videos. From the perspective of engineering, "
            "it seeks to understand and automate tasks that the human visual "
            "system can do. Computer vision tasks include methods for "
            "acquiring, processing, analyzing and understanding digital "
            "images, and extraction of high-dimensional data from the real "
            "world in order to produce numerical or symbolic information. "
            "Applications include autonomous vehicles, medical imaging, "
            "surveillance, and augmented reality."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Chatbot",
        "title": "Chatbot",
        "content": (
            "A chatbot is a software application or web interface that is "
            "designed to mimic human conversation through text or voice "
            "interactions. Modern chatbots are typically online and use "
            "generative artificial intelligence systems that are capable of "
            "maintaining a conversation with a user in natural language and "
            "simulating the way a human would behave as a conversational "
            "partner. Chatbots are used in customer service, information "
            "acquisition, education, healthcare, and entertainment. Recent "
            "advances in large language models have significantly improved "
            "chatbot capabilities."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Data_science",
        "title": "Data science",
        "content": (
            "Data science is an interdisciplinary academic field that uses "
            "statistics, scientific computing, scientific methods, processes, "
            "algorithms and systems to extract or extrapolate knowledge and "
            "insights from potentially noisy, structured, or unstructured "
            "data. Data science also integrates domain knowledge from the "
            "underlying application domain. Data science is multifaceted and "
            "can be described as a science, a research paradigm, a research "
            "method, a discipline, a workflow, and a profession. It employs "
            "techniques from mathematics, statistics, computer science, and "
            "information science."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "title": "Python (programming language)",
        "content": (
            "Python is a high-level, general-purpose programming language. "
            "Its design philosophy emphasizes code readability with the use "
            "of significant indentation. Python is dynamically typed and "
            "garbage-collected. It supports multiple programming paradigms, "
            "including structured, object-oriented and functional programming. "
            "Python is commonly used for web development, data analysis, "
            "artificial intelligence, machine learning, automation, and "
            "scientific computing. Popular frameworks include Django, Flask, "
            "NumPy, pandas, TensorFlow, and PyTorch."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/API",
        "title": "API",
        "content": (
            "An application programming interface (API) is a way for two or "
            "more computer programs or components to communicate with each "
            "other. It is a type of software interface, offering a service to "
            "other pieces of software. An API specification describes how to "
            "build or use such a connection or interface. APIs are used to "
            "integrate different software systems, enable communication "
            "between services in microservice architectures, and provide "
            "access to web services. REST APIs use HTTP requests to perform "
            "CRUD operations and are widely used in modern web development."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Cloud_computing",
        "title": "Cloud computing",
        "content": (
            "Cloud computing is the on-demand availability of computer system "
            "resources, especially data storage and computing power, without "
            "direct active management by the user. Large clouds often have "
            "functions distributed over multiple locations, each of which is "
            "a data center. Cloud computing relies on sharing of resources to "
            "achieve coherence and typically uses a pay-as-you-go model, "
            "which can help in reducing capital expenses. Major cloud "
            "providers include Amazon Web Services (AWS), Microsoft Azure, "
            "and Google Cloud Platform (GCP)."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Docker_(software)",
        "title": "Docker (software)",
        "content": (
            "Docker is a set of platform as a service (PaaS) products that "
            "use OS-level virtualization to deliver software in packages "
            "called containers. Containers are isolated from one another and "
            "bundle their own software, libraries and configuration files; "
            "they can communicate with each other through well-defined "
            "channels. Docker containers are lightweight compared to virtual "
            "machines because they share the host OS kernel. Docker is used "
            "for deploying applications, microservices architecture, CI/CD "
            "pipelines, and development environments."
        ),
    },
    {
        "url": "https://en.wikipedia.org/wiki/Prompt_engineering",
        "title": "Prompt engineering",
        "content": (
            "Prompt engineering is the process of structuring an instruction "
            "that can be interpreted and understood by a generative AI model. "
            "A prompt is natural language text describing the task that an AI "
            "should perform. In the context of large language models, prompt "
            "engineering involves crafting inputs that guide the model to "
            "produce desired outputs. Techniques include zero-shot prompting, "
            "few-shot prompting, chain-of-thought prompting, and retrieval-"
            "augmented generation. Effective prompt engineering can "
            "significantly improve the quality of AI-generated responses "
            "without modifying the underlying model."
        ),
    },
]


# ──────────────────────────────────────────────────
# Resources
# ──────────────────────────────────────────────────


@ns.route("/setup")
class Setup(Resource):
    """Setup inicial do sistema."""

    @ns.marshal_with(setup_response)
    def post(self):
        """Cria a tabela de documentos e o vectorizer.

        - Cria a tabela 'documents' se não existir
        - Cria o vectorizer que configura o pgai para gerar
          embeddings automaticamente usando nomic-embed-text
        - O vectorizer worker começa a processar automaticamente
        """
        table_created = False
        vectorizer_created = False

        with get_cursor() as cur:
            # Criar tabela de documentos
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{}'::jsonb
                )
            """
            )
            table_created = True
            logger.info("Tabela 'documents' verificada/criada")

            # Criar vectorizer (pgai 0.12.1)
            try:
                cur.execute(
                    """
                    SELECT ai.create_vectorizer(
                        'documents'::regclass,
                        if_not_exists => true,
                        loading => ai.loading_column('content'),
                        destination => ai.destination_table(
                            target_table => 'documents_embeddings_store'
                        ),
                        embedding => ai.embedding_ollama(%s, %s),
                        chunking => ai.chunking_recursive_character_text_splitter(
                            chunk_size => 512,
                            chunk_overlap => 50
                        ),
                        formatting => ai.formatting_python_template(
                            '$title: $chunk'
                        )
                    )
                    """,
                    (Config.EMBEDDING_MODEL, Config.EMBEDDING_DIMENSIONS),
                )
                vectorizer_created = True
                logger.info("Vectorizer criado/verificado com sucesso")
            except Exception as e:
                error_msg = str(e)
                if "already exists" in error_msg.lower():
                    vectorizer_created = True
                    logger.info("Vectorizer já existia")
                else:
                    logger.error("Erro ao criar vectorizer: %s", e)
                    ns.abort(500, f"Erro ao criar vectorizer: {error_msg}")

        return {
            "message": "Setup concluído com sucesso",
            "table_created": table_created,
            "vectorizer_created": vectorizer_created,
        }


@ns.route("/seed")
class Seed(Resource):
    """Carga de artigos de exemplo da Wikipedia."""

    @ns.marshal_with(seed_response)
    def post(self):
        """Carrega artigos da Wikipedia como dados de exemplo.

        Insere 20 artigos sobre temas de IA, banco de dados, NLP,
        programação e cloud. O vectorizer worker gera os embeddings
        automaticamente. Após inserir, aguarde pending_items chegar
        a 0 no endpoint /api/system/vectorizer/status.
        """
        inserted = 0

        with get_cursor() as cur:
            # Verificar se a tabela existe
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'documents'
                )
            """
            )
            if not cur.fetchone()["exists"]:
                ns.abort(
                    400,
                    "Tabela 'documents' não existe. "
                    "Execute POST /api/system/setup primeiro.",
                )

            for article in WIKI_ARTICLES:
                # Evitar duplicatas pelo título
                cur.execute(
                    "SELECT id FROM documents WHERE title = %s",
                    (article["title"],),
                )
                if cur.fetchone():
                    logger.info(
                        "Artigo '%s' já existe, pulando",
                        article["title"],
                    )
                    continue

                cur.execute(
                    """
                    INSERT INTO documents (title, content, metadata)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        article["title"],
                        article["content"],
                        '{"source": "wikipedia", "url": "' + article["url"] + '"}',
                    ),
                )
                inserted += 1
                logger.info("Artigo inserido: %s", article["title"])

        return {
            "message": (
                f"{inserted} artigos inseridos com sucesso. "
                "O vectorizer worker gerará os embeddings automaticamente. "
                "Verifique o status em GET /api/system/vectorizer/status."
            ),
            "articles_inserted": inserted,
        }


@ns.route("/vectorizer/status")
class VectorizerStatus(Resource):
    """Status do vectorizer."""

    @ns.marshal_list_with(vectorizer_status_model)
    def get(self):
        """Retorna o status dos vectorizers.

        Mostra quantos itens estão pendentes de embedding.
        Quando pending_items = 0, todos os embeddings foram gerados.
        """
        try:
            with get_cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        s.id,
                        s.source_table::text,
                        s.target_table::text,
                        COALESCE(s.pending_items, 0) AS pending_items
                    FROM ai.vectorizer_status s
                    ORDER BY s.id
                """
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error("Erro ao consultar status: %s", e)
            ns.abort(
                500,
                f"Erro ao consultar status do vectorizer: {str(e)}",
            )


@ns.route("/health")
class Health(Resource):
    """Verificação de saúde do sistema."""

    @ns.marshal_with(health_model)
    def get(self):
        """Verifica a conectividade com o banco e o Ollama."""
        result = {}

        # Verificar banco
        try:
            with get_cursor() as cur:
                cur.execute("SELECT 1")
            result["database"] = "ok"
        except Exception:
            result["database"] = "erro"

        # Verificar Ollama
        try:
            resp = req.get(f"{Config.OLLAMA_HOST}/api/tags", timeout=5)
            resp.raise_for_status()
            result["ollama"] = "ok"
        except Exception:
            result["ollama"] = "erro"

        return result
