# Ganhos de FinOps do mydata a partir das leituras datadas de `railway usage`.
# Uso: python3 scripts/finops-ganhos.py. Acrescente uma leitura em L e rode de novo.
# Ritmo = diferença entre leituras dividida pelo tempo, nunca o total acumulado:
# o período 14/10–14/11 mistura dias de antes e de depois do F1.

from datetime import datetime, timedelta, timezone
BRT = timezone(timedelta(hours=-3)); UTC = timezone.utc
M = 30.4  # dias por mês
# (instante, projeto, postgres_memoria) — leituras de `railway usage projects`, período 14/10–14/11
ini = datetime(2026,10,14,0,0,tzinfo=UTC)
L = [
 ("início período", ini, 0.00, 0.00),
 ("01/11 (doc, 18,6 d)", ini+timedelta(days=18.6), 12.71, 10.30),
 ("04/11 08:12 BRT", datetime(2026,11,4,8,12,tzinfo=BRT), 13.81, 11.09),
 ("05/11 08:13 BRT", datetime(2026,11,5,8,13,tzinfo=BRT), 14.11, 11.29),
 ("06/11 08:14 BRT", datetime(2026,11,6,8,14,tzinfo=BRT), 14.47, 11.52),
 ("07/11 08:14 BRT", datetime(2026,11,7,8,14,tzinfo=BRT), 14.83, 11.76),
 ("08/11 08:17 BRT", datetime(2026,11,8,8,17,tzinfo=BRT), 15.26, 12.08),
 ("10/11 20:39 BRT", datetime(2026,11,10,20,39,tzinfo=BRT), 16.19, 12.71),
]
def taxa(a,b):
    d=(L[b][1]-L[a][1]).total_seconds()/86400
    return d,(L[b][2]-L[a][2])/d,(L[b][3]-L[a][3])/d
print("trecho | dias | projeto $/dia ($/mês) | memória PG $/dia ($/mês) | GB médio implícito")
for a,b in [(0,1),(1,2),(2,6),(6,7),(2,7)]:
    d,p,m=taxa(a,b)
    print(f"{L[a][0]} → {L[b][0]} | {d:.2f} | {p:.3f} ({p*M:.2f}) | {m:.3f} ({m*M:.2f}) | {m*M/10:.2f}")
_,p_pre,m_pre=taxa(0,1); _,p_pos,m_pos=taxa(2,7)
print(f"\nganho F1+CPU vs ritmo pré-F1: projeto {(p_pre-p_pos)*M:.2f} $/mês ({(1-p_pos/p_pre)*100:.0f}%), memória PG {(m_pre-m_pos)*M:.2f} $/mês")
print(f"vs fatura fechada 14/09–14/10 ($25,78): {25.78-p_pos*M:.2f} $/mês ({(1-p_pos*M/25.78)*100:.0f}%)")
# F2: upside real = metade do GB médio pago hoje, se o cache encher 500 MB
gb_pos=m_pos*M/10
print(f"\nF2 (500 MB): memória paga hoje ~{gb_pos:.2f} GB médio; a 0,5 GB cheio → economia {(gb_pos-0.5)*10:.2f} $/mês")
# próxima fatura limpa (14/11–14/12) ao ritmo pós-F1
print(f"projeção 14/11–14/12 ao ritmo pós-F1: projeto {p_pos*M:.2f} $/mês")
print("cruzamento: railway metrics 7d médio = 0,819 GB → memória prevista 8,19 $/mês")
