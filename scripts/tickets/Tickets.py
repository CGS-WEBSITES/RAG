import json
import psycopg2
from sentence_transformers import SentenceTransformer

CAMINHO_JSON = r"C:\Users\vitor\Downloads\todos_os_tickets_consolidado.json"
DOCKER_DB_CONFIG = {
    "host": "localhost",
    "database": "postgres",
    "user": "postgres",
    "password": "postgres",
    "port": "5432"
}

def main():
    print("Lendo o arquivo consolidado...")
    try:
        with open(CAMINHO_JSON, 'r', encoding='utf-8') as f:
            dados = json.load(f)
    except Exception as e:
        print(f"Erro ao abrir JSON: {e}")
        return

    conn = psycopg2.connect(**DOCKER_DB_CONFIG)
    cur = conn.cursor()
    model = SentenceTransformer('all-MiniLM-L6-v2')

    total = len(dados)
    print(f"Iniciando integração de {total} tickets...")

    # acompanha o progresso
    for i, item in enumerate(dados, 1):
        id_ticket = item.get('id')
        pergunta = item.get('texto_original', '')
        resposta = "\n---\n".join(item.get('respostas', []))

        # Gerando o conhecimento para a IA
        texto_para_ia = f"PERGUNTA: {pergunta} | RESPOSTA: {resposta}"
        vetor = model.encode(texto_para_ia).tolist()

        try:
            cur.execute("""
                        INSERT INTO tickets (id_original, pergunta, resposta, projeto, embedding)
                        VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id_original) DO NOTHING
                        """, (id_ticket, pergunta, resposta, "Dante/Drunagor", vetor))

            # Imprime o progresso a cada 100 tickets
            if i % 100 == 0:
                conn.commit()  # Salva o lote atual no banco
                print(f"Progresso: {i}/{total} tickets processados ({(i / total) * 100:.2f}%)")

        except Exception as e:
            print(f"Erro no ticket {id_ticket}: {e}")

    conn.commit()
    print("-" * 30)
    print(f"SUCESSO! {total} tickets únicos foram processados e indexados.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()