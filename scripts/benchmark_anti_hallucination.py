import requests
import json
import time

test_suite = [
    {
        "id": 1,
        "name": "O Paradoxo dos Fragmentos da Escuridão",
        "question": "Uma carta de Runa manda colocar um Darkness Tile no mapa para perseguir o Herói Mais Forte. Porém, a peça não cabe e é dividida em 3 tiles pequenos. O primeiro tile pequeno colocado já alcança o Herói Mais Forte. O que acontece com os 2 tiles pequenos restantes? Os heróis sofrem dano de Crush se as peças restantes não puderem ser colocadas?"
    },
    {
        "id": 2,
        "name": "Exaustão Forçada (Unwilling Recall)",
        "question": "É o turno da Heroína Lorelai e ela gasta seu último Action Cube para ganhar movimento extra. Em seguida ela pisa em uma armadilha e precisa usar uma Reação, mas está sem cubos. Ela faz um Unwilling Recall Action. Isso encerra o turno dela imediatamente?"
    },
    {
        "id": 3,
        "name": "Atualização de Regras - Apocalypse / Awakenings (Ações Menores e Troca de Itens)",
        "question": "Nas atualizações das expansões (Apocalypse / Awakenings), quais foram as duas grandes mudanças em relação à quantidade de Ações Menores que um herói pode fazer por turno, e como passou a funcionar a troca de itens (Exchange Items) entre os heróis?"
    },
    {
        "id": 4,
        "name": "Reação contra Dano Zero",
        "question": "Um Monstro ataca um Herói causando 3 de dano. O Herói possui 4 tokens de Shield, reduzindo o dano do ataque a zero. Como não vai sofrer perda de vida, o herói ainda pode usar uma habilidade de Reação?"
    },
    {
        "id": 5,
        "name": "O Paradoxo da Capivara (Polymorph)",
        "question": "O Mago do grupo sofreu a condição Polymorph e virou uma Capivara. No turno seguinte, o Monstro aplica Polymorph no Patrulheiro. Podem existir dois heróis sob o efeito de Polymorph ao mesmo tempo?"
    },
    {
        "id": 6,
        "name": "A Prioridade dos Pets",
        "question": "Um monstro com a habilidade CLEAVE 2 (que permite atacar múltiplos alvos) tem o Herói Mais Forte como seu Alvo Primário. Ele pode escolher entre: Opção A) Atacar o Herói Mais Forte e o Herói Mais Fraco; ou Opção B) Atacar o Herói Mais Forte e o Pet do grupo. Qual opção o monstro escolhe?"
    },
    {
        "id": 7,
        "name": "A Imunidade de Wermunggdir",
        "question": "Na aventura 'The Charge of Several Peoples', o herói usa um Spell Attack focado em PUSH (Empurrar) para jogar Wermunggdir na lava. Isso funciona?"
    },
    {
        "id": 8,
        "name": "O Nocaute e as Maldições",
        "question": "Um Herói é Nocauteado (Knocked Out), deitado no chão, sofre 1 Trauma Cube e realiza um Free Recall Action para recuperar os cubos. Ele ganha um Curse Cube de penalidade por esse Recall?"
    },
    {
        "id": 9,
        "name": "Dano Indefensável (Non-Preventable) vs Reações",
        "question": "Um herói entra em um terreno de Escuridão e vai sofrer 2 de dano. Ele tem uma habilidade de Reação com o ícone de raio que diz 'PREVENT 3'. Ele pode usá-la para evitar o dano da Escuridão?"
    }
]

print("Running 9-Question Anti-Hallucination Benchmark against Live RAG API...")
print("=" * 80)

results = []
for test in test_suite:
    payload = {
        "question": test["question"],
        "project": "Drunagor",
        "language": "pt"
    }
    start_t = time.time()
    try:
        res = requests.post("http://3.23.4.11:5001/api/rag/tickets", json=payload, timeout=30)
        elapsed = round(time.time() - start_t, 2)
        if res.status_code == 200:
            data = res.json()
            ans = data.get("answer", "")
            manual_src = [m.get("title") for m in data.get("sources", {}).get("manual", [])]
            kw_src = [k.get("title") for k in data.get("sources", {}).get("keywords", [])]
            results.append({
                "id": test["id"],
                "name": test["name"],
                "question": test["question"],
                "answer": ans,
                "manual_sources": manual_src,
                "keyword_sources": kw_src,
                "latency_sec": elapsed
            })
            print(f"[SUCCESS] Q{test['id']}: {test['name']} ({elapsed}s)")
        else:
            print(f"[ERROR] Q{test['id']} HTTP {res.status_code}")
    except Exception as e:
        print(f"[ERROR] Q{test['id']} Exception: {e}")

print("=" * 80)
print(json.dumps(results, indent=2, ensure_ascii=False))
