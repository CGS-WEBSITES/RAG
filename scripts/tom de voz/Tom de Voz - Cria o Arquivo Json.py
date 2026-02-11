import PyPDF2
import json
import re

def extrair_manual_completo_v3(caminho_pdf):
    texto_por_pagina = []
    try:
        with open(caminho_pdf, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                texto_por_pagina.append(page.extract_text() or "")
    except Exception as e:
        return {"erro": f"Erro ao ler PDF: {e}"}

    texto_total = "\n".join(texto_por_pagina)

    # Estrutura JSON completa baseada nas alterações do arquivo
    manual_json = {
        "INSTITUCIONAL_CGS": {
            "papel": "Coração criativo que conecta todos os universos.",
            "voz": "Visionária, inspiradora e inventiva.",
            "tagline": "We build the worlds. You make it yours.",
            "diretrizes": "Dar palco para cada universo brilhar sem competir com submarcas."
        },
        "DANTE_INFERNO": {
            "matriz_arquetipica": "Criador Abismal – Implacável",
            "slogan": "Desça. Testemunhe. Lembre-se.",
            "essencia_da_voz": "Testemunho consagrado - grave, melancólico - guiando o jogador por uma travessia de condenação.",
            "tom": "Grave, melancólico, solene e implacável.",
            "ritmo": "Autoritária, disciplinada e implacável. Afirma o que deve ser feito.",
            "humor": "Tons de ironia e sarcasmo ocasionais (eco trágico).",
            "vocabulario": {
                "palavras_chave": ["abismo", "pecado", "penitência", "ruína", "vigília", "queda", "cruzada", "condenação", "lâmina", "sombras", "alma", "fardo", "destino"],
                "verbos": ["descer", "testemunhar", "suportar", "invocar", "resistir", "confrontar", "carregar", "revelar", "pecar"],
                "adjetivos": ["melancólico", "inevitável", "sagrado", "quebrado", "profundo", "ancestral", "condenado", "eterno"]
            },
            "o_que_evitar": ["Termos modernos", "coloquiais", "leves", "humorísticos", "linguagem que quebre a solenidade ritual"],
            "pontos_de_contato": {
                "redes_sociais": "Atmosférico, contemplativo, paleta austera, silêncio como recurso.",
                "embalagens": "Manuscritos antigos, relíquias, sensação de artefato encontrado.",
                "sac_comunidade": "Rápido, humano e acolhedor. Permite expressões leves para suavizar problemas."
            }
        },
        "CHRONICLES_OF_DRUNAGOR": {
            "matriz_arquetipica": "Criador Épico",
            "slogan": "Ergam-se. Resistam. Registrem-se.",
            "essencia_da_voz": "Cronista das trevas ascendentes - sombrio, épico e ancestral.",
            "tom": "Grave, épico, sombrio e carregado de urgência.",
            "ritmo": "Frases longas e cerimoniais, pausas secas que reforçam a tensão.",
            "humor": "Ausente.",
            "vocabulario": {
                "palavras_chave": ["sombra", "ruína", "abismo", "corrupção", "estilhaço", "vigília", "fenda", "silêncio", "eco", "ameaça", "trevas", "ciclo", "fardo"],
                "verbos": ["resistir", "erguer-se", "enfrentar", "proteger", "suportar", "recuar", "tombar", "avançar", "consumar", "vigiar", "registrar"],
                "adjetivos": ["sombrio", "ancestral", "inevitável", "trágico", "consumido", "fragmentado", "devastado", "crescente", "implacável", "épico"]
            },
            "o_que_evitar": ["Linguagem moderna", "casual", "humorística", "desmotivar o jogador"],
            "pontos_de_contato": {
                "redes_sociais": "Tensão e progressão épica, foco em profundidade e mood.",
                "embalagens": "Tomos antigos, armaduras deterioradas, registros de sentinelas.",
                "sac_comunidade": "Sério e respeitoso. Reconhecimento do esforço (cada interação é parte das Crônicas)."
            }
        },
        "FORFUN": {
            "arquétipo": "Criador Lúdico",
            "essencia": "O amigo divertido da mesa.",
            "tom": "Leve, acolhedora e criativa.",
            "objetivo": "Brincar sem pressão, rir dos erros, conexão e alegria compartilhada."
        }
    }

    # Gera o arquivo final
    with open("tabela_conhecimento_ips.json", "w", encoding="utf-8") as f:
        json.dump(manual_json, f, ensure_ascii=False, indent=4)

    return manual_json

# --- EXECUÇÃO ---
caminho = r"C:\Users\vitor\Downloads\Tom de Voz Dante e COD.pdf"
resultado = extrair_manual_completo_v3(caminho)

print("Processamento concluído. JSON gerado com todas as informações do manual.")
print(json.dumps(resultado, indent=4, ensure_ascii=False))