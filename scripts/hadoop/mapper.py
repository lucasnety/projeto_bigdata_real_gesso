#!/usr/bin/env python3
import sys
import csv

for linha in csv.reader(sys.stdin):
    # lstrip("﻿"): os CSVs são gravados em utf-8-sig (com BOM), então
    # o 1º campo do cabeçalho chega como "﻿id_servico".
    if not linha or linha[0].lstrip("﻿") == "id_servico":
        continue
    if len(linha) > 2:
        print(f"{linha[2].strip().title()}\t1")