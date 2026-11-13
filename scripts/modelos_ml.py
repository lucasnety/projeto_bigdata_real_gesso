#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modelos_ml.py

Machine Learning do sistema Real Gesso. É o PASSO 4 do pipeline de dados:

    gerador_dados.py --> tratar_dados.R --> carregar_dados.py --> modelos_ml.py
                                                                  (este script)

Lê os dados JÁ TRATADOS direto do PostgreSQL e treina dois modelos:

  1) SEGMENTAÇÃO DE CLIENTES (aprendizado não supervisionado, K-Means)
     Cada cliente vira três números (RFM):
       recência   = dias desde o último serviço
       frequência = quantidade de serviços
       valor      = soma do valor_total
     O K-Means agrupa clientes parecidos; os grupos recebem nomes de negócio
     (grandes clientes, frequentes, ocasionais, inativos).

  2) ESTIMADOR DE ORÇAMENTO (aprendizado supervisionado, Random Forest)
     Aprende o preço unitário praticado a partir de: tipo/subtipo do serviço,
     cidade e quantidade. O valor estimado = preço unitário previsto x quantidade.
     O erro é medido em dados que o modelo NÃO viu (20% separados) e comparado
     com uma regra simples (média do tipo), para mostrar se o ML ajuda de fato.

Saída (pasta dados/modelos/, lida pela API e mostrada na aba "Insights"):
    segmentos.json            resumo dos grupos + top clientes
    clientes_segmento.csv     o grupo de cada cliente
    estimador.json            catálogo, métricas, importância das variáveis, faixa de erro
    modelo_estimador.joblib   o modelo treinado

Uso:
    python scripts/modelos_ml.py
    python scripts/modelos_ml.py --saida dados/modelos --grupos 4 --semente 42
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.cluster import KMeans
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score, silhouette_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import create_engine

SQL = """
SELECT s.id_servico, s.id_cliente, s.tipo_servico, COALESCE(s.subtipo, '') AS subtipo,
       s.unidade_medida, s.quantidade::float8 AS quantidade,
       s.valor_unitario_aplicado::float8 AS pu, s.valor_total::float8 AS valor_total,
       s.data_execucao, s.status, c.nome_completo, COALESCE(c.cidade, '') AS cidade
FROM servicos s
JOIN clientes c ON c.id_cliente = s.id_cliente
"""

NOMES_FEATURES = {"servico": "Tipo / subtipo do serviço", "cidade": "Cidade", "quantidade": "Quantidade"}


