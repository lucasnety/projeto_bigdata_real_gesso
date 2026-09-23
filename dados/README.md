# Dados

`raw/` contém o primeiro conjunto de dados brutos gerado pelo simulador
(`scripts/gerador_dados.py`, seed=42, 330 clientes / 1.600 serviços /
190 manutenções). São dados **fictícios**, gerados propositalmente com
inconsistências (valores ausentes, duplicidades, formatos divergentes,
categorias com grafias diferentes) para serem tratados na etapa de AED.

Para gerar um novo lote:

```bash
python scripts/gerador_dados.py --out-dir dados/raw
```
