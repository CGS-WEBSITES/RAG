import json
import psycopg2
from sentence_transformers import SentenceTransformer

# --- CONFIGURAÇÕES ---
CAMINHO_JSON = r"C:\Users\vitor\Downloads\tabela_conhecimento_ips.json"
DOCKER_DB_CONFIG = {
    "host": "localhost",
    "database": "postgres",
    "user": "postgres",
    "password": "Vitorio3235",
    "port": "5432"
}

def main():
    print("Lendo diretrizes de IPs...")
    with open(CAMINHO_JSON, 'r', encoding='utf-8') as f:
        dados = json.load(f)

    conn = psycopg2.connect(**DOCKER_DB_CONFIG)
    cur = conn.cursor()
    model = SentenceTransformer('all-MiniLM-L6-v2')

    for ip_nome, info in dados.items():
        print(f"Processando diretrizes para: {ip_nome}")

        # Vamos transformar cada parte do JSON em um bloco de conhecimento
        for categoria, valor in info.items():
            # Tratamento especial para o dicionário de vocabulário
            if isinstance(valor, dict):
                for sub_cat, lista in valor.items():
                    texto_conhecimento = f"IP: {ip_nome} | {categoria} ({sub_cat}): {', '.join(lista)}"
                    armazenar(cur, model, ip_nome, f"{categoria}_{sub_cat}", texto_conhecimento)

            # Tratamento para listas (como 'o_que_evitar')
            elif isinstance(valor, list):
                texto_conhecimento = f"IP: {ip_nome} | {categoria}: {', '.join(valor)}"
                armazenar(cur, model, ip_nome, categoria, texto_conhecimento)

            # Texto simples
            else:
                texto_conhecimento = f"IP: {ip_nome} | {categoria}: {valor}"
                armazenar(cur, model, ip_nome, categoria, texto_conhecimento)

    conn.commit()
    print("-" * 30)
    print("SUCESSO! As diretrizes de tom de voz e IPs foram indexadas.")
    cur.close()
    conn.close()

def armazenar(cur, model, ip, cat, texto):
    vetor = model.encode(texto).tolist()
    cur.execute("""
        INSERT INTO conhecimento_ips (ip_nome, categoria, conteudo, embedding)
        VALUES (%s, %s, %s, %s)
    """, (ip, cat, texto, vetor))

if __name__ == "__main__":
    main()