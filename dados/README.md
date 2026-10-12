# Dados

`raw/` contém os dados brutos gerados pelo simulador
(`scripts/gerador_dados.py`, seed=42, 330 clientes / 1.600 orçamentos /
190 manutenções, período de 01/01/2024 a 30/09/2026). São dados **fictícios**,
gerados propositalmente com inconsistências (valores ausentes, duplicidades,
formatos divergentes, categorias com grafias diferentes) para serem tratados
na preparação dos dados (`notebooks/01_preparacao_dados.ipynb`).

`raw/gabarito_perfis.csv` traz o perfil "verdadeiro" de cada cliente sorteado
pelo simulador. Ele **não** vai para o banco nem para o treino dos modelos;
serve só para conferir, no fim, se os modelos redescobriram os padrões.

`processed/` é gerada por `scripts/preparar_dados.py` e pelos notebooks
(bases limpas, segmentos e métricas dos modelos).

As duas pastas não são versionadas: com a mesma seed, o simulador gera
sempre os mesmos dados.

Para gerar um novo lote:

```bash
python scripts/gerador_dados.py --out-dir dados/raw
```
