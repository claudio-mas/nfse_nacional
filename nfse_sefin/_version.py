"""Fonte única da versão.

Mora num módulo próprio, e não em `__init__.py`, porque `facade/dps.py` precisa dela
para montar `verAplic` — e `__init__.py` importa a fachada. Ter a constante aqui
desfaz o ciclo sem obrigar ninguém a importar tarde.

`pyproject.toml` lê este arquivo (`[tool.hatch.version]`), e `release.yml` compara a
tag com `nfse_sefin.__version__`, que é reexportado por `__init__.py`. As três leituras
apontam para esta linha.
"""

from __future__ import annotations

__version__ = "0.1.0"