def gravar_json(caminho: Path, obj) -> None:
    """Grava por arquivo temporário + rename, para a API nunca ler um arquivo pela metade."""
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------
# 1) Segmentação de clientes (RFM + K-Means)
# ---------------------------------------------------------------------
def segmentar_clientes(df: pd.DataFrame, k: int, semente: int, saida: Path) -> dict:
    status = df["status"].fillna("").str.lower().str.replace("í", "i", regex=False)
    base = df[df["valor_total"].notna() & (status != "cancelado")].copy()
    base["data"] = pd.to_datetime(base["data_execucao"], errors="coerce")
    base = base.dropna(subset=["data"])

    ref = base["data"].max() + pd.Timedelta(days=1)  # "hoje" dos dados (reprodutível)
    g = base.groupby("id_cliente").agg(
        nome=("nome_completo", "first"), cidade=("cidade", "first"),
        frequencia=("id_servico", "size"), valor=("valor_total", "sum"), ultima=("data", "max"),
    )
    g["recencia"] = (ref - g["ultima"]).dt.days
    if len(g) < k * 10:
        raise SystemExit(f"Poucos clientes com serviços ({len(g)}) para formar {k} grupos.")

    # log1p reduz a assimetria (poucos clientes gastam muito); StandardScaler iguala as escalas
    X = StandardScaler().fit_transform(np.log1p(g[["recencia", "frequencia", "valor"]]))
    km = KMeans(n_clusters=k, n_init=10, random_state=semente).fit(X)
    g["cluster"] = km.labels_
    silhueta = float(silhouette_score(X, km.labels_, sample_size=min(5000, len(g)), random_state=semente))

    # Nome de negócio de cada grupo, pelo perfil médio (regra determinística)
    perfil = g.groupby("cluster").agg(recencia=("recencia", "mean"), frequencia=("frequencia", "mean"),
                                      valor=("valor", "mean"))
    nomes = {c: f"Grupo {i + 1}" for i, c in enumerate(perfil.sort_values("valor", ascending=False).index)}
    if k == 4:
        restantes = list(perfil.index)
        grande = perfil["valor"].idxmax(); restantes.remove(grande)
        inativo = perfil.loc[restantes, "recencia"].idxmax(); restantes.remove(inativo)
        frequente = perfil.loc[restantes, "frequencia"].idxmax(); restantes.remove(frequente)
        resto = restantes[0]
        # O grupo que sobra é "ocasional", a menos que seja o que comprou mais recentemente
        # (em lotes pequenos isso acontece): aí o nome mais fiel ao perfil é "recentes".
        mais_recente = perfil["recencia"].idxmin() == resto
        nomes = {grande: "Grandes clientes", frequente: "Clientes frequentes",
                 inativo: "Clientes inativos",
                 resto: "Clientes recentes" if mais_recente else "Clientes ocasionais"}
    g["segmento"] = g["cluster"].map(nomes)

    total_valor = float(g["valor"].sum())
    segmentos = []
    for cid, sub in g.groupby("cluster"):
        segmentos.append({
            "nome": nomes[cid],
            "clientes": int(len(sub)),
            "pct_clientes": round(100 * len(sub) / len(g), 1),
            "frequencia_media": round(float(sub["frequencia"].mean()), 1),
            "valor_medio": round(float(sub["valor"].mean()), 2),
            "ticket_servico": round(float(sub["valor"].sum() / sub["frequencia"].sum()), 2),
            "recencia_media_dias": round(float(sub["recencia"].mean())),
            "faturamento": round(float(sub["valor"].sum()), 2),
            "pct_faturamento": round(100 * float(sub["valor"].sum()) / total_valor, 1),
        })
    segmentos.sort(key=lambda s: -s["faturamento"])

    top = g.sort_values("valor", ascending=False).head(10).reset_index()
    top_clientes = [{
        "id_cliente": int(r.id_cliente), "nome": r.nome, "cidade": r.cidade or "—",
        "servicos": int(r.frequencia), "valor": round(float(r.valor), 2), "segmento": r.segmento,
    } for r in top.itertuples()]

    g.reset_index()[["id_cliente", "segmento", "recencia", "frequencia", "valor"]].round(2).to_csv(
        saida / "clientes_segmento.csv", index=False, encoding="utf-8-sig")

    resultado = {
        "gerado_em": agora_iso(), "metodo": "K-Means sobre RFM (recência, frequência, valor)",
        "grupos": k, "clientes_analisados": int(len(g)), "data_referencia": ref.date().isoformat(),
        "silhueta": round(silhueta, 3), "segmentos": segmentos, "top_clientes": top_clientes,
    }
    gravar_json(saida / "segmentos.json", resultado)
    return resultado


