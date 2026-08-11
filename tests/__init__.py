"""Suíte de testes.

Existe como pacote para que `from tests.conftest import ...` resolva para um módulo
só. Sem isto, o `mypy` enxerga `conftest.py` sob dois nomes e recusa checar a suíte.
"""
