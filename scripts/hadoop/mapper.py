#!/usr/bin/env python3
import sys
import csv

for linha in csv.reader(sys.stdin):
    if not linha or linha[0] == "id_servico":
        continue
    if len(linha) > 2:
        print(f"{linha[2].strip().title()}\t1")