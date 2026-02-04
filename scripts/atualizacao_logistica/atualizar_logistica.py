import pandas as pd
import psycopg2
from sentence_transformers import SentenceTransformer

# colocar o caminho do arquivo csv pra rodar
CAMINHO_CSV = r"C:\Users\vitor\Downloads\Status Shipping.csv"
DOCKER_DB_CONFIG = {
    "host": "localhost",
    "database": "postgres",
    "user": "postgres",
    "password": "postgres",
    "port": "5432"
}

def converter_data(data_str):
    try:
        return pd.to_datetime(data_str, dayfirst=True).date()
    except:
        return None

def main():
    print("Lendo planilha de logística...")
    df = pd.read_csv(CAMINHO_CSV, sep=';')

    conn = psycopg2.connect(**DOCKER_DB_CONFIG)
    cur = conn.cursor()
    model = SentenceTransformer('all-MiniLM-L6-v2')

    print(f"Processando {len(df)} atualizações de logística...")

    for _, row in df.iterrows():
        # Criamos o contexto para a IA (o que ela vai usar para responder perguntas)
        texto_ia = (f"Projeto: {row['PROJETO']} | Região: {row['REGIAO']} | "
                    f"Status: {row['STATUS_ATUAL']} | Previsão: {row['CONCLUSAO_ESTIMADA']} | "
                    f"Nota: {row['OBSERVACOES_BACKER']}")

        vetor = model.encode(texto_ia).tolist()
        data_formatada = converter_data(row['DATA_RELATORIO'])

        cur.execute("""
                    INSERT INTO logistica_status (id_update, data_relatorio, projeto, regiao, parceiro_logistico,
                                                  status_atual, eta_warehouse, inicio_envios, conclusao_estimada,
                                                  ocorrencias, links_visuais, observacoes_backer, descricao, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id_update) DO
                    UPDATE SET
                        status_atual = EXCLUDED.status_atual,
                        conclusao_estimada = EXCLUDED.conclusao_estimada,
                        observacoes_backer = EXCLUDED.observacoes_backer,
                        embedding = EXCLUDED.embedding;
                    """, (
                        row['ID_UPDATE'], data_formatada, row['PROJETO'], row['REGIAO'], row['PARCEIRO_LOGISTICO'],
                        row['STATUS_ATUAL'], row['ETA_WAREHOUSE'], row['INICIO_ENVIOS'], row['CONCLUSAO_ESTIMADA'],
                        row['OCORRENCIAS'], row['LINKS_VISUAIS'], row['OBSERVACOES_BACKER'], row['DESCRIÇÃO'], vetor
                    ))

    conn.commit()
    print("-" * 30)
    print("SUCESSO! Sua planilha de logística foi integrada ao cérebro da IA.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()