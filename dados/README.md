# Dados

- `raw/` (**não versionado**, gerado): saída do simulador `scripts/gerador_dados.py` (seed 42, 330 clientes / 1.600 serviços /
  190 manutenções). Dados **fictícios**, sujos de propósito (formatos de data e telefone divergentes, duplicidades,
  valores ausentes, grafias diferentes).
- `tratado/` (versionado): resultado do tratamento em R (`scripts/tratar_dados.R`) — é o que vai para o PostgreSQL.
  Traz também `relatorio_qualidade.txt` (o que foi corrigido), `servicos_qualidade.csv` (flags por serviço) e
  `clientes_mapa_duplicados.csv`.
- `exemplo_dados.csv`: amostra do **simulador de chamados** (`simulador/simulador.py`, Checkpoint 01 de DevOps).

Para gerar e tratar um novo lote:

```bash
python scripts/gerador_dados.py --out-dir dados/raw
Rscript scripts/tratar_dados.R --entrada dados/raw --saida dados/tratado
```
