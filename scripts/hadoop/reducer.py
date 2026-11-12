#!/usr/bin/env python3
import sys

tipo_atual = None
total = 0

for linha in sys.stdin:
    tipo, quantidade = linha.strip().split("\t")
    quantidade = int(quantidade)

    if tipo == tipo_atual:
        total += quantidade
    else:
        if tipo_atual is not None:
            print(f"{tipo_atual}\t{total}")
        tipo_atual = tipo
        total = quantidade

if tipo_atual is not None:
    print(f"{tipo_atual}\t{total}")
