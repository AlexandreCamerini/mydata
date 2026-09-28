"""Console central do portfólio — Bloco A (ADR-25, ADR-23 Fase 3).

Pacote isolado dentro do admin do mydata: coleta somente-leitura de 5
sistemas (MCP, mydata, Boris+, semente-id via Railway, portal MCP) em
tabelas próprias `console_*`, sem tocar em `app/motor` — guardião testado
em `tests/test_console.py`.

A console nunca aplica mudança em nenhum sistema monitorado, nunca chama
fonte externa de dado de mercado e nunca chama modelo para produzir fato
(ver §6 da spec). Este pacote cobre só o Bloco A: coletor, tabelas e
credenciais de leitura por origem.
"""
from __future__ import annotations