# ---------------------------------------------------------------------
# 2) Estimador de orçamento (Random Forest sobre o preço unitário)
# ---------------------------------------------------------------------
def treinar_estimador(df: pd.DataFrame, semente: int, saida: Path) -> dict:
    est = df[df["pu"].notna() & (df["pu"] > 0) & df["quantidade"].notna() & (df["quantidade"] > 0)].copy()
    est["servico"] = est["tipo_servico"] + "|" + est["subtipo"]
    est["cidade"] = est["cidade"].replace("", "Não informada")
    if len(est) < 200:
        raise SystemExit(f"Poucos serviços válidos ({len(est)}) para treinar o estimador.")

    X = est[["servico", "cidade", "quantidade"]]
    y = est["pu"]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=semente)

    pre = ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                              ["servico", "cidade"])], remainder="passthrough")
    modelo = Pipeline([("pre", pre), ("rf", RandomForestRegressor(
        n_estimators=80, min_samples_leaf=30, n_jobs=-1, random_state=semente))])
    modelo.fit(X_tr, y_tr)

    # Erro no valor TOTAL do orçamento (preço unitário x quantidade), em dados não vistos
    q = X_te["quantidade"].to_numpy()
    real = y_te.to_numpy() * q
    previsto = modelo.predict(X_te) * q
    media_tipo = y_tr.groupby(X_tr["servico"]).mean()
    base = X_te["servico"].map(media_tipo).fillna(y_tr.mean()).to_numpy() * q

    def metricas(pred):
        return {"mae": round(float(mean_absolute_error(real, pred)), 2),
                "erro_pct": round(float(np.mean(np.abs(real - pred) / real) * 100), 2),
                "r2": round(float(r2_score(real, pred)), 4)}

    razao = real / previsto  # quanto o valor real costuma variar em torno da previsão
    faixa = [round(float(np.quantile(razao, 0.05)), 4), round(float(np.quantile(razao, 0.95)), 4)]

    # Importância de cada variável (soma das colunas "one-hot" de cada uma)
    nomes_col = modelo.named_steps["pre"].get_feature_names_out()
    imp = modelo.named_steps["rf"].feature_importances_
    soma = {k: 0.0 for k in NOMES_FEATURES}
    for nome, valor in zip(nomes_col, imp):
        if nome.startswith("cat__servico_"):
            soma["servico"] += valor
        elif nome.startswith("cat__cidade_"):
            soma["cidade"] += valor
        else:
            soma["quantidade"] += valor
    total_imp = sum(soma.values()) or 1.0
    importancia = sorted(({"variavel": NOMES_FEATURES[k], "pct": round(100 * v / total_imp, 1)}
                          for k, v in soma.items()), key=lambda d: -d["pct"])

    cat = (est.groupby(["tipo_servico", "subtipo"])
              .agg(unidade=("unidade_medida", lambda s: s.mode().iat[0] if not s.mode().empty else ""),
                   pu_medio=("pu", "mean"), servicos=("pu", "size")).reset_index())
    catalogo = [{"tipo_servico": r.tipo_servico, "subtipo": r.subtipo, "unidade": r.unidade,
                 "pu_medio": round(float(r.pu_medio), 2), "servicos": int(r.servicos)}
                for r in cat.sort_values(["tipo_servico", "subtipo"]).itertuples()]

    joblib.dump(modelo, saida / "modelo_estimador.tmp", compress=3)
    os.replace(saida / "modelo_estimador.tmp", saida / "modelo_estimador.joblib")

    resultado = {
        "gerado_em": agora_iso(), "metodo": "Random Forest (preço unitário) x quantidade",
        "treino": int(len(X_tr)), "teste": int(len(X_te)),
        "metricas_modelo": metricas(previsto), "metricas_regra_media_do_tipo": metricas(base),
        "faixa_90": faixa, "importancia": importancia,
        "catalogo": catalogo, "cidades": sorted(est["cidade"].unique().tolist()),
        "preco_unitario_variacao_pct": round(float((est["pu"] / est.groupby("servico")["pu"].transform("mean")).std() * 100), 1),
    }
    gravar_json(saida / "estimador.json", resultado)
    return resultado


def main():
    ap = argparse.ArgumentParser(description="Treina os modelos de ML (segmentação de clientes e estimador de orçamento).")
    ap.add_argument("--saida", default="dados/modelos", help="Pasta de saída (padrão: dados/modelos).")
    ap.add_argument("--grupos", type=int, default=4, help="Número de grupos de clientes (K-Means).")
    ap.add_argument("--semente", type=int, default=42, help="Semente para resultados reprodutíveis.")
    args = ap.parse_args()

    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("ERRO: variável DATABASE_URL não encontrada. Copie .env.example para .env.")

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    df = pd.read_sql(SQL, create_engine(url))
    print(f"Dados lidos do PostgreSQL: {len(df)} serviços ({time.time() - t0:.1f}s)")
    if df.empty:
        sys.exit("ERRO: não há serviços no banco. Rode antes o pipeline (make pipeline).")

    t1 = time.time()
    seg = segmentar_clientes(df, args.grupos, args.semente, saida)
    print(f"\n[1/2] Segmentação de clientes ({time.time() - t1:.1f}s): {seg['clientes_analisados']} clientes em "
          f"{seg['grupos']} grupos (silhueta {seg['silhueta']})")
    for s in seg["segmentos"]:
        print(f"      {s['nome']:<22}{s['clientes']:>6} clientes ({s['pct_clientes']:>4}%)  "
              f"{s['frequencia_media']:>4} serv./cliente  R$ {s['valor_medio']:>10,.2f}/cliente  "
              f"último serviço há {s['recencia_media_dias']} dias")

    t2 = time.time()
    e = treinar_estimador(df, args.semente, saida)
    m, b = e["metricas_modelo"], e["metricas_regra_media_do_tipo"]
    print(f"\n[2/2] Estimador de orçamento ({time.time() - t2:.1f}s): treino {e['treino']} / teste {e['teste']}")
    print(f"      modelo (Random Forest): erro médio R$ {m['mae']:,.2f} ({m['erro_pct']}%)  R² {m['r2']}")
    print(f"      regra simples (média do tipo): erro médio R$ {b['mae']:,.2f} ({b['erro_pct']}%)  R² {b['r2']}")
    print(f"      faixa de 90%: {e['faixa_90'][0]:.2f}x a {e['faixa_90'][1]:.2f}x da estimativa")
    print("      o que pesa no preço: " + "; ".join(f"{i['variavel']} {i['pct']}%" for i in e["importancia"]))
    print(f"\nModelos gravados em {saida}/  (total {time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
